"""
REST API (FastAPI) para consultar o clima persistido em SQLite.

Esta API NÃO roda o pipeline nem fala com a Open-Meteo — ela só lê o que o
pipeline (pipeline.py) já deixou salvo em data/clima.db.
"""

from contextlib import asynccontextmanager
import datetime as dt
import unicodedata

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import RedirectResponse

from clima_pipeline.api.schemas import CidadeOut, ClimaDiarioOut, HealthOut
from clima_pipeline.config import CIDADES, resolver_slug_cidade
from clima_pipeline.load import SQLiteRepository
from clima_pipeline.transform.resumo import gerar_resumo


# ============================================================
# Infra
# ============================================================
_repositorio = SQLiteRepository()


def get_repository() -> SQLiteRepository:
    """Devolve a instância única de SQLiteRepository usada por toda a API."""
    return _repositorio


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    get_repository().dispose()


app = FastAPI(
    title="Clima Pipeline API",
    description="Consulta dados climáticos históricos tratados e agregados.",
    version="0.1.0",
    lifespan=lifespan,
)


# ============================================================
# Resolução de cidade — aceita slug, nome com/sem acento, UF
# ============================================================
def _normalizar(texto: str) -> str:
    """
    Normaliza um texto para comparação:
      - remove espaços nas pontas
      - converte para minúsculas
      - remove acentos (NFD + filtro de marcas)
      - troca hífen e espaço por underscore
    Ex.: 'São Paulo' → 'sao_paulo'
         'Belém'     → 'belem'
         'RIO-DE-JANEIRO' → 'rio_de_janeiro'
    """
    texto = texto.strip().lower()
    texto = "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )
    return texto.replace("-", "_").replace(" ", "_")


def _resolver_ou_404(identificador: str) -> str:
    """
    Traduz o texto recebido (slug / nome de exibição / UF) em slug canônico.
    Tenta primeiro o resolver_slug_cidade() do projeto; se falhar, faz uma
    busca normalizada em CIDADES (tolerante a acento, espaço, hífen e caixa).
    """
    # 1) Caminho normal do projeto
    slug = resolver_slug_cidade(identificador)
    if slug is not None:
        return slug

    # 2) Fallback tolerante a acentos / espaços / hífens
    alvo = _normalizar(identificador)
    for slug, info in CIDADES.items():
        candidatos = {
            _normalizar(slug),
            _normalizar(info.get("nome_exibicao", "")),
            _normalizar(info.get("uf", "")),
        }
        if alvo in candidatos:
            return slug

    # 3) Nada bateu → 404
    raise HTTPException(
        status_code=404,
        detail=(
            f"Cidade '{identificador}' não encontrada. "
            f"Use /cidades para ver as opções."
        ),
    )


# ============================================================
# Rotas
# ============================================================
@app.get("/", include_in_schema=False)
def raiz() -> RedirectResponse:
    return RedirectResponse(url="/docs")


@app.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    return HealthOut()


@app.get("/cidades", response_model=list[CidadeOut])
def listar_cidades() -> list[CidadeOut]:
    return [
        CidadeOut(
            slug=slug,
            nome_exibicao=info["nome_exibicao"],
            uf=info["uf"],
            regiao=info["regiao"],
            lat=info["lat"],
            lon=info["lon"],
        )
        for slug, info in CIDADES.items()
    ]


@app.get("/clima/diario", response_model=list[ClimaDiarioOut])
def clima_diario(
    cidade: str = Query(..., description="Slug, nome de exibição ou UF da cidade"),
    inicio: dt.date | None = Query(None, description="Data inicial (YYYY-MM-DD)"),
    fim: dt.date | None = Query(None, description="Data final (YYYY-MM-DD)"),
) -> list[ClimaDiarioOut]:
    slug = _resolver_ou_404(cidade)
    df = get_repository().get_daily(city=slug)

    if df.empty:
        return []

    df["data"] = df["data"].dt.date
    if inicio:
        df = df[df["data"] >= inicio]
    if fim:
        df = df[df["data"] <= fim]

    return [ClimaDiarioOut(**row) for row in df.to_dict(orient="records")]


# ============================================================
# /clima/resumo — resumo estatístico de UMA cidade
# ============================================================
def _pick(row: dict, *nomes: str):
    """Retorna o primeiro valor não-None entre as chaves dadas."""
    for n in nomes:
        v = row.get(n)
        if v is not None:
            return v
    return None


@app.get("/clima/resumo", tags=["Clima"])
def resumo_clima(
    cidade: str = Query(..., description="Slug, nome de exibição ou UF da cidade"),
    limite: int = Query(30, ge=1, le=365, description="Quantos dias recentes considerar"),
):
    """
    Retorna um resumo estatístico (médias, máximas, mínimas, totais)
    do clima para uma cidade, considerando os N registros mais recentes.
    """
    slug = _resolver_ou_404(cidade)
    df = get_repository().get_daily(city=slug)

    if df.empty:
        raise HTTPException(
            status_code=404,
            detail=f"Nenhum registro encontrado para a cidade '{cidade}'.",
        )

    # Ordena por data (se existir) e pega os N mais recentes
    if "data" in df.columns:
        df = df.sort_values("data").tail(limite)
    else:
        df = df.tail(limite)

    # Mapeamento flexível: aceita diferentes nomes de coluna
    registros = []
    for row in df.to_dict(orient="records"):
        registros.append({
            "data":         str(_pick(row, "data", "date") or ""),
            "temperatura":  _pick(row, "temp_media", "temperatura", "temp"),
            "umidade":      _pick(row, "umidade_media", "umidade", "humidity"),
            "precipitacao": _pick(
                row,
                "precipitacao_total", "precipitacao", "chuva", "precipitation",
            ),
        })

    resumo = gerar_resumo(cidade=slug, registros=registros)
    return resumo.to_dict()