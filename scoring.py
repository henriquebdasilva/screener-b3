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


def build_dataframe(funds: list[Fundamentals], pl_min: float = 2.0,
                    dy_max: float = 20.0) -> pd.DataFrame:
    rows = []
    for f in funds:
        fin = f.is_financial()
        # múltiplos <= 0 são dado inválido, não "barato" -> viram NaN (não entram no rank)
        pvp_v = f.pvp if (pd.notna(f.pvp) and f.pvp > 0) else np.nan
        ev_v = f.ev_ebitda if (pd.notna(f.ev_ebitda) and f.ev_ebitda > 0) else np.nan
        pl_v = f.pl if (pd.notna(f.pl) and f.pl > 0) else np.nan
        # dado suspeito (erro de fonte): P/L irreal (não-financeira) ou DY médio impossível.
        # Neutraliza no SCORE (colunas *_s); o dado bruto continua p/ o teto (que tem guarda).
        dy_for = f.dy_medio if pd.notna(f.dy_medio) else f.dy
        pl_susp = (not fin) and pd.notna(f.pl) and f.pl < pl_min
        dy_susp = pd.notna(dy_for) and dy_for >= dy_max
        motivos = []
        if pl_susp:
            motivos.append(f"P/L={f.pl:.2f}<{pl_min:g}")
        if dy_susp:
            motivos.append(f"DY5a={dy_for:.1f}%>={dy_max:g}")

        # crescimento p/ o PEG: sustentável (ROE×(1−payout)); fallback = CAGR de receita.
        # se P/L suspeito, não usa (fica com cresc_5a) e o PEG sai do Value.
        dy_growth = np.nan if dy_susp else dy_for
        g_est = None if pl_susp else sustainable_growth(f.roe, dy_growth, f.pl)
        growth_peg = g_est if (g_est is not None and g_est > 0) else f.cresc_5a
        peg = (f.pl / growth_peg) if (not pl_susp and pd.notna(f.pl)
                                      and pd.notna(growth_peg) and growth_peg > 0) else np.nan
        rows.append({
            "ticker": f.ticker, "setor": f.setor, "financeira": fin,
            "pl": f.pl, "pvp": f.pvp, "dy": f.dy,
            "dy_div": dy_for,                       # bruto (teto/exibição)
            # ranking Value: múltiplos <= 0 são dado inválido (não é "barato") -> NaN
            "pl_s": np.nan if pl_susp else pl_v,
            "pvp_s": pvp_v,
            "ev_ebitda_s": np.nan if fin else ev_v,
            "dy_div_s": np.nan if dy_susp else dy_for,  # p/ ranking Dividend (neutralizado)
            "dado_suspeito": "; ".join(motivos),
            "roe": f.roe, "roic": f.roic, "mrg_liq": f.mrg_liq,
            "ev_ebitda": np.nan if fin else f.ev_ebitda,
            "div_liq_ebitda": np.nan if fin else f.div_liq_ebitda,
            "div_liq_patrim_src": np.nan if fin else f.div_liq_patrim,
            "div_patrim": np.nan if fin else f.div_patrim,
            "liq_corr": np.nan if fin else f.liq_corr,
            "cresc_5a": f.cresc_5a,
            "growth_est": g_est if g_est is not None else np.nan,
            "peg": peg,
            "lpa": f.lpa, "payout_ratio": f.payout_ratio, "pl_fut": f.pl_fut,
            "roa": f.roa,
        })
    return pd.DataFrame(rows).set_index("ticker")


def score_universe(funds: list[Fundamentals], pl_min: float = 2.0,
                   dy_max: float = 20.0, selic: float = 14.0) -> pd.DataFrame:
    df = build_dataframe(funds, pl_min=pl_min, dy_max=dy_max)
    if df.empty:
        return df

    # notas normalizadas (n-XXX)
    nq = {
        "roe": _rank_score(df["roe"], True),
        "roic": _rank_score(df["roic"], True),
        "mrg_liq": _rank_score(df["mrg_liq"], True),
    }
    nv = {
        "pl": _rank_score(df["pl_s"], False),        # P/L neutralizado se suspeito/inválido
        "pvp": _rank_score(df["pvp_s"], False),      # P/VP <= 0 (inválido) fora do ranking
        "peg": _rank_score(df["peg"], False),
        "ev_ebitda": _rank_score(df["ev_ebitda_s"], False),
    }
    # Alavancagem AJUSTADA pelo retorno: DL/EBITDA ÷ (ROIC/Selic). Quando o ROIC supera o
    # custo de capital (Selic), a dívida "pesa menos"; quando fica abaixo, pesa mais. Assim o
    # Safety cruza ROIC com dívida líquida. Fallback ao DL/EBITDA cru quando falta ROIC.
    _selic = float(selic) if selic and selic > 0 else 14.0
    _fator = (pd.to_numeric(df["roic"], errors="coerce") / _selic).clip(lower=0.4, upper=2.5)
    _lev = pd.to_numeric(df["div_liq_ebitda"], errors="coerce")
    df["lev_roic_adj"] = _lev / _fator
    df["lev_roic_adj"] = df["lev_roic_adj"].fillna(_lev)      # sem ROIC -> alavancagem crua
    ns = {
        "div_liq_ebitda": _rank_score(df["lev_roic_adj"], False),
        "liq_corr": _rank_score(df["liq_corr"], True),
        "div_patrim": _rank_score(df["div_patrim"], False),
    }
    nd = _rank_score(df["dy_div_s"], True)           # DY neutralizado se suspeito

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


# ---------------- Ciclicidade setorial (penaliza o Safety de setores cíclicos) ----------
# 1.0 = altamente cíclico  ...  0.0 = defensivo. Chaves casadas por substring (normalizado),
# cobrindo os setores do yfinance (inglês) e alguns sinônimos em português.
SECTOR_CYCLICALITY = {
    "basic materials": 1.0, "materiais basicos": 1.0, "materiais": 1.0, "mineracao": 1.0,
    "siderurgia": 1.0, "papel": 0.9, "quimic": 0.9,
    "energy": 0.9, "energia": 0.9, "petroleo": 0.9, "oil": 0.9, "gas": 0.9,
    "consumer cyclical": 0.9, "consumo ciclico": 0.9, "consumo discricionario": 0.9,
    "discricionar": 0.9, "varejo": 0.8, "vestuario": 0.9, "auto": 0.9, "viagens": 0.9,
    "turismo": 0.9,
    "real estate": 0.8, "imobiliar": 0.8, "construc": 0.85, "incorporac": 0.85,
    "industrials": 0.7, "industrial": 0.7, "industriais": 0.7, "bens industriais": 0.7,
    "transporte": 0.7, "aere": 0.95, "airlines": 0.95,
    "technology": 0.5, "tecnologia": 0.5,
    "communication services": 0.4, "comunica": 0.4, "midia": 0.5,
    "financial services": 0.4, "financ": 0.4, "banco": 0.4, "insurance": 0.3, "seguro": 0.3,
    "healthcare": 0.2, "saude": 0.2,
    "consumer defensive": 0.15, "consumo defensivo": 0.15, "consumo nao ciclico": 0.15,
    "consumo basico": 0.15, "alimentos": 0.2, "bebidas": 0.15,
    "utilities": 0.1, "utilidade publica": 0.1, "energia eletrica": 0.1, "saneamento": 0.1,
    "servicos publicos": 0.1, "servico publico": 0.1, "eletrica": 0.1, "transmissao": 0.1,
    "agua": 0.1, "telecom": 0.3,
}
CYCLICALITY_DEFAULT = 0.0     # setor desconhecido -> não penaliza (conservador)


def cyclicality(setor) -> float:
    """Fator de ciclicidade 0..1 a partir do nome do setor (0 = defensivo).
    Usa o rótulo MAIS ESPECÍFICO (substring mais longa) — ex.: 'energia elétrica' (0.1)
    prevalece sobre 'energia' (0.9), que é para petróleo/óleo & gás."""
    if not setor:
        return CYCLICALITY_DEFAULT
    import unicodedata
    s = unicodedata.normalize("NFKD", str(setor)).encode("ascii", "ignore").decode().lower()
    best_key = None
    for chave in SECTOR_CYCLICALITY:
        if chave in s and (best_key is None or len(chave) > len(best_key)):
            best_key = chave
    return SECTOR_CYCLICALITY[best_key] if best_key is not None else CYCLICALITY_DEFAULT
