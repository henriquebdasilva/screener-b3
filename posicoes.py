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


def strike_do_codigo(code: str, spot: float = None):
    """Estima o strike a partir do código da opção (fallback quando não há strike limpo).
    Ex.: 'PETRK406' -> tenta 406/10=40,6 ou 406/100=4,06 e escolhe o mais próximo do spot.
    Retorna float ou None. POUCO confiável: use o strike do COTAHIST quando possível."""
    import re
    m = re.match(r"^[A-Za-z]+?([A-Za-z])(\d+)$", str(code).upper())
    if not m:
        return None
    dig = m.group(2)
    cands = [int(dig) / 10.0, int(dig) / 100.0, float(int(dig))]
    if spot and spot > 0:
        return min(cands, key=lambda x: abs(x - spot))
    return cands[0]                  # sem spot: assume /10 (mais comum p/ ações da B3)


def resolver_destaques_oi(maior_oi: dict, strike_map: dict = None, spot: dict = None) -> dict:
    """Enriquece o dict 'maior_oi' (raiz -> {code,tipo,oi}) com o strike: usa o strike LIMPO do
    COTAHIST (strike_map por código) e cai para a estimativa do código quando não houver."""
    strike_map = strike_map or {}
    spot = spot or {}
    out = {}
    for raiz, d in (maior_oi or {}).items():
        st = strike_map.get(d["code"])
        if st is None:
            st = strike_do_codigo(d["code"], spot.get(raiz))
        out[raiz] = {**d, "strike": st}
    return out


def _ratio(call_oi: float, put_oi: float) -> dict:
    tot = call_oi + put_oi
    return {"call_oi": call_oi, "put_oi": put_oi,
            "oi_ratio": (put_oi / call_oi) if call_oi > 0 else math.nan,
            "pct_call": (call_oi / tot * 100) if tot > 0 else math.nan,
            "pct_put": (put_oi / tot * 100) if tot > 0 else math.nan}


def oi_ratios(posicoes: list, ticker_setor: dict = None) -> dict:
    """Razão de open interest Put/Call por ativo, setor e mercado. Também guarda, por ativo, a
    série de MAIOR open interest (code, tipo, oi) para destaque no relatório."""
    por_base = {}
    maior_oi = {}                    # raiz -> série com maior OI
    for p in posicoes:
        d = por_base.setdefault(p["raiz"], [0.0, 0.0])
        d[0 if p["tipo"] == "C" else 1] += p["oi"]
        cur = maior_oi.get(p["raiz"])
        if cur is None or p["oi"] > cur["oi"]:
            maior_oi[p["raiz"]] = {"code": p["ticker"], "tipo": p["tipo"], "oi": p["oi"]}
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
    return {"mercado": mercado, "por_setor": por_setor, "por_ativo": por_ativo,
            "maior_oi": maior_oi}


def _parse_oi_json(texto: str, underlying_roots=None):
    """Parser flexível para JSON do BDI novo (arquivos.b3.com.br/bdi/tabelas). Procura, em
    qualquer lista de registros, os campos de código do instrumento e de posição em aberto."""
    import json
    try:
        data = json.loads(texto)
    except Exception:
        return []

    def achar_registros(obj):
        # procura recursivamente a maior lista de dicts
        melhor = []
        if isinstance(obj, list) and obj and isinstance(obj[0], dict):
            melhor = obj
        elif isinstance(obj, dict):
            for v in obj.values():
                cand = achar_registros(v)
                if len(cand) > len(melhor):
                    melhor = cand
        return melhor

    regs = achar_registros(data)
    if not regs:
        return []
    keys = list(regs[0].keys())

    def achar_key(termos):
        for k in keys:
            if any(t in str(k).upper() for t in termos):
                return k
        return None
    kcod = achar_key(("TCKR", "SYMB", "INSTRUMENT", "CODIGO", "CÓDIGO", "SERIE", "SÉRIE"))
    koi = achar_key(("POSABRT", "ABRT", "ABERT", "POSI", "CONTRAT", "OPEN", "OINTR"))
    if not kcod or not koi:
        return []
    roots_ord = sorted({str(r).upper() for r in (underlying_roots or [])},
                       key=len, reverse=True)
    out = []
    for r in regs:
        code = str(r.get(kcod, "")).strip().upper()
        cl = classificar_opcao(code, roots_ord) if roots_ord else (
            (raiz_do_codigo(code), tipo_opcao(code)) if tipo_opcao(code) else None)
        if not cl:
            continue
        raiz, tp = cl
        try:
            oi = float(str(r.get(koi)).replace(".", "").replace(",", ".").strip())
        except Exception:
            continue
        out.append({"ticker": code, "raiz": raiz, "tipo": tp, "oi": oi})
    return out


