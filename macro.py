"""macro.py — Panorama macro (fontes oficiais) e Índice de Regime Brasil.

Fontes (APIs públicas; rodam no ambiente do usuário — no sandbox de testes podem falhar,
e tudo degrada para n/d sem inventar nada):
- BCB SGS:  https://api.bcb.gov.br/dados/serie/bcdata.sgs.{cod}/dados
- Focus:    https://olinda.bcb.gov.br/olinda/servico/Expectativas (Expectativas de Mercado)
- yfinance: câmbio (BRL=X) e commodities (best-effort)

Regras: nada é estimado/inventado; cada indicador carrega sua DATA-BASE e FONTE; itens sem
dado ficam None ("Dado ainda não disponível na fonte oficial."). Desligue com env MACRO=0.
"""
from __future__ import annotations

import datetime as dt
import json
import math
from urllib.parse import quote
from urllib.request import Request, urlopen

# código SGS -> rótulo (para referência/depuração)
SGS = {
    "selic_meta": 432, "ipca_mensal": 433, "ipca_12m": 13522,
    "bc_saldo": 22707, "bc_exp": 22708, "bc_imp": 22709, "tc_mensal": 22701,
    "dbgg": 13762, "ibcbr": 24364, "reservas": 3546,
}


def _get_json(url: str, timeout: int = 25):
    req = Request(url, headers={"User-Agent": "screener-b3/1.0"})
    with urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def sgs(cod: int, n: int = 1):
    """Últimos n pontos de uma série SGS: lista de (date, float). [] em falha."""
    try:
        url = (f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{cod}"
               f"/dados/ultimos/{n}?formato=json")
        out = []
        for d in _get_json(url):
            try:
                dd = dt.datetime.strptime(d["data"], "%d/%m/%Y").date()
                out.append((dd, float(str(d["valor"]).replace(",", "."))))
            except Exception:
                pass
        return out
    except Exception:
        return []


def _last(cod: int):
    """Último ponto da série como (valor, data) — mesma ordem do _sum12 e do uso em fetch_macro.
    (sgs() devolve (data, valor); aqui invertemos para (valor, data).)"""
    s = sgs(cod, 1)
    return (s[-1][1], s[-1][0]) if s else (None, None)


def _sum12(cod: int):
    """Soma dos últimos 12 pontos (p/ acumulado 12m) e data-base do último ponto."""
    s = sgs(cod, 12)
    if not s:
        return None, None
    return sum(v for _, v in s), s[-1][0]


def focus_anual(indicador: str, ano: int):
    """Mediana Focus do indicador p/ o ano de referência: hoje e ~7/30/90 dias atrás.
    Retorna {'hoje':.., 'd7':.., 'd30':.., 'd90':.., 'data':date} ou {}.
    """
    try:
        filt = quote(f"Indicador eq '{indicador}' and DataReferencia eq '{ano}'")
        url = ("https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/"
               "ExpectativasMercadoAnuais?$format=json&$orderby=Data desc&$top=400&$filter="
               + filt)
        recs = _get_json(url).get("value", [])
        serie = []
        for r in recs:
            try:
                d = dt.datetime.strptime(r["Data"][:10], "%Y-%m-%d").date()
                serie.append((d, float(r["Mediana"])))
            except Exception:
                pass
        if not serie:
            return {}
        serie.sort(key=lambda x: x[0], reverse=True)
        hoje_d, hoje_v = serie[0]

        def _closest(offset):
            alvo = hoje_d - dt.timedelta(days=offset)
            best = min(serie, key=lambda x: abs((x[0] - alvo).days))
            return best[1] if abs((best[0] - alvo).days) <= 20 else None

        return {"hoje": hoje_v, "d7": _closest(7), "d30": _closest(30),
                "d90": _closest(90), "data": hoje_d}
    except Exception:
        return {}


