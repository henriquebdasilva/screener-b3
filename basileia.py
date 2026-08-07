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
    "BBAS3":  ("00000000", ["BANCO DO BRASIL"]),
    "ITUB4":  ("60701190", ["ITAU UNIBANCO", "ITAÚ UNIBANCO"]),
    "ITUB3":  ("60701190", ["ITAU UNIBANCO", "ITAÚ UNIBANCO"]),
    "BBDC4":  ("60746948", ["BRADESCO"]),
    "BBDC3":  ("60746948", ["BRADESCO"]),
    "SANB11": ("90400888", ["SANTANDER"]),
    "BPAC11": ("30306294", ["BTG PACTUAL"]),
    "ABCB4":  ("28195667", ["ABC BRASIL"]),
    "BMGB4":  ("61186680", ["BMG"]),
    "BRSR6":  ("92702067", ["BANRISUL", "ESTADO DO RIO GRANDE DO SUL"]),
    "BPAN4":  ("59285411", ["BANCO PAN", "PANAMERICANO"]),
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

    # --- sondagem de metadados (só no debug): descobre relatórios válidos e formato ---
    if debug:
        try:
            rr = requests.get(f"{BASE}/ListaDeRelatorio?$format=json&$top=80", timeout=40)
            if rr.status_code == 200:
                for it in rr.json().get("value", []):
                    num = it.get("NumeroRelatorio") or it.get("Numero") or it.get("Codigo")
                    nome = it.get("NomeRelatorio") or it.get("Nome") or it.get("Descricao")
                    print(f"   [basileia][rel] {num} = {nome}")
            else:
                print(f"   [basileia] ListaDeRelatorio HTTP {rr.status_code}: {rr.text[:200]}")
        except Exception as e:
            print(f"   [basileia] ListaDeRelatorio erro: {e}")
        for am in _candidate_anomes()[:2]:
            try:
                rc = requests.get(
                    f"{BASE}/IfDataCadastro(AnoMes=@AnoMes)?@AnoMes={am}&$format=json&$top=1",
                    timeout=40)
                txt = rc.text[:220]
                print(f"   [basileia] Cadastro {am}: HTTP {rc.status_code} {txt}")
            except Exception as e:
                print(f"   [basileia] Cadastro {am} erro: {e}")

    def _get(url):
        try:
            r = requests.get(url, timeout=40)
            if r.status_code != 200:
                if debug and _err_shown[0] < 4:      # mostra o corpo do erro do BC
                    _err_shown[0] += 1
                    print(f"   [basileia] HTTP {r.status_code}: {r.text[:280]}")
                return None
            return r.json().get("value", [])
        except Exception as e:
            if debug:
                print(f"   [basileia] erro: {e}")
            return None

    def _url(anomes, tipo, rel, quote_rel):
        # @ LITERAL (o requests codificaria como %40 e o Olinda rejeita)
        r = f"'{rel}'" if quote_rel else str(rel)
        return (f"{BASE}/IfDataValores(AnoMes=@AnoMes,TipoInstituicao=@TipoInstituicao,"
                f"Relatorio=@Relatorio)?@AnoMes={anomes}&@TipoInstituicao={tipo}"
                f"&@Relatorio={r}&$format=json")

    # relatórios candidatos que costumam conter Basileia (Resumo / Informações de Capital)
    relatorios = os.getenv("BASILEIA_RELATORIOS", "1,11,2").split(",")
    tipos = os.getenv("BASILEIA_TIPOS", "2,1,3,4").split(",")

    for anomes in _candidate_anomes():
        registros = []
        for tipo in tipos:
            for rel in relatorios:
                for quote_rel in (False, True):      # tenta Relatorio sem e com aspas
                    vals = _get(_url(anomes, tipo.strip(), rel.strip(), quote_rel))
                    if vals:
                        if debug and registros == []:
                            print(f"   [basileia] OK {anomes} tipo={tipo} rel={rel} "
                                  f"quote={quote_rel}: {len(vals)} regs | chaves: "
                                  f"{list(vals[0].keys())[:14]}")
                        registros.extend(vals)
                        break                        # achou o formato -> não repete
        if not registros:
            continue

        out = {}
        for tk in alvos:
            cnpj_root, nomes = BANKS[tk]
            achou = None
            for rec in registros:
                # casa por CNPJ (raiz) ou por nome (substring)
                rec_cnpj = _digits(rec.get("CNPJ") or rec.get("Cnpj") or "")[:8]
                rec_nome = str(rec.get("NomeInstituicao") or rec.get("Instituicao")
                               or rec.get("Nome") or "").upper()
                match = (cnpj_root and rec_cnpj == cnpj_root) or \
                        any(h.upper() in rec_nome for h in nomes)
                if not match:
                    continue
                val = _find_basileia_in_record(rec)
                if val is not None:
                    achou = val
                    break
            if achou is not None:
                out[tk] = achou
        if out:
            print(f"[basileia] IF.data {anomes}: {len(out)} banco(s) com Basileia "
                  f"({', '.join(sorted(out))}).")
            return out

    print("[basileia] IF.data: não foi possível obter Basileia (Safety das financeiras "
          "segue n/d). Rode com BASILEIA_DEBUG=1 para ver os campos retornados e ajustar "
          "os parâmetros (BASILEIA_RELATORIOS / BASILEIA_TIPOS).")
    return {}
