# -*- coding: utf-8 -*-
"""
Universo de ações a varrer: constituintes do BOVA11 (Ibovespa) e do SMALL11 (SMLL).

IMPORTANTE — honestidade sobre os dados:
A composição OFICIAL e ponderada desses ETFs/índices é "gated" (a página da B3 é
renderizada por JavaScript e o arquivo da iShares/BlackRock exige download manual).
Por isso mantemos as listas de tickers AQUI, em um arquivo versionado e fácil de editar.
Elas mudam a cada rebalanceamento (quadrimestral na B3). Atualize periodicamente.

Como atualizar rapidamente:
  1. B3 -> Índices -> IBOV / SMLL -> "Composição da carteira" (exportar CSV), ou
  2. iShares -> BOVA11 / SMALL11 -> baixar "Holdings", ou
  3. Status Invest / Investidor10 -> página do índice.
Cole os tickers (sem sufixo) nas listas abaixo.

Observação: pesos não são usados no screener (ele avalia cada ação individualmente),
então basta a LISTA de tickers.
"""

from __future__ import annotations

import csv
import io
import os
import re

# CSVs oficiais de composição (iShares/BlackRock). A lista é buscada daqui a cada execução;
# se a rede/formato falhar, cai na lista estática abaixo.
BOVA11_URL = ("https://www.blackrock.com/br/products/251816/ishares-ibovespa-fundo-de-"
              "ndice-fund/1506433276998.ajax?fileType=csv&fileName=BOVA11_holdings&"
              "dataType=fund")
SMAL11_URL = ("https://www.blackrock.com/br/products/251752/ishares-bmfbovespa-small-cap-"
              "fundo-de-ndice-fund/1506433276998.ajax?fileType=csv&fileName=SMAL11_"
              "holdings&dataType=fund")

_TICKER_RE = re.compile(r"^[A-Z]{4}[0-9]{1,2}$")

# --- Ibovespa (proxy do BOVA11). Lista de referência ~2026; edite conforme o rebal. ---
IBOV = [
    "ALOS3", "ABEV3", "ASAI3", "AURE3", "AZUL4", "AZZA3", "B3SA3", "BBSE3", "BBDC3",
    "BBDC4", "BRAP4", "BBAS3", "BRKM5", "BRAV3", "BPAC11", "CXSE3", "CRFB3", "CCRO3",
    "CMIG4", "COGN3", "CPLE6", "CSAN3", "CPFE3", "CMIN3", "CVCB3", "CYRE3", "ELET3",
    "ELET6", "EMBR3", "ENGI11", "ENEV3", "EGIE3", "EQTL3", "FLRY3", "GGBR4", "GOAU4",
    "NTCO3", "HAPV3", "HYPE3", "IGTI11", "IRBR3", "ITSA4", "ITUB4", "JBSS3", "KLBN11",
    "RENT3", "LREN3", "MGLU3", "POMO4", "MRFG3", "BEEF3", "MRVE3", "MULT3", "PCAR3",
    "PETR3", "PETR4", "RECV3", "PRIO3", "PSSA3", "RADL3", "RAIZ4", "RDOR3", "RAIL3",
    "SBSP3", "SANB11", "STBP3", "SMTO3", "CSNA3", "SLCE3", "SUZB3", "TAEE11", "VIVT3",
    "TIMS3", "TOTS3", "UGPA3", "USIM5", "VALE3", "VAMO3", "VBBR3", "VIVA3", "WEGE3",
    "YDUQ3",
]

# --- SMLL (proxy do SMALL11). Lista de referência ~2026; edite conforme o rebal. ---
# Small caps são muitas (100+); esta é uma amostra ampla e representativa.
SMLL = [
    "AGRO3", "ALUP11", "ABCB4", "ARML3", "AMBP3", "ANIM3", "ARZZ3", "AZEV4", "BMGB4",
    "BRSR6", "CAML3", "CBAV3", "CEAB3", "CSMG3", "CURY3", "DIRR3", "DXCO3", "ECOR3",
    "ENJU3", "EZTC3", "FESA4", "FRAS3", "GMAT3", "GRND3", "GUAR3", "INTB3", "JALL3",
    "JHSF3", "KEPL3", "LAVV3", "LEVE3", "LOGG3", "LWSA3", "MDIA3", "MYPK3", "ODPV3",
    "ONCO3", "ORVR3", "PGMN3", "PLPL3", "PNVL3", "POSI3", "PTBL3", "QUAL3", "RANI3",
    "RAPT4", "SAPR11", "SBFG3", "SEER3", "SIMH3", "SMFT3", "TASA4", "TEND3", "TGMA3",
    "TTEN3", "TUPY3", "VLID3", "VULC3", "WIZC3", "YDUQ3",
]