def _yf_last(sym: str):
    try:
        import yfinance as yf
        h = yf.Ticker(sym).history(period="5d", auto_adjust=True)
        c = h["Close"].dropna()
        return (float(c.iloc[-1]), c.index[-1].date()) if len(c) else (None, None)
    except Exception:
        return (None, None)


def fetch_macro(selic_pct: float = None) -> dict:
    """Coleta o panorama macro. Cada campo é {'val':.., 'data':date|None, 'src':str} ou None.
    Degrada para n/d sem inventar. Desligue com env MACRO=0."""
    import os
    if os.getenv("MACRO", "1") == "0":
        return {}
    hoje = dt.date.today()
    ano = hoje.year
    m = {"consulta": hoje}

    sd, sdt = _last(SGS["selic_meta"])
    m["selic"] = {"val": (sd if sd is not None else selic_pct),
                  "data": sdt, "src": "BCB SGS 432"}
    ipca, ipdt = _last(SGS["ipca_12m"])
    m["ipca_12m"] = {"val": ipca, "data": ipdt, "src": "BCB SGS 13522"}
    bc, bcdt = _last(SGS["bc_saldo"])
    bc12, _ = _sum12(SGS["bc_saldo"])
    m["bc_saldo_mes"] = {"val": bc, "data": bcdt, "src": "BCB SGS 22707"}
    m["bc_saldo_12m"] = {"val": bc12, "data": bcdt, "src": "BCB SGS 22707 (12m)"}
    tc, tcdt = _last(SGS["tc_mensal"])
    tc12, _ = _sum12(SGS["tc_mensal"])
    m["tc_mes"] = {"val": tc, "data": tcdt, "src": "BCB SGS 22701"}
    m["tc_12m"] = {"val": tc12, "data": tcdt, "src": "BCB SGS 22701 (12m)"}
    dbgg, dbdt = _last(SGS["dbgg"])
    m["dbgg"] = {"val": dbgg, "data": dbdt, "src": "BCB SGS 13762"}
    ibc, ibdt = _last(SGS["ibcbr"])
    m["ibcbr"] = {"val": ibc, "data": ibdt, "src": "BCB SGS 24364"}

    cambio, cdt = _yf_last("BRL=X")
    m["cambio"] = {"val": cambio, "data": cdt, "src": "yfinance BRL=X"}
    brent, brdt = _yf_last("BZ=F")
    m["brent"] = {"val": brent, "data": brdt, "src": "yfinance BZ=F"}

    m["focus_ipca"] = focus_anual("IPCA", ano)
    m["focus_selic"] = focus_anual("Selic", ano)
    m["focus_cambio"] = focus_anual("Câmbio", ano)
    m["focus_pib"] = focus_anual("PIB Total", ano)

    try:                                                 # fluxo estrangeiro (best-effort B3)
        from fluxo import fetch_fluxo_estrangeiro
        fx = fetch_fluxo_estrangeiro()
        m["fluxo_estrangeiro"] = fx                      # dict ou None
    except Exception:
        m["fluxo_estrangeiro"] = None
    return m


# ------------------- Índice de Regime Brasil (simplificado) -------------------
# Pesos originais do painel: setor externo 20, inflação 15, juros 15, fluxo 15,
# mercado 10, valuation 20, fiscal 5. Sem fluxo estrangeiro e valuation (não confiáveis
# headless), renormaliza sobre os componentes disponíveis.
_PESOS = {"externo": 20, "inflacao": 15, "juros": 15, "mercado": 10, "fiscal": 5}


def _clamp(x, lo=0.0, hi=100.0):
    return max(lo, min(hi, x))


def _score_externo(bc12m, tc12m):
    if bc12m is None:
        return None
    s = 55 + _clamp(bc12m / 1000.0 * 0.6, -35, 35)      # cada US$ bi de saldo 12m
    if tc12m is not None:
        s += _clamp(tc12m / 1000.0 * 0.4, -20, 15)
    return _clamp(s)


