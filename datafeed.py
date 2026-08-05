# -*- coding: utf-8 -*-
"""
Camada de dados.

- FUNDAMENTOS: usa a biblioteca `fundamentus` (raspa fundamentus.com.br, ótima cobertura
  para a B3). Se indisponível, cai para o `yfinance` (.info). Campos ausentes viram NaN e
  simplesmente não entram no ranking daquele indicador (mesma lógica de "média ignora vazio"
  usada na planilha).
- PREÇOS (OHLCV) para o rompimento gráfico: `yfinance` (histórico diário, já ajustado).

Nenhuma fonte é 100%% confiável para todo o universo — o app é defensivo por design.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional

import pandas as pd

from universe import to_yahoo

# -------- FUNDAMENTOS --------

@dataclass
class Fundamentals:
    ticker: str
    pl: float = math.nan            # Preço/Lucro
    pvp: float = math.nan           # Preço/Valor Patrimonial
    dy: float = math.nan            # Dividend Yield (%)
    roe: float = math.nan           # ROE (%)
    roic: float = math.nan          # ROIC (%)
    mrg_liq: float = math.nan       # Margem líquida (%)
    ev_ebitda: float = math.nan     # EV/EBITDA
    div_liq_ebitda: float = math.nan  # Dívida líquida/EBITDA
    div_patrim: float = math.nan    # Dívida/Patrimônio
    liq_corr: float = math.nan      # Liquidez corrente
    cresc_5a: float = math.nan      # Crescimento receita 5a (%) -> proxy p/ PEG
    market_cap: float = math.nan    # Valor de mercado (R$)
    setor: str = ""

    def is_financial(self) -> bool:
        """Bancos/seguros/holdings: alguns indicadores não se aplicam."""
        s = (self.setor or "").lower()
        return any(k in s for k in (
            "financ", "banco", "bank", "segur", "insurance", "previd", "holding",
            "bolsa", "exchange",
        ))


# ---- fundamentus (primário) ----
@lru_cache(maxsize=1)
def _fundamentus_table() -> Optional[pd.DataFrame]:
    try:
        import fundamentus  # type: ignore
    except Exception:
        return None
    for fn in ("get_resultado_raw", "get_resultado"):
        try:
            df = getattr(fundamentus, fn)()
            df.index = [str(i).upper() for i in df.index]
            return df
        except Exception:
            continue
    return None


# Nomes de coluna candidatos (variam por versão do pacote / raw vs. formatado)
_COLS = {
    "pl":            ["pl", "p/l", "P/L"],
    "pvp":           ["pvp", "p/vp", "P/VP"],
    "dy":            ["dy", "div.yield", "Div.Yield"],
    "roe":           ["roe", "ROE"],
    "roic":          ["roic", "ROIC"],
    "mrg_liq":       ["mrgliq", "marg. líquida", "Marg. Líquida", "margliq"],
    "ev_ebitda":     ["evebitda", "ev/ebitda", "EV/EBITDA"],
    "div_liq_ebitda":["divliq_ebitda", "dívida líquida/ebitda", "divliqebitda"],
    "div_patrim":    ["divbpatr", "dívbruta/patrim.", "divb_patr", "div_patrim"],
    "liq_corr":      ["liqc", "liquidez corr.", "liqcorr", "liquidez corrente"],
    "cresc_5a":      ["c5y", "cres. rec (5a)", "cresc_rec_5a", "cresc5a"],
    "setor":         ["setor", "Setor"],
}


def _pick(row: pd.Series, keys: list[str]) -> float:
    for k in keys:
        if k in row.index and pd.notna(row[k]):
            return row[k]
        lk = k.lower()
        for c in row.index:
            if str(c).lower() == lk and pd.notna(row[c]):
                return row[c]
    return math.nan


def _to_float(x) -> float:
    if isinstance(x, str):
        x = x.replace("%", "").replace(".", "").replace(",", ".").strip()
    try:
        return float(x)
    except Exception:
        return math.nan


def _from_fundamentus(ticker: str) -> Optional[Fundamentals]:
    df = _fundamentus_table()
    if df is None or ticker.upper() not in df.index:
        return None
    row = df.loc[ticker.upper()]
    if isinstance(row, pd.DataFrame):
        row = row.iloc[0]
    f = Fundamentals(ticker=ticker.upper())
    for attr, keys in _COLS.items():
        val = _pick(row, keys)
        if attr == "setor":
            f.setor = "" if (val is None or (isinstance(val, float) and math.isnan(val))) else str(val)
        else:
            setattr(f, attr, _to_float(val))
    # fundamentus costuma trazer dy/roe/roic/margem já em fração (0.08) OU em %.
    for pct_attr in ("dy", "roe", "roic", "mrg_liq", "cresc_5a"):
        v = getattr(f, pct_attr)
        if pd.notna(v) and abs(v) < 1.5:   # provavelmente fração -> vira %
            setattr(f, pct_attr, v * 100.0)
    return f


# ---- yfinance (fallback) ----
def _from_yfinance(ticker: str) -> Fundamentals:
    f = Fundamentals(ticker=ticker.upper())
    try:
        import yfinance as yf
        info = yf.Ticker(to_yahoo(ticker)).info or {}
    except Exception:
        return f

    def g(*keys):
        for k in keys:
            v = info.get(k)
            if v is not None:
                try:
                    return float(v)
                except Exception:
                    pass
        return math.nan

    f.pl = g("trailingPE")
    f.pvp = g("priceToBook")
    dy = g("dividendYield")
    f.dy = dy * 100 if pd.notna(dy) and dy < 1.5 else dy
    roe = g("returnOnEquity")
    f.roe = roe * 100 if pd.notna(roe) else math.nan
    mrg = g("profitMargins")
    f.mrg_liq = mrg * 100 if pd.notna(mrg) else math.nan
    f.ev_ebitda = g("enterpriseToEbitda")
    de = g("debtToEquity")                       # yfinance devolve em % (ex.: 92.0)
    f.div_patrim = de / 100 if pd.notna(de) else math.nan
    f.liq_corr = g("currentRatio")
    eg = g("earningsGrowth", "revenueGrowth")
    f.cresc_5a = eg * 100 if pd.notna(eg) else math.nan
    f.market_cap = g("marketCap")
    f.setor = str(info.get("sector") or info.get("industry") or "")
    return f


def get_fundamentals(ticker: str) -> Fundamentals:
    f = _from_fundamentus(ticker)
    if f is None:
        return _from_yfinance(ticker)
    # completa buracos com yfinance
    yf_needed = any(pd.isna(getattr(f, a)) for a in
                    ("pl", "pvp", "dy", "roe", "ev_ebitda", "div_patrim",
                     "liq_corr", "market_cap"))
    if yf_needed:
        yf_f = _from_yfinance(ticker)
        for a in ("pl", "pvp", "dy", "roe", "roic", "mrg_liq", "ev_ebitda",
                  "div_liq_ebitda", "div_patrim", "liq_corr", "cresc_5a",
                  "market_cap"):
            if pd.isna(getattr(f, a)) and pd.notna(getattr(yf_f, a)):
                setattr(f, a, getattr(yf_f, a))
        if not f.setor and yf_f.setor:
            f.setor = yf_f.setor
    return f


# -------- PREÇOS (OHLCV) --------
def get_prices(ticker: str, period: str = "5y", interval: str = "1d") -> Optional[pd.DataFrame]:
    """Retorna DataFrame OHLCV (+coluna Dividends) ou None. 5 anos p/ o DY médio."""
    try:
        import yfinance as yf
        df = yf.Ticker(to_yahoo(ticker)).history(
            period=period, interval=interval, auto_adjust=True, actions=True
        )
    except Exception:
        return None
    if df is None or df.empty:
        return None
    df = df.rename(columns=str.title)
    keep = [c for c in ("Open", "High", "Low", "Close", "Volume", "Dividends")
            if c in df.columns]
    df = df[keep].dropna(subset=[c for c in keep if c != "Dividends"])
    return df if len(df) >= 60 else None


def avg_annual_dy(px: Optional[pd.DataFrame], years: int = 5) -> float:
    """DY médio dos últimos `years` anos = média de (proventos do ano / preço médio do ano).

    Suaviza dividendos extraordinários que distorcem o DY de 12 meses. NaN se não houver
    histórico de proventos (ex.: IPO recente) -> o chamador cai no DY corrente.
    """
    if px is None or "Dividends" not in px.columns or "Close" not in px.columns:
        return math.nan
    df = px[["Close", "Dividends"]].dropna()
    if df.empty:
        return math.nan
    yr = df.index.year
    div_y = df["Dividends"].groupby(yr).sum()
    px_y = df["Close"].groupby(yr).mean()
    dy_y = (div_y / px_y * 100.0)
    dy_y = dy_y[dy_y > 0].dropna()
    if dy_y.empty:
        return math.nan
    return float(dy_y.tail(years).mean())


# -------- SELIC (Banco Central) --------
def get_selic(default: float = 15.0) -> float:
    """Selic meta anual (%). Tenta a API do BCB (série 432); cai no env SELIC ou default.

    A rede do GitHub Actions alcança api.bcb.gov.br normalmente.
    """
    import os
    env = os.getenv("SELIC")
    if env:
        try:
            return float(str(env).replace(",", "."))
        except Exception:
            pass
    try:
        import requests
        url = ("https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados/"
               "ultimos/1?formato=json")
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        return float(str(r.json()[-1]["valor"]).replace(",", "."))
    except Exception:
        return default


# -------- INSIDERS (Fundamentus) --------
def get_insider_sells(ticker: str, meses: int = 12,
                      min_volume: float = 1_000_000.0):
    """Best-effort: houve VENDA expressiva de insiders nos últimos `meses`?

    Raspa a página de insiders do Fundamentus e soma o volume de vendas recentes.
    Retorna:
        True  -> houve venda relevante (>= min_volume no período)
        False -> não houve venda relevante
        None  -> não deu para avaliar (página mudou, sem dados, erro de rede)

    Como é raspagem, é frágil por natureza; em qualquer dúvida retorna None (n/d) e o
    critério simplesmente não pesa. Desligue com env INSIDER_CHECK=0.
    """
    import os
    if os.getenv("INSIDER_CHECK", "1") == "0":
        return None
    try:
        import io
        import datetime as _dt
        import requests
        url = f"https://www.fundamentus.com.br/insiders.php?papel={ticker.upper()}&tipo=2"
        headers = {"User-Agent": "Mozilla/5.0 (screener)"}
        html = requests.get(url, headers=headers, timeout=20).text
        tables = pd.read_html(io.StringIO(html), decimal=",", thousands=".")
        if not tables:
            return None
        # escolhe a maior tabela (a de movimentações)
        df = max(tables, key=lambda t: t.shape[0]).copy()
        df.columns = [str(c).strip().lower() for c in df.columns]

        col_data = next((c for c in df.columns if "data" in c or "mês" in c or "mes" in c), None)
        col_tipo = next((c for c in df.columns if "tipo" in c or "opera" in c or "movim" in c), None)
        col_vol = next((c for c in df.columns if "volume" in c or "valor" in c or "r$" in c), None)
        if not (col_data and col_vol):
            return None

        dt = pd.to_datetime(df[col_data], errors="coerce", dayfirst=True)
        corte = pd.Timestamp(_dt.date.today()) - pd.DateOffset(months=meses)
        recent = df[dt >= corte]
        if col_tipo:
            mask = recent[col_tipo].astype(str).str.contains("venda", case=False, na=False)
            recent = recent[mask]
        vol = pd.to_numeric(recent[col_vol], errors="coerce").fillna(0).abs().sum()
        return bool(vol >= min_volume)
    except Exception:
        return None
