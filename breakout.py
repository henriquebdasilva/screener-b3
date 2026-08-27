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
  • TENDÊNCIA (is_uptrend): via MM21 + MM30 — Em Alta (ambas subindo e preço acima da MM30),
#    Em Baixa (ambas caindo e preço abaixo), Lateral nos demais casos.
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
import os

# ---- constantes originais do repositório ----
NARROW_VARIATION_PERCENTAGE_PIVOT = 20
NARROW_VARIATION_PERCENTAGE_BREAKOUT = 15
MIN_DAYS_BEFORE_WINDOW_PIVOT = 5
MAX_DAYS_BEFORE_WINDOW_PIVOT = 15
MIN_DAYS_BEFORE_WINDOW_BREAKOUT = 7
MAX_DAYS_BEFORE_WINDOW_BREAKOUT = 15

__build__ = "2026-08-27e-fundoduplo-virada"   # marcador de versão (aparece no log)

EM_ALTA_STR = "Em Alta"
EM_BAIXA_STR = "Em Baixa"
LATERAL_STR = "Lateral"
BREAKOUT_STR = "Rompimento"
PIVOT_STR = "Pivô de alta"
DOUBLE_BOTTOM_STR = "Fundo duplo"
TRIPLE_BOTTOM_STR = "Fundo triplo"
BULL_FLAG_STR = "Bandeira de alta"
CUP_HANDLE_STR = "Xícara com alça"


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


def range_estruturado(janela: pd.Series, edge_frac: float = 0.30,
                      min_toques: int = 2) -> bool:
    """A janela é uma BASE de verdade (oscila entre suporte e resistência) e não um 'drift'?

    Uma amplitude pequena, sozinha, não distingue uma base real de uma subida lenta em linha
    reta — as duas cabem no mesmo percentual. Aqui exigimos ESTRUTURA: o preço precisa ter
    visitado a região BAIXA (≤ edge_frac da faixa, medindo do fundo) e a região ALTA
    (≥ 1-edge_frac) pelo menos `min_toques` vezes cada. Assim o rompimento sai de uma base
    testada dos dois lados, não de um movimento direcional disfarçado de consolidação.
    """
    if janela is None or len(janela) < 5:
        return False
    v = pd.to_numeric(janela, errors="coerce").dropna()
    if len(v) < 5:
        return False
    lo, hi = float(v.min()), float(v.max())
    faixa = hi - lo
    if faixa <= 0:
        return False
    pos = (v - lo) / faixa                                # 0 = fundo, 1 = topo da faixa
    toques_baixo = int((pos <= edge_frac).sum())
    toques_alto = int((pos >= 1.0 - edge_frac).sum())
    if toques_baixo < min_toques or toques_alto < min_toques:
        return False
    # ALTERNÂNCIA: numa subida em linha reta os pontos baixos vêm todos antes dos altos, o que
    # satisfaria a contagem sem ser base. Exigimos que o preço ALTERNE entre as bordas — pelo
    # menos `min_toques` transições baixo->alto ou alto->baixo ao longo da janela.
    seq = []
    for p in pos:
        z = "B" if p <= edge_frac else ("A" if p >= 1.0 - edge_frac else None)
        if z and (not seq or seq[-1] != z):
            seq.append(z)                                 # registra só as mudanças de borda
    return len(seq) - 1 >= min_toques                      # nº de transições entre bordas


def is_uptrend(df, curto: int = 21, longo: int = 30) -> str:
    """Tendência via DUAS médias móveis (curta = MM21 e longa = MM30):
      • Em Alta  : ambas as médias subindo E preço acima da MM longa;
      • Em Baixa : ambas as médias caindo E preço abaixo da MM longa;
      • Lateral  : nos demais casos (médias divergindo, ou preço no meio).
    Exigir a concordância das DUAS médias (curto e longo prazo) reduz falsos sinais de
    tendência. Histórico curto -> 'Em Alta' (default, como antes)."""
    if df is None or len(df) < longo + 6:
        return EM_ALTA_STR
    close = df["Close"]
    mmc = close.rolling(curto).mean()
    mml = close.rolling(longo).mean()
    price = float(close.iloc[-1])
    ref = 6                                              # inclinação vs ~5 pregões atrás
    c_up, c_dn = mmc.iloc[-1] > mmc.iloc[-ref], mmc.iloc[-1] < mmc.iloc[-ref]
    l_up, l_dn = mml.iloc[-1] > mml.iloc[-ref], mml.iloc[-1] < mml.iloc[-ref]
    mml_now = float(mml.iloc[-1])
    if c_up and l_up and price >= mml_now:
        return EM_ALTA_STR
    if c_dn and l_dn and price <= mml_now:
        return EM_BAIXA_STR
    return LATERAL_STR


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


