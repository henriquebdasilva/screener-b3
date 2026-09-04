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
    div_patrim: float = math.nan    # Dívida bruta/Patrimônio (fundamentus)
    div_liq_patrim: float = math.nan  # Dívida líquida/Patrimônio (derivada do yfinance)
    lpa: float = math.nan             # lucro por ação (trailing EPS)
    pl_fut: float = math.nan          # P/L futuro estimado (forward P/E, yfinance)
    roa: float = math.nan             # retorno sobre ativos (returnOnAssets, %)
    liq_geral: float = math.nan       # liquidez geral (best-effort, do balanço)
    grau_endiv: float = math.nan      # grau de endividamento: Passivo/Ativo (%)
    indep_fin: float = math.nan       # independência financeira: PL/Ativo (%)
    payout_ratio: float = math.nan    # payout real (0-1), quando disponível
    liq_corr: float = math.nan      # Liquidez corrente
    cresc_5a: float = math.nan      # Crescimento receita 5a (%) -> proxy p/ PEG
    market_cap: float = math.nan    # Valor de mercado (R$)
    dy_medio: float = math.nan      # DY médio de N anos (preenchido pelo screener)
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
    f.lpa = g("trailingEps", "epsTrailingTwelveMonths")
    f.pl_fut = g("forwardPE")
    roa = g("returnOnAssets")
    f.roa = roa * 100 if (pd.notna(roa) and abs(roa) < 5) else roa   # fração -> %
    pr = g("payoutRatio")
    f.payout_ratio = pr if (pd.notna(pr) and 0 < pr <= 2) else math.nan
    # Dívida líquida a partir do balanço (yfinance): (dívida total − caixa)
    td, tc, eb = g("totalDebt"), g("totalCash"), g("ebitda")
    if pd.notna(td) and pd.notna(eb) and eb > 0:
        nd = td - (tc if pd.notna(tc) else 0.0)
        f.div_liq_ebitda = nd / eb
        if pd.notna(f.market_cap) and f.market_cap > 0 and pd.notna(f.pvp) and f.pvp > 0:
            equity = f.market_cap / f.pvp          # P/VP = market cap / patrimônio
            if equity > 0:
                f.div_liq_patrim = nd / equity
    f.setor = str(info.get("sector") or info.get("industry") or "")
    return f


# Setor forçado por ticker: holdings/papéis que o yfinance/fundamentus rotulam errado.
# Ex.: Itaúsa (holding financeira) às vezes vem como "Industrials".
SECTOR_OVERRIDE = {
    "ITSA4": "Financial Services", "ITSA3": "Financial Services",   # Itaúsa (holding)
    "BRAP4": "Basic Materials", "BRAP3": "Basic Materials",         # Bradespar (Vale)
    "SIMH3": "Industrials",                                          # Simpar (holding logística)
    # seguradoras (garante is_financial() e evita penalidade de ciclicidade indevida)
    "BBSE3": "Insurance", "PSSA3": "Insurance", "CXSE3": "Insurance", "IRBR3": "Insurance",
}


def get_fundamentals(ticker: str, sector_hint: str = "") -> Fundamentals:
    f = _from_fundamentus(ticker)
    if f is None:
        f = _from_yfinance(ticker)
    else:
        # completa buracos com yfinance (inclui dívida líquida, que o fundamentus não traz)
        yf_needed = any(pd.isna(getattr(f, a)) for a in
                        ("pl", "pvp", "dy", "roe", "ev_ebitda", "div_patrim",
                         "liq_corr", "market_cap", "div_liq_ebitda", "div_liq_patrim",
                         "pl_fut"))
        if yf_needed:
            yf_f = _from_yfinance(ticker)
            for a in ("pl", "pvp", "dy", "roe", "roic", "mrg_liq", "ev_ebitda",
                      "div_liq_ebitda", "div_liq_patrim", "div_patrim", "liq_corr",
                      "cresc_5a", "market_cap", "lpa", "payout_ratio", "pl_fut", "roa"):
                if pd.isna(getattr(f, a)) and pd.notna(getattr(yf_f, a)):
                    setattr(f, a, getattr(yf_f, a))
            if not f.setor and yf_f.setor:
                f.setor = yf_f.setor
    # precedência de setor: override manual > iShares (hint) > yfinance/fundamentus
    if sector_hint:
        f.setor = sector_hint
    ov = SECTOR_OVERRIDE.get((f.ticker or ticker).upper())
    if ov:
        f.setor = ov
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


