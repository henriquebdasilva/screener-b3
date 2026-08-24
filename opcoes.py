"""opcoes.py — "Options ratio" (Put/Call) a partir do COTAHIST diário OFICIAL da B3.

O COTAHIST é o arquivo público e histórico da B3 (existe há décadas) com o fechamento de
TODO instrumento negociado no dia, incluindo opções. Campos por posição fixa; TPMERC
070 = CALL (opção de compra), 080 = PUT (opção de venda), 010 = à vista (ação).

Calcula a razão Put/Call (por VOLUME financeiro) em três níveis: por ativo, por setor e do
mercado inteiro. É best-effort: NÃO é testável no sandbox (sem acesso à B3) — a busca valida
no runtime do usuário; o parser é testado com dados sintéticos. Desligue com env OPCOES=0.

Interpretação: P/C > 1 = mais puts negociadas (viés defensivo/baixista); P/C < 1 = mais
calls (viés altista). É volume NEGOCIADO no dia (proxy de sentimento), não open interest.
"""
from __future__ import annotations

import datetime as dt
import io
import math
import os
import re
import zipfile
from urllib.request import Request, urlopen


def _raiz(ticker: str) -> str:
    """Raiz do ticker: PETR4 -> PETR ; PETRI38 (opção) -> PETR."""
    m = re.match(r"^([A-Za-z]+)", str(ticker))
    return m.group(1).upper() if m else str(ticker).upper()


def _baixar_cotahist(dataobj: dt.date) -> str:
    ddmmyyyy = dataobj.strftime("%d%m%Y")
    url = f"https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_D{ddmmyyyy}.ZIP"
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 (screener-b3)"})
    with urlopen(req, timeout=90) as r:
        raw = r.read()
    zf = zipfile.ZipFile(io.BytesIO(raw))
    return zf.read(zf.namelist()[0]).decode("latin-1")


def _baixar_com_fallback(dataobj: dt.date, dias: int = 6):
    """Tenta a data pedida e volta até `dias` pregões atrás (fim de semana/feriado)."""
    for i in range(dias):
        d = dataobj - dt.timedelta(days=i)
        try:
            return _baixar_cotahist(d), d
        except Exception:
            continue
    return None, None


def parse_cotahist(texto: str):
    """Faz o parsing do COTAHIST. Retorna (opcoes, spot_por_raiz).
    opcoes: lista de dict(ticker, raiz, tipo 'C'/'P', volume, negocios, strike, venc)."""
    opcoes, spot = [], {}
    for l in texto.split("\n"):
        if len(l) < 210 or l[0:2] != "01":
            continue
        tpmerc = l[24:27].strip()
        codneg = l[12:24].strip()
        if tpmerc == "010":                              # à vista -> preço da ação
            try:
                preult = int(l[108:121]) / 100.0
            except Exception:
                continue
            raiz = _raiz(codneg)
            if raiz not in spot and preult > 0:
                spot[raiz] = preult
            continue
        if tpmerc not in ("070", "080"):                 # só opções (call/put)
            continue
        try:
            voltot = int(l[170:188]) / 100.0
        except Exception:
            voltot = 0.0
        try:
            totneg = int(l[147:152])
        except Exception:
            totneg = 0
        try:
            strike = int(l[188:201]) / 100.0
        except Exception:
            strike = math.nan
        datven = l[202:210].strip()
        venc = (f"{datven[6:8]}/{datven[4:6]}/{datven[0:4]}"
                if len(datven) == 8 else datven)
        opcoes.append({"ticker": codneg, "raiz": _raiz(codneg),
                       "tipo": "C" if tpmerc == "070" else "P",
                       "volume": voltot, "negocios": totneg,
                       "strike": strike, "venc": venc})
    return opcoes, spot


