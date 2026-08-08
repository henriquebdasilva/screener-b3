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
            r = requests.get(url, timeout=60)
            if r.status_code != 200:
                if debug and _err_shown[0] < 3:
                    _err_shown[0] += 1
                    print(f"   [basileia] HTTP {r.status_code}: {r.text[:160]}")
                return None
            return r.json().get("value", [])
        except Exception as e:
            if debug:
                print(f"   [basileia] erro: {e}")
            return None

    # sondagem dedicada ao Relatório 5 (descobre TipoInstituicao/variação que responde 200)
    if debug:
        for am in _candidate_anomes()[:2]:
            for tp in (1, 2, 3, 4):
                for label, extra in (("plain", ""),
                                     ("top", "&$top=30000")):
                    u = (f"{BASE}/IfDataValores(AnoMes=@AnoMes,TipoInstituicao="
                         f"@TipoInstituicao,Relatorio=@Relatorio)?@AnoMes={am}"
                         f"&@TipoInstituicao={tp}&@Relatorio='5'{extra}&$format=json")
                    try:
                        r = requests.get(u, timeout=60)
                        n = len(r.json().get("value", [])) if r.status_code == 200 else 0
                        bas = False
                        if n:
                            bas = any("basileia" in str(x.get("NomeColuna", "")).lower()
                                      for x in r.json()["value"])
                        print(f"   [basileia][probe5] {am} tipo={tp} {label}: "
                              f"HTTP {r.status_code} regs={n} basileia={bas}")
                    except Exception as e:
                        print(f"   [basileia][probe5] {am} tipo={tp} {label}: ERRO {e}")

    def _cadastro(anomes):
        """CodInst -> NomeInstituicao (para casar tickers por nome)."""
        url = (f"{BASE}/IfDataCadastro(AnoMes=@AnoMes)?@AnoMes={anomes}"
               f"&$format=json&$select=CodInst,NomeInstituicao&$top=5000")
        vals = _get(url) or []
        return {r.get("CodInst"): str(r.get("NomeInstituicao") or "").upper() for r in vals}

    def _valores(anomes, tipo=2, rel=5):
        # Relatório 5 = "Informações de Capital" (Índice de Basileia). Relatorio é TEXTO.
        url = (f"{BASE}/IfDataValores(AnoMes=@AnoMes,TipoInstituicao=@TipoInstituicao,"
               f"Relatorio=@Relatorio)?@AnoMes={anomes}&@TipoInstituicao={tipo}"
               f"&@Relatorio='{rel}'&$format=json")
        for _ in range(2):                 # 1 retry em caso de 500 transitório
            v = _get(url)
            if v:
                return v
        return _get(url) or []

    tipo = int(os.getenv("BASILEIA_TIPO", "2"))
    # Relatório 5 = "Informações de Capital" (contém o Índice de Basileia). Confirmado
    # via catálogo ListaDeRelatorio. Fixável/ajustável por env BASILEIA_RELATORIO.
    env_rel = os.getenv("BASILEIA_RELATORIO", "").strip()
    relatorios = [env_rel] if env_rel else ["5"]
    # o par (TipoInstituicao, Relatorio) precisa ser válido; Basileia é métrica de
    # conglomerado prudencial -> o tipo pode não ser 2. Testa vários (fixável por env).
    env_tipos = os.getenv("BASILEIA_TIPOS", "").strip()
    tipos = ([int(x) for x in env_tipos.split(",")] if env_tipos
             else [tipo, 1, 3, 4, 5])
    # dedup preservando ordem
    tipos = list(dict.fromkeys(tipos))

    # catálogo de relatórios (debug) — número + nome de cada relatório disponível
    if debug:
        # 1) $metadata: assinatura EXATA das funções (para de adivinhar parâmetros)
        try:
            md = requests.get(f"{BASE}/$metadata", timeout=40).text
            for alvo in ("ListaDeRelatorio", "IfDataValores", "TipoInstituicao"):
                i = md.find(alvo)
                if i >= 0:
                    print(f"   [basileia][meta] …{md[max(0,i-40):i+320]}…")
        except Exception as e:
            print(f"   [basileia][meta] erro: {e}")
        # 2) tenta ListaDeRelatorio em algumas formas
        am0 = _candidate_anomes()[1]
        for probe in (
            f"{BASE}/ListaDeRelatorio()?$format=json",
            f"{BASE}/ListaDeRelatorio(TipoInstituicao=@T)?@T={tipo}&$format=json",
            f"{BASE}/ListaDeRelatorio(AnoMes=@A,TipoInstituicao=@T)?@A={am0}&@T={tipo}"
            f"&$format=json",
        ):
            got = _get(probe)
            if got:
                for it in got:
                    print(f"   [basileia][catalogo] {it}")
                break

    for ai, anomes in enumerate(_candidate_anomes()[:3]):   # 3 trimestres mais recentes
        registros = None
        for rel in relatorios:
            for tp in tipos:
                regs = _valores(anomes, tp, rel.strip())
                if not regs:
                    continue
                tem_bas = any("basileia" in str(r.get("NomeColuna", "")).lower()
                              or "basileia" in str(r.get("DescricaoColuna", "")).lower()
                              for r in regs)
                if debug and ai == 0:
                    cols = sorted({str(r.get("NomeColuna")) for r in regs})
                    print(f"   [basileia] {anomes} tipo={tp} rel={rel}: {len(regs)} regs "
                          f"| basileia? {tem_bas} | 1as colunas: {cols[:6]}")
                if tem_bas:
                    print(f"   [basileia] >>> ACHOU Basileia em {anomes} tipo={tp} rel={rel}")
                    registros = regs
                    break
            if registros is not None:
                break
        if not registros:
            continue

        # 1) Índice de Basileia por CodInst. "Informações de Capital" pode ter vários
        #    campos com "Basileia" (ex.: Ampliado); preferimos o principal.
        cand = {}   # cod -> {nome_norm: valor}
        col_ex = set()
        for rec in registros:
            nome_col = str(rec.get("NomeColuna") or "")
            desc_col = str(rec.get("DescricaoColuna") or "")
            alvo = f"{nome_col} {desc_col}".lower()
            if "basileia" in alvo:
                cod = rec.get("CodInst")
                try:
                    fv = float(str(rec.get("Saldo")).replace(",", "."))
                except Exception:
                    continue
                if cod and not math.isnan(fv):
                    cand.setdefault(cod, {})[_norm(nome_col)] = fv
            elif debug and len(col_ex) < 40:
                col_ex.add(nome_col)

        def _pick(d):
            # prefere "Índice de Basileia" puro; evita Ampliado/Nível/Principal
            exato = [v for k, v in d.items() if "basileia" in k
                     and not any(x in k for x in ("AMPL", "NIVEL", "PRINCIPAL", "IMOBIL"))]
            return exato[0] if exato else next(iter(d.values()))

        basileia_por_inst = {cod: _pick(d) for cod, d in cand.items() if d}

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