# ------------------ padrões gráficos adicionais (conservadores) ------------------
def _local_minima(series: pd.Series, order: int = 5) -> list:
    """Índices de mínimos locais robustos a platôs: ponto é o mínimo da janela e está
    abaixo de pelo menos um vizinho imediato. Mínimos a < `order` pregões um do outro são
    deduplicados (mantém o de menor preço)."""
    v = series.values
    raw = []
    for i in range(order, len(v) - order):
        seg = v[i - order:i + order + 1]
        if v[i] == seg.min() and (v[i] < v[i - 1] or v[i] < v[i + 1]):
            raw.append(i)
    out = []
    for i in raw:
        if out and (i - out[-1]) < order:
            if v[i] < v[out[-1]]:
                out[-1] = i                 # mantém o fundo mais baixo do cluster
        else:
            out.append(i)
    return out


def detect_double_bottom(df, lookback: int = 120, tol: float = 0.02,
                         min_sep: int = 10, max_sep: int = 45, neckline_min: float = 0.08,
                         drop_min: float = 0.20, order: int = 5,
                         max_bars_since: int = 10, max_ext: float = 0.05, exigir_virada: bool = True,
                         low_zone: float = 0.03, debug: bool = False, ticker: str = ""):
    """Fundo duplo (W) — padrão de REVERSÃO. Exige:
      • tendência de BAIXA antes do padrão e queda ≥ drop_min de um topo prévio até os fundos;
      • dois fundos alinhados (≤ tol entre eles) e separados entre min_sep e max_sep pregões;
      • AMBOS os fundos na PARTE BAIXA do período (≤ low_zone acima da mínima da janela) — assim
        os dois são o "fundo" de verdade, e não um vale na descida casado com o fundo real;
      • pico intermediário (pescoço) ≥ neckline_min acima dos fundos;
      • CONFIRMA no rompimento do pescoço, se RECENTE (≤ max_bars_since) e não ESTICADO
        (≤ max_ext acima do pescoço)."""
    close = df["Close"].iloc[-lookback:]
    if len(close) < 40:
        return None
    offset = len(df) - len(close)
    mins = _local_minima(close, order)
    if len(mins) < 2:
        return None
    cur = float(close.iloc[-1])
    lo_janela = float(close.min())                       # mínima do período
    teto_zona = lo_janela * (1 + low_zone)               # topo da "zona de fundo"

    def _dbg(msg):
        if debug:
            print(f"[padrao-debug {ticker}] {msg}")

    if debug:
        _dbg(f"{len(mins)} mínimos locais em R$: " +
             ", ".join(f"{float(close.iloc[i]):.2f}(idx{i})" for i in mins) +
             f" | zona de fundo ≤ R${teto_zona:.2f} (mín R${lo_janela:.2f} +{low_zone*100:.0f}%)")

    for b in range(len(mins) - 1, 0, -1):
        for a in range(b - 1, -1, -1):
            i1, i2 = mins[a], mins[b]
            if i2 - i1 < min_sep or i2 - i1 > max_sep:
                if debug and i2 - i1 > max_sep:
                    _dbg(f"par idx{i1}/idx{i2}: fundos MUITO distantes "
                         f"({i2 - i1} pregões > {max_sep}) — descartado (não é um W)")
                continue
            p1, p2 = float(close.iloc[i1]), float(close.iloc[i2])
            if abs(p1 - p2) / min(p1, p2) > tol:          # fundos alinhados (≤2%)
                continue
            if p1 > teto_zona or p2 > teto_zona:          # algum vale NÃO está na parte baixa
                if debug:
                    _dbg(f"par R${p1:.2f}/R${p2:.2f}: fora da zona de fundo "
                         f"(> R${teto_zona:.2f}) — um vale está na descida, não é W")
                continue
            peak = float(close.iloc[i1:i2 + 1].max())
            base = min(p1, p2)
            if peak / base - 1 < neckline_min:            # pescoço ~8% acima
                _dbg(f"par R${p1:.2f}/R${p2:.2f}: pescoço R${peak:.2f} baixo demais "
                     f"({(peak/base-1)*100:.1f}% < {neckline_min*100:.0f}%) — descartado")
                continue
            confirma = cur > peak and float(close.iloc[i2:].min()) >= base * (1 - tol)
            after = close.iloc[i2:]
            broke_idx = next((i2 + j for j in range(len(after))
                              if float(after.iloc[j]) > peak), None)
            bars_since = (len(close) - 1 - broke_idx) if broke_idx is not None else None
            ext = cur / peak - 1
            rev = _reversal_context(df, offset + i1, base, lookback, drop_min)
            _dbg(f"par R${p1:.2f}(idx{i1})/R${p2:.2f}(idx{i2}) pescoço R${peak:.2f} | "
                 f"confirma_rompimento={confirma} | rompeu há {bars_since} pregões "
                 f"(máx {max_bars_since}) | extensão {ext*100:+.1f}% (máx {max_ext*100:.0f}%) | "
                 f"reversão(baixa+queda≥{drop_min*100:.0f}%)={rev}")
            if not confirma:
                continue                                   # confirma rompimento do pescoço
            if broke_idx is None or bars_since > max_bars_since:
                continue                                   # rompeu há muito tempo
            if ext > max_ext:                              # já subiu demais acima do pescoço
                continue
            if not rev:
                continue                                   # exige baixa + queda antes
            # A VIRADA TEM QUE SER O EVENTO: no SEGUNDO FUNDO (antes do repique final) a
            # tendência ainda não podia ser "Em Alta". Se já era, a reversão ocorreu antes e
            # este "W" é histórico — o papel está em alta madura, não virando agora.
            if exigir_virada:
                abs_i2 = offset + i2
                pre_i2 = df.iloc[:abs_i2 + 1]              # dados até o 2º fundo
                if len(pre_i2) >= 40 and is_uptrend(pre_i2) == EM_ALTA_STR:
                    _dbg(f"descartado: no 2º fundo (idx{i2}) a tendência JÁ era 'Em Alta' — "
                         f"reversão antiga, não é sinal de virada")
                    continue
            _dbg(f">>> FUNDO DUPLO CONFIRMADO: pescoço R${peak:.2f}, base R${base:.2f}")
            return {"neckline": peak, "base": base}
    return None