def _ratio(call_vol: float, put_vol: float) -> dict:
    tot = call_vol + put_vol
    return {"call_vol": call_vol, "put_vol": put_vol,
            "pc_ratio": (put_vol / call_vol) if call_vol > 0 else math.nan,
            "pct_call": (call_vol / tot * 100) if tot > 0 else math.nan,
            "pct_put": (put_vol / tot * 100) if tot > 0 else math.nan}


def put_call_ratios(opcoes: list, ticker_setor: dict = None,
                    underlying_roots=None) -> dict:
    """Razão Put/Call (por volume) do mercado, por setor e por ativo.
    As opções são casadas ao ATIVO-BASE pelo PREFIXO do código (ex.: 'PETRX40' começa com
    'PETR'), usando os roots das ações (do COTAHIST à vista e/ou do universo)."""
    roots = set(underlying_roots or [])
    if ticker_setor:
        roots |= {_raiz(tk) for tk in ticker_setor}
    roots_ord = sorted(roots, key=len, reverse=True)      # prefixo mais longo primeiro

    def base_de(opt_ticker: str) -> str:
        for r in roots_ord:
            if r and opt_ticker.startswith(r):
                return r
        return _raiz(opt_ticker)                          # fallback (sem universo)

    por_base = {}
    mais_neg = {}                    # base -> opção com MAIOR volume (destaque negociada)
    strike_map = {}                  # código da opção -> strike limpo (do COTAHIST)
    for o in opcoes:
        b = base_de(o["ticker"])
        d = por_base.setdefault(b, [0.0, 0.0])
        d[0 if o["tipo"] == "C" else 1] += o["volume"]
        if o.get("strike") is not None:
            strike_map[o["ticker"]] = o["strike"]
        cur = mais_neg.get(b)
        if cur is None or o["volume"] > cur["volume"]:
            mais_neg[b] = {"code": o["ticker"], "strike": o.get("strike"),
                           "tipo": o["tipo"], "volume": o["volume"],
                           "negocios": o.get("negocios", 0)}
    por_ativo = {r: _ratio(c, p) for r, (c, p) in por_base.items()}
    tc = sum(v[0] for v in por_base.values())
    tp = sum(v[1] for v in por_base.values())
    mercado = _ratio(tc, tp)

    por_setor = {}
    if ticker_setor:
        raiz_setor = {}
        for tk, s in ticker_setor.items():
            if s:
                raiz_setor.setdefault(_raiz(tk), s)
        acc = {}
        for r, (c, p) in por_base.items():
            s = raiz_setor.get(r)
            if not s:
                continue
            a = acc.setdefault(s, [0.0, 0.0])
            a[0] += c
            a[1] += p
        por_setor = {s: _ratio(c, p) for s, (c, p) in acc.items()}
    return {"mercado": mercado, "por_setor": por_setor, "por_ativo": por_ativo,
            "mais_negociada": mais_neg, "strike_map": strike_map}


def fetch_opcoes(ticker_setor: dict = None, data: str = None) -> dict | None:
    """Baixa o COTAHIST (com fallback) e calcula os Put/Call ratios. None em falha.
    Só roda de verdade no ambiente do usuário (rede). Desligue com env OPCOES=0."""
    if os.getenv("OPCOES", "1") == "0":
        return None
    base = (dt.datetime.strptime(data, "%Y-%m-%d").date() if data else dt.date.today())
    txt, d = _baixar_com_fallback(base)
    if not txt:
        print("[opcoes] COTAHIST indisponível (B3 fora do ar ou formato do link mudou).")
        return None
    opcoes, spot = parse_cotahist(txt)
    r = put_call_ratios(opcoes, ticker_setor, underlying_roots=spot.keys())
    r["data"] = d
    r["n_opcoes"] = len(opcoes)
    r["spot"] = spot
    print(f"[opcoes] COTAHIST {d}: {len(opcoes)} opções; P/C mercado="
          f"{r['mercado']['pc_ratio']:.2f}" if not math.isnan(r['mercado']['pc_ratio'])
          else f"[opcoes] COTAHIST {d}: {len(opcoes)} opções")
    return r
