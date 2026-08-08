"""Índice de Basileia das financeiras via IF.data do Banco Central (API Olinda/OData).

Objetivo: dar um Safety às financeiras (que ficam NaN nos indicadores de balanço), ancorado
no piso regulatório. Fonte pública, JSON, sem autenticação:
  https://olinda.bcb.gov.br/olinda/servico/IFDATA/versao/v1/odata/

Tudo degrada com elegância: em qualquer falha (rede, formato, banco fora do mapa), retorna
vazio e o Safety segue n/d (comportamento atual). Desligue com env BASILEIA=0.

ATENÇÃO: os CNPJs abaixo são best-effort e devem ser conferidos; o casamento também tenta
por NOME (substring) contra o cadastro do IF.data, o que torna a busca mais robusta.
"""
from __future__ import annotations

import math
import os

BASE = "https://olinda.bcb.gov.br/olinda/servico/IFDATA/versao/v1/odata"

# ticker -> (raiz do CNPJ 8 dígitos | None, pistas de nome p/ casar no cadastro do IF.data)
BANKS = {
    "BBAS3":  ("00000000", ["BANCO DO BRASIL", "BCO DO BRASIL", "BB"]),
    "ITUB4":  ("60701190", ["ITAU"]),
    "ITUB3":  ("60701190", ["ITAU"]),
    "BBDC4":  ("60746948", ["BRADESCO"]),
    "BBDC3":  ("60746948", ["BRADESCO"]),
    "SANB11": ("90400888", ["SANTANDER"]),
    "BPAC11": ("30306294", ["BTG"]),
    "ABCB4":  ("28195667", ["ABC BRASIL", "ABC-BRASIL", "ABCBRASIL"]),
    "BMGB4":  ("61186680", ["BMG"]),
    "BRSR6":  ("92702067", ["BANRISUL"]),
    "BPAN4":  ("59285411", ["BANCO PAN", "PAN", "PANAMERICANO"]),
    "PINE4":  ("62144175", ["PINE"]),
}

BASILEIA_FLOOR = 11.0     # piso regulatório (%) -> nota 0
BASILEIA_TOP = 18.0       # a partir daqui -> nota 100


def basileia_safety(pct, floor: float = BASILEIA_FLOOR, top: float = BASILEIA_TOP) -> float:
    """Mapeia o Índice de Basileia (%) para 0-100 (linear entre floor e top, saturando)."""
    try:
        p = float(pct)
    except Exception:
        return math.nan
    if math.isnan(p):
        return math.nan
    s = (p - floor) / (top - floor) * 100.0
    return float(max(0.0, min(100.0, s)))


def _digits(s) -> str:
    return "".join(ch for ch in str(s) if ch.isdigit())


def _norm(s) -> str:
    """Uppercase, sem acentos, só A-Z0-9 (p/ casar nomes curtos do IF.data)."""
    import unicodedata
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return "".join(ch for ch in s.upper() if ch.isalnum())


def _find_basileia_in_record(rec: dict):
    """Procura um campo cujo nome contenha 'basileia' e devolve o valor numérico."""
    for k, v in rec.items():
        if "basileia" in str(k).lower():
            try:
                fv = float(str(v).replace(",", "."))
                if not math.isnan(fv):
                    return fv
            except Exception:
                pass
    return None


def _candidate_anomes(n: int = 8):
    """Últimos trimestres (YYYYMM, MM∈{03,06,09,12}), do mais recente ao mais antigo."""
    import datetime as dt
    d = dt.date.today()
    out = []
    for yy in (d.year, d.year - 1, d.year - 2):
        for mm in (12, 9, 6, 3):
            if yy * 100 + mm <= d.year * 100 + d.month:
                out.append(yy * 100 + mm)
    out = sorted(set(out), reverse=True)
    return out[:n]


def fetch_basileia_map(tickers, debug: bool = None) -> dict:
    """Retorna {ticker: indice_basileia_%} para os tickers financeiros do mapa.

    v1: tenta o relatório de capital/resumo do IF.data no trimestre mais recente. Como a
    parametrização exata do Olinda pode variar, faz uma varredura defensiva e imprime
    diagnósticos; em falha, retorna {} (Safety segue n/d).
    """
    if os.getenv("BASILEIA", "1") == "0":
        return {}
    if debug is None:
        _dbg = os.getenv("BASILEIA_DEBUG", "0").strip().lower()
        debug = _dbg not in ("", "0", "false", "no")   # qualquer outro valor liga
    alvos = [t for t in tickers if t in BANKS]
    if not alvos:
        return {}
    try:
        import requests
    except Exception:
        return {}

    _err_shown = [0]

    def _get(url):
        try:
            r = requests.get(url, timeout=40)
            if r.status_code != 200:
                if debug and _err_shown[0] < 3:
                    _err_shown[0] += 1
                    print(f"   [basileia] HTTP {r.status_code}: {r.text[:200]}")
                return None
            return r.json().get("value", [])
        except Exception as e:
            if debug:
                print(f"   [basileia] erro: {e}")
            return None

    def _cadastro(anomes):
        """CodInst -> NomeInstituicao (para casar tickers por nome)."""
        url = (f"{BASE}/IfDataCadastro(AnoMes=@AnoMes)?@AnoMes={anomes}"
               f"&$format=json&$select=CodInst,NomeInstituicao&$top=5000")
        vals = _get(url) or []
        return {r.get("CodInst"): str(r.get("NomeInstituicao") or "").upper() for r in vals}

    def _valores(anomes, tipo=2, rel=1):
        # Relatório 1 = "Resumo" (contém o Índice de Basileia). Relatorio como TEXTO ('1').
        url = (f"{BASE}/IfDataValores(AnoMes=@AnoMes,TipoInstituicao=@TipoInstituicao,"
               f"Relatorio=@Relatorio)?@AnoMes={anomes}&@TipoInstituicao={tipo}"
               f"&@Relatorio='{rel}'&$format=json")
        return _get(url) or []

    tipo = int(os.getenv("BASILEIA_TIPO", "2"))
    # a Basileia fica no relatório de "Informações/Índices de Capital" (não no Resumo=1).
    # varremos candidatos; o número certo é fixável por env BASILEIA_RELATORIO.
    env_rel = os.getenv("BASILEIA_RELATORIO", "").strip()
    relatorios = [env_rel] if env_rel else ["11", "12", "13", "14", "2", "3", "4", "6"]

    # catálogo de relatórios (debug) — ajuda a achar o nº do relatório de capital
    if debug:
        for probe in (f"{BASE}/ListaDeRelatorio?$format=json",
                      f"{BASE}/ListaDeRelatorio(AnoMes=@AnoMes)?@AnoMes="
                      f"{_candidate_anomes()[1]}&$format=json"):
            got = _get(probe)
            if got:
                for it in got:
                    n = it.get("Relatorio") or it.get("NumeroRelatorio") or it.get("Numero")
                    nm = (it.get("NomeRelatorio") or it.get("Nome")
                          or it.get("Descricao") or it.get("NomeColuna"))
                    print(f"   [basileia][catalogo] {n} = {nm}")
                break

    for anomes in _candidate_anomes():
        registros = None
        for rel in relatorios:
            regs = _valores(anomes, tipo, rel.strip())
            if not regs:
                continue
            tem_bas = any("basileia" in str(r.get("NomeColuna", "")).lower()
                          or "basileia" in str(r.get("DescricaoColuna", "")).lower()
                          for r in regs)
            if debug:
                cols = sorted({str(r.get("NomeColuna")) for r in regs})[:12]
                print(f"   [basileia] {anomes} rel={rel}: {len(regs)} regs | "
                      f"basileia? {tem_bas} | colunas: {cols}")
            if tem_bas:
                registros = regs
                break
        if not registros:
            continue

        # 1) Índice de Basileia por CodInst: linha cujo NomeColuna/Descrição contém "basileia"
        basileia_por_inst = {}
        col_ex = set()
        for rec in registros:
            nome_col = str(rec.get("NomeColuna") or "").lower()
            desc_col = str(rec.get("DescricaoColuna") or "").lower()
            if "basileia" in nome_col or "basileia" in desc_col:
                cod = rec.get("CodInst")
                val = rec.get("Saldo")
                try:
                    fv = float(str(val).replace(",", "."))
                    if cod and not math.isnan(fv):
                        basileia_por_inst[cod] = fv
                except Exception:
                    pass
            elif debug and len(col_ex) < 40:
                col_ex.add(rec.get("NomeColuna"))

        if not basileia_por_inst:
            if debug:
                print(f"   [basileia] {anomes}: {len(registros)} regs, nenhuma coluna "
                      f"'Basileia'. Exemplos de NomeColuna: {sorted(c for c in col_ex if c)[:20]}")
            continue

        # 2) mapa CodInst -> nome (para casar por nome do banco)
        cad = _cadastro(anomes)

        # 3) casa cada ticker por nome (via cadastro), com normalização
        out = {}
        cad_norm = {cod: _norm(nome) for cod, nome in cad.items()}
        for tk in alvos:
            _, nomes = BANKS[tk]
            hints = [_norm(h) for h in nomes]
            for cod, pct in basileia_por_inst.items():
                nome_inst = cad_norm.get(cod, "")
                if nome_inst and any(h and h in nome_inst for h in hints):
                    out[tk] = pct
                    break
        if out:
            print(f"[basileia] IF.data {anomes}: {len(out)} banco(s) com Basileia "
                  f"({', '.join(f'{k} {v:.1f}%' for k, v in sorted(out.items()))}).")
            return out
        if debug:
            print(f"   [basileia] {anomes}: {len(basileia_por_inst)} instituições com "
                  f"Basileia, mas nenhuma casou. Ex.: "
                  f"{[cad.get(c) for c in list(basileia_por_inst)[:8]]}")

    print("[basileia] IF.data: não foi possível casar Basileia (Safety das financeiras segue "
          "n/d). Rode com BASILEIA_DEBUG=on para ver instituições/colunas e ajustar o mapa.")
    return {}