def detect_triple_bottom(df, lookback: int = 160, tol: float = 0.02,
                         min_sep: int = 8, max_sep: int = 45, neckline_min: float = 0.08,
                         drop_min: float = 0.20, order: int = 5,
                         max_bars_since: int = 10, max_ext: float = 0.05,
                         low_zone: float = 0.15):
    """Fundo triplo — reversão. Três fundos alinhados (≤tol) com picos entre eles, após
    tendência de baixa + queda ≥drop_min; CONFIRMA no rompimento da resistência — só se o
    rompimento for RECENTE (≤max_bars_since) e o preço não estiver ESTICADO (≤max_ext).
    Fundos consecutivos entre min_sep e max_sep pregões (nem colados, nem distantes demais)."""
    close = df["Close"].iloc[-lookback:]
    if len(close) < 60:
        return None
    offset = len(df) - len(close)
    mins = _local_minima(close, order)
    if len(mins) < 3:
        return None
    cur = float(close.iloc[-1])
    i1, i2, i3 = mins[-3], mins[-2], mins[-1]
    if (i2 - i1) < min_sep or (i3 - i2) < min_sep:
        return None
    if (i2 - i1) > max_sep or (i3 - i2) > max_sep:        # fundos distantes demais -> não é padrão
        return None
    ps = [float(close.iloc[i]) for i in (i1, i2, i3)]
    base = min(ps)
    if (max(ps) - base) / base > tol:                     # três fundos alinhados (≤2%)
        return None
    if max(ps) > float(close.min()) * (1 + low_zone):     # algum vale fora da zona de fundo
        return None
    resist = float(close.iloc[i1:i3 + 1].max())
    if resist / base - 1 < neckline_min:
        return None
    if cur <= resist:
        return None
    after = close.iloc[i3:]                                # rompimento recente e não esticado
    broke_idx = next((i3 + j for j in range(len(after))
                      if float(after.iloc[j]) > resist), None)
    if broke_idx is None or (len(close) - 1 - broke_idx) > max_bars_since:
        return None
    if cur / resist - 1 > max_ext:
        return None
    if not _reversal_context(df, offset + i1, base, lookback, drop_min):
        return None
    return {"neckline": resist, "base": base}


