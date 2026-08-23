"""posicoes.py — OPEN INTEREST (posições em aberto) de opções, fonte oficial da B3.

A B3 publica diariamente, de graça (histórico de ~10 dias), o arquivo "Posições em Aberto em
Derivativos (Listado)" no Boletim Diário. Diferente do volume (COTAHIST), o open interest é o
total de contratos EM ABERTO — bem mais informativo para pressão/posicionamento.

IMPORTANTE (honestidade): a URL exata do arquivo diário da B3 é dinâmica e muda; configure em
env OI_URL. O PARSER é flexível (acha as colunas por nome) e testado; a BUSCA valida no runtime
do usuário. Sem OI_URL/erro -> None (nada é inventado). Desligue com env OI=0.

Call/Put é derivado da LETRA DE SÉRIE do código da opção (padrão B3): 5ª posição após a raiz —
A–L = CALL (jan–dez), M–X = PUT (jan–dez). Heurística: vale para opções mensais padrão; séries
semanais/especiais podem fugir. Razão OI = OI de puts ÷ OI de calls (proxy de posicionamento).
"""
from __future__ import annotations

import io
import math
import os
import re
from urllib.request import Request, urlopen


def _raiz(ticker: str) -> str:
    m = re.match(r"^([A-Za-z]+)", str(ticker))
    return m.group(1).upper() if m else str(ticker).upper()


def _split_letras_digitos(code: str):
    """'PETRX40' -> ('PETRX','40'). Retorna (letras, digitos) ou (code,'')."""
    m = re.match(r"^([A-Za-z]+)(\d+)", str(code).upper())
    return (m.group(1), m.group(2)) if m else (str(code).upper(), "")


def tipo_opcao(code: str):
    """'C' (call) / 'P' (put) / None, pela letra de série (A–L call, M–X put)."""
    letras, dig = _split_letras_digitos(code)
    if not dig or len(letras) < 2:
        return None
    serie = letras[-1]                      # letra logo antes do strike
    if "A" <= serie <= "L":
        return "C"
    if "M" <= serie <= "X":
        return "P"
    return None


def raiz_do_codigo(code: str) -> str:
    """Raiz do ATIVO-BASE a partir do código da opção: 'PETRX40' -> 'PETR' (tira a série)."""
    letras, dig = _split_letras_digitos(code)
    return letras[:-1] if (dig and len(letras) >= 2) else letras


def _achar_col(header, termos):
    """Índice da 1ª coluna cujo nome (normalizado) contém algum dos termos."""
    for i, h in enumerate(header):
        hn = str(h).upper()
        if any(t in hn for t in termos):
            return i
    return -1


def classificar_opcao(code: str, roots_ord):
    """Dada a lista de raízes conhecidas (mais longas primeiro), decide se `code` é uma OPÇÃO
    e retorna (raiz_base, tipo 'C'/'P') ou None. Regra: o código começa com uma raiz conhecida
    e o caractere logo após a raiz é uma LETRA de série (a AÇÃO tem um dígito ali)."""
    up = str(code).upper()
    for r in roots_ord:
        if r and up.startswith(r) and len(up) > len(r):
            serie = up[len(r)]
            if serie.isalpha():                 # letra de série -> é opção
                if "A" <= serie <= "L":
                    return r, "C"
                if "M" <= serie <= "X":
                    return r, "P"
                return None                     # letra fora do padrão mensal
            return None                         # dígito após a raiz -> é a AÇÃO à vista
    return None


