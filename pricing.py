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


def sustainable_growth(roe_pct, dy_pct, pl, cap: float = 15.0):
    """Crescimento sustentável g = ROE × (1 − payout), em %.

    payout = DPA/LPA = (DY% × preço) / (preço/PL) = DY%/100 × PL.
    Usa NÍVEIS (não razão entre lucros) — sem raiz de negativo. Retorna None quando não é
    confiável (ROE ≤ 0, payout fora de [0,1], dados ausentes), p/ o chamador cair no
    CAGR de receita. `cap` limita o resultado (evita ROE/alavancagem atípicos distorcerem).
    """
    def _f(x):
        try:
            x = float(x)
            return x if not math.isnan(x) else None
        except Exception:
            return None
    roe, dy, pl = _f(roe_pct), _f(dy_pct), _f(pl)
    if roe is None or roe <= 0:
        return None
    payout = (dy / 100.0) * pl if (dy is not None and dy > 0 and pl is not None and pl > 0) else 0.0
    if payout < 0 or payout > 1:
        return None
    g = roe * (1 - payout)
    if cap is not None:
        g = min(g, cap)
    return g


@dataclass
class Ceilings:
    bazin: float = math.nan
    graham: float = math.nan
    gordon: float = math.nan
    dcf: float = math.nan
    lynch: float = math.nan
    projetivo: float = math.nan         # Bazin projetivo: LPA×(1+g)×payout / DY-alvo
    graham_selic: float = math.nan      # Graham ajustado à taxa de juros (Selic)
    mult_ebitda: float = math.nan       # múltiplo-alvo EV/EBITDA (setor)
    media: float = math.nan
    mediana: float = math.nan
    ajustado: float = math.nan          # mediana × (1 − desconto): margem de segurança
    desconto: float = math.nan          # fator de desconto aplicado (ex.: 0.10)
    upside_pct: float = math.nan        # ajustado/preço − 1 (headline, conservador)
    upside_media_pct: float = math.nan  # media/preço − 1 (bruto, referência)
    bazin_yield: float = math.nan       # yield-alvo do Bazin usado (ex.: Selic)
    n_metodos: int = 0                  # métodos que entraram no consolidado (pós-outlier)
    confiavel: bool = True              # False = métodos discordam demais / upside absurdo
    dispersao: float = math.nan         # max/min dos métodos (antes do descarte de outlier)
    k: float = math.nan
    g: float = math.nan

    def as_dict(self):
        return asdict(self)


def _pos(x) -> bool:
    return x is not None and not (isinstance(x, float) and math.isnan(x)) and x > 0


