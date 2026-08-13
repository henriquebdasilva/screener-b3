# -*- coding: utf-8 -*-
"""
Checklist de critérios fundamentalistas (merge com o Investment Score existente).

Critérios avaliados por papel (cada um vira Sim / Não / n/d):
  1. ROE ≥ Selic
  2. ROE ≥ média do setor
  3. ROIC ≥ média do setor
  4. Margem líquida ≥ 15%            (não se aplica a bancos/seguros -> n/a)
  5. CAGR 5a ≥ média do setor
  6. Dív.Líq/EBITDA < 3 E ≤ média do setor  (n/a para bancos/seguros)
  7. Market cap ≥ R$ 300 milhões
  8. Sem venda expressiva de insiders no último ano  (best-effort; n/d se indisponível)

- "vs setor" usa a média do próprio universo varrido naquele setor (limitação honesta).
- criterios_ok = quantos foram atendidos; criterios_aplicaveis = quantos deram p/ avaliar.
- passa_checklist = todos os aplicáveis atendidos.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

MARKETCAP_MIN = 500_000_000.0
MARGEM_MIN = 15.0
DIVIDA_MAX = 3.0


def _num(x):
    try:
        v = float(x)
        return v if not math.isnan(v) else None
    except Exception:
        return None


def sector_means(df: pd.DataFrame) -> dict:
    """Média por setor (dentro do universo) de roe, roic, div_liq_ebitda, cresc_5a."""
    out = {}
    for setor, g in df.groupby(df["setor"].fillna("")):
        out[setor] = {
            "roe": g["roe"].mean(skipna=True),
            "roic": g["roic"].mean(skipna=True),
            "div_liq_ebitda": g["div_liq_ebitda"].mean(skipna=True),
            "cresc_5a": g["cresc_5a"].mean(skipna=True),
        }
    return out


@dataclass
class Checklist:
    roe_roic_ge_selic: object = None
    roe_ge_setor: object = None
    roic_ge_setor: object = None
    margem_ge_15: object = None
    cagr_ge_setor: object = None
    divida_ok: object = None
    marketcap_ok: object = None
    insider_ok: object = None
    criterios_ok: int = 0
    criterios_aplicaveis: int = 0
    passa_checklist: bool = False

    def as_dict(self):
        d = self.__dict__.copy()
        return d


def _ge(a, b):
    a, b = _num(a), _num(b)
    if a is None or b is None:
        return None
    return bool(a >= b)


def _roe_or_roic_ge(roe, roic, bar) -> object:
    """True se ROE >= bar OU ROIC >= bar; False se algum disponível e nenhum atinge;
    None se ambos indisponíveis."""
    bar = _num(bar)
    vals = [x for x in (_num(roe), _num(roic)) if x is not None]
    if bar is None or not vals:
        return None
    return bool(any(v >= bar for v in vals))


def evaluate(row: pd.Series, smeans: dict, selic_pct: float,
             market_cap=None, insider_sell_relevante=None,
             is_financial: bool = False, require_roe_roic_selic: bool = True,
             marketcap_min: float = MARKETCAP_MIN) -> Checklist:
    c = Checklist()
    setor = row.get("setor", "") or ""
    sm = smeans.get(setor, {})

    c.roe_roic_ge_selic = (_roe_or_roic_ge(row.get("roe"), row.get("roic"), selic_pct)
                           if require_roe_roic_selic else None)
    c.roe_ge_setor = _ge(row.get("roe"), sm.get("roe"))
    c.roic_ge_setor = _ge(row.get("roic"), sm.get("roic"))
    c.cagr_ge_setor = _ge(row.get("cresc_5a"), sm.get("cresc_5a"))

    if is_financial:                       # não se aplica a bancos/seguros
        c.margem_ge_15 = None
        c.divida_ok = None
    else:
        m = _num(row.get("mrg_liq"))
        c.margem_ge_15 = None if m is None else bool(m >= MARGEM_MIN)
        d = _num(row.get("div_liq_ebitda"))
        dmed = _num(sm.get("div_liq_ebitda"))
        if d is None:
            c.divida_ok = None
        elif dmed is None:
            c.divida_ok = bool(d < DIVIDA_MAX)
        else:
            c.divida_ok = bool(d < DIVIDA_MAX and d <= dmed)

    mc = _num(market_cap)
    c.marketcap_ok = None if mc is None else bool(mc >= marketcap_min)

    if insider_sell_relevante is None:
        c.insider_ok = None                # n/d
    else:
        c.insider_ok = (not bool(insider_sell_relevante))

    flags = [c.roe_roic_ge_selic, c.roe_ge_setor, c.roic_ge_setor, c.margem_ge_15,
             c.cagr_ge_setor, c.divida_ok, c.marketcap_ok, c.insider_ok]
    aplicaveis = [f for f in flags if f is not None]
    c.criterios_aplicaveis = len(aplicaveis)
    c.criterios_ok = sum(1 for f in aplicaveis if f)
    c.passa_checklist = bool(aplicaveis) and all(aplicaveis)
    return c


# ---------------- Consistência (8 critérios que influenciam a nota) ----------------
@dataclass
class Consistency:
    mais_5a_bolsa: object = None
    sem_prejuizo_anual: object = None      # nos anos disponíveis (best-effort)
    lucro_20t: object = None               # 20 trimestres (n/d se dados insuficientes)
    div_ge5_5a: object = None              # DY >= 5% em todos os últimos 5 anos
    div_sem_corte: object = None           # sem corte relevante de dividendo em 5 anos
    roe_ge_10: object = None
    divida_menor_patrim: object = None     # Dív/Patrim < 1 (n/a p/ financeira)
    cresc_receita_5a: object = None
    cresc_lucro_5a: object = None          # best-effort
    ebitda_cresc_5a: object = None         # EBITDA crescente (best-effort)
    margem_cresc_5a: object = None         # margem líquida crescente (best-effort)
    roe_cresc_5a: object = None            # ROE crescente (best-effort)
    roic_cresc_5a: object = None           # ROIC crescente (best-effort; raramente disponível)
    n_ok: int = 0
    n_aplic: int = 0
    score: float = math.nan                # 0-100 = % dos aplicáveis atendidos

    def as_dict(self):
        return self.__dict__.copy()


def consistency(row, listed_y, div_ge5, ni_annual, ni_quarterly,
                is_financial: bool = False, div_no_cut=None,
                ebitda_by_year=None, margem_by_year=None, roe_by_year=None,
                roic_by_year=None) -> Consistency:
    from datafeed import trend_up
    c = Consistency()
    ly = _num(listed_y)
    c.mais_5a_bolsa = None if ly is None else bool(ly >= 5)
    c.div_ge5_5a = div_ge5 if isinstance(div_ge5, bool) else None
    c.div_sem_corte = div_no_cut if isinstance(div_no_cut, bool) else None

    roe = _num(row.get("roe"))
    c.roe_ge_10 = None if roe is None else bool(roe >= 10.0)

    if is_financial:
        c.divida_menor_patrim = None       # não se aplica a banco/seguro
    else:
        dp = _num(row.get("div_patrim"))
        c.divida_menor_patrim = None if dp is None else bool(dp < 1.0)

    cr = _num(row.get("cresc_5a"))
    c.cresc_receita_5a = None if cr is None else bool(cr > 0)

    # lucro (best-effort; yfinance p/ B3 é irregular) — ordem: recente -> antigo
    if ni_annual and len(ni_annual) >= 2:
        c.sem_prejuizo_anual = bool(all(x > 0 for x in ni_annual))
        c.cresc_lucro_5a = bool(ni_annual[0] > ni_annual[-1] > 0)
    if ni_quarterly and len(ni_quarterly) >= 20:
        c.lucro_20t = bool(all(x > 0 for x in ni_quarterly[:20]))

    # tendências crescentes em 5 anos (best-effort; None = sem dados suficientes)
    if ebitda_by_year:
        c.ebitda_cresc_5a = bool(trend_up(ebitda_by_year))
    if margem_by_year:
        c.margem_cresc_5a = bool(trend_up(margem_by_year))
    if roe_by_year:
        c.roe_cresc_5a = bool(trend_up(roe_by_year))
    if roic_by_year:
        c.roic_cresc_5a = bool(trend_up(roic_by_year))

    flags = [c.mais_5a_bolsa, c.sem_prejuizo_anual, c.lucro_20t, c.div_ge5_5a,
             c.div_sem_corte, c.roe_ge_10, c.divida_menor_patrim,
             c.cresc_receita_5a, c.cresc_lucro_5a, c.ebitda_cresc_5a,
             c.margem_cresc_5a, c.roe_cresc_5a, c.roic_cresc_5a]
    ap = [f for f in flags if f is not None]
    c.n_aplic = len(ap)
    c.n_ok = sum(1 for f in ap if f)
    c.score = (100.0 * c.n_ok / c.n_aplic) if ap else math.nan
    return c


def net_debt_to_equity(pvp, ev_ebitda, div_liq_ebitda):
    """Dív.Líq/Patrim DERIVADA dos índices do fundamentus (sem chamada extra):
        = (Dív.Líq/EBITDA × P/VP) / (EV/EBITDA − Dív.Líq/EBITDA).
    Retorna None quando instável (EBITDA implícito ~0/negativo, dados ausentes)."""
    pv = _num(pvp); ev = _num(ev_ebitda); dl = _num(div_liq_ebitda)
    if pv is None or pv <= 0 or ev is None or dl is None:
        return None
    denom = ev - dl                     # = ValorDeMercado/EBITDA (>0 se EBITDA>0)
    if denom <= 0.1:
        return None
    return dl * pv / denom
