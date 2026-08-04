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

MARKETCAP_MIN = 300_000_000.0
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
    roe_ge_selic: object = None
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


def evaluate(row: pd.Series, smeans: dict, selic_pct: float,
             market_cap=None, insider_sell_relevante=None,
             is_financial: bool = False) -> Checklist:
    c = Checklist()
    setor = row.get("setor", "") or ""
    sm = smeans.get(setor, {})

    c.roe_ge_selic = _ge(row.get("roe"), selic_pct)
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
    c.marketcap_ok = None if mc is None else bool(mc >= MARKETCAP_MIN)

    if insider_sell_relevante is None:
        c.insider_ok = None                # n/d
    else:
        c.insider_ok = (not bool(insider_sell_relevante))

    flags = [c.roe_ge_selic, c.roe_ge_setor, c.roic_ge_setor, c.margem_ge_15,
             c.cagr_ge_setor, c.divida_ok, c.marketcap_ok, c.insider_ok]
    aplicaveis = [f for f in flags if f is not None]
    c.criterios_aplicaveis = len(aplicaveis)
    c.criterios_ok = sum(1 for f in aplicaveis if f)
    c.passa_checklist = bool(aplicaveis) and all(aplicaveis)
    return c
