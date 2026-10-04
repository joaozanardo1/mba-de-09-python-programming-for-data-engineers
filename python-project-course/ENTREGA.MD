# Membros 
* Eduardo Lucio de Oliveira
* João Marcos Zanardo Martins de Castro
* Ana Carolina Santana Zanon
*

# 🌤️ Clima Pipeline
Pipeline de ETL que coleta dados históricos do Open-Meteo, trata, agrega e
disponibiliza via API REST (FastAPI) e Dashboard (Streamlit).

Cidades: São Paulo, Rio de Janeiro, Manaus, Porto Alegre, Recife, **Belém** e **Curitiba**.

## ⚙️ Preparar o ambiente (venv)

```bash
---> cd .\python-project-course\
Sequencia' run abaixo'
  |
  |
 \ /
  v
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python.exe -m pip install --upgrade pip

pip install -e ".[notebooks]"
```

> Reative o venv a cada novo terminal: `.\.venv\Scripts\Activate.ps1`
## 🚀 Rodando o projeto
### 1. Pipeline (popular o banco SQLite)
```bash
python -m clima_pipeline.pipeline
```

### 2. API FastAPI
Em outro terminal (ative o venv novamente):
```bash
uvicorn clima_pipeline.api.main:app --reload
```

### 3. Dashboard Streamlit
Em outro terminal (ative o venv novamente):
```bash
streamlit run src/clima_pipeline/dashboard/app.py
```

### 4. Documentação Sphinx
Em outro terminal (ative o venv novamente):
```bash
pip install -e ".[docs]"
python -m pip install sphinx sphinx-rtd-theme
python -m sphinx -b html docs docs/_build/html

#Em caso de erro; Seguir passos acima de comando;
python -m http.server 8001 --directory docs/_build/html
```
Abrir: http://localhost:8001
Ou abrir direto o HTML:
```bash
Start-Process .\docs\_build\html\index.html
```

--------------------------------------------------------------------------------

## 📋 Endpoints
| Rota | Descrição |
|---|---|
| `/health` | Health check |
| `/cidades` | Lista as cidades cadastradas |
| `/clima/diario` | Visão diária de uma cidade |
| `/clima/resumo` | Resumo estatístico do período |

**1. Rodar o pipeline completo:**
```bash
python -m clima_pipeline.pipeline
```

**2. Testar o módulo resumo:**
```bash
python -m clima_pipeline.transform.resumo
```

**3. Subir a API FastAPI:**

```bash
uvicorn clima_pipeline.api.main:app --reload
```

Acesse http://127.0.0.1:8000/docs, expanda o endpoint **GET /clima/resumo**,
clique em "Try it out" → digite `belem` ou `curitiba` → **Execute**.


**4. Subir o Dashboard Streamlit:**
```bash
streamlit run src/clima_pipeline/dashboard/app.py
```
