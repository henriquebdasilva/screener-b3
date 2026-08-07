# -*- coding: utf-8 -*-
"""
Motor de scores fundamentalistas — replica a metodologia da planilha.

- Normalização por RANKING dentro do universo varrido (0–100, melhor = 100), robusta a
  outliers. Indicadores "quanto menor melhor" (P/L, P/VP, PEG, EV/EBITDA, Dív.Líq/EBITDA,
  Dív/Patrim) são invertidos.
- Tratamento por setor: bancos/seguros/holdings não usam EV/EBITDA, Dív.Líq/EBITDA,
  liquidez corrente nem Dív/Patrim (viram NaN e saem da média daquele bloco).
- PEG = P/L ÷ crescimento esperado (proxy: crescimento de receita 5a). 'n/m' se <= 0.
- Blocos:
    Quality  = média[ n-ROE, n-ROIC, n-Margem Líq. ]
    Value    = média[ n-P/L, n-P/VP, n-PEG, n-EV/EBITDA ]
    Safety   = média[ n-Dív.Líq/EBITDA, n-Liq.Corr, n-Dív/Patrim ]   (não-financeiras)
    Dividend = n-DY
    Investment = 0.35*Q + 0.30*V + 0.20*S + 0.15*D
       (pesos re-normalizados quando algum bloco é NaN — ex.: banco sem Safety)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from datafeed import Fundamentals
from pricing import sustainable_growth

W = {"quality": 0.45, "value": 0.25, "safety": 0.20, "dividend": 0.10}


def _rank_score(s: pd.Series, higher_better: bool) -> pd.Series:
    """0–100 por ranking (percentil). NaN permanece NaN."""
    r = s.rank(method="average", ascending=higher_better)
    n = r.notna().sum()
    if n <= 1:
        return pd.Series(np.where(r.notna(), 100.0, np.nan), index=s.index)
    return (r - 1) / (n - 1) * 100.0


def _wmean(vals: dict[str, float], weights: dict[str, float]) -> float:
    num = den = 0.0
    for k, w in weights.items():
        v = vals.get(k, np.nan)
        if pd.notna(v):
            num += w * v
            den += w
    return num / den if den > 0 else np.nan


def build_dataframe(funds: list[Fundamentals]) -> pd.DataFrame:
    rows = []
    for f in funds:
        # crescimento p/ o PEG: sustentável (ROE×(1−payout)); fallback = CAGR de receita
        dy_for = f.dy_medio if pd.notna(f.dy_medio) else f.dy
        g_est = sustainable_growth(f.roe, dy_for, f.pl)
        growth_peg = g_est if (g_est is not None and g_est > 0) else f.cresc_5a
        peg = (f.pl / growth_peg) if (pd.notna(f.pl) and pd.notna(growth_peg)
                                      and growth_peg > 0) else np.nan
        fin = f.is_financial()
        rows.append({
            "ticker": f.ticker, "setor": f.setor, "financeira": fin,
            "pl": f.pl, "pvp": f.pvp, "dy": f.dy,
            "dy_div": dy_for,                       # DY usado no score de dividendo (médio)
            "roe": f.roe, "roic": f.roic, "mrg_liq": f.mrg_liq,
            "ev_ebitda": np.nan if fin else f.ev_ebitda,
            "div_liq_ebitda": np.nan if fin else f.div_liq_ebitda,
            "div_patrim": np.nan if fin else f.div_patrim,
            "liq_corr": np.nan if fin else f.liq_corr,
            "cresc_5a": f.cresc_5a,
            "growth_est": g_est if g_est is not None else np.nan,
            "peg": peg,
        })
    return pd.DataFrame(rows).set_index("ticker")


def score_universe(funds: list[Fundamentals]) -> pd.DataFrame:
    df = build_dataframe(funds)
    if df.empty:
        return df

    # notas normalizadas (n-XXX)
    nq = {
        "roe": _rank_score(df["roe"], True),
        "roic": _rank_score(df["roic"], True),
        "mrg_liq": _rank_score(df["mrg_liq"], True),
    }
    nv = {
        "pl": _rank_score(df["pl"], False),
        "pvp": _rank_score(df["pvp"], False),
        "peg": _rank_score(df["peg"], False),
        "ev_ebitda": _rank_score(df["ev_ebitda"], False),
    }
    ns = {
        "div_liq_ebitda": _rank_score(df["div_liq_ebitda"], False),
        "liq_corr": _rank_score(df["liq_corr"], True),
        "div_patrim": _rank_score(df["div_patrim"], False),
    }
    nd = _rank_score(df["dy_div"], True)

    def block_mean(dct: dict[str, pd.Series]) -> pd.Series:
        return pd.concat(dct.values(), axis=1).mean(axis=1, skipna=True)

    df["quality"] = block_mean(nq)
    df["value"] = block_mean(nv)
    df["safety"] = block_mean(ns)
    df["dividend"] = nd

    df["investment"] = [
        _wmean({"quality": q, "value": v, "safety": s, "dividend": d}, W)
        for q, v, s, d in zip(df["quality"], df["value"], df["safety"], df["dividend"])
    ]
    df = df.sort_values("investment", ascending=False)
    df["rank_invest"] = range(1, len(df) + 1)
    return df


def investment_series(df: pd.DataFrame) -> pd.Series:
    """Recalcula o Investment a partir das colunas de bloco (quality/value/safety/dividend),
    re-normalizando os pesos sobre os blocos disponíveis. Útil depois de preencher o Safety
    das financeiras (Basileia)."""
    def _wm(row):
        vals = {k: row.get(k) for k in W}
        return _wmean(vals, W)
    return df.apply(_wm, axis=1)