def _reversal_context(df, abs_i1: int, base: float, lookback: int,
                      drop_min: float) -> bool:
    """True se, ANTES do padrão (até o 1º fundo), havia tendência de baixa E um topo prévio
    ≥ (1+drop_min) acima dos fundos (queda relevante que o padrão vem reverter)."""
    pre = df.iloc[:abs_i1]
    if len(pre) < 30:
        return False
    if is_uptrend(pre) != EM_BAIXA_STR:                   # nosso padrão de tendência (MM21)
        return False
    ini = max(0, abs_i1 - lookback)
    prior_peak = float(df["Close"].iloc[ini:abs_i1].max())
    return prior_peak >= base * (1 + drop_min)            # queda ≥ drop_min do topo aos fundos


def detect_bull_flag(df, pole_win: int = 20, pole_min: float = 0.12,
                     flag_win: int = 15, flag_min: int = 7,
                     flag_max_retrace: float = 0.45, flag_min_retrace: float = 0.05,
                     break_win: int = 3, max_ext: float = 0.10):
    """Bandeira de alta: forte alta ('mastro', ≥pole_min em pole_win pregões) seguida de
    consolidação curta ('bandeira', recuo ≤flag_max_retrace). A janela da bandeira é FLEXÍVEL:
    testa de `flag_min` (default 7) a `flag_win` (default 15) pregões e aceita a mais curta que
    for válida (consolidação mais recente/apertada). A bandeira deve ter inclinação leve para
    baixo ou lateral. CONFIRMA quando o preço rompe a LINHA DE TENDÊNCIA SUPERIOR (descendente).
    FRESCOR: o fechamento antes da janela de rompimento ainda estava na/abaixo da linha.
    EXTENSÃO: não sinaliza se já esticou >max_ext acima da linha superior ou do topo do mastro.
    """
    close = df["Close"]
    flag_min = max(break_win + 4, int(flag_min))          # piso técnico (polyfit + rompimento)
    for flag_len in range(flag_min, int(flag_win) + 1):   # bandeira mais curta primeiro
        need = pole_win + flag_len
        if len(close) < need + 5:
            continue
        seg = close.iloc[-need:]
        pole, flag = seg.iloc[:pole_win], seg.iloc[pole_win:]
        pole_low, pole_high = float(pole.min()), float(pole.max())
        if pole_low <= 0 or (pole_high / pole_low - 1) < pole_min:
            continue
        flag_low = float(flag.min())
        retrace = (pole_high - flag_low) / (pole_high - pole_low)
        if retrace > flag_max_retrace:               # recuou demais -> não é bandeira
            continue
        if retrace < flag_min_retrace:               # recuo raso demais -> continuação, não bandeira
            continue
        body = flag.iloc[:-break_win]                # consolidação (sem os pregões de rompimento)
        y = body.values.astype(float)
        x = np.arange(len(y), dtype=float)
        slope, intercept = np.polyfit(x, y, 1)
        ampl = float(body.max() - body.min()) or 1.0
        if slope > 0.05 * ampl:                      # subindo -> não é bandeira
            continue
        resid = y - (slope * x + intercept)
        buf = float(np.nanmax(resid)) if len(resid) else 0.0
        upper_ref = slope * (len(y) - 1) + intercept + buf
        cur = float(close.iloc[-1])
        prev = float(close.iloc[-(break_win + 1)])   # fechamento antes do rompimento
        brk = close.iloc[-break_win:]
        rompeu = (cur >= upper_ref and cur > prev and cur >= float(brk.max()))
        fresco = prev <= upper_ref * (1 + 0.01)      # antes do rompimento ainda estava na linha
        nao_esticado = (cur <= upper_ref * (1 + max_ext) and
                        cur <= pole_high * (1 + max_ext))
        if rompeu and fresco and nao_esticado and cur >= pole_high * 0.90:
            return {"pole_pct": (pole_high / pole_low - 1) * 100.0,
                    "flag_retrace": retrace * 100.0, "flag_dias": flag_len,
                    "resistencia": round(upper_ref, 2), "incl": round(slope, 4)}
    return None


