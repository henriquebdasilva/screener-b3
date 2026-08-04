# -*- coding: utf-8 -*-
"""
Orquestrador: varre BOVA11 + SMALL11, calcula os scores fundamentalistas e aplica o
filtro de rompimento gráfico. Gera relatórios em `reports/`.

Uso:
    python screener.py --universe both --top-quantile 0.5 --lookback 20
    python screener.py --universe smll --min-invest 60 --require-contraction

Seleção = passa no corte fundamentalista. O rompimento/pivô NÃO exclui papéis: vira uma
flag "oportunidade_grafica" (Rompimento | Pivô de alta | Não) em cada papel.
Dica: use --top-quantile 1.0 para listar TODOS os papéis avaliados.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import time

import numpy as np
import pandas as pd

from universe import get_universe
from datafeed import get_fundamentals, get_prices
from scoring import score_universe
from breakout import detect_breakout


def run(universe="both", top_quantile=0.5, min_invest=None, lookback=20,
        vol_mult=1.5, require_trend=True, require_volume=True,
        require_contraction=False, sleep=0.4, outdir="reports", limit=None,
        send_email=True, strict_criteria=False, mktcap_filter=True, enrich=True):

    tickers = get_universe(universe)
    items = list(tickers.items())
    if limit:
        items = items[:limit]

    from datafeed import get_selic, get_insider_sells
    selic = get_selic()
    print(f"Universo: {len(items)} tickers ({universe}). Selic usada: {selic:.2f}%")

    funds, breaks, origem, mcap, insider = [], {}, {}, {}, {}
    for i, (tk, orig) in enumerate(items, 1):
        origem[tk] = "+".join(orig)
        try:
            f = get_fundamentals(tk)
            funds.append(f)
            mcap[tk] = f.market_cap
        except Exception as e:
            print(f"  [fund] {tk}: {e}")
        try:
            px = get_prices(tk)
            breaks[tk] = detect_breakout(
                px, ticker=tk, lookback=lookback, vol_mult=vol_mult,
                require_trend=require_trend, require_volume=require_volume,
                require_contraction=require_contraction,
            )
        except Exception as e:
            print(f"  [preço] {tk}: {e}")
        try:
            insider[tk] = get_insider_sells(tk)
        except Exception:
            insider[tk] = None
        if i % 10 == 0:
            print(f"  ...{i}/{len(items)}")
        time.sleep(sleep)

    scores = score_universe(funds)
    if scores.empty:
        print("Sem dados fundamentalistas — abortando.")
        return None

    # junta rompimento
    bdf = pd.DataFrame(
        {tk: b.as_dict() for tk, b in breaks.items()}
    ).T
    df = scores.join(bdf, how="left")
    df.insert(0, "origem", pd.Series(origem))

    # ---- market cap, checklist de critérios e preços-teto ----
    from criteria import sector_means, evaluate
    from pricing import compute_ceilings
    df["market_cap"] = pd.Series(mcap)
    smeans = sector_means(df)
    # médias do setor (pares do universo) por papel — alimentam a tese da IA
    df["roe_setor_med"] = df["setor"].map(lambda s: smeans.get(s, {}).get("roe"))
    df["roic_setor_med"] = df["setor"].map(lambda s: smeans.get(s, {}).get("roic"))
    df["div_setor_med"] = df["setor"].map(lambda s: smeans.get(s, {}).get("div_liq_ebitda"))
    df["cagr_setor_med"] = df["setor"].map(lambda s: smeans.get(s, {}).get("cresc_5a"))
    fin_map = {f.ticker: f.is_financial() for f in funds}

    chk_rows, ceil_rows = {}, {}
    for tk in df.index:
        row = df.loc[tk]
        ch = evaluate(row, smeans, selic, market_cap=mcap.get(tk),
                      insider_sell_relevante=insider.get(tk),
                      is_financial=fin_map.get(tk, False))
        chk_rows[tk] = ch.as_dict()
        cc = compute_ceilings(row.get("close"), row.get("pl"), row.get("pvp"),
                              row.get("dy"), row.get("cresc_5a"), selic_pct=selic)
        ceil_rows[tk] = {"teto_bazin": cc.bazin, "teto_graham": cc.graham,
                         "teto_gordon": cc.gordon, "teto_dcf": cc.dcf,
                         "teto_lynch": cc.lynch, "teto_medio": cc.media,
                         "teto_mediana": cc.mediana, "teto_upside_pct": cc.upside_pct,
                         "teto_upside_media_pct": cc.upside_media_pct}
    df = df.join(pd.DataFrame(chk_rows).T).join(pd.DataFrame(ceil_rows).T)

    # corte fundamentalista (Investment Score) + piso de market cap (>= R$300 mi)
    if min_invest is not None:
        fund_ok = df["investment"] >= float(min_invest)
    else:
        thr = df["investment"].quantile(1 - top_quantile)
        fund_ok = df["investment"] >= thr
    fund_ok = fund_ok.fillna(False)
    if mktcap_filter:
        fund_ok = fund_ok & (df["marketcap_ok"] != False)   # noqa: E712 (mantém n/d)
    if strict_criteria:
        fund_ok = fund_ok & (df["passa_checklist"] == True)  # noqa: E712
    df["fund_ok"] = fund_ok
    df["breakout"] = df["signal"].fillna(False).astype(bool)
    df["aprovado"] = df["fund_ok"] & df["breakout"]
    # FLAG de oportunidade gráfica: mostra o papel de qualquer forma e sinaliza o rompimento
    strat = df["strategy"].fillna("") if "strategy" in df.columns else ""
    df["oportunidade_grafica"] = np.where(
        df["breakout"] & (strat.astype(str) != ""), strat.astype(str), "Não")

    hoje = dt.date.today().isoformat()
    # ---- enriquecimento: agenda (selecionados) + tese IA (aprovados) ----
    df["prox_resultado"] = "n/d"
    df["ex_dividendo"] = "n/d"
    df["ex_tipo"] = ""
    df["tese_ia"] = ""
    if enrich:
        from enrich import get_events, generate_theses
        sel_idx = list(df.index[df["fund_ok"]])
        for tk in sel_idx:
            try:
                ev = get_events(tk)
                df.at[tk, "prox_resultado"] = ev.get("prox_resultado") or "n/d"
                df.at[tk, "ex_dividendo"] = ev.get("ex_dividendo") or "n/d"
                df.at[tk, "ex_tipo"] = ev.get("ex_tipo") or ""
            except Exception as e:
                print(f"  [agenda] {tk}: {e}")
            time.sleep(0.2)
        aprov = df[df["aprovado"]]
        teses = generate_theses(aprov, hoje, outdir)
        for tk, txt in teses.items():
            df.at[tk, "tese_ia"] = txt

    os.makedirs(outdir, exist_ok=True)

    cols = ["origem", "setor", "investment", "quality", "value", "safety", "dividend",
            "rank_invest", "oportunidade_grafica", "criterios_ok", "criterios_aplicaveis",
            "passa_checklist", "roe_ge_selic", "roe_ge_setor", "roic_ge_setor",
            "margem_ge_15", "cagr_ge_setor", "divida_ok", "marketcap_ok", "insider_ok",
            "market_cap", "pl", "pvp", "dy", "roe", "roic", "mrg_liq", "div_liq_ebitda",
            "liq_corr", "div_patrim", "peg", "close", "teto_bazin", "teto_gordon",
            "teto_dcf", "teto_graham", "teto_lynch", "teto_medio", "teto_mediana",
            "teto_upside_pct", "teto_upside_media_pct", "prox_resultado",
            "ex_dividendo", "ex_tipo", "tese_ia", "strategy",
            "trend", "breakout_level", "pct_to_level", "dist_52w_high_pct",
            "fund_ok", "breakout", "aprovado", "note"]
    cols = [c for c in cols if c in df.columns]
    full = df[cols].round(2)
    full.to_csv(f"{outdir}/screener_{hoje}.csv", encoding="utf-8-sig")

    # SELEÇÃO = passa nos critérios fundamentalistas (o rompimento é só flag, não filtra)
    selecionados = full[full["fund_ok"]].sort_values("investment", ascending=False)
    selecionados.to_csv(f"{outdir}/selecionados_{hoje}.csv", encoding="utf-8-sig")

    _write_markdown(full, selecionados, hoje, outdir,
                    dict(universe=universe, top_quantile=top_quantile,
                         min_invest=min_invest, lookback=lookback, vol_mult=vol_mult,
                         require_contraction=require_contraction))

    # planilha (.xlsx) com Selecionados + Universo
    xlsx_path = f"{outdir}/screener_{hoje}.xlsx"
    try:
        from mailer import export_xlsx
        export_xlsx(full, selecionados, xlsx_path)
    except Exception as e:
        print(f"[xlsx] falhou: {e}")
        xlsx_path = None

    # e-mail (só se configurado por variáveis de ambiente / Secrets)
    if send_email:
        try:
            from mailer import build_html, send_report_email
            html = build_html(selecionados, hoje, dict(universe=universe,
                              top_quantile=top_quantile, min_invest=min_invest))
            n_graf = int((selecionados["oportunidade_grafica"] != "Não").sum()) \
                if len(selecionados) else 0
            subject = (f"[Screener B3] {len(selecionados)} papéis nos critérios "
                       f"({n_graf} com oportunidade gráfica) — {hoje}")
            anexos = [p for p in (xlsx_path, f"{outdir}/selecionados_{hoje}.csv") if p]
            send_report_email(subject, html, anexos)
        except Exception as e:
            print(f"[email] falhou: {e}")

    print(f"\nOK. {len(full)} avaliadas | {int(full['fund_ok'].sum())} nos critérios "
          f"fundamentalistas | {int(full['breakout'].sum())} com oportunidade gráfica "
          f"(rompimento/pivô) | {int(full['aprovado'].sum())} com ambos.")
    print(f"Relatórios em {outdir}/ (screener_{hoje}.csv/.xlsx, selecionados_{hoje}.csv, latest.md)")
    return full


def _write_markdown(full, selecionados, hoje, outdir, params):
    from tabulate import tabulate
    n_graf = int((selecionados["oportunidade_grafica"] != "Não").sum()) if len(selecionados) else 0
    lines = [f"# Screener B3 — {hoje}", "",
             f"*Parâmetros:* `{params}`", "",
             "> Material analítico gerado automaticamente. **Não é recomendação de "
             "investimento.** Preços/fundamentos de fontes públicas podem conter erros "
             "ou defasagem. O rompimento/pivô é um port do algoritmo de referência "
             "(`breakout.py`) e serve como **flag de timing**, não como filtro.", "",
             f"## Papéis nos critérios fundamentalistas — {len(selecionados)} "
             f"({n_graf} com oportunidade gráfica)", ""]
    if len(selecionados):
        t = selecionados.reset_index()[
            ["ticker", "origem", "setor", "investment", "quality", "value",
             "safety", "dividend", "oportunidade_grafica", "trend", "close",
             "pct_to_level"]
        ].rename(columns={"index": "ticker", "oportunidade_grafica": "oport_grafica"})
        lines.append(tabulate(t, headers="keys", tablefmt="github", showindex=False))
    else:
        lines.append("_Nenhum papel passou no corte fundamentalista hoje._")

    lines += ["", "## 🏅 Top 15 por Investment Score (universo todo)", ""]
    top = full.sort_values("investment", ascending=False).head(15).reset_index()[
        ["ticker", "origem", "setor", "investment", "quality", "value", "safety",
         "dividend", "oportunidade_grafica", "trend"]
    ].rename(columns={"oportunidade_grafica": "oport_grafica"})
    lines.append(tabulate(top, headers="keys", tablefmt="github", showindex=False))
    with open(f"{outdir}/latest.md", "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def parse_args():
    p = argparse.ArgumentParser(description="Screener fundamentalista + rompimento (B3)")
    p.add_argument("--universe", choices=["ibov", "smll", "both"], default="both")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--top-quantile", type=float, default=0.5,
                   help="fração superior por Investment Score que passa no fundamentalista")
    g.add_argument("--min-invest", type=float, default=None,
                   help="nota mínima de Investment (0-100) em vez de quantil")
    p.add_argument("--lookback", type=int, default=20)
    p.add_argument("--vol-mult", type=float, default=1.5)
    p.add_argument("--no-trend", action="store_true")
    p.add_argument("--no-volume", action="store_true")
    p.add_argument("--require-contraction", action="store_true")
    p.add_argument("--sleep", type=float, default=0.4)
    p.add_argument("--limit", type=int, default=None, help="varre só os N primeiros (debug)")
    p.add_argument("--no-email", action="store_true", help="não enviar e-mail")
    p.add_argument("--strict-criteria", action="store_true",
                   help="exige TODOS os critérios do checklist (além do Investment Score)")
    p.add_argument("--no-mktcap-filter", action="store_true",
                   help="não aplicar o piso de market cap (>= R$ 300 mi)")
    p.add_argument("--no-enrich", action="store_true",
                   help="não buscar agenda (resultado/ex-div) nem gerar tese por IA")
    p.add_argument("--outdir", default="reports")
    return p.parse_args()


if __name__ == "__main__":
    a = parse_args()
    run(universe=a.universe, top_quantile=a.top_quantile, min_invest=a.min_invest,
        lookback=a.lookback, vol_mult=a.vol_mult, require_trend=not a.no_trend,
        require_volume=not a.no_volume, require_contraction=a.require_contraction,
        sleep=a.sleep, outdir=a.outdir, limit=a.limit, send_email=not a.no_email,
        strict_criteria=a.strict_criteria, mktcap_filter=not a.no_mktcap_filter,
        enrich=not a.no_enrich)
