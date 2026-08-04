# -*- coding: utf-8 -*-
"""
Preços-teto / valor justo por ação.

Métodos (todos derivam de preço + P/L + P/VP + DY, mais premissas de k e g):
  LPA = preço / P/L        (lucro por ação)
  VPA = preço / P/VP       (valor patrimonial por ação)
  DPA = DY% × preço        (dividendo por ação, 12m)

  • BAZIN   = DPA ÷ yield_alvo         (default 6%)
  • GRAHAM  = raiz(22,5 × LPA × VPA)
  • GORDON  = DPA × (1+g) ÷ (k − g)    (perpetuidade de dividendos)
  • DCF     = LPA × (1+g) ÷ (k − g)    (perpetuidade de lucros; "DCF simplificado")
  • MÉDIA   = média dos métodos aplicáveis

k (taxa de desconto) por padrão = Selic + prêmio (prêmio configurável, default 0),
alinhado à sua régua de "ROE ≥ Selic". g (crescimento na perpetuidade) usa o CAGR
informado, limitado a algo conservador e sempre < k.

Onde faltar insumo (LPA≤0, DY≤0, etc.), o método vira NaN e sai da média — nada é inventado.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from typing import Optional

import numpy as np


@dataclass
class Ceilings:
    bazin: float = math.nan
    graham: float = math.nan
    gordon: float = math.nan
    dcf: float = math.nan
    lynch: float = math.nan
    media: float = math.nan
    mediana: float = math.nan
    upside_pct: float = math.nan       # mediana/preço - 1 (consolidado robusto)
    upside_media_pct: float = math.nan  # media/preço - 1
    k: float = math.nan
    g: float = math.nan

    def as_dict(self):
        return asdict(self)


def _pos(x) -> bool:
    return x is not None and not (isinstance(x, float) and math.isnan(x)) and x > 0


def compute_ceilings(price: float, pl: float, pvp: float, dy_pct: float,
                     growth_pct: Optional[float], selic_pct: float = 15.0,
                     bazin_yield: float = 0.06, premium: float = 0.0,
                     g_default: float = 0.04, g_cap: float = 0.06) -> Ceilings:
    c = Ceilings()
    if not _pos(price):
        return c

    lpa = price / pl if _pos(pl) else math.nan
    vpa = price / pvp if _pos(pvp) else math.nan
    dpa = (dy_pct / 100.0) * price if _pos(dy_pct) else math.nan

    k = selic_pct / 100.0 + premium
    g = (growth_pct / 100.0) if (growth_pct is not None and not
         (isinstance(growth_pct, float) and math.isnan(growth_pct)) and growth_pct > 0) else g_default
    g = min(g, g_cap, k - 0.01)          # conservador e sempre < k
    c.k, c.g = k, g

    if _pos(dpa):
        c.bazin = dpa / bazin_yield
    if _pos(lpa) and _pos(vpa):
        c.graham = math.sqrt(22.5 * lpa * vpa)
    if _pos(dpa) and k > g:
        c.gordon = dpa * (1 + g) / (k - g)
    if _pos(lpa) and k > g:
        c.dcf = lpa * (1 + g) / (k - g)
    # Lynch/PEGY: P/L justo = crescimento% + DY% (precisa de crescimento positivo)
    if _pos(lpa) and growth_pct is not None and not (
            isinstance(growth_pct, float) and math.isnan(growth_pct)) and growth_pct > 0:
        fair_pl = min(growth_pct + (dy_pct if _pos(dy_pct) else 0.0), 30.0)  # teto sensato
        c.lynch = lpa * fair_pl

    vals = [x for x in (c.bazin, c.graham, c.gordon, c.dcf, c.lynch) if _pos(x)]
    if vals:
        c.media = float(np.mean(vals))
        c.mediana = float(np.median(vals))
        c.upside_pct = (c.mediana / price - 1) * 100.0
        c.upside_media_pct = (c.media / price - 1) * 100.0
    return c