def _score_inflacao(ipca12m, focus):
    if ipca12m is None:
        return None
    s = _clamp(100 - (ipca12m - 3.0) * 12)              # meta 3%; 6%->64; 8%->40
    if focus and focus.get("hoje") is not None and focus.get("d30") is not None:
        s += 8 if focus["hoje"] < focus["d30"] else (-8 if focus["hoje"] > focus["d30"] else 0)
    return _clamp(s)


def _score_juros(selic, focus):
    if selic is None:
        return None
    s = _clamp(50 - (selic - 10.5) * 6)                 # 10,5% neutro; 14%->29; 8%->65
    if focus and focus.get("hoje") is not None and focus.get("d30") is not None:
        s += 8 if focus["hoje"] < focus["d30"] else (-8 if focus["hoje"] > focus["d30"] else 0)
    return _clamp(s)


def _score_mercado(breadth_alta):
    return None if breadth_alta is None else _clamp(float(breadth_alta))


def _score_fiscal(dbgg):
    if dbgg is None:
        return None
    return _clamp(75 - (dbgg - 75.0) * 2.5)             # ~75% do PIB neutro; sobe -> pior


def regime_brasil(macro: dict, breadth_alta=None) -> dict:
    """Índice 0-100 (renormalizado sobre componentes disponíveis) + detalhamento.
    Retorna {'score':float|None, 'componentes':{nome:(nota,peso_norm)}, 'faixa':str}."""
    def gv(k):
        return (macro.get(k) or {}).get("val") if isinstance(macro.get(k), dict) else None
    notas = {
        "externo": _score_externo(gv("bc_saldo_12m"), gv("tc_12m")),
        "inflacao": _score_inflacao(gv("ipca_12m"), macro.get("focus_ipca")),
        "juros": _score_juros(gv("selic"), macro.get("focus_selic")),
        "mercado": _score_mercado(breadth_alta),
        "fiscal": _score_fiscal(gv("dbgg")),
    }
    disp = {k: v for k, v in notas.items() if v is not None}
    if not disp:
        return {"score": None, "componentes": {}, "faixa": "n/d"}
    peso_tot = sum(_PESOS[k] for k in disp)
    comp, score = {}, 0.0
    for k, v in disp.items():
        pw = _PESOS[k] / peso_tot
        comp[k] = (round(v, 1), round(pw * 100, 1))
        score += v * pw
    score = round(score, 1)
    faixa = ("🟢 Bull/acumulação" if score >= 80 else "🟢 Normal/positivo" if score >= 60
             else "🟠 Atenção/seletivo" if score >= 40 else "🔴 Estresse" if score >= 20
             else "🔴 Crise")
    return {"score": score, "componentes": comp, "faixa": faixa,
            "n_disp": len(disp), "n_tot": len(_PESOS)}


# ------------------- Renderização -------------------
def _fmt_d(d):
    return d.strftime("%d/%m/%Y") if d else "n/d"


def _seta(focus):
    if not focus or focus.get("hoje") is None or focus.get("d30") is None:
        return ""
    if focus["hoje"] < focus["d30"]:
        return " <span style='color:#16a34a'>▼</span>"
    if focus["hoje"] > focus["d30"]:
        return " <span style='color:#dc2626'>▲</span>"
    return " ="


def _v(macro, k):
    d = macro.get(k)
    return d.get("val") if isinstance(d, dict) else None


def _row(label, valor, data, focus_txt=""):
    return (f"<tr><td>{label}</td><td class='r'>{valor}</td>"
            f"<td class='r' style='color:#6b7280'>{data}</td>"
            f"<td class='r'>{focus_txt}</td></tr>")


