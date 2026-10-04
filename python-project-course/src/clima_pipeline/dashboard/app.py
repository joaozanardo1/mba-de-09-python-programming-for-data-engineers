"""Dashboard Streamlit — consome a REST API (não acessa o SQLite diretamente).

Importante para entender a arquitetura: este arquivo nunca importa
SQLiteRepository nem ClimaCleaner/ClimaAggregator — ele só faz requisições
HTTP para a API (clima_pipeline.api.main). Isso significa que o dashboard
pode rodar numa máquina diferente da API, e que trocar como os dados são
guardados no banco não exige tocar neste arquivo.
"""

import datetime as dt

import matplotlib.pyplot as plt
import pandas as pd
import requests
import streamlit as st

from clima_pipeline.config import API_BASE_URL, DATA_FIM_PADRAO, DATA_INICIO_PADRAO

st.set_page_config(page_title="Clima Pipeline", layout="wide")
st.title("Clima Pipeline — Dashboard")

# Barra lateral: controles que o usuário pode mudar a qualquer momento e que
# afetam o resto da página (Streamlit reexecuta o script inteiro a cada
# interação, de cima para baixo).
with st.sidebar:
    api_base_url = st.text_input("URL da API", value=API_BASE_URL)
    inicio = st.date_input("Data inicial", value=dt.date.fromisoformat(DATA_INICIO_PADRAO))
    fim = st.date_input("Data final", value=dt.date.fromisoformat(DATA_FIM_PADRAO))


# ============================================================
# Funções de acesso à API (cacheadas)
# ============================================================
@st.cache_data(ttl=300)
def carregar_cidades(base_url: str) -> pd.DataFrame:
    """Busca a lista de cidades na API. Cacheada por 5 min (muda raramente)."""
    resposta = requests.get(f"{base_url}/cidades", timeout=10)
    resposta.raise_for_status()
    return pd.DataFrame(resposta.json())


@st.cache_data(ttl=60)
def carregar_diario(base_url: str, slug: str, inicio: dt.date, fim: dt.date) -> pd.DataFrame:
    """Busca a visão diária de UMA cidade na API. Cacheada por 1 min."""
    params = {"cidade": slug, "inicio": str(inicio), "fim": str(fim)}
    resposta = requests.get(f"{base_url}/clima/diario", params=params, timeout=10)
    resposta.raise_for_status()
    df = pd.DataFrame(resposta.json())
    if not df.empty:
        df["data"] = pd.to_datetime(df["data"])
    return df


@st.cache_data(ttl=60)
def carregar_resumo(base_url: str, slug: str, limite: int) -> dict:
    """Busca o resumo estatístico de UMA cidade na API. Cacheada por 1 min.

    Endpoint novo (Etapa 2 do trabalho): GET /clima/resumo?cidade=...&limite=...
    """
    params = {"cidade": slug, "limite": limite}
    resposta = requests.get(f"{base_url}/clima/resumo", params=params, timeout=10)
    resposta.raise_for_status()
    return resposta.json()


# ============================================================
# Carrega lista de cidades
# ============================================================
try:
    cidades_df = carregar_cidades(api_base_url)
except requests.RequestException as erro:
    st.error(f"Não foi possível falar com a API em '{api_base_url}': {erro}")
    st.stop()

nome_por_slug = dict(zip(cidades_df["slug"], cidades_df["nome_exibicao"]))
slug_por_nome = dict(zip(cidades_df["nome_exibicao"], cidades_df["slug"]))

with st.sidebar:
    nomes_selecionados = st.multiselect(
        "Cidades", options=list(slug_por_nome), default=list(slug_por_nome)[:3]
    )
    limite_resumo = st.slider(
        "Dias para o resumo", min_value=7, max_value=365, value=30, step=1
    )

if not nomes_selecionados:
    st.info("Selecione ao menos uma cidade na barra lateral.")
    st.stop()

slugs_selecionados = [slug_por_nome[nome] for nome in nomes_selecionados]


# ============================================================
# Carrega diário de cada cidade
# ============================================================
partes = []
for slug in slugs_selecionados:
    try:
        partes.append(carregar_diario(api_base_url, slug, inicio, fim))
    except requests.RequestException as erro:
        st.warning(f"Não foi possível carregar dados de {nome_por_slug[slug]}: {erro}")

diario = pd.concat(partes, ignore_index=True) if partes else pd.DataFrame()

if diario.empty:
    st.warning("Sem dados para o período/cidades selecionados.")
    st.stop()

diario["nome_exibicao"] = diario["cidade"].map(nome_por_slug)


# ============================================================
# ETAPA 2 DO TRABALHO — 4 CARDS DE MÉTRICAS (via /clima/resumo)
# Mostramos um bloco de 4 métricas por cidade selecionada.
# ============================================================
st.subheader("📊 Resumo do período")