def compute_ceilings(price: float, pl: float, pvp: float, dy_pct: float,
                     growth_pct: Optional[float], selic_pct: float = 15.0,
                     bazin_yield: Optional[float] = None, premium: float = 0.0,
                     g_default: float = 0.04, g_cap: float = 0.06,
                     safety_discount: float = 0.10,
                     outlier_mult: float = 2.5,
                     is_financial: bool = False,
                     pl_min: float = 2.5, pl_max: float = 150.0,
                     max_upside: float = 200.0, raw_disp_max: float = 8.0,
                     eps_real: float = None, payout: float = None,
                     proj_yield: float = 0.06, proj_g_cap: float = 0.15,
                     ev_ebitda: float = None, div_liq_ebitda: float = None,
                     target_ev_ebitda: float = None, graham_g_cap: float = 15.0) -> Ceilings:
    c = Ceilings()
    if not _pos(price):
        return c

    # LPA/VPA/DPA. O guarda de confiabilidade (dispersão + upside) captura P/L implausível
    # pela discordância entre métodos (ex.: dividendo ~0 vs lucro inflado por P/L errado).
    lpa = price / pl if (_pos(pl) and pl <= pl_max) else math.nan
    vpa = price / pvp if _pos(pvp) else math.nan
    dpa = (dy_pct / 100.0) * price if _pos(dy_pct) else math.nan

    k = selic_pct / 100.0 + premium
    g = (growth_pct / 100.0) if (growth_pct is not None and not
         (isinstance(growth_pct, float) and math.isnan(growth_pct)) and growth_pct > 0) else g_default
    g = min(g, g_cap, k - 0.01)          # conservador e sempre < k
    c.k, c.g = k, g
    byield = bazin_yield if (bazin_yield and bazin_yield > 0) else (selic_pct / 100.0)
    c.bazin_yield = byield

    if _pos(dpa):
        c.bazin = dpa / byield
    if _pos(lpa) and _pos(vpa):
        c.graham = math.sqrt(22.5 * lpa * vpa)
    if _pos(dpa) and k > g:
        c.gordon = dpa * (1 + g) / (k - g)
    if _pos(lpa) and k > g:
        c.dcf = lpa * (1 + g) / (k - g)
    if _pos(lpa) and growth_pct is not None and not (
            isinstance(growth_pct, float) and math.isnan(growth_pct)) and growth_pct > 0:
        fair_pl = min(growth_pct + (dy_pct if _pos(dy_pct) else 0.0), 30.0)
        c.lynch = lpa * fair_pl

    # Teto projetivo (à la Hannah): LPA×(1+g)×payout ÷ DY-alvo (fixo).
    # LPA real (yfinance) ou preço/PL; payout: usa o passado (payout médio) se houver, senão
    # o implícito (DPA médio/LPA); DY-alvo = proj_yield (fixo, ex.: 6%).
    eps = eps_real if _pos(eps_real) else lpa
    pay = payout if (payout is not None and 0 < payout <= 1.5) else \
        ((dpa / eps) if (_pos(dpa) and _pos(eps)) else math.nan)
    if _pos(pay):
        pay = min(pay, 1.0)                             # payout > 100% não é sustentável
    gp = (growth_pct / 100.0) if (growth_pct is not None and not
          (isinstance(growth_pct, float) and math.isnan(growth_pct)) and growth_pct > 0) else 0.0
    gp = min(gp, proj_g_cap)
    if _pos(eps) and _pos(pay) and proj_yield and proj_yield > 0:
        c.projetivo = eps * (1 + gp) * pay / proj_yield

    # Graham ajustado à Selic: LPA × (8,5 + 2g) × 4,4 / Y  (Y = Selic %, g em pontos %)
    if _pos(lpa) and selic_pct and selic_pct > 0:
        g_pct = growth_pct if (growth_pct is not None and not
                (isinstance(growth_pct, float) and math.isnan(growth_pct))
                and growth_pct > 0) else 0.0
        g_pct = min(g_pct, graham_g_cap)
        c.graham_selic = lpa * (8.5 + 2.0 * g_pct) * 4.4 / selic_pct

    # Múltiplo-alvo EV/EBITDA: preço a que a ação negociaria no múltiplo-alvo (mediana do
    # setor). Deriva de EBITDA implícito: preço × (alvo − DL/EBITDA)/(EV/EBITDA − DL/EBITDA).
    if (target_ev_ebitda and target_ev_ebitda > 0 and _pos(ev_ebitda)
            and div_liq_ebitda is not None and not (isinstance(div_liq_ebitda, float)
            and math.isnan(div_liq_ebitda))):
        denom = ev_ebitda - div_liq_ebitda          # = valor de mercado / EBITDA (>0)
        if denom > 0.1:
            val = price * (target_ev_ebitda - div_liq_ebitda) / denom
            if val > 0:
                c.mult_ebitda = val

    if is_financial:
        candidates = (c.bazin, c.gordon, c.dcf, c.projetivo)
    else:
        candidates = (c.bazin, c.graham, c.gordon, c.dcf, c.lynch, c.projetivo,
                      c.graham_selic, c.mult_ebitda)
    vals = [x for x in candidates if _pos(x)]
    if vals:
        # dispersão CRUA (antes do descarte) — sinaliza inputs inconsistentes
        c.dispersao = max(vals) / min(vals) if min(vals) > 0 else math.inf
        med0 = float(np.median(vals))
        if outlier_mult and outlier_mult > 0 and med0 > 0 and len(vals) >= 3:
            kept = [x for x in vals if (med0 / outlier_mult) <= x <= med0 * outlier_mult]
            vals = kept if len(kept) >= 2 else vals
        c.n_metodos = len(vals)
        c.media = float(np.mean(vals))
        c.mediana = float(np.median(vals))
        c.desconto = safety_discount
        c.ajustado = c.mediana * (1 - safety_discount)
        c.upside_pct = (c.ajustado / price - 1) * 100.0
        c.upside_media_pct = (c.media / price - 1) * 100.0
        # confiabilidade: métodos discordam demais OU upside implausível -> não confiar
        if (raw_disp_max and c.dispersao > raw_disp_max) or \
           (max_upside and max_upside > 0 and c.upside_pct > max_upside):
            c.confiavel = False
            c.media = c.mediana = c.ajustado = math.nan
            c.upside_pct = c.upside_media_pct = math.nan
    return c