def parse_oi(texto: str, underlying_roots=None):
    """Parser flexível do CSV de posições em aberto. Retorna lista de
    dict(ticker, raiz, tipo, oi). Se `underlying_roots` for dado, classifica opção vs ação de
    forma robusta (raiz conhecida + letra de série); senão, usa a heurística da última letra."""
    linhas = [l for l in texto.splitlines() if l.strip()]
    if not linhas:
        return []
    sep = ";" if linhas[0].count(";") >= linhas[0].count(",") else ","
    hidx = 0
    for i, l in enumerate(linhas[:15]):
        up = l.upper()
        if ("TCKR" in up or "INSTRUMENT" in up or "CODIGO" in up or "CÓDIGO" in up
                or "SIMBOLO" in up or "SÍMBOLO" in up):
            hidx = i
            break
    header = [h.strip() for h in linhas[hidx].split(sep)]
    ci = _achar_col(header, ("TCKRSYMB", "INSTRUMENT", "CODIGO", "CÓDIGO", "SIMBOLO",
                             "SÍMBOLO", "SERIE", "SÉRIE"))
    oi_i = _achar_col(header, ("POSABRT", "ABRT", "ABERT", "POSI", "CONTRAT",
                               "OPNINTRST", "OPENINTEREST", "OINTR", "OPEN", "TITULAR"))
    if ci == -1 or oi_i == -1:
        return []
    roots_ord = sorted({str(r).upper() for r in (underlying_roots or [])},
                       key=len, reverse=True)
    out = []
    for l in linhas[hidx + 1:]:
        cols = l.split(sep)
        if len(cols) <= max(ci, oi_i):
            continue
        code = cols[ci].strip().strip('"')
        if roots_ord:
            cl = classificar_opcao(code, roots_ord)
            if cl is None:
                continue
            raiz, tp = cl
        else:
            tp = tipo_opcao(code)
            if tp is None:
                continue
            raiz = raiz_do_codigo(code)
        try:
            oi = float(str(cols[oi_i]).replace(".", "").replace(",", ".").strip('" '))
        except Exception:
            continue
        out.append({"ticker": code, "raiz": raiz, "tipo": tp, "oi": oi})
    return out


def _ratio(call_oi: float, put_oi: float) -> dict:
    tot = call_oi + put_oi
    return {"call_oi": call_oi, "put_oi": put_oi,
            "oi_ratio": (put_oi / call_oi) if call_oi > 0 else math.nan,
            "pct_call": (call_oi / tot * 100) if tot > 0 else math.nan,
            "pct_put": (put_oi / tot * 100) if tot > 0 else math.nan}


def oi_ratios(posicoes: list, ticker_setor: dict = None) -> dict:
    """Razão de open interest Put/Call por ativo, setor e mercado."""
    por_base = {}
    for p in posicoes:
        d = por_base.setdefault(p["raiz"], [0.0, 0.0])
        d[0 if p["tipo"] == "C" else 1] += p["oi"]
    por_ativo = {r: _ratio(c, pp) for r, (c, pp) in por_base.items()}
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
        for r, (c, pp) in por_base.items():
            s = raiz_setor.get(r)
            if not s:
                continue
            a = acc.setdefault(s, [0.0, 0.0])
            a[0] += c
            a[1] += pp
        por_setor = {s: _ratio(c, pp) for s, (c, pp) in acc.items()}
    return {"mercado": mercado, "por_setor": por_setor, "por_ativo": por_ativo}


def fetch_open_interest(ticker_setor: dict = None) -> dict | None:
    """Baixa o arquivo de posições em aberto (env OI_URL) e calcula os ratios. None em falha.
    A URL é configurável porque o endpoint diário da B3 muda; valida no runtime."""
    if os.getenv("OI", "1") == "0":
        return None
    url = os.getenv("OI_URL")
    if not url:
        print("[oi] defina OI_URL com o arquivo 'Posições em Aberto em Derivativos (Listado)' "
              "da B3 (Boletim Diário → Arquivos para download). Open interest fica n/d.")
        return None
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0 (screener-b3)"})
        with urlopen(req, timeout=90) as r:
            raw = r.read()
        # pode vir zipado
        if raw[:4] == b"PK\x03\x04":
            import zipfile
            zf = zipfile.ZipFile(io.BytesIO(raw))
            texto = zf.read(zf.namelist()[0]).decode("latin-1")
        else:
            texto = raw.decode("latin-1")
        roots = None
        if ticker_setor:
            roots = {_raiz(tk) for tk in ticker_setor}
        posicoes = parse_oi(texto, underlying_roots=roots)
        if not posicoes:
            print("[oi] arquivo baixado mas não reconheci as colunas — rode com o cabeçalho "
                  "real que eu ajusto o parser.")
            return None
        r = oi_ratios(posicoes, ticker_setor)
        r["n_series"] = len(posicoes)
        pc = r["mercado"]["oi_ratio"]
        print(f"[oi] {len(posicoes)} séries; OI Put/Call mercado="
              + (f"{pc:.2f}" if not math.isnan(pc) else "n/d"))
        return r
    except Exception as e:
        print(f"[oi] falha ao baixar/parsear: {e}")
        return None