for slug in slugs_selecionados:
    nome = nome_por_slug[slug]
    try:
        resumo = carregar_resumo(api_base_url, slug, limite_resumo)
    except requests.RequestException as erro:
        st.warning(f"Não foi possível carregar o resumo de {nome}: {erro}")
        continue

    st.markdown(f"**{nome}** — últimos {limite_resumo} dias")

    # Dias chuvosos: contamos os dias com precipitacao_total > 1.0 mm
    subset = diario[(diario["cidade"] == slug)]
    if not subset.empty:
        dias_chuvosos = int((subset["precipitacao_total"] > 1.0).sum())
    else:
        dias_chuvosos = 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric(
        "🌡️ Temperatura média",
        f"{resumo.get('temperatura_media', '—')} °C",
    )
    c2.metric(
        "🔥 Máxima do período",
        f"{resumo.get('temperatura_maxima', '—')} °C",
    )
    c3.metric(
        "🌧️ Chuva total",
        f"{resumo.get('precipitacao_total', '—')} mm",
    )
    c4.metric(
        "☔ Dias chuvosos",
        f"{dias_chuvosos} dias",
    )

    # Linha extra com sensação térmica (Etapa 1 do trabalho)
    s1, s2, s3 = st.columns(3)
    s1.metric(
        "🥵 Sensação média",
        f"{resumo.get('temperatura_media', '—')} °C  (aprox.)",
    )
    s2.metric(
        "📅 Período",
        f"{resumo.get('periodo_inicio', '—')} → {resumo.get('periodo_fim', '—')}",
    )
    s3.metric(
        "📈 Registros",
        f"{resumo.get('total_registros', 0)} dias",
    )
    st.divider()


# ============================================================
# Gráfico 1: temperatura diária + média móvel
# ============================================================
st.subheader("Temperatura ao longo do tempo (diária vs. média móvel de 7 dias)")
fig, ax = plt.subplots(figsize=(11, 4))
for slug in slugs_selecionados:
    subset = diario[diario["cidade"] == slug]
    nome = nome_por_slug[slug]
    ax.plot(subset["data"], subset["temp_media"], alpha=0.35, label=f"{nome} (diária)")
    ax.plot(subset["data"], subset["media_movel_7d"], linewidth=2, label=f"{nome} (móvel 7d)")
ax.set_xlabel("Data")
ax.set_ylabel("Temperatura (°C)")
ax.legend(fontsize=8)
fig.autofmt_xdate(rotation=45)
st.pyplot(fig)


# ============================================================
# Gráfico NOVO — sensação térmica (Etapa 1 do trabalho)
# ============================================================
st.subheader("Sensação térmica ao longo do tempo")
fig2, ax2 = plt.subplots(figsize=(11, 4))
for slug in slugs_selecionados:
    subset = diario[diario["cidade"] == slug]
    nome = nome_por_slug[slug]
    if "sensacao_media" in subset.columns:
        ax2.plot(subset["data"], subset["sensacao_media"], linewidth=2, label=f"{nome} (sensação média)")
    if "temp_media" in subset.columns:
        ax2.plot(subset["data"], subset["temp_media"], alpha=0.35, linestyle="--", label=f"{nome} (temp. real)")
ax2.set_xlabel("Data")
ax2.set_ylabel("Temperatura (°C)")
ax2.legend(fontsize=8)
fig2.autofmt_xdate(rotation=45)
st.pyplot(fig2)


# ============================================================
# Gráfico 2: comparativo entre cidades
# ============================================================
st.subheader("Comparativo entre cidades")
opcoes_variavel = [
    "temp_media", "temp_max", "temp_min",
    "umidade_media", "precipitacao_total", "vento_medio",
    "indice_conforto_c",
]
# Só oferece as colunas de sensação se elas existirem no retorno da API
if "sensacao_media" in diario.columns:
    opcoes_variavel.insert(1, "sensacao_media")
if "sensacao_max" in diario.columns:
    opcoes_variavel.insert(2, "sensacao_max")

variavel = st.selectbox("Variável", opcoes_variavel, index=0)

comparativo_df = diario.pivot_table(index="data", columns="nome_exibicao", values=variavel)
if comparativo_df.empty:
    st.info("Sem dados comparativos para essa combinação.")
else:
    st.line_chart(comparativo_df)


# ============================================================
# Tabela final
# ============================================================
st.subheader("Tabela agregada (visão diária)")
colunas_tabela = [
    "nome_exibicao", "data", "temp_media", "temp_min", "temp_max",
    "umidade_media", "precipitacao_total",
    "categoria_temp", "categoria_chuva", "indice_conforto_c",
]
if "sensacao_media" in diario.columns:
    colunas_tabela.insert(5, "sensacao_media")
if "sensacao_max" in diario.columns:
    colunas_tabela.insert(6, "sensacao_max")

colunas_presentes = [c for c in colunas_tabela if c in diario.columns]
st.dataframe(
    diario[colunas_presentes].sort_values(["nome_exibicao", "data"]),
    width="stretch",
    hide_index=True,
)