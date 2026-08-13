"""fluxo.py — fluxo de investidores ESTRANGEIROS na B3 (best-effort scraping).

Realidade honesta: a B3 NÃO tem uma API pública estável para isto. O dado sai em páginas
dinâmicas / arquivos (CSV, XLSX) que mudam de formato e URL. Este módulo é *best-effort*:
baixa um arquivo/URL, procura a linha de participação do estrangeiro em qualquer formato
tabular e extrai o valor. Degrada para None sem inventar nada.

Como usar / iterar:
- Configure a URL do arquivo de participação de investidores em FLUXO_URL (recomendado).
- Ative FLUXO_DEBUG=1 para imprimir o que foi encontrado (para ajustarmos o parser).
- Desligue com FLUXO=0.

Retorno de fetch_fluxo_estrangeiro(): dict
  {"dia": float|None, "mes": float|None, "acum_ano": float|None, "data": date|None,
   "unidade": "R$ mi", "src": url} — ou None se nada pôde ser obtido.
"""
from __future__ import annotations

import datetime as dt
import io
import os
import re
from urllib.request import Request, urlopen

# rótulos que identificam o investidor estrangeiro em relatórios da B3
_ALVOS = ("estrangeiro", "não residente", "nao residente", "investidor não residente",
          "investidor nao residente", "capital estrangeiro", "foreign")

# URLs candidatas (podem estar desatualizadas — ajuste FLUXO_URL). São apenas tentativas.
_CANDIDATAS = [
    # arquivo público de participação por tipo de investidor (formato varia)
    "https://arquivos.b3.com.br/apinegocios/tickercsv",  # placeholder — provavelmente incorreto
]


def _dbg(*a):
    if os.getenv("FLUXO_DEBUG", "0") == "1":
        print("[fluxo]", *a)


def _download(url: str, timeout: int = 30):
    """(bytes, content_type) de uma URL. Levanta em falha."""
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (screener-b3)",
        "Accept": "text/csv,application/vnd.ms-excel,application/json,*/*",
    })
    with urlopen(req, timeout=timeout) as r:
        return r.read(), (r.headers.get("Content-Type") or "").lower()


def _to_number(s):
    """Converte número em formato BR/US para float. Aceita número nativo. None se não der."""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    t = str(s).strip().replace("R$", "").replace("US$", "").replace("%", "").strip()
    if t in ("", "-", "—", "n/d", "nd", "N/D"):
        return None
    neg = t.startswith("(") and t.endswith(")")           # (1.234) = negativo
    t = t.strip("()").replace("\u00a0", "").replace(" ", "")
    if "," in t:                                           # BR: vírgula decimal, ponto milhar
        t = t.replace(".", "").replace(",", ".")
    elif t.count(".") >= 1:                                # só pontos: milhar se grupos de 3
        parts = t.split(".")
        if len(parts) >= 2 and all(len(p) == 3 for p in parts[1:]):
            t = "".join(parts)                            # 2.500 -> 2500 ; 1.234.567 -> ...
        # senão, ponto é decimal (mantém)
    try:
        v = float(t)
        return -v if neg else v
    except Exception:
        return None


def _rows_from_bytes(raw: bytes, ctype: str):
    """Tenta transformar o conteúdo baixado numa lista de linhas (listas de células)."""
    # XLSX
    if b"PK\x03\x04" == raw[:4] or "spreadsheet" in ctype or "excel" in ctype:
        try:
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
            rows = []
            for ws in wb.worksheets:
                for r in ws.iter_rows(values_only=True):
                    rows.append([c if isinstance(c, (int, float))
                                 else ("" if c is None else str(c)) for c in r])
            return rows
        except Exception as e:
            _dbg("xlsx falhou:", e)
    # JSON
    txt = None
    try:
        txt = raw.decode("utf-8", errors="replace")
    except Exception:
        txt = None
    if txt and ("json" in ctype or txt.lstrip()[:1] in "[{"):
        try:
            import json
            data = json.loads(txt)
            flat = data if isinstance(data, list) else data.get("values") or data.get("data") \
                or []
            rows = []
            for item in flat:
                if isinstance(item, dict):
                    rows.append([str(k) for k in item.keys()])
                    rows.append([str(v) for v in item.values()])
                elif isinstance(item, (list, tuple)):
                    rows.append([str(x) for x in item])
            if rows:
                return rows
        except Exception as e:
            _dbg("json falhou:", e)
    # CSV/TXT (detecta separador)
    if txt:
        sep = ";" if txt.count(";") >= txt.count(",") else ","
        return [ln.split(sep) for ln in txt.splitlines() if ln.strip()]
    return []


def _extrai_estrangeiro(rows):
    """Procura a linha do estrangeiro e devolve os números daquela linha (na ordem)."""
    for row in rows:
        joined = " ".join(str(c) for c in row).lower()
        if any(a in joined for a in _ALVOS):
            nums = [n for n in (_to_number(c) for c in row) if n is not None]
            if nums:
                _dbg("linha estrangeiro:", row, "-> números:", nums)
                return nums
    return None


def fetch_fluxo_estrangeiro() -> dict | None:
    """Best-effort: baixa o arquivo de participação de investidores e extrai o fluxo do
    estrangeiro. Retorna dict ou None. Só roda de verdade no ambiente do usuário (rede)."""
    if os.getenv("FLUXO", "1") == "0":
        return None
    urls = []
    if os.getenv("FLUXO_URL"):
        urls.append(os.getenv("FLUXO_URL"))
    urls += _CANDIDATAS
    for url in urls:
        try:
            _dbg("baixando", url)
            raw, ctype = _download(url)
            rows = _rows_from_bytes(raw, ctype)
            _dbg(f"{len(rows)} linhas; content-type={ctype}")
            nums = _extrai_estrangeiro(rows)
            if not nums:
                _dbg("não achei a linha do estrangeiro neste arquivo")
                continue
            # heurística: 1º número = fluxo do dia; se houver, 2º = mês; 3º = ano.
            return {
                "dia": nums[0] if len(nums) >= 1 else None,
                "mes": nums[1] if len(nums) >= 2 else None,
                "acum_ano": nums[2] if len(nums) >= 3 else None,
                "data": dt.date.today(),
                "unidade": "R$ mi",
                "src": url,
            }
        except Exception as e:
            _dbg("falhou:", url, e)
            continue
    return None