def render_panel(macro: dict, regime: dict) -> str:
    """Painel macro compacto p/ o TOPO do e-mail (usa as classes CSS do relatório)."""
    if not macro:
        return ""
    def g(k):
        return macro.get(k) or {}
    selic, ipca = _v(macro, "selic"), _v(macro, "ipca_12m")
    cam = _v(macro, "cambio")
    bc12, tc12 = _v(macro, "bc_saldo_12m"), _v(macro, "tc_12m")
    dbgg = _v(macro, "dbgg")
    fi, fs, fc = macro.get("focus_ipca"), macro.get("focus_selic"), macro.get("focus_cambio")
    rows = []
    rows.append(_row("Juros — Selic",
                     f"{selic:.2f}%" if selic is not None else "n/d",
                     _fmt_d(g("selic").get("data")),
                     (f"{fs['hoje']:.2f}%{_seta(fs)}" if fs and fs.get("hoje") is not None
                      else "")))
    rows.append(_row("Inflação — IPCA 12m",
                     f"{ipca:.2f}%" if ipca is not None else "n/d",
                     _fmt_d(g("ipca_12m").get("data")),
                     (f"{fi['hoje']:.2f}%{_seta(fi)}" if fi and fi.get("hoje") is not None
                      else "")))
    rows.append(_row("Câmbio — USD/BRL",
                     f"R$ {cam:.2f}" if cam is not None else "n/d",
                     _fmt_d(g("cambio").get("data")),
                     (f"R$ {fc['hoje']:.2f}{_seta(fc)}" if fc and fc.get("hoje") is not None
                      else "")))
    rows.append(_row("Balança comercial (12m)",
                     f"US$ {bc12/1000:.1f} bi" if bc12 is not None else "n/d",
                     _fmt_d(g("bc_saldo_12m").get("data")), ""))
    rows.append(_row("Transações correntes (12m)",
                     f"US$ {tc12/1000:.1f} bi" if tc12 is not None else "n/d",
                     _fmt_d(g("tc_12m").get("data")), ""))
    rows.append(_row("Dívida bruta (DBGG)",
                     f"{dbgg:.1f}% PIB" if dbgg is not None else "n/d",
                     _fmt_d(g("dbgg").get("data")), ""))
    fx = macro.get("fluxo_estrangeiro")
    if fx and fx.get("dia") is not None:
        dia = fx["dia"]
        cor = "#16a34a" if dia >= 0 else "#dc2626"
        extra_fx = ""
        if fx.get("mes") is not None:
            extra_fx = (f" · mês <span style='color:"
                        f"{'#16a34a' if fx['mes'] >= 0 else '#dc2626'}'>"
                        f"{fx['mes']:+,.0f}</span>")
        rows.append(_row("Fluxo estrangeiro (B3)",
                         f"<span style='color:{cor}'>{dia:+,.0f}</span> R$ mi{extra_fx}",
                         _fmt_d(fx.get("data")), ""))
    else:
        rows.append(_row("Fluxo estrangeiro (B3)", "n/d", "", ""))

    sc = regime.get("score")
    if sc is not None:
        comp = " · ".join(f"{k} {n:.0f}" for k, (n, _) in regime["componentes"].items())
        badge = (f'<div style="margin:6px 0 2px;font-size:15px"><b>Índice de Regime Brasil: '
                 f'{sc:.0f}/100</b> — {regime["faixa"]}</div>'
                 f'<p class="sub" style="margin:0 0 8px">Componentes (0-100): {comp}. '
                 f'Renormalizado sobre {regime["n_disp"]}/{regime["n_tot"]} componentes '
                 f'disponíveis; exclui fluxo estrangeiro e valuation (sem fonte confiável '
                 f'automática). Não é previsão — é um termômetro heurístico.</p>')
    else:
        badge = '<p class="sub">Índice de Regime Brasil: dados macro indisponíveis hoje.</p>'

    head = ("<tr><th>Indicador</th><th class='r'>Atual</th><th class='r'>Data-base</th>"
            "<th class='r'>Focus (ano)</th></tr>")
    return (f'<h2 style="font-size:15px;margin:6px 0 6px;color:#0f172a">Panorama macro</h2>'
            f'{badge}<div class="ind"><table>{head}{"".join(rows)}</table></div>'
            '<p class="sub" style="margin:4px 0 14px">Fontes: BCB (SGS e Focus) e yfinance. '
            'Focus ▼ = expectativa caiu vs. ~30 dias; ▲ = subiu. Relatório macro completo '
            'no anexo.</p>')