def _num_br(s):
    """'9.800' -> 9800.0 ; '-'/vazio -> None (formato numérico brasileiro)."""
    s = str(s).strip().strip('"')
    if not s or s == "-":
        return None
    try:
        return float(s.replace(".", "").replace(",", "."))
    except Exception:
        return None


def parse_oi_pdf(fonte) -> list:
    """Extrai o open interest de OPÇÕES SOBRE AÇÕES do PDF 'Derivativos de bolsa' (BDI_03-4).
    A tabela 'Quadro Analítico das Posições em Aberto' traz, por série: Ativo (ativo-base),
    Segmento ('EQUITY CALL'/'EQUITY PUT') e 'Total de posições' (índice 11) = open interest.
    Reconstrói as linhas pelas coordenadas das palavras. Requer PyMuPDF (pymupdf)."""
    import pymupdf
    from collections import defaultdict
    doc = pymupdf.open(stream=fonte, filetype="pdf") if isinstance(fonte, (bytes, bytearray)) \
        else pymupdf.open(fonte)
    out = []
    for page in doc:
        words = page.get_text("words")
        if not words:
            continue
        L = defaultdict(list)
        for w in words:
            L[round(w[1] / 3) * 3].append((w[0], w[4]))
        for y in sorted(L):
            cells = [t for _, t in sorted(L[y])]
            # junta o segmento em duas palavras ('EQUITY' + 'CALL'/'PUT')
            r, i = [], 0
            while i < len(cells):
                if cells[i] == "EQUITY" and i + 1 < len(cells) and cells[i + 1] in ("CALL", "PUT"):
                    r.append("EQUITY " + cells[i + 1])
                    i += 2
                else:
                    r.append(cells[i])
                    i += 1
            if len(r) >= 12 and r[4] in ("EQUITY CALL", "EQUITY PUT") and r[2]:
                oi = _num_br(r[11])                 # 'Total de posições'
                if oi is not None:
                    out.append({"ticker": r[0], "raiz": r[2].upper(),
                                "tipo": "C" if r[4] == "EQUITY CALL" else "P", "oi": oi})
    return out


def parse_aluguel_pdf(fonte) -> dict:
    """Extrai o ALUGUEL (empréstimo de ativos) do PDF 'Empréstimos de ativos' (BDI_04-2),
    tabela 'Posições em aberto'. Por ativo, soma a linha 'Total': 'Saldo em quantidade do ativo'
    (ações em aberto) e 'Saldo em R$'. Retorna {ticker: {'qtd': ações, 'valor': R$}}.
    Ações em aberto no empréstimo = proxy de posição vendida (short) = pressão vendedora."""
    import pymupdf
    from collections import defaultdict
    doc = pymupdf.open(stream=fonte, filetype="pdf") if isinstance(fonte, (bytes, bytearray)) \
        else pymupdf.open(fonte)
    out, na_secao = {}, False
    for page in doc:
        txt = page.get_text()
        if "Posições em aberto" in txt or "Posições em Aberto" in txt:
            na_secao = True
        if not na_secao:
            continue
        words = page.get_text("words")
        L = defaultdict(list)
        for w in words:
            L[round(w[1] / 2) * 2].append((w[0], w[4]))
        for y in sorted(L):
            cells = [t for _, t in sorted(L[y])]
            if len(cells) >= 6 and cells[0].count("/") == 2 and "Total" in cells:
                tk = cells[1]
                qtd = _num_br(cells[-3])            # Saldo em quantidade do ativo
                val = _num_br(cells[-1])            # Saldo em R$
                if qtd is not None:
                    d = out.setdefault(tk, {"qtd": 0.0, "valor": 0.0})
                    d["qtd"] += qtd
                    d["valor"] += (val or 0.0)
    return out