# -------- HISTÓRICO p/ critérios de consistência --------
def listed_years(px) -> float:
    """Anos desde o primeiro pregão disponível no histórico (proxy de tempo de Bolsa)."""
    try:
        import datetime as _dt
        first = px.index[0]
        days = (pd.Timestamp(_dt.date.today()) - pd.Timestamp(first)).days
        return days / 365.25
    except Exception:
        return math.nan


def annual_dy_series(px, years: int = 5):
    """Série de DY anual (proventos do ano / preço médio do ano), últimos `years` anos."""
    if px is None or "Dividends" not in getattr(px, "columns", []) or "Close" not in px.columns:
        return None
    df = px[["Close", "Dividends"]].dropna()
    if df.empty:
        return None
    yr = df.index.year
    div_y = df["Dividends"].groupby(yr).sum()
    px_y = df["Close"].groupby(yr).mean()
    dy_y = (div_y / px_y * 100.0).dropna()
    return dy_y.tail(years) if len(dy_y) else None


def paid_dividends_ge(px, years: int = 5, thr_pct: float = 5.0):
    """True se pagou DY >= thr_pct em TODOS os últimos `years` anos; None se histórico curto."""
    s = annual_dy_series(px, years)
    if s is None or len(s) < years:
        return None
    return bool((s >= thr_pct).all())


def _row_by_year(st, keys) -> dict:
    """Extrai {ano: valor} da 1ª linha existente entre `keys` de um demonstrativo yfinance."""
    out = {}
    for key in keys:
        if key in st.index:
            for col, val in st.loc[key].items():
                yr = getattr(col, "year", None)
                if yr and pd.notna(val):
                    try:
                        out[int(yr)] = float(val)
                    except Exception:
                        pass
            break
    return out


def get_net_income_history(ticker: str):
    """Best-effort do income statement (uma chamada): retorna
       (lucro ANUAL, lucro TRIMESTRAL, {ano:LPA}, {ano:EBITDA}, {ano:margem_liq%}).
    Cobertura da B3 é irregular. Desligue com env PROFIT_HISTORY=0."""
    import os
    if os.getenv("PROFIT_HISTORY", "1") == "0":
        return [], [], {}, {}, {}
    annual, quarterly, eps_by_year, ebitda_by_year, margem_by_year = [], [], {}, {}, {}
    try:
        import yfinance as yf
        t = yf.Ticker(to_yahoo(ticker))
        for attr, dest in (("income_stmt", annual), ("quarterly_income_stmt", quarterly)):
            try:
                st = getattr(t, attr)
                if st is None or st.empty:
                    continue
                for key in ("Net Income", "NetIncome", "Net Income Common Stockholders"):
                    if key in st.index:
                        dest.extend([float(x) for x in st.loc[key].tolist() if pd.notna(x)])
                        break
                if attr == "income_stmt":
                    eps_by_year.update(_row_by_year(st, ("Diluted EPS", "Basic EPS")))
                    ebitda_by_year.update(_row_by_year(st, ("EBITDA", "Normalized EBITDA")))
                    ni_y = _row_by_year(st, ("Net Income", "Net Income Common Stockholders"))
                    rev_y = _row_by_year(st, ("Total Revenue", "Operating Revenue"))
                    for yr, rev in rev_y.items():           # margem líquida anual (%)
                        if yr in ni_y and rev and rev != 0:
                            margem_by_year[yr] = ni_y[yr] / rev * 100
            except Exception:
                pass
    except Exception:
        pass
    return annual, quarterly, eps_by_year, ebitda_by_year, margem_by_year


