"""Índice de Basileia das financeiras (Safety) — IF.data do Banco Central.

Objetivo: dar Safety às financeiras, que ficam NaN nos indicadores de balanço, ancorado no
piso regulatório (11% -> 0; 18% -> 100).

Fontes, nesta ordem:
  1) TABELA MANUAL (BASILEIA_MANUAL abaixo, ou env BASILEIA_MANUAL em JSON) — CONFIÁVEL.
     Preencha ~1x por trimestre com o Índice de Basileia de cada banco. Onde obter:
       - IF.data web: https://www3.bcb.gov.br/ifdata/  (Relatório "Informações de Capital"), ou
       - release de resultados / RI de cada banco.
  2) API Olinda/OData (IF.data) — BÔNUS, se disponível. Hoje o relatório de capital (nº 5,
     "Informações de Capital"), o ÚNICO com a Basileia, retorna HTTP 500 no servidor do BC
     em todos os tipos/trimestres (bug do lado deles). Fica ligada para popular sozinha se e
     quando o BC corrigir. Desligue a chamada de rede com env BASILEIA_API=0.

Tudo degrada com elegância: sem dado -> Safety segue n/d (nada quebra). Desligue tudo com
env BASILEIA=0.
"""
from __future__ import annotations

import json
import math
import os

BASE = "https://olinda.bcb.gov.br/olinda/servico/IFDATA/versao/v1/odata"

# ticker -> pistas de nome p/ casar no cadastro do IF.data (quando a API voltar a funcionar)
BANKS = {
    "BBAS3":  ["BANCO DO BRASIL", "BCO DO BRASIL", "BB"],
    "ITUB4":  ["ITAU"],
    "ITUB3":  ["ITAU"],
    "BBDC4":  ["BRADESCO"],
    "BBDC3":  ["BRADESCO"],
    "SANB11": ["SANTANDER"],
    "BPAC11": ["BTG"],
    "ABCB4":  ["ABC BRASIL", "ABC-BRASIL", "ABCBRASIL"],
    "BMGB4":  ["BMG"],
    "BRSR6":  ["BANRISUL"],
    "BPAN4":  ["BANCO PAN", "PAN", "PANAMERICANO"],
    "PINE4":  ["PINE"],
}

# ------------------------------------------------------------------------------------------
# TABELA MANUAL — preencha o Índice de Basileia (%) por ticker e a data-base de referência.
# Ex.: {"ITUB4": 15.3, "BBAS3": 14.9, "BBDC4": 15.1, ...}. Deixe vazio o que não tiver.
# (Vazio por padrão de propósito: não invento números — preencha com dados oficiais.)
BASILEIA_MANUAL: dict[str, float] = {
    # "ITUB4": 0.0,
    # "BBAS3": 0.0,
}
BASILEIA_MANUAL_REF = "preencha em basileia.py (BASILEIA_MANUAL)"

BASILEIA_FLOOR = 11.0     # piso regulatório (%) -> nota 0
BASILEIA_TOP = 18.0       # a partir daqui -> nota 100


def basileia_safety(pct, floor: float = BASILEIA_FLOOR, top: float = BASILEIA_TOP) -> float:
    """Índice de Basileia (%) -> 0-100 (linear entre floor e top, saturando)."""
    try:
        p = float(pct)
    except Exception:
        return math.nan
    if math.isnan(p):
        return math.nan
    return float(max(0.0, min(100.0, (p - floor) / (top - floor) * 100.0)))


def _norm(s) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return "".join(ch for ch in s.upper() if ch.isalnum())


def _manual_map() -> dict:
    """Tabela manual (código) + override por env BASILEIA_MANUAL (JSON)."""
    out = {k: float(v) for k, v in BASILEIA_MANUAL.items()
           if isinstance(v, (int, float)) and float(v) > 0}
    env = os.getenv("BASILEIA_MANUAL", "").strip()
    if env:
        try:
            for k, v in json.loads(env).items():
                if float(v) > 0:
                    out[str(k).upper()] = float(v)
        except Exception:
            pass
    return out


