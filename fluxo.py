"""fluxo.py — fluxo de investidores ESTRANGEIROS na B3, via o BDI oficial (bdi_indices.py).

Antes este módulo era um placeholder (sem fonte confiável). A B3 publica, no capítulo 02 do
BDI ("Indicadores e Informativos"), a participação de investidores com compras/vendas
ACUMULADAS DO MÊS do Investidor Estrangeiro. O fluxo do DIA é a diferença entre o acumulado
de hoje e o de ontem (por isso depende de um cache — ver bdi_indices.py). Desligue com
BDI_INDICES=0. Retorna None sem inventar nada se a fonte ou o cache faltarem.
"""
from __future__ import annotations

from bdi_indices import fetch_fluxo_estrangeiro as _fetch


def fetch_fluxo_estrangeiro() -> dict | None:
    """Mantém a assinatura antiga; delega para a fonte real (BDI). Formato do retorno:
    {"dia": float|None, "mes": float, "acum_mes": float, "data": date} ou None."""
    return _fetch()