def get_balance_metrics(ticker: str) -> dict:
    """Best-effort do balanço (uma chamada). Retorna liquidez geral, grau de endividamento
    (Passivo/Ativo %), independência financeira (PL/Ativo %) e {ano: patrimônio} p/ ROE.
    Desligue com env BALANCE=0."""
    import os
    out = {"liq_geral": math.nan, "grau_endiv": math.nan, "indep_fin": math.nan,
           "equity_by_year": {}}
    if os.getenv("BALANCE", "1") == "0":
        return out
    try:
        import yfinance as yf
        st = yf.Ticker(to_yahoo(ticker)).balance_sheet
        if st is None or st.empty:
            return out
        col = st.columns[0]                                  # ano mais recente
        def v(*keys):
            for k in keys:
                if k in st.index and pd.notna(st.loc[k, col]):
                    return float(st.loc[k, col])
            return math.nan
        ativo = v("Total Assets")
        passivo = v("Total Liabilities Net Minority Interest", "Total Liabilities")
        pl = v("Stockholders Equity", "Total Equity Gross Minority Interest",
               "Common Stock Equity")
        ac = v("Current Assets", "Total Current Assets")
        pc = v("Current Liabilities", "Total Current Liabilities")
        if pd.notna(ativo) and ativo > 0:
            if pd.notna(passivo):
                out["grau_endiv"] = passivo / ativo * 100
            if pd.notna(pl):
                out["indep_fin"] = pl / ativo * 100
        # liquidez geral ≈ (Ativo Circulante + Realizável LP) / Passivo total
        rlp = v("Other Non Current Assets")                  # aproxima o realizável LP
        if pd.notna(ac) and pd.notna(passivo) and passivo > 0:
            num = ac + (rlp if pd.notna(rlp) else 0.0)
            out["liq_geral"] = num / passivo
        out["equity_by_year"] = _row_by_year(
            st, ("Stockholders Equity", "Common Stock Equity"))
    except Exception:
        pass
    return out


def trend_up(by_year: dict, min_years: int = 4, tol: float = 0.0) -> bool:
    """True se a série (por ano) é predominantemente CRESCENTE: pelo menos min_years anos e
    a maioria das variações ano-a-ano positivas, com o último > primeiro (margem tol)."""
    try:
        if not by_year:
            return False
        anos = sorted(by_year.keys())
        vals = [by_year[a] for a in anos]
        if len(vals) < min_years:
            return False
        subiu = sum(1 for i in range(1, len(vals)) if vals[i] > vals[i - 1])
        desceu = sum(1 for i in range(1, len(vals)) if vals[i] < vals[i - 1])
        return (vals[-1] > vals[0] * (1 + tol)) and (subiu > desceu)
    except Exception:
        return False


def avg_payout(eps_by_year: dict, px, years: int = 5):
    """Payout médio = média de (dividendo anual por ação ÷ LPA do ano), nos anos disponíveis.

    Usa LPA anual (yfinance) e dividendos anuais (histórico de preços). Retorna None se
    houver menos de 2 anos com ambos válidos. Ignora payout <=0 ou > 200% (dado ruim)."""
    try:
        if not eps_by_year or px is None or "Dividends" not in getattr(px, "columns", []):
            return None
        d = px["Dividends"].fillna(0.0).groupby(px.index.year).sum()
        pos = []
        for yr, eps in eps_by_year.items():
            if yr in d.index and eps and eps > 0 and d[yr] > 0:
                po = float(d[yr]) / float(eps)
                if 0 < po <= 2:
                    pos.append(po)
        if len(pos) >= 2:
            return sum(pos) / len(pos)
    except Exception:
        pass
    return None


def dividends_no_cut(px, years: int = 5, tol: float = 0.20):
    """True se NÃO houve corte relevante de dividendo ano a ano nos últimos `years`.

    Usa valores anuais pagos (não DY, p/ não sofrer efeito de preço). Um 'corte' conta
    quando o pago no ano cai mais que `tol` (ex.: 20%) vs. o ano anterior — a tolerância
    evita marcar variação normal (dividendo variável/JCP) como corte. None se histórico
    insuficiente (< 3 anos com pagamento)."""
    try:
        if px is None or "Dividends" not in getattr(px, "columns", []):
            return None
        d = px["Dividends"].fillna(0.0)
        yr = d.groupby(d.index.year).sum()
        vals = list(yr.tail(years + 1).values)     # 1 ano a mais p/ comparar
        while vals and vals[0] <= 0:               # remove zeros iniciais (pré-pagamento)
            vals.pop(0)
        if len([v for v in vals if v > 0]) < 3:
            return None
        cortes = sum(1 for i in range(1, len(vals))
                     if vals[i - 1] > 0 and vals[i] < (1 - tol) * vals[i - 1])
        return cortes == 0
    except Exception:
        return None


def price_stats(px, selic: float = None) -> dict:
    """Estatísticas técnicas do histórico (~1 ano): mínima/máxima 52s, distância da mínima e
    da média de 100 dias, MEDIANA do preço, DRAWDOWN MÁXIMO (pico->vale), VOLATILIDADE
    anualizada e RETORNO no ano (YTD) — para contexto de risco por papel. Também MOMENTUM,
    Value at Risk, Índice de Sharpe e DESVIO PADRÃO (diário, não anualizado — complementa a
    volatilidade anualizada já calculada acima com o número "cru")."""
    out = {}
    try:
        close = px["Close"].dropna()
        if len(close) < 20:
            return out
        c = float(close.iloc[-1])
        w = close.iloc[-252:]                      # ~1 ano de pregões
        low52, high52 = float(w.min()), float(w.max())
        out["min_52s"] = round(low52, 2)
        out["max_52s"] = round(high52, 2)
        out["dist_min52"] = round((c / low52 - 1) * 100, 1) if low52 > 0 else float("nan")
        out["dist_max52"] = round((c / high52 - 1) * 100, 1) if high52 > 0 else float("nan")
        if len(close) >= 100:
            mm100 = float(close.rolling(100).mean().iloc[-1])
            out["dist_mm100"] = round((c / mm100 - 1) * 100, 1) if mm100 > 0 else float("nan")
        # mediana do preço em ~1 ano (mais robusta a outliers que a média) + a MÉDIA também
        out["mediana_1a"] = round(float(w.median()), 2)
        out["media_1a"] = round(float(w.mean()), 2)
        # drawdown máximo: maior queda pico->vale dentro da janela de ~1 ano (%), medido
        # SEMPRE sobre o preço em si (pico corrente do próprio histórico) — não usa média
        # nem mediana como referência.
        roll_max = w.cummax()
        dd = (w / roll_max - 1) * 100
        out["max_drawdown"] = round(float(dd.min()), 1) if len(dd) else float("nan")
        # volatilidade anualizada dos retornos diários (%) — desvio padrão × √252
        rets = w.pct_change().dropna()
        out["vol_anual"] = (round(float(rets.std() * (252 ** 0.5) * 100), 1)
                            if len(rets) > 20 else float("nan"))
        # DESVIO PADRÃO diário dos retornos (%) — o número "cru", sem anualizar (vol_anual
        # acima já é isso × √252; aqui fica explícito como métrica própria, a pedido).
        out["desvio_padrao"] = (round(float(rets.std() * 100), 2)
                                if len(rets) > 20 else float("nan"))
        # MOMENTUM 12-1: retorno dos últimos 12 meses EXCLUINDO o último mês (~21 pregões) —
        # definição clássica de fator momentum (Jegadeesh & Titman), evita capturar reversão
        # de curtíssimo prazo. Usa até 252 pregões (~1 ano); precisa de pelo menos ~11 meses
        # de histórico (231 pregões) pra fazer sentido.
        if len(close) >= 231:
            janela_mom = close.iloc[-252:] if len(close) >= 252 else close
            preco_fim = float(janela_mom.iloc[-21])         # ~1 mês atrás (exclui o último mês)
            preco_ini = float(janela_mom.iloc[0])            # início da janela (~12 meses atrás)
            out["momentum_12_1"] = (round((preco_fim / preco_ini - 1) * 100, 1)
                                    if preco_ini > 0 else float("nan"))
        # VALUE AT RISK histórico, 1 dia, 95% de confiança (%) — percentil 5 dos retornos
        # diários dos últimos ~1 ano. Não assume distribuição normal (usa a distribuição
        # EMPÍRICA de verdade), mais robusto a caudas gordas que o VaR paramétrico. Negativo
        # = perda estimada (ex.: -3.2% significa que, historicamente, em 95% dos dias a perda
        # NÃO passou de 3.2% — e em 5% dos dias, passou).
        out["var_95"] = (round(float(rets.quantile(0.05) * 100), 2)
                         if len(rets) > 20 else float("nan"))
        # ÍNDICE DE SHARPE anualizado: (retorno anualizado - taxa livre de risco) / vol
        # anualizada. Usa a SELIC como taxa livre de risco (referência padrão no Brasil);
        # se não vier, cai pro cálculo sem desconto de juros (equivalente a Sharpe c/ taxa=0,
        # menos correto mas melhor que não calcular nada).
        if len(rets) > 20 and rets.std() > 0:
            ret_anual = float(rets.mean() * 252)
            vol_anual_frac = float(rets.std() * (252 ** 0.5))
            taxa_livre = (selic / 100.0) if selic is not None else 0.0
            out["sharpe"] = round((ret_anual - taxa_livre) / vol_anual_frac, 2)
        # retorno da própria ação no ano corrente (YTD, %) — p/ comparar com o Ibovespa
        today = close.index[-1]
        yr = close[close.index.year == today.year]
        out["ret_ytd"] = (round((c / float(yr.iloc[0]) - 1) * 100, 1)
                          if len(yr) else float("nan"))
        # mínima e máxima do PRÓPRIO ANO CORRENTE (diferente de min/max 52 semanas, que é
        # janela móvel de 12 meses; aqui é estritamente 1º de janeiro até hoje)
        if len(yr):
            out["min_ytd"] = round(float(yr.min()), 2)
            out["max_ytd"] = round(float(yr.max()), 2)
    except Exception:
        pass
    return out


