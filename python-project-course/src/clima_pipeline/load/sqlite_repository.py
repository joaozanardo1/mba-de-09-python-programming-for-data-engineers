import logging

import pandas as pd
from sqlalchemy import Column, Float, Integer, MetaData, String, Table, create_engine, select
from sqlalchemy.dialects.sqlite import insert as sqlite_upsert

from clima_pipeline.config import DATA_DIR, DB_PATH

logger = logging.getLogger(__name__)

# Lista explícita e ordenada das colunas que vão para cada tabela — usada
# para garantir que o DataFrame tenha exatamente essas colunas (nem a mais,
# nem a menos) antes de gravar, e na mesma ordem em que a tabela foi criada.
_COLUNAS_RAW = [
    "cidade", "datetime", "temp_c", "umidade_pct",
    "precipitacao_mm", "vento_kmh", "sensacao_c",
]
_COLUNAS_DIARIO = [
    "cidade", "data", "temp_media", "temp_min", "temp_max", "umidade_media",
    "precipitacao_total", "vento_medio", "categoria_temp", "categoria_chuva",
    "media_movel_3d", "media_movel_7d", "ranking_temp_dia", "indice_conforto_c",
    "sensacao_media", "sensacao_max",
]


class SQLiteRepository:
    """Responsável apenas por persistência.

    "Repository" é um padrão comum: o resto do código (pipeline, API) não
    escreve SQL nem conhece a estrutura das tabelas — só chama métodos como
    save_daily(df) ou get_daily(cidade). Se um dia trocarmos SQLite por outro
    banco, só esta classe precisa mudar.
    """

    def __init__(self, db_path=DB_PATH):
        # SQLAlchemy Core: engine é a conexão com o banco (aqui, um arquivo
        # SQLite local); MetaData guarda a definição das tabelas em memória
        # (schema), sem precisar escrever SQL "CREATE TABLE" à mão.
        self.engine = create_engine(f"sqlite:///{db_path}")
        self.metadata = MetaData()
        self._clima_raw = self._tabela_raw()
        self._clima_diario = self._tabela_diario()
        # Cria as tabelas no arquivo .db se ainda não existirem (checkfirst
        # evita erro caso já existam de uma execução anterior).
        self.metadata.create_all(self.engine, checkfirst=True)

    def _tabela_raw(self) -> Table:
        """Schema da tabela com dado horário tratado (uma linha por cidade+hora)."""
        return Table(
            "clima_raw",
            self.metadata,
            # Chave primária composta (cidade, datetime): impede duas linhas
            # para a mesma cidade na mesma hora — e é exatamente o que
            # _upsert() usa para decidir se uma linha é nova ou já existe.
            Column("cidade", String, primary_key=True),
            Column("datetime", String, primary_key=True),
            Column("temp_c", Float),
            Column("umidade_pct", Float),
            Column("precipitacao_mm", Float),
            Column("vento_kmh", Float),
            Column("sensacao_c", Float),
        )

    def _tabela_diario(self) -> Table:
        """Schema da tabela com a visão agregada (uma linha por cidade+dia)."""
        return Table(
            "clima_diario",
            self.metadata,
            Column("cidade", String, primary_key=True),
            Column("data", String, primary_key=True),
            Column("temp_media", Float),
            Column("temp_min", Float),
            Column("temp_max", Float),
            Column("umidade_media", Float),
            Column("precipitacao_total", Float),
            Column("vento_medio", Float),
            Column("categoria_temp", String),
            Column("categoria_chuva", String),
            Column("media_movel_3d", Float),
            Column("media_movel_7d", Float),
            Column("ranking_temp_dia", Integer),
            Column("indice_conforto_c", Float),
            Column("sensacao_media", Float),
            Column("sensacao_max", Float),
        )

    def _upsert(
        self,
        tabela: Table,
        df: pd.DataFrame,
        colunas_pk: list[str],
        lote: int = 500,
    ) -> None:
        """"UPSERT" em LOTES para não estourar o limite de variáveis do SQLite.

        O SQLite aceita no máximo ~32.766 parâmetros por statement. Como
        cada linha tem N colunas, inserir tudo de uma vez estoura em
        datasets grandes (ex.: 7 cidades × 31 dias × 24 horas). Aqui
        dividimos o DataFrame em blocos de `lote` linhas e executamos um
        UPSERT por bloco.

        Continua idempotente: rodar o pipeline várias vezes para o mesmo
        período apenas atualiza as linhas existentes, sem duplicar.
        """
        if df.empty:
            return

        colunas_atualizaveis = [c.name for c in tabela.columns if c.name not in colunas_pk]
        total = 0

        for inicio in range(0, len(df), lote):
            bloco = df.iloc[inicio : inicio + lote]
            registros = bloco.to_dict(orient="records")

            stmt = sqlite_upsert(tabela).values(registros)
            stmt = stmt.on_conflict_do_update(
                index_elements=colunas_pk,
                set_={c: getattr(stmt.excluded, c) for c in colunas_atualizaveis},
            )

            with self.engine.begin() as conn:
                conn.execute(stmt)

            total += len(registros)

        logger.info("Upsert em '%s': %d linha(s) em lotes de %d", tabela.name, total, lote)

    def save_raw(self, df: pd.DataFrame) -> None:
        """Grava o DataFrame horário (saída de ClimaCleaner) em 'clima_raw'."""
        # Seleciona só as colunas esperadas (na ordem certa) e converte
        # datetime para string, porque a coluna no SQLite é String, não um
        # tipo de data nativo (SQLite não tem um tipo DATETIME de verdade).
        df = df[_COLUNAS_RAW].assign(datetime=lambda d: d["datetime"].astype(str))
        self._upsert(self._clima_raw, df, colunas_pk=["cidade", "datetime"])

    def save_daily(self, df: pd.DataFrame) -> None:
        """Grava o DataFrame diário (saída de ClimaAggregator) em 'clima_diario'."""
        df = df[_COLUNAS_DIARIO].assign(data=lambda d: d["data"].astype(str))
        self._upsert(self._clima_diario, df, colunas_pk=["cidade", "data"])

    def get_daily(self, city: str | None = None) -> pd.DataFrame:
        """Lê a visão diária do banco; se `city` for informado, filtra só aquela cidade.

        É este método que a API chama a cada requisição (não o pipeline) —
        veja api/main.py.
        """
        query = select(self._clima_diario)
        if city:
            query = query.where(self._clima_diario.c.cidade == city)
        # parse_dates converte a coluna "data" (armazenada como texto) de
        # volta para datetime do pandas ao ler — o inverso do astype(str)
        # feito em save_daily().
        return pd.read_sql(query, self.engine, parse_dates=["data"])

    def dispose(self) -> None:
        """Fecha as conexões do engine. Chamado no encerramento da API (veja api/main.py)."""
        self.engine.dispose()