def fetch_aluguel(ticker_setor: dict = None) -> dict | None:
    """Baixa o PDF 'Empréstimos de ativos' (BDI_04-2) e extrai a posição em aberto de aluguel
    por ativo. Envs: ALUGUEL=0 desliga; ALUGUEL_URL força URL; ALUGUEL_CAPITULO troca capítulo.
    Valida no runtime (B3 bloqueada no sandbox); parser testado em PDF real."""
    if os.getenv("ALUGUEL", "1") == "0":
        return None
    import datetime as dt
    cap = os.getenv("ALUGUEL_CAPITULO", "04-2")
    forcado = os.getenv("ALUGUEL_URL")
    tentativas = ([forcado] if forcado else
                  [_bdi_pdf_url(dt.date.today() - dt.timedelta(days=i), cap) for i in range(6)])
    for url in tentativas:
        try:
            req = Request(url, headers={"User-Agent": "Mozilla/5.0 (screener-b3)"})
            with urlopen(req, timeout=120) as r:
                raw = r.read()
        except Exception as e:
            print(f"[aluguel] {url.split('/')[-1]}: {e}")
            continue
        try:
            dados = raw
            if raw[:4] == b"PK\x03\x04":
                import zipfile
                zf = zipfile.ZipFile(io.BytesIO(raw))
                dados = zf.read(zf.namelist()[0])
            por_ativo = parse_aluguel_pdf(bytes(dados))
        except Exception as e:
            print(f"[aluguel] falha ao parsear {url.split('/')[-1]}: {e}")
            continue
        if not por_ativo:
            print(f"[aluguel] {url.split('/')[-1]} sem posições reconhecidas.")
            continue
        print(f"[aluguel] {url.split('/')[-1]}: {len(por_ativo)} ativos com posição de aluguel.")
        return {"por_ativo": por_ativo}
    print("[aluguel] não consegui baixar o BDI de empréstimos (B3 fora do ar ou layout mudou).")
    return None


def _bdi_pdf_url(dataobj, capitulo="03-4"):
    d = dataobj
    return (f"https://arquivos.b3.com.br/bdi/download/bdi/{d.strftime('%Y-%m-%d')}/"
            f"BDI_{capitulo}_{d.strftime('%Y%m%d')}.pdf")


def fetch_open_interest(ticker_setor: dict = None) -> dict | None:
    """Baixa o PDF 'Derivativos de bolsa' (BDI_03-4) da B3 e calcula o open interest Put/Call
    das opções sobre ações. Tenta a data de hoje e volta pregões. URL/capítulo configuráveis
    por env (OI_URL força uma URL; OI_CAPITULO troca o capítulo). Desligue com OI=0. None em falha.
    A busca valida no runtime (a B3 é bloqueada no meu sandbox); o parser é testado em PDF real."""
    if os.getenv("OI", "1") == "0":
        return None
    import datetime as dt
    cap = os.getenv("OI_CAPITULO", "03-4")
    forcado = os.getenv("OI_URL")
    tentativas = ([(forcado, None)] if forcado else
                  [(_bdi_pdf_url(dt.date.today() - dt.timedelta(days=i), cap),
                    dt.date.today() - dt.timedelta(days=i)) for i in range(6)])
    for url, d in tentativas:
        try:
            req = Request(url, headers={"User-Agent": "Mozilla/5.0 (screener-b3)"})
            with urlopen(req, timeout=120) as r:
                raw = r.read()
        except Exception as e:
            print(f"[oi] {url.split('/')[-1]}: {e}")
            continue
        try:
            if raw[:4] == b"%PDF":
                posicoes = parse_oi_pdf(bytes(raw))
            elif raw[:4] == b"PK\x03\x04":
                import zipfile
                zf = zipfile.ZipFile(io.BytesIO(raw))
                nome = zf.namelist()[0]
                dados = zf.read(nome)
                posicoes = (parse_oi_pdf(bytes(dados)) if nome.lower().endswith(".pdf")
                            else parse_oi(dados.decode("latin-1"),
                                          underlying_roots=({_raiz(t) for t in ticker_setor}
                                                            if ticker_setor else None)))
            elif raw[:1].decode("latin-1", "ignore") in "[{":
                posicoes = _parse_oi_json(raw.decode("utf-8", "replace"),
                                          {_raiz(t) for t in ticker_setor} if ticker_setor else None)
            else:
                posicoes = parse_oi(raw.decode("latin-1"),
                                    underlying_roots=({_raiz(t) for t in ticker_setor}
                                                      if ticker_setor else None))
        except Exception as e:
            print(f"[oi] falha ao parsear {url.split('/')[-1]}: {e}")
            continue
        if not posicoes:
            print(f"[oi] {url.split('/')[-1]} sem séries reconhecidas.")
            continue
        r = oi_ratios(posicoes, ticker_setor)
        r["n_series"] = len(posicoes)
        r["data"] = d
        pc = r["mercado"]["oi_ratio"]
        print(f"[oi] {url.split('/')[-1]}: {len(posicoes)} séries de opções; "
              f"OI Put/Call mercado=" + (f"{pc:.2f}" if not math.isnan(pc) else "n/d"))
        return r
    print("[oi] não consegui baixar o BDI de derivativos (B3 fora do ar ou layout mudou).")
    return None
