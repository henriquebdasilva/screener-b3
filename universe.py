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


def get_universe(which: str = "both") -> dict[str, list[str]]:
    """Retorna dict {ticker: [origem,...]} respeitando a seleção.

    which: 'ibov' | 'smll' | 'both'
    """
    which = which.lower()
    groups = {}
    if which in ("ibov", "both"):
        for t in _dedup(IBOV):
            groups.setdefault(t, []).append("BOVA11")
    if which in ("smll", "both"):
        for t in _dedup(SMLL):
            groups.setdefault(t, []).append("SMALL11")
    return groups


def to_yahoo(ticker: str) -> str:
    """Converte ticker B3 para o formato do Yahoo Finance (sufixo .SA)."""
    return f"{ticker.strip().upper()}.SA"


if __name__ == "__main__":
    u = get_universe("both")
    print(f"Total de tickers no universo: {len(u)}")
    print("Exemplos:", list(u.items())[:5])
