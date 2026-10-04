# src/clima_pipeline/transform/resumo.py
"""
Módulo responsável por gerar resumos estatísticos dos dados climáticos.
Calcula médias, máximas e mínimas de temperatura, umidade e precipitação.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Iterable, Optional
from statistics import mean


@dataclass
class ResumoClima:
    cidade: str
    periodo_inicio: str
    periodo_fim: str
    total_registros: int
    temperatura_media: Optional[float]
    temperatura_maxima: Optional[float]
    temperatura_minima: Optional[float]
    umidade_media: Optional[float]
    umidade_maxima: Optional[float]
    umidade_minima: Optional[float]
    precipitacao_total: Optional[float]
    precipitacao_media: Optional[float]

    def to_dict(self) -> dict:
        return asdict(self)


def _extrair(registros: Iterable[dict], chave: str) -> list[float]:
    """Extrai valores numéricos válidos de uma chave específica."""
    valores: list[float] = []
    for r in registros:
        v = r.get(chave)
        if v is None:
            continue
        try:
            valores.append(float(v))
        except (TypeError, ValueError):
            continue
    return valores


def _media(valores: list[float]) -> Optional[float]:
    return round(mean(valores), 2) if valores else None


def _maximo(valores: list[float]) -> Optional[float]:
    return round(max(valores), 2) if valores else None


def _minimo(valores: list[float]) -> Optional[float]:
    return round(min(valores), 2) if valores else None


def gerar_resumo(
    cidade: str,
    registros: list[dict],
    periodo_inicio: str = "",
    periodo_fim: str = "",
) -> ResumoClima:
    """
    Gera um resumo estatístico a partir de uma lista de registros climáticos.

    Cada registro é um dict com chaves como:
      - temperatura (float)
      - umidade (float)
      - precipitacao (float)
    """
    if not registros:
        return ResumoClima(
            cidade=cidade,
            periodo_inicio=periodo_inicio,
            periodo_fim=periodo_fim,
            total_registros=0,
            temperatura_media=None,
            temperatura_maxima=None,
            temperatura_minima=None,
            umidade_media=None,
            umidade_maxima=None,
            umidade_minima=None,
            precipitacao_total=None,
            precipitacao_media=None,
        )

    temps = _extrair(registros, "temperatura")
    umid = _extrair(registros, "umidade")
    precip = _extrair(registros, "precipitacao")

    return ResumoClima(
        cidade=cidade,
        periodo_inicio=periodo_inicio or registros[0].get("data", ""),
        periodo_fim=periodo_fim or registros[-1].get("data", ""),
        total_registros=len(registros),
        temperatura_media=_media(temps),
        temperatura_maxima=_maximo(temps),
        temperatura_minima=_minimo(temps),
        umidade_media=_media(umid),
        umidade_maxima=_maximo(umid),
        umidade_minima=_minimo(umid),
        precipitacao_total=round(sum(precip), 2) if precip else None,
        precipitacao_media=_media(precip),
    )