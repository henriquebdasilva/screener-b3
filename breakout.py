# -*- coding: utf-8 -*-
"""
FILTRO DE ROMPIMENTO / PIVÔ — port fiel do algoritmo de
github.com/henriquebdasilva/stock_screener (branch `master`, arquivo screener.py).

Reproduz as regras originais:

  • CONSOLIDAÇÃO (is_consolidated_flexible): existe alguma janela de tamanho entre
    `min_days` e `max_days-1` pregões em que a mínima dos fechamentos está a menos de
    `percentage`% abaixo da máxima (i.e. a ação andou "de lado").
  • ROMPIMENTO (is_breaking_out): consolidada E último fechamento > máxima dos 15
    fechamentos anteriores (df[-16:-1]).
  • TENDÊNCIA (is_uptrend): via MM21 — 'Em Alta' / 'Lateral' / 'Em Baixa'.
  • PIVÔ DE ALTA (is_pivoting): consolidada, NÃO rompendo, com recuo e retomada,
    confirmado por preço OU engolfo de alta OU martelo (candlestick).

Parâmetros originais (mantidos):
    Rompimento: percentage=15, janela 7..15
    Pivô:       percentage=20, janela 5..15

Candlestick: usa TA-Lib se estiver instalado (idêntico ao original, CDLENGULFING /
CDLHAMMER); caso contrário, usa implementações equivalentes em pandas puro — assim o
GitHub Actions roda sem precisar compilar o TA-Lib.

A assinatura pública `detect_breakout(df, ...) -> BreakoutResult` foi preservada.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd

# ---- constantes originais do repositório ----
NARROW_VARIATION_PERCENTAGE_PIVOT = 20
NARROW_VARIATION_PERCENTAGE_BREAKOUT = 15
MIN_DAYS_BEFORE_WINDOW_PIVOT = 5
MAX_DAYS_BEFORE_WINDOW_PIVOT = 15
MIN_DAYS_BEFORE_WINDOW_BREAKOUT = 7
MAX_DAYS_BEFORE_WINDOW_BREAKOUT = 15

EM_ALTA_STR = "Em Alta"
EM_BAIXA_STR = "Em Baixa"
LATERAL_STR = "Lateral"
BREAKOUT_STR = "Rompimento"
PIVOT_STR = "Pivô de alta"


@dataclass
class BreakoutResult:
    ticker: str = ""
    signal: bool = False
    strategy: str = ""            # 'Rompimento' | 'Pivô de alta' | ''
    trend: str = ""              # 'Em Alta' | 'Lateral' | 'Em Baixa'
    close: float = np.nan
    breakout_level: float = np.nan   # máxima dos 15 fechamentos anteriores
    pct_to_level: float = np.nan     # (close/level - 1)*100
    dist_52w_high_pct: float = np.nan
    vol_ratio: float = np.nan
    above_sma200: bool = False
    sma50_gt_sma200: bool = False
    days_since_breakout: int = -1
    note: str = ""

    def as_dict(self):
        return asdict(self)


# ------------------ regras originais ------------------
def is_consolidated_flexible(df, percentage, min_days, max_days) -> bool:
    closes = df["Close"]
    for days in range(min_days, max_days):
        window = closes.iloc[-days:]
        max_close, min_close = window.max(), window.min()
        if min_close > max_close * ((100 - percentage) / 100):
            return True
    return False


def _sma(s, n):
    return s.rolling(n, min_periods=n).mean()


def is_breaking_out(df, percentage, min_days, max_days, margin_pct=0.0) -> bool:
    last_close = df["Close"].iloc[-1]
    if is_consolidated_flexible(df, percentage, min_days, max_days):
        recent = df["Close"].iloc[-16:-1]
        # margem mínima: fechar acima do topo por pelo menos margin_pct%
        if len(recent) and last_close > recent.max() * (1 + margin_pct / 100.0):
            return True
    return False


def is_uptrend(df) -> str:
    days_before = 7
    q = df.copy()
    if q.empty or len(q) < 30:
        return EM_ALTA_STR
    q["MM21"] = q["Close"].rolling(21).mean()
    trend = EM_ALTA_STR
    for i in range(days_before):
        if q["MM21"].iloc[-i - 1] < q["MM21"].iloc[-i - 2]:
            if q["MM21"].iloc[-days_before:-1].mean() > q["MM21"].iloc[-1]:
                trend = EM_BAIXA_STR
            else:
                trend = LATERAL_STR
    return trend


# ---- candlestick (TA-Lib se houver; senão, pandas puro) ----
def _talib():
    try:
        import talib  # type: ignore
        return talib
    except Exception:
        return None


def last_day_is_bullish_engulfing(df) -> bool:
    ta = _talib()
    if ta is not None:
        r = ta.CDLENGULFING(df["Open"], df["High"], df["Low"], df["Close"])
        return bool(r.iloc[-1] > 0)
    o, c = df["Open"], df["Close"]
    po, pc = o.iloc[-2], c.iloc[-2]
    lo, lc = o.iloc[-1], c.iloc[-1]
    prev_bear = pc < po
    last_bull = lc > lo
    engulfs = (lo <= pc) and (lc >= po)
    return bool(prev_bear and last_bull and engulfs)


def before_last_day_is_hammer(df) -> bool:
    ta = _talib()
    if ta is not None:
        r = ta.CDLHAMMER(df["Open"], df["High"], df["Low"], df["Close"])
        return bool(r.iloc[-2] > 0)
    o, h, l, c = (df["Open"].iloc[-2], df["High"].iloc[-2],
                  df["Low"].iloc[-2], df["Close"].iloc[-2])
    body = abs(c - o)
    rng = h - l
    if rng <= 0:
        return False
    lower_shadow = min(o, c) - l
    upper_shadow = h - max(o, c)
    return bool(body <= 0.35 * rng and lower_shadow >= 2 * body
                and upper_shadow <= body)


def is_pivoting(df, percentage, min_days, max_days) -> bool:
    if not is_consolidated_flexible(df, percentage, min_days, max_days):
        return False
    if is_breaking_out(df, percentage, min_days, max_days):
        return False
    c = df["Close"]
    for d in range(min_days, max_days):
        # o dia imediatamente antes da janela foi um topo local?
        if c.iloc[-1 - d] >= c.iloc[-d:-1].max():
            if c.iloc[-1] > c.iloc[-3:-1].max():
                return True
            if last_day_is_bullish_engulfing(df):
                return True
            if before_last_day_is_hammer(df) and c.iloc[-1] > c.iloc[-2]:
                return True
    return False


# ------------------ API pública ------------------
def detect_breakout(df: pd.DataFrame, ticker: str = "",
                    breakout_consol_pct: float = 10.0,   # consolidação mais estreita (era 15)
                    min_breakout_margin_pct: float = 1.5,  # romper o topo por ≥ isso
                   # require_volume: bool = True, vol_mult: float = 1.5,
                    require_trend: bool = True,
                    pivot_consol_pct: float = 20.0,
                    **_ignored) -> BreakoutResult:
    """Rompimento/pivô com filtros de assertividade sobre o algoritmo original.

    ROMPIMENTO exige, além de consolidação + novo topo:
      • margem mínima (fechar acima do topo de 15 dias por ≥ `min_breakout_margin_pct`%);
      • volume do dia ≥ `vol_mult`× média de 20 (se `require_volume`);
      • tendência de alta: preço > MM200 e MM50 > MM200 (se `require_trend`).
    Desligue os filtros para reproduzir o comportamento original do repositório.
    """
    res = BreakoutResult(ticker=ticker)
    if df is None or len(df) < 40:
        res.note = "histórico insuficiente"
        return res

    close = df["Close"]
    res.close = float(close.iloc[-1])
    recent = close.iloc[-16:-1]
    if len(recent):
        res.breakout_level = float(recent.max())
        res.pct_to_level = (res.close / res.breakout_level - 1) * 100.0
    try:
        h52 = df["High"].rolling(252, min_periods=60).max().iloc[-1]
        res.dist_52w_high_pct = (res.close / h52 - 1) * 100.0
    except Exception:
        pass
    try:
        av = df["Volume"].rolling(20, min_periods=20).mean().iloc[-1]
        res.vol_ratio = float(df["Volume"].iloc[-1] / av) if av else np.nan
    except Exception:
        pass

    res.trend = is_uptrend(df)
    sma50 = _sma(close, 50).iloc[-1]
    sma200 = _sma(close, 200).iloc[-1]
    res.above_sma200 = bool(pd.notna(sma200) and res.close > sma200)
    res.sma50_gt_sma200 = bool(pd.notna(sma50) and pd.notna(sma200) and sma50 > sma200)

    # ---- ROMPIMENTO (consolidação estreita + margem + volume + tendência) ----
    broke_raw = is_breaking_out(
        df, breakout_consol_pct, MIN_DAYS_BEFORE_WINDOW_BREAKOUT,
        MAX_DAYS_BEFORE_WINDOW_BREAKOUT, margin_pct=min_breakout_margin_pct)
    vol_ok = (not require_volume) or (pd.notna(res.vol_ratio) and res.vol_ratio >= vol_mult)
    trend_ok = (not require_trend) or (res.above_sma200 and res.sma50_gt_sma200)
    breakout = bool(broke_raw and vol_ok and trend_ok)

    # ---- PIVÔ (mantém a lógica original; já exige tendência não-baixa) ----
    pivot = (res.trend != EM_BAIXA_STR) and is_pivoting(
        df, pivot_consol_pct, MIN_DAYS_BEFORE_WINDOW_PIVOT,
        MAX_DAYS_BEFORE_WINDOW_PIVOT)

    if breakout:
        res.signal, res.strategy, res.days_since_breakout = True, BREAKOUT_STR, 0
        res.note = (f"Rompimento (vol x{res.vol_ratio:.1f}, +{res.pct_to_level:.1f}% "
                    f"do topo, MM50>MM200)")
    elif pivot:
        res.signal, res.strategy = True, PIVOT_STR
        res.note = "Pivô de alta"
    else:
        motivos = []
        if broke_raw and not vol_ok:
            motivos.append(f"volume baixo (x{res.vol_ratio:.1f})"
                           if pd.notna(res.vol_ratio) else "sem volume")
        if broke_raw and not trend_ok:
            motivos.append("fora de tendência de alta (MM200)")
        if not broke_raw:
            motivos.append(f"sem novo topo ({res.pct_to_level:+.1f}%)")
        res.note = f"sem sinal ({res.trend}" + (
            "; " + ", ".join(motivos) if motivos else "") + ")"
    return res