if __name__ == "__main__":
    # Entrada mockada: usa um arquivo .db de teste separado, na mesma pasta
    # do banco real (DATA_DIR), para testar save_raw/save_daily/get_daily
    # isolados sem mexer no data/clima.db de verdade. Como é um arquivo em
    # disco (não ":memory:"), dá para inspecionar depois com
    # `sqlite3 data/clima_teste.db`.
    db_path_teste = DATA_DIR / "clima_teste.db"
    repo = SQLiteRepository(db_path=db_path_teste)

    df_raw_mock = pd.DataFrame({
        "cidade": ["sao_paulo", "sao_paulo"],
        "datetime": ["2025-01-01 00:00:00", "2025-01-01 01:00:00"],
        "temp_c": [22.5, 22.1],
        "umidade_pct": [80.0, 82.0],
        "precipitacao_mm": [0.0, 0.0],
        "vento_kmh": [10.2, 9.8],
        "sensacao_c": [23.0, 22.7],
    })
    repo.save_raw(df_raw_mock)

    df_diario_mock = pd.DataFrame({
        "cidade": ["sao_paulo"],
        "data": ["2025-01-01"],
        "temp_media": [22.3],
        "temp_min": [22.1],
        "temp_max": [22.5],
        "umidade_media": [81.0],
        "precipitacao_total": [0.0],
        "vento_medio": [10.0],
        "categoria_temp": ["ameno"],
        "categoria_chuva": ["seco"],
        "media_movel_3d": [22.3],
        "media_movel_7d": [22.3],
        "ranking_temp_dia": [1],
        "indice_conforto_c": [22.3],
        "sensacao_media": [22.9],
        "sensacao_max": [23.0],
    })
    repo.save_daily(df_diario_mock)

    print(repo.get_daily("sao_paulo"))
    repo.dispose()