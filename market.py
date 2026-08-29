"""Resumo de mercado: retornos de índices no ano (YTD) e no mês (MTD).

Fontes automáticas (yfinance). Fluxo estrangeiro e opções NÃO são cobertos por essas
fontes de forma confiável -> ficam 'n/d'. Tudo degrada com elegância (NaN) em falha.
"""
from __future__ import annotations

import math

# Proxies negociáveis/índices no yfinance. IFIX usa IFIX.SA (não ^IFIX, que não existe no Yahoo).
INDEX_SYMS = {
    "Ibovespa": "^BVSP",
    "Small Caps (SMAL11)": "SMAL11.SA",
    "IFIX": "IFIX.SA",   # Yahoo trata o IFIX como papel comum (IFIX.SA), não como índice (^IFIX)
}


def _period_returns(sym: str):
    """(YTD%, MTD%) de um símbolo via yfinance; (nan, nan) em falha."""
    try:
        import yfinance as yf
        h = yf.Ticker(sym).history(period="1y", auto_adjust=True)
        if h is None or h.empty:
            return (math.nan, math.nan)
        c = h["Close"].dropna()
        if len(c) < 2:
            return (math.nan, math.nan)
        last = float(c.iloc[-1])
        today = c.index[-1]
        yr = c[c.index.year == today.year]
        ytd = (last / float(yr.iloc[0]) - 1) * 100 if len(yr) else math.nan
        mo = c[(c.index.year == today.year) & (c.index.month == today.month)]
        mtd = (last / float(mo.iloc[0]) - 1) * 100 if len(mo) else math.nan
        return (ytd, mtd)
    except Exception:
        return (math.nan, math.nan)


def market_summary(selic_pct: float) -> dict:
    """Resumo: Selic, índices (YTD/MTD) e placeholders p/ o que não é automatizável."""
    indices = {}
    for name, sym in INDEX_SYMS.items():
        indices[name] = _period_returns(sym)
    return {
        "selic": selic_pct,
        "indices": indices,                 # {nome: (ytd, mtd)}
        "fluxo_estrangeiro": None,           # n/d (B3 gated; sem fonte automática)
        "opcoes": None,                      # n/d (yfinance não cobre opções da B3)
    }


def market_mood(df) -> dict:
    """% em alta / lateral / baixa por origem (BOVA11/SMALL11) e por setor.

    Usa a coluna 'trend' (classificação MM21) já calculada para cada papel do universo.
    """
    def _breadth(sub):
        n = len(sub)
        if not n:
            return None
        t = sub["trend"].fillna("")
        up = int((t == "Em Alta").sum())
        down = int((t == "Em Baixa").sum())
        flat = n - up - down
        return {"n": n, "alta": round(100 * up / n),
                "baixa": round(100 * down / n), "lateral": round(100 * flat / n)}

    out = {"indices": {}, "setores": {}}
    if df is None or "trend" not in getattr(df, "columns", []):
        return out
    for label, key in (("BOVA11", "BOVA11"), ("SMALL11", "SMALL11")):
        sub = df[df["origem"].astype(str).str.contains(key, na=False)]
        b = _breadth(sub)
        if b:
            out["indices"][label] = b
    for setor, sub in df.groupby(df["setor"].fillna("(sem setor)")):
        if setor and len(sub) >= 3:          # ignora setores com amostra ínfima
            b = _breadth(sub)
            if b:
                out["setores"][setor] = b
    return out
