"""Safety das SEGURADORAS via índice de solvência (preenchimento manual).

A SUSEP não expõe API aberta limpa (diferente da Basileia no BC), então usamos tabela
manual — mesmo molde do basileia.py.

Indicador: índice de solvência = PLA / CMR (Patrimônio Líquido Ajustado / Capital Mínimo
Requerido). Regulatório: >= 1,0 (100%). As seguradoras divulgam nos releases/RI e nos
quadros da SUSEP.

Mapeamento p/ Safety (equivalente aos 11%–18% da Basileia):
    piso 1,0 (mínimo regulatório) -> 0   e   teto 1,5 (colchão de 50%) -> 100  (satura).

Preencha SOLVENCIA_MANUAL (ou env SOLVENCIA_MANUAL em JSON) ~1x por trimestre. Vazio por
padrão (não invento números). Degrada com elegância: sem dado -> Safety segue n/d.
Desligue com env SOLVENCIA=0.
"""
from __future__ import annotations

import json
import math
import os

# tickers de seguradoras/resseguradoras (capitalização de referência do Safety por solvência)
INSURERS = {"BBSE3", "PSSA3", "CXSE3", "WIZC3", "IRBR3", "CSAB4", "CSAB3"}

# ------------------------------------------------------------------------------------------
# TABELA MANUAL — índice de solvência PLA/CMR por ticker (ex.: 1,35 = 135%).
# Atualize ~1x por trimestre com os dados oficiais (release/RI da seguradora ou SUSEP).
SOLVENCIA_MANUAL: dict[str, float] = {
    # "BBSE3": 1.40,
    # "PSSA3": 1.60,
}

SOLV_FLOOR = 1.0     # mínimo regulatório (100%) -> nota 0
SOLV_TOP = 1.5       # colchão de 50% acima do mínimo -> nota 100


def solvencia_safety(indice, floor: float = SOLV_FLOOR, top: float = SOLV_TOP) -> float:
    """Índice de solvência (PLA/CMR) -> 0-100 (linear entre floor e top, saturando)."""
    try:
        x = float(indice)
    except Exception:
        return math.nan
    if math.isnan(x):
        return math.nan
    return float(max(0.0, min(100.0, (x - floor) / (top - floor) * 100.0)))


def _manual_map() -> dict:
    out = {k.upper(): float(v) for k, v in SOLVENCIA_MANUAL.items()
           if isinstance(v, (int, float)) and float(v) > 0}
    env = os.getenv("SOLVENCIA_MANUAL", "").strip()
    if env:
        try:
            for k, v in json.loads(env).items():
                if float(v) > 0:
                    out[str(k).upper()] = float(v)
        except Exception:
            pass
    return out


def fetch_solvencia_map(tickers) -> dict:
    """{ticker: índice de solvência} para as seguradoras do mapa (fonte: tabela manual)."""
    if os.getenv("SOLVENCIA", "1") == "0":
        return {}
    alvos = [t for t in tickers if t in INSURERS]
    if not alvos:
        return {}
    manual = _manual_map()
    out = {tk: manual[tk] for tk in alvos if tk in manual}
    if out:
        print(f"[solvencia] tabela manual: {len(out)} seguradora(s) "
              f"({', '.join(f'{k} {v:.2f}' for k, v in sorted(out.items()))}).")
    return out