def get_ibov_close(period: str = "2y"):
    """Fechamentos diários do Ibovespa (^BVSP) para cálculo de beta/correlação. None em falha."""
    try:
        import yfinance as yf
        h = yf.Ticker("^BVSP").history(period=period, auto_adjust=True)
        s = h["Close"].dropna()
        s.index = s.index.tz_localize(None) if getattr(s.index, "tz", None) else s.index
        return s if len(s) else None
    except Exception:
        return None


def get_usd_close(period: str = "2y"):
    """Fechamentos diários do USD/BRL (yfinance 'BRL=X') para correlação cambial por papel.
    None em falha."""
    try:
        import yfinance as yf
        h = yf.Ticker("BRL=X").history(period=period, auto_adjust=True)
        s = h["Close"].dropna()
        s.index = s.index.tz_localize(None) if getattr(s.index, "tz", None) else s.index
        return s if len(s) else None
    except Exception:
        return None


def corr_usd(px, usd_close, window: int = 252) -> float:
    """Correlação dos retornos diários da ação vs. USD/BRL (~1 ano). POSITIVA = a ação tende
    a subir junto com o dólar (ex.: exportadoras/commodities); NEGATIVA = junto com o real
    forte (ex.: importadoras/consumo doméstico endividado em dólar). nan se faltar dado."""
    try:
        if px is None or usd_close is None:
            return float("nan")
        s = px["Close"].copy()
        s.index = s.index.tz_localize(None) if getattr(s.index, "tz", None) else s.index
        rs = s.pct_change()
        ru = usd_close.pct_change()
        j = pd.concat([rs, ru], axis=1, join="inner").dropna()
        if len(j) < 60:
            return float("nan")
        j = j.iloc[-window:]
        return round(float(j.iloc[:, 0].corr(j.iloc[:, 1])), 2)
    except Exception:
        return float("nan")


def beta_corr(px, ibov_close, window: int = 252):
    """(beta, correlação) dos retornos diários da ação vs Ibovespa na janela (~1 ano).
    beta = cov(ação, ibov)/var(ibov); correlação de Pearson. (nan, nan) se dados insuficientes."""
    try:
        if px is None or ibov_close is None:
            return float("nan"), float("nan")
        s = px["Close"].copy()
        s.index = s.index.tz_localize(None) if getattr(s.index, "tz", None) else s.index
        rs = s.pct_change()
        rm = ibov_close.pct_change()
        j = pd.concat([rs, rm], axis=1, join="inner").dropna()
        if len(j) < 60:
            return float("nan"), float("nan")
        j = j.iloc[-window:]
        sv, mv = j.iloc[:, 0], j.iloc[:, 1]
        var = float(mv.var())
        beta = float(sv.cov(mv) / var) if var > 0 else float("nan")
        corr = float(sv.corr(mv))
        return round(beta, 2), round(corr, 2)
    except Exception:
        return float("nan"), float("nan")