def detect_cup_handle(df, cup_min: int = 20, cup_max: int = 90, handle_max: int = 20,
                      rim_tol: float = 0.06, depth_min: float = 0.10, depth_max: float = 0.45,
                      handle_retrace_max: float = 0.45, max_ext: float = 0.05,
                      round_min: float = 0.55, debug: bool = False, ticker: str = ""):
    """Xícara com alça (cup and handle) — CONTINUAÇÃO de alta. Estrutura:
      • duas BORDAS em nível parecido (≤ rim_tol) separadas por cup_min..cup_max pregões;
      • um FUNDO arredondado entre elas (profundidade entre depth_min e depth_max da borda) e
        formato de 'U' (não 'V'): o fundo fica na metade inferior por vários pregões (round_min);
      • uma ALÇA curta (≤ handle_max pregões) logo após a 2ª borda: recuo raso (≤ handle_retrace_max
        da profundidade da xícara);
      • CONFIRMA quando o preço rompe a borda, sem estar esticado (≤ max_ext acima da borda).
    Diferente do fundo duplo (reversão), aqui as bordas ficam no ALTO e o padrão aparece dentro
    de uma tendência de alta."""
    close = df["Close"]
    n = cup_max + handle_max + 5
    if len(close) < cup_min + 8:
        return None
    seg = close.iloc[-min(len(close), n):]
    cur = float(seg.iloc[-1])

    def _dbg(m):
        if debug:
            print(f"[padrao-debug {ticker}] (cup) {m}")

    # a alça é o trecho final; a borda direita é o topo local antes da alça
    for handle_len in range(3, handle_max + 1):
        if len(seg) < cup_min + handle_len + 2:
            break
        cup = seg.iloc[:-handle_len]
        handle = seg.iloc[-handle_len:]
        rim_r_idx = int(np.argmax(cup.values))            # borda direita = topo da xícara
        rim_r = float(cup.iloc[rim_r_idx])
        # borda esquerda: topo à esquerda do fundo, em nível parecido com a direita
        fundo_idx = int(np.argmin(cup.values))
        if fundo_idx <= 2 or fundo_idx >= len(cup) - 3:
            continue
        left = cup.iloc[:fundo_idx]
        rim_l = float(left.max())
        if rim_l <= 0:
            continue
        if abs(rim_r - rim_l) / rim_l > rim_tol:          # bordas em nível parecido
            continue
        rim = (rim_r + rim_l) / 2.0
        fundo = float(cup.min())
        depth = (rim - fundo) / rim
        if not (depth_min <= depth <= depth_max):         # profundidade típica de xícara
            continue
        largura = rim_r_idx - fundo_idx
        if not (cup_min <= (len(cup) - 1) <= cup_max):
            continue
        # formato em U: boa parte da xícara na metade INFERIOR (arredondado, não V)
        meia = rim - depth * rim * 0.5
        frac_baixo = float((cup.values <= meia).mean())
        if frac_baixo < round_min * 0.5:                  # muito pouco tempo embaixo -> V
            _dbg(f"fundo pouco arredondado (só {frac_baixo*100:.0f}% do tempo na metade baixa)")
            continue
        # alça: recuo raso a partir da borda direita
        h_low = float(handle.min())
        h_retr = (rim_r - h_low) / (rim - fundo) if (rim - fundo) > 0 else 1.0
        if h_retr > handle_retrace_max:                   # alça funda demais
            continue
        prev = float(seg.iloc[-2])
        rompeu = cur >= rim and cur > prev
        nao_esticado = cur <= rim * (1 + max_ext)
        _dbg(f"borda≈R${rim:.2f} fundo R${fundo:.2f} prof {depth*100:.0f}% "
             f"alça {handle_len}d recuo {h_retr*100:.0f}% | rompeu={rompeu} esticado_ok={nao_esticado}")
        if rompeu and nao_esticado:
            return {"borda": round(rim, 2), "fundo": round(fundo, 2),
                    "profundidade": depth * 100.0, "alca_dias": handle_len}
    return None