def _candidate_anomes(n: int = 6):
    """Últimos trimestres (YYYYMM, MM∈{03,06,09,12}), do mais recente ao mais antigo."""
    import datetime as dt
    d = dt.date.today()
    out = []
    for yy in (d.year, d.year - 1):
        for mm in (12, 9, 6, 3):
            if yy * 100 + mm <= d.year * 100 + d.month:
                out.append(yy * 100 + mm)
    return sorted(set(out), reverse=True)[:n]


def _fetch_api(alvos, debug=False) -> dict:
    """Tenta a API OData (relatório de capital). Hoje costuma falhar (500 no BC)."""
    if os.getenv("BASILEIA_API", "1") == "0":
        return {}
    try:
        import requests
    except Exception:
        return {}
    rel = os.getenv("BASILEIA_RELATORIO", "5")
    tipos = [int(x) for x in os.getenv("BASILEIA_TIPOS", "1,2,3").split(",")]

    def _get(url):
        try:
            r = requests.get(url, timeout=45)
            if r.status_code != 200:
                if debug:
                    print(f"   [basileia] HTTP {r.status_code} (rel={rel})")
                return None
            return r.json().get("value", [])
        except Exception as e:
            if debug:
                print(f"   [basileia] erro: {e}")
            return None

    for anomes in _candidate_anomes():
        for tp in tipos:
            url = (f"{BASE}/IfDataValores(AnoMes=@AnoMes,TipoInstituicao=@TipoInstituicao,"
                   f"Relatorio=@Relatorio)?@AnoMes={anomes}&@TipoInstituicao={tp}"
                   f"&@Relatorio='{rel}'&$format=json")
            regs = _get(url)
            if not regs:
                continue
            if not any("basileia" in str(r.get("NomeColuna", "")).lower() for r in regs):
                continue
            # extrai Basileia principal por CodInst
            por_inst = {}
            for r in regs:
                nome = str(r.get("NomeColuna") or "")
                if "basileia" not in nome.lower():
                    continue
                nn = _norm(nome)
                if any(x in nn for x in ("AMPL", "NIVEL", "PRINCIPAL", "IMOBIL")):
                    continue
                try:
                    por_inst[r.get("CodInst")] = float(str(r.get("Saldo")).replace(",", "."))
                except Exception:
                    pass
            if not por_inst:
                continue
            cad_url = (f"{BASE}/IfDataCadastro(AnoMes=@AnoMes)?@AnoMes={anomes}"
                       f"&$format=json&$select=CodInst,NomeInstituicao&$top=5000")
            cad = {r.get("CodInst"): _norm(r.get("NomeInstituicao"))
                   for r in (_get(cad_url) or [])}
            out = {}
            for tk in alvos:
                hints = [_norm(h) for h in BANKS[tk]]
                for cod, pct in por_inst.items():
                    nm = cad.get(cod, "")
                    if nm and any(h and h in nm for h in hints):
                        out[tk] = pct
                        break
            if out:
                print(f"[basileia] IF.data API {anomes}: {len(out)} banco(s) "
                      f"({', '.join(f'{k} {v:.1f}%' for k, v in sorted(out.items()))}).")
                return out
    return {}


def fetch_basileia_map(tickers, debug: bool = None) -> dict:
    """{ticker: Índice de Basileia %} para os bancos do mapa. Manual primeiro; API como bônus."""
    if os.getenv("BASILEIA", "1") == "0":
        return {}
    if debug is None:
        _dbg = os.getenv("BASILEIA_DEBUG", "0").strip().lower()
        debug = _dbg not in ("", "0", "false", "no")
    alvos = [t for t in tickers if t in BANKS]
    if not alvos:
        return {}

    manual = _manual_map()
    out = {tk: manual[tk] for tk in alvos if tk in manual}
    if out:
        print(f"[basileia] tabela manual: {len(out)} banco(s) "
              f"({', '.join(f'{k} {v:.1f}%' for k, v in sorted(out.items()))}).")

    faltam = [tk for tk in alvos if tk not in out]
    if faltam:
        api = _fetch_api(faltam, debug=debug)
        out.update(api)

    if not out:
        print("[basileia] sem Basileia (Safety das financeiras segue n/d). Preencha a tabela "
              "manual BASILEIA_MANUAL em basileia.py — a API do IF.data (relatório de capital) "
              "está retornando 500 no servidor do BC.")
    return out
