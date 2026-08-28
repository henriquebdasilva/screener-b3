"""bdi_indices.py — IFIX e Fluxo estrangeiro via o capítulo 02 do BDI ("Indicadores e
Informativos"), fonte oficial B3 (mesmo canal já usado em opcoes.py/posicoes.py).

IFIX: o BDI traz "Evolução dos Índices" com fechamento e variações (dia/mês/ano) — direto,
sem cálculo. Fluxo estrangeiro: o BDI só publica o ACUMULADO DO MÊS (compras/vendas), não o
valor isolado do dia. O fluxo do dia é a DIFERENÇA entre o acumulado de hoje e o de ontem —
por isso precisa de um cache do valor anterior (arquivo em reports/, versionado no repo pelo
próprio workflow). Na virada do mês, o acumulado reinicia; detectamos e não calculamos delta
negativo espúrio nesse caso (fica n/d nesse único dia).

Honestidade: nada é estimado — se a fonte ou o cache faltar, o indicador fica None. Desligue
com env BDI_INDICES=0. Cache: env FLUXO_CACHE_PATH (default 'reports/.fluxo_cache.json').
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
from urllib.request import Request, urlopen


def _bdi_pdf_url(dataobj, capitulo="02"):
    d = dataobj
    return (f"https://arquivos.b3.com.br/bdi/download/bdi/{d.strftime('%Y-%m-%d')}/"
            f"BDI_{capitulo}_{d.strftime('%Y%m%d')}.pdf")


def _pdf_text(fonte) -> str:
    import pymupdf
    doc = pymupdf.open(stream=fonte, filetype="pdf") if isinstance(fonte, (bytes, bytearray)) \
        else pymupdf.open(fonte)
    return "\n".join(p.get_text() for p in doc)


def _num_br(s):
    """Padrão BR: ponto = milhar, vírgula = decimal (usado na tabela de investidores)."""
    s = str(s).strip().replace(".", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return None


def _num_pts(s):
    """Pontos de índice no BDI: vírgula = separador de milhar (ex.: '133,009' = 133009)."""
    s = str(s).strip().replace(",", "")
    try:
        return float(s)
    except Exception:
        return None


def _num_pct(s):
    """Percentuais de 'Evolução dos Fechamentos': ponto decimal direto (ex.: '-0.21')."""
    try:
        return float(str(s).strip())
    except Exception:
        return None


def parse_ifix(texto: str) -> dict | None:
    """Extrai o bloco IFIX de 'Evolução dos Índices' (fechamento + variações)."""
    m = re.search(r"IFIX\s*\n?Comportamento no Dia.*?Fechamento\s+([\d.,]+)", texto, re.S)
    if not m:
        return None
    fechamento = _num_pts(m.group(1))
    out = {"fechamento": fechamento}
    m2 = re.search(r"IFIX\s*\(%\)\s*Do dia\s+([\-\d.]+)%.*?No mês\s+([\-\d.]+)%"
                   r".*?No ano\s+([\-\d.]+)%", texto, re.S)
    if m2:
        out["var_dia_pct"] = _num_pct(m2.group(1))
        out["var_mes_pct"] = _num_pct(m2.group(2))
        out["var_ano_pct"] = _num_pct(m2.group(3))
    return out if fechamento is not None else None


def parse_fluxo_acumulado(texto: str) -> dict | None:
    """Extrai 'Participação dos Investidores' (compras/vendas ACUMULADAS do mês) do
    Investidor Estrangeiro. Também tenta capturar a data-base ('até o dia DD/MM/AAAA')."""
    m = re.search(r"Investidor Estrangeiro\s+([\d.,]+)\s+([\d,]+)\s+([\d.,]+)\s+([\d,]+)",
                  texto)
    if not m:
        return None
    compras, vendas = _num_br(m.group(1)), _num_br(m.group(3))
    if compras is None or vendas is None:
        return None
    dm = re.search(r"até o dia (\d{2}/\d{2}/\d{4})", texto)
    data_base = None
    if dm:
        try:
            data_base = dt.datetime.strptime(dm.group(1), "%d/%m/%Y").date()
        except Exception:
            pass
    return {"compras_acum_mes": compras, "vendas_acum_mes": vendas,
            "saldo_acum_mes": compras - vendas, "data_base": data_base}


def _fetch_bdi02(dias_tentativa: int = 6):
    """Baixa o BDI_02 mais recente disponível. Retorna (texto, data) ou (None, None)."""
    for i in range(dias_tentativa):
        d = dt.date.today() - dt.timedelta(days=i)
        url = _bdi_pdf_url(d)
        try:
            req = Request(url, headers={"User-Agent": "Mozilla/5.0 (screener-b3)"})
            with urlopen(req, timeout=90) as r:
                raw = r.read()
            if raw[:4] != b"%PDF":
                continue
            return _pdf_text(bytes(raw)), d
        except Exception:
            continue
    return None, None


def fetch_ifix() -> dict | None:
    """IFIX (fechamento + variações) via BDI. None se indisponível — nunca inventa."""
    if os.getenv("BDI_INDICES", "1") == "0":
        return None
    texto, d = _fetch_bdi02()
    if not texto:
        print("[bdi_indices] IFIX: não consegui baixar o BDI_02.")
        return None
    ifix = parse_ifix(texto)
    if not ifix:
        print("[bdi_indices] IFIX: layout não reconhecido no BDI_02.")
        return None
    ifix["data"] = d
    print(f"[bdi_indices] IFIX {d}: {ifix['fechamento']:.0f} pts "
          f"({ifix.get('var_dia_pct', float('nan')):+.2f}% no dia)")
    return ifix


def fetch_fluxo_estrangeiro(cache_path: str = None) -> dict | None:
    """Fluxo estrangeiro DIÁRIO = delta do acumulado do mês (BDI) vs. o cache de ontem.
    Sem cache anterior (1º dia do mês ou primeira execução), retorna só o acumulado, sem
    'dia' (não há como isolar o primeiro dia sem o acumulado do dia anterior do mês)."""
    if os.getenv("BDI_INDICES", "1") == "0":
        return None
    cache_path = cache_path or os.getenv("FLUXO_CACHE_PATH", "reports/.fluxo_cache.json")
    texto, d = _fetch_bdi02()
    if not texto:
        print("[bdi_indices] fluxo estrangeiro: não consegui baixar o BDI_02.")
        return None
    acc = parse_fluxo_acumulado(texto)
    if not acc:
        print("[bdi_indices] fluxo estrangeiro: layout não reconhecido no BDI_02.")
        return None
    data_ref = acc.get("data_base") or d

    cache = {}
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            cache = json.load(f)
    except Exception:
        pass

    resultado = {"acum_mes": acc["saldo_acum_mes"], "data": data_ref, "dia": None, "mes": None}
    prev = cache.get("ultimo")
    if prev:
        prev_data = dt.date.fromisoformat(prev["data"]) if prev.get("data") else None
        mesmo_mes = prev_data and prev_data.year == data_ref.year and prev_data.month == data_ref.month
        if mesmo_mes and prev_data < data_ref:
            resultado["dia"] = acc["saldo_acum_mes"] - prev["acum_mes"]
        resultado["mes"] = acc["saldo_acum_mes"]  # acumulado do mês corrente, sempre disponível

    # grava o cache para o próximo dia (best-effort; não quebra o fluxo se falhar)
    try:
        os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({"ultimo": {"data": data_ref.isoformat(),
                                  "acum_mes": acc["saldo_acum_mes"]}}, f)
    except Exception as e:
        print(f"[bdi_indices] fluxo estrangeiro: falha ao gravar cache: {e}")

    if resultado["dia"] is not None:
        print(f"[bdi_indices] fluxo estrangeiro {data_ref}: dia R$ {resultado['dia']:+,.0f} mi "
              f"| mês R$ {resultado['mes']:+,.0f} mi")
    else:
        print(f"[bdi_indices] fluxo estrangeiro {data_ref}: sem cache do dia anterior — "
              f"só acumulado do mês (R$ {resultado['acum_mes']:+,.0f} mi). "
              f"Amanhã já calcula o valor diário.")
    return resultado