# ------------------ API pública ------------------
def detect_breakout(df: pd.DataFrame, ticker: str = "",
                    breakout_consol_pct: float = 10.0,   # consolidação mais estreita (era 15)
                    min_breakout_margin_pct: float = 1.5,  # romper o topo por ≥ isso
                    require_volume: bool = True, vol_mult: float = 1.5,
                    require_trend: bool = True,
                    pivot_consol_pct: float = 20.0,
                    breakout_max_ext: float = 0.03,
                    require_base_structure: bool = True,
                    base_edge_frac: float = 0.30,
                    base_min_toques: int = 2,
                    pivot_max_ext: float = 0.04,
                    pivot_lower_frac: float = 0.5,
                    pivot_range_pct: float = 5.0,
                    pattern_max_ext: float = 0.10,
                    flag_max_ext: float = 0.04,
                    flag_min_dias: int = 7,
                    flag_pole_min: float = 0.12,
                    flag_min_retrace: float = 0.05,
                    trend_ma_long: int = 30,
                    pattern_max_sep: int = 45,
                    pattern_low_zone: float = 0.03,
                    pattern_exigir_virada: bool = True,
                    detect_patterns: bool = True,
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

    res.trend = is_uptrend(df, longo=trend_ma_long)
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
    # extensão: não sinalizar rompimento já esticado acima do topo rompido
    ext_ok = (pd.isna(res.pct_to_level) or
              res.pct_to_level <= breakout_max_ext * 100.0)
    # ESTRUTURA: a base tem que ter sido testada nas duas bordas (não vale 'drift' direcional)
    estrut_ok = (not require_base_structure) or range_estruturado(
        recent, edge_frac=base_edge_frac, min_toques=base_min_toques)
    breakout = bool(broke_raw and vol_ok and trend_ok and ext_ok and estrut_ok)

    # ---- PIVÔ: recuo ao suporte que vira p/ cima DENTRO de tendência de alta ----
    #   • tendência de ALTA ESTRUTURAL (preço > MM200 e MM50 > MM200) — a consolidação achata a
    #     MM21, então a alta de fundo é medida pelas médias longas, não pelos últimos 7 dias;
    #   • o fechamento deve estar até pivot_lower_frac da faixa (medida do fundo) — evita pivô
    #     ou seja, virando perto do suporte — não no meio/topo do range;
    #   • não pode estar esticado acima do topo da consolidação (pivot_max_ext).
    pivot_raw = (res.above_sma200 and res.sma50_gt_sma200) and is_pivoting(
        df, pivot_consol_pct, MIN_DAYS_BEFORE_WINDOW_PIVOT,
        MAX_DAYS_BEFORE_WINDOW_PIVOT)
    pivot_ext_ok, pivot_low_ok = True, True
    _pos_faixa = None
    _lo_adapt = _hi_adapt = float("nan")
    try:
        # JANELA ADAPTATIVA: usa a MAIOR janela recente que ainda é uma consolidação válida
        # (amplitude ≤ pivot_consol_pct). A janela fixa longa mistura o rally com a pausa e joga
        # o preço para o topo da "faixa"; a mais estreita degenera num trecho achatado. A maior
        # janela válida representa a pausa inteira.
        melhor = None
        for w in range(5, MAX_DAYS_BEFORE_WINDOW_PIVOT + 1):
            j = close.iloc[-(w + 1):-1]
            if len(j) < 4:
                continue
            lo_w, hi_w = float(j.min()), float(j.max())
            if lo_w <= 0 or hi_w <= 0:
                continue
            amp_pct = (hi_w - lo_w) / hi_w * 100.0        # amplitude da janela (%)
            if amp_pct <= pivot_range_pct:                # pausa de verdade (faixa estreita)
                melhor = (w, lo_w, hi_w)                  # guarda a MAIOR válida
        if melhor:
            _, lo, hi = melhor
            _lo_adapt, _hi_adapt = lo, hi
            if res.close > hi * (1 + pivot_max_ext):      # esticado acima do topo
                pivot_ext_ok = False
            faixa = hi - lo
            if faixa > 0:
                _pos_faixa = (res.close - lo) / faixa
                if res.close > lo + pivot_lower_frac * faixa:
                    pivot_low_ok = False                  # está acima da parte inferior
    except Exception:
        pass
    pivot = bool(pivot_raw and pivot_ext_ok and pivot_low_ok)

    if os.getenv("PATTERN_DEBUG", "").upper() == str(ticker or "").upper() \
            and os.getenv("PATTERN_DEBUG"):
        print(f"[padrao-debug {ticker}] (pivô) alta_estrutural="
              f"{bool(res.above_sma200 and res.sma50_gt_sma200)} "
              f"(>MM200={res.above_sma200}, MM50>MM200={res.sma50_gt_sma200}) | "
              f"is_pivoting={bool(pivot_raw)} | faixa adaptativa "
              f"R${_lo_adapt:.2f}-R${_hi_adapt:.2f} fechou R${res.close:.2f}"
              + (f" ({_pos_faixa*100:.0f}% da faixa, máx {pivot_lower_frac*100:.0f}%)"
                 if _pos_faixa is not None else "")
              + f" | posição_ok={pivot_low_ok} | extensão_ok={pivot_ext_ok} => PIVÔ={pivot}")
        print(f"[padrao-debug {ticker}] (rompimento) topo15={res.breakout_level:.2f} "
              f"fechou R${res.close:.2f} ({res.pct_to_level:+.1f}% do topo, máx "
              f"{breakout_max_ext*100:.0f}%) | tendência={res.trend} => ROMP={breakout}")

    if breakout:
        res.signal, res.strategy, res.days_since_breakout = True, BREAKOUT_STR, 0
        res.note = (f"Rompimento (vol x{res.vol_ratio:.1f}, +{res.pct_to_level:.1f}% "
                    f"do topo, MM50>MM200)")
    elif pivot:
        res.signal, res.strategy = True, PIVOT_STR
        res.note = "Pivô de alta"
    elif detect_patterns and res.trend != EM_BAIXA_STR:
        # padrões adicionais (candidatos), só fora de tendência de baixa
        _pdbg = os.getenv("PATTERN_DEBUG", "").upper() == str(ticker or "").upper() \
            and bool(os.getenv("PATTERN_DEBUG"))
        db = detect_double_bottom(df, max_ext=pattern_max_ext, max_sep=pattern_max_sep,
                                  low_zone=pattern_low_zone,
                                  exigir_virada=pattern_exigir_virada,
                                  debug=_pdbg, ticker=ticker)
        tb = detect_triple_bottom(df, max_ext=pattern_max_ext, max_sep=pattern_max_sep)
        ch = detect_cup_handle(df, max_ext=flag_max_ext, debug=_pdbg, ticker=ticker)
        bf = detect_bull_flag(df, max_ext=flag_max_ext, flag_min=flag_min_dias,
                              pole_min=flag_pole_min, flag_min_retrace=flag_min_retrace)
        if tb:
            res.signal, res.strategy = True, TRIPLE_BOTTOM_STR
            res.note = f"Fundo triplo — rompeu pescoço ~R${tb['neckline']:.2f} (candidato)"
        elif ch:
            res.signal, res.strategy = True, CUP_HANDLE_STR
            res.note = (f"Xícara com alça — borda ~R${ch['borda']:.2f}, fundo R${ch['fundo']:.2f} "
                        f"(prof. {ch['profundidade']:.0f}%), alça {ch['alca_dias']}d (candidato)")
        elif db:
            res.signal, res.strategy = True, DOUBLE_BOTTOM_STR
            res.note = f"Fundo duplo — rompeu pescoço ~R${db['neckline']:.2f} (candidato)"
        elif bf:
            res.signal, res.strategy = True, BULL_FLAG_STR
            res.note = (f"Bandeira de alta — mastro +{bf['pole_pct']:.0f}%, "
                        f"recuo {bf['flag_retrace']:.0f}%, bandeira {bf['flag_dias']}d "
                        f"(candidato)")
        else:
            res.note = f"sem sinal ({res.trend})"
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