def render_report(macro: dict, regime: dict, hoje: str) -> str:
    """Relatório macro mais completo para anexar (HTML standalone)."""
    if not macro:
        return "<html><body><p>Dados macro indisponíveis nesta execução.</p></body></html>"
    panel = render_panel(macro, regime)
    def g(k):
        return macro.get(k) or {}
    exp = _v(macro, "bc_exp"); imp = _v(macro, "bc_imp")
    ibc = _v(macro, "ibcbr"); brent = _v(macro, "brent")
    extra = []
    if _v(macro, "bc_saldo_mes") is not None:
        extra.append(f"<li>Balança comercial (mês): US$ {_v(macro,'bc_saldo_mes')/1000:.1f} bi "
                     f"({_fmt_d(g('bc_saldo_mes').get('data'))})</li>")
    if ibc is not None:
        extra.append(f"<li>IBC-Br (proxy do PIB mensal): {ibc:.1f} "
                     f"({_fmt_d(g('ibcbr').get('data'))})</li>")
    if brent is not None:
        extra.append(f"<li>Petróleo Brent: US$ {brent:.2f} ({_fmt_d(g('brent').get('data'))})</li>")
    css = ("body{font-family:Arial,Helvetica,sans-serif;color:#111;max-width:760px;"
           "margin:24px auto;padding:0 16px}table{border-collapse:collapse;width:100%;"
           "font-size:13px}th{background:#1f3864;color:#fff;text-align:left;padding:6px}"
           "td{padding:5px 6px;border-bottom:1px solid #e5e7eb}td.r,th.r{text-align:right}"
           ".sub{color:#6b7280;font-size:12px}h1{font-size:20px}")
    metod = (
        "<h2>Metodologia do Índice de Regime Brasil</h2>"
        "<p class='sub'>Índice heurístico 0-100 (quanto maior, mais favorável). Componentes e "
        "pesos originais: setor externo 20, inflação/expectativas 15, juros 15, fluxo "
        "estrangeiro 15, mercado 10, valuation 20, fiscal 5. <b>Fluxo estrangeiro e valuation "
        "foram removidos</b> por não terem fonte automática confiável, e os pesos foram "
        "renormalizados sobre os componentes disponíveis. Notas por componente: setor externo "
        "(saldo comercial e transações correntes 12m), inflação (IPCA 12m vs. meta 3% e "
        "trajetória do Focus), juros (nível da Selic e trajetória do Focus), mercado (amplitude "
        "de altas do universo do dia) e fiscal (DBGG). <b>Não é previsão nem recomendação</b>; "
        "é um termômetro para leitura de regime.</p>")
    return (f"<!doctype html><html><head><meta charset='utf-8'><style>{css}</style></head>"
            f"<body><h1>Relatório Macro · Brasil</h1>"
            f"<p class='sub'>Data da consulta: {_fmt_d(g('consulta') if not isinstance(macro.get('consulta'),dict) else None) or hoje}. "
            f"Fontes oficiais: BCB (SGS e Boletim Focus) e IBGE via BCB; mercado via yfinance.</p>"
            f"{panel}"
            + ("<h2>Outros indicadores</h2><ul>" + "".join(extra) + "</ul>" if extra else "")
            + metod +
            "<p class='sub'>Material analítico automático. Não constitui recomendação de "
            "investimento. Itens sem dado na fonte oficial aparecem como n/d — nada é "
            "estimado.</p></body></html>")
