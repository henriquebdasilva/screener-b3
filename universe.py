# -*- coding: utf-8 -*-
"""
Universo de ações a varrer: constituintes do BOVA11 (Ibovespa), do SMALL11 (SMLL) e do
DIVO11 (IDIV — índice de dividendos da B3).

IMPORTANTE — honestidade sobre os dados:
A composição OFICIAL e ponderada desses ETFs/índices é "gated" (a página da B3 é
renderizada por JavaScript e o arquivo da iShares/BlackRock exige download manual).
Por isso mantemos as listas de tickers AQUI, em um arquivo versionado e fácil de editar.
Elas mudam a cada rebalanceamento (quadrimestral na B3). Atualize periodicamente.

O DIVO11 (It Now IDIV, gestora Itaú Asset) é AINDA MENOS automatizável que o BOVA11/SMALL11:
não é gerido pela iShares/BlackRock (que ao menos tem um CSV de holdings), então não há
sequer uma tentativa de download automático — só a lista estática abaixo. Atualize com mais
frequência que as demais (o IDIV é rebalanceado quadrimestralmente, mas a lista de "quem entra
no índice" pode variar mais entre janelas, já que o critério é DY dos últimos 36 meses).

Como atualizar rapidamente:
  1. B3 -> Índices -> IBOV / SMLL / IDIV -> "Composição da carteira" (exportar CSV), ou
  2. iShares -> BOVA11 / SMALL11 -> baixar "Holdings" (não existe para o DIVO11/It Now), ou
  3. Status Invest / Investidor10 / itnow.com.br/divo11/composicao -> página do índice
     (renderizada por JS — copie os tickers manualmente).
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

# --- IDIV (proxy do DIVO11 — índice de dividendos da B3). Critério do índice: estar entre os
# 33% de MAIOR dividend yield nos últimos 36 meses. Setorialmente concentrado em bancos,
# elétricas/saneamento e seguradoras (pagadores tradicionais). Lista de referência ~2026;
# SEM fonte automática (nem CSV tipo iShares) — atualize manualmente com mais frequência que
# as demais (ver aviso no topo do arquivo). ---
IDIV = [
    "TAEE11", "CMIG4", "CPFE3", "CPLE6", "EGIE3", "ELET3", "ELET6", "ISAE4", "AURE3",
    "ITSA4", "BBAS3", "BBDC4", "BBDC3", "ITUB4", "SANB11", "ABCB4", "BRSR6", "BPAC11",
    "BBSE3", "PSSA3", "CXSE3", "WIZC3", "CSMG3", "SAPR11", "SBSP3",
    "VALE3", "PETR3", "PETR4", "VBBR3", "UGPA3", "CSAN3",
    "GGBR4", "GOAU4", "USIM5", "CMIN3", "UNIP6",
    "VIVT3", "TIMS3", "KLBN4", "SUZB3", "TRPL4",
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


def _fetch_b3_index_portfolio(index_code: str, timeout: int = 30):
    """Baixa a composição OFICIAL de um índice B3 (ex.: 'IDIV', 'IBOV', 'SMLL') via a API
    pública que alimenta a própria página da bolsa (sistemaswebb3-listados.b3.com.br/
    indexProxy/indexCall/GetPortfolioDay) — SEM o bloqueio de JavaScript da página em si;
    é um endpoint JSON puro. Diferente do CSV da iShares, não devolve setor (GICS) — só o
    ticker. Retorna (tickers|None, {}) — o dict vazio mantém a mesma assinatura de
    _fetch_ishares_tickers para o chamador não precisar diferenciar."""
    try:
        import base64
        import json
        import requests
        params = {"language": "pt-br", "pageNumber": 1, "pageSize": 200,
                  "index": index_code, "segment": "1"}
        b64 = base64.b64encode(json.dumps(params, separators=(",", ":")).encode()).decode()
        url = f"https://sistemaswebb3-listados.b3.com.br/indexProxy/indexCall/GetPortfolioDay/{b64}"
        headers = {"User-Agent": "Mozilla/5.0 (screener-b3)"}
        r = requests.get(url, headers=headers, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        results = data.get("results") or []
        tickers = [str(row["cod"]).strip().upper() for row in results if row.get("cod")]
        tickers = [t for t in tickers if _TICKER_RE.match(t)]
        return (tickers if tickers else None), {}
    except Exception as e:
        print(f"[universo] falha ao baixar B3 API ({index_code}: {e}) — usando lista estática.")
        return None, {}


_ISHARES_SECTORS: dict[str, str] = {}


def get_ishares_sectors() -> dict[str, str]:
    """{ticker: setor} coletado dos CSVs no último get_universe (setor GICS oficial)."""
    return dict(_ISHARES_SECTORS)


def get_universe(which: str = "both") -> dict[str, list[str]]:
    """Retorna dict {ticker: [origem,...]}.

    Fonte: CSVs oficiais da iShares (BOVA11/SMAL11) e a API pública da B3 (DIVO11/IDIV — a
    mesma que alimenta a página oficial da bolsa, sem o bloqueio de JavaScript da página em
    si), com fallback para as listas estáticas em caso de falha de qualquer uma das duas.
    O DIVO11 é SEMPRE incluído (independente de `which`) — é usado por uma seção à parte do
    relatório ('Qualidade + dividendos'), não pela seleção principal BOVA11/SMALL11. Um
    ticker pode aparecer em mais de uma origem (ex.: ITSA4 em BOVA11 E DIVO11).
    Defina env UNIVERSE_SOURCE=static para pular os downloads e usar só as listas fixas.
    """
    which = which.lower()
    static_only = os.getenv("UNIVERSE_SOURCE", "ishares").lower() == "static"
    groups: dict[str, list[str]] = {}

    def _add(tickers, origem):
        for t in tickers:
            g = groups.setdefault(t.upper(), [])
            if origem not in g:
                g.append(origem)

    # cada item: (origem, fonte, referência p/ a fonte, lista estática de fallback)
    #   fonte "ishares" -> referência = URL do CSV; fonte "b3api" -> referência = código do
    #   índice na B3 (ex.: "IDIV")
    plan = []
    if which in ("ibov", "both"):
        plan.append(("BOVA11", "ishares", BOVA11_URL, IBOV))
    if which in ("smll", "both"):
        plan.append(("SMALL11", "ishares", SMAL11_URL, SMLL))
    plan.append(("DIVO11", "b3api", "IDIV", IDIV))  # sempre incluído

    _ISHARES_SECTORS.clear()
    for origem, fonte, ref, estatica in plan:
        if static_only:
            tks, setores = None, {}
        elif fonte == "ishares":
            tks, setores = _fetch_ishares_tickers(ref)
        elif fonte == "b3api":
            tks, setores = _fetch_b3_index_portfolio(ref)
        else:
            tks, setores = None, {}
        if tks:
            fonte_txt = "iShares (composição oficial)" if fonte == "ishares" \
                else "API oficial da B3 (composição oficial)"
            print(f"[universo] {origem}: {len(tks)} ativos da {fonte_txt}.")
            _add(tks, origem)
            _ISHARES_SECTORS.update(setores)
        else:
            print(f"[universo] {origem}: {len(_dedup(estatica))} ativos da lista estática "
                  f"(fonte automática falhou ou UNIVERSE_SOURCE=static).")
            _add(_dedup(estatica), origem)
    return groups


def to_yahoo(ticker: str) -> str:
    """Converte ticker B3 para o formato do Yahoo Finance (sufixo .SA)."""
    return f"{ticker.strip().upper()}.SA"


if __name__ == "__main__":
    u = get_universe("both")
    print(f"Total de tickers no universo: {len(u)}")
    print("Exemplos:", list(u.items())[:5])