def _dedup(seq):
    seen, out = set(), []
    for x in seq:
        x = x.strip().upper()
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _parse_ishares_csv(text: str):
    """Extrai (tickers, {ticker: setor}) de ação (Asset Class = Renda Variável) do CSV."""
    text = text.lstrip("\ufeff")
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines)
                  if l.strip().lower().startswith("ticker,")), None)
    if start is None:
        return None, {}
    reader = csv.reader(io.StringIO("\n".join(lines[start:])))
    header = next(reader, None)
    if not header:
        return None, {}
    cols = {h.strip().lower(): idx for idx, h in enumerate(header)}
    i_tk = cols.get("ticker")
    i_ac = cols.get("asset class")
    i_se = cols.get("setor") if "setor" in cols else cols.get("sector")
    if i_tk is None:
        return None, {}
    out, setores = [], {}
    for row in reader:
        if not row or len(row) <= i_tk:
            continue
        tk = row[i_tk].strip().strip('"').upper()
        ac = row[i_ac].strip() if (i_ac is not None and len(row) > i_ac) else "Renda Variável"
        if ac.lower() != "renda variável":            # exclui caixa, money market, futuros
            continue
        if _TICKER_RE.match(tk):
            out.append(tk)
            if i_se is not None and len(row) > i_se:
                se = row[i_se].strip().strip('"')
                if se and se != "-":
                    setores[tk] = se
    seen = set()
    res = [t for t in out if not (t in seen or seen.add(t))]
    return (res or None), setores


def _fetch_ishares_tickers(url: str, timeout: int = 30):
    """Baixa e parseia o CSV. Retorna (tickers|None, {ticker: setor})."""
    try:
        import requests
        headers = {"User-Agent": "Mozilla/5.0 (screener-b3)"}
        r = requests.get(url, headers=headers, timeout=timeout)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
        return _parse_ishares_csv(r.text)
    except Exception as e:
        print(f"[universo] falha ao baixar iShares ({e}) — usando lista estática.")
        return None, {}


_ISHARES_SECTORS: dict[str, str] = {}


def get_ishares_sectors() -> dict[str, str]:
    """{ticker: setor} coletado dos CSVs no último get_universe (setor GICS oficial)."""
    return dict(_ISHARES_SECTORS)


def get_universe(which: str = "both") -> dict[str, list[str]]:
    """Retorna dict {ticker: [origem,...]}.

    Fonte: CSVs oficiais da iShares (BOVA11/SMAL11), com fallback para as listas estáticas.
    Defina env UNIVERSE_SOURCE=static para pular o download e usar só as listas fixas.
    """
    which = which.lower()
    static_only = os.getenv("UNIVERSE_SOURCE", "ishares").lower() == "static"
    groups: dict[str, list[str]] = {}

    def _add(tickers, origem):
        for t in tickers:
            g = groups.setdefault(t.upper(), [])
            if origem not in g:
                g.append(origem)

    plan = []
    if which in ("ibov", "both"):
        plan.append(("BOVA11", BOVA11_URL, IBOV))
    if which in ("smll", "both"):
        plan.append(("SMALL11", SMAL11_URL, SMLL))

    _ISHARES_SECTORS.clear()
    for origem, url, estatica in plan:
        tks, setores = (None, {}) if static_only else _fetch_ishares_tickers(url)
        if tks:
            print(f"[universo] {origem}: {len(tks)} ativos da iShares (composição oficial).")
            _add(tks, origem)
            _ISHARES_SECTORS.update(setores)
        else:
            print(f"[universo] {origem}: {len(_dedup(estatica))} ativos da lista estática.")
            _add(_dedup(estatica), origem)
    return groups


def to_yahoo(ticker: str) -> str:
    """Converte ticker B3 para o formato do Yahoo Finance (sufixo .SA)."""
    return f"{ticker.strip().upper()}.SA"


if __name__ == "__main__":
    u = get_universe("both")
    print(f"Total de tickers no universo: {len(u)}")
    print("Exemplos:", list(u.items())[:5])
