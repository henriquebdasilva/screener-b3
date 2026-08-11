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

from universe import get_universe, get_ishares_sectors
from datafeed import get_fundamentals, get_prices
from scoring import score_universe
from breakout import detect_breakout


def run(universe="both", top_quantile=0.5, min_invest=None, lookback=20,
        vol_mult=1.5, require_trend=True, require_volume=True,
        require_contraction=False, sleep=0.4, outdir="reports", limit=None,
        send_email=True, strict_criteria=False, mktcap_filter=True, enrich=True,
        force_ia=False, breakout_consol_pct=10.0, breakout_margin_pct=1.5,
        dy_years=5, use_avg_dy=True, bazin_yield_pct=0.0, teto_desconto_pct=10.0,
        teto_outlier_mult=2.5, require_roe_roic_selic=True, max_leverage=3.0,
        min_marketcap=500_000_000.0, consistency_weight=0.15,
        max_net_debt_equity=1.5, split_by_origin=True, group_top=None,
        use_basileia=True, cyclical_penalty=0.25, defensive_max_cyc=0.4,
        teto_max_upside=200.0, teto_disp_max=8.0,
        suspect_pl_min=2.0, suspect_dy_max=20.0):

    tickers = get_universe(universe)
    from watchlist import get_wishlist, get_carteira
    wl, cart = get_wishlist(), get_carteira()
    for tk in wl:
        tickers.setdefault(tk, [])
        if "Wishlist" not in tickers[tk]:
            tickers[tk].append("Wishlist")
    for tk in cart:
        tickers.setdefault(tk, [])
        if "Carteira" not in tickers[tk]:
            tickers[tk].append("Carteira")
    if wl or cart:
        print(f"Wishlist: {len(wl)} papel(is) | Carteira: {len(cart)} papel(is) "
              f"(sempre exibidos, com IA).")
    ishares_setores = get_ishares_sectors()      # {ticker: setor GICS oficial}
    items = list(tickers.items())
    if limit:
        items = items[:limit]

    from datafeed import (get_selic, get_insider_sells, avg_annual_dy,
                          listed_years, paid_dividends_ge, get_net_income_history,
                          dividends_no_cut)
    selic = get_selic()
    print(f"Universo: {len(items)} tickers ({universe}). Selic usada: {selic:.2f}%")

    funds, breaks, origem, mcap, insider, avg_dy = [], {}, {}, {}, {}, {}
    listed_y, div_ge5, profit_hist, div_nocut = {}, {}, {}, {}
    for i, (tk, orig) in enumerate(items, 1):
        origem[tk] = "+".join(orig)
        try:
            f = get_fundamentals(tk, sector_hint=ishares_setores.get(tk, ""))
            funds.append(f)
            mcap[tk] = f.market_cap
        except Exception as e:
            print(f"  [fund] {tk}: {e}")
        try:
            px = get_prices(tk)
            breaks[tk] = detect_breakout(
                px, ticker=tk, vol_mult=vol_mult,
                require_trend=require_trend, require_volume=require_volume,
                breakout_consol_pct=breakout_consol_pct,
                min_breakout_margin_pct=breakout_margin_pct,
            )
            if use_avg_dy:
                avg_dy[tk] = avg_annual_dy(px, dy_years)
            listed_y[tk] = listed_years(px)
            div_ge5[tk] = paid_dividends_ge(px, 5, 5.0)
            div_nocut[tk] = dividends_no_cut(px, 5, 0.20)
        except Exception as e:
            print(f"  [preço] {tk}: {e}")
        try:
            insider[tk] = get_insider_sells(tk)
        except Exception:
            insider[tk] = None
        try:
            profit_hist[tk] = get_net_income_history(tk)     # (anual, trimestral)
        except Exception:
            profit_hist[tk] = ([], [])
        if i % 10 == 0:
            print(f"  ...{i}/{len(items)}")
        time.sleep(sleep)

    # DY médio (5 anos) alimenta o score de Dividend e o crescimento sustentável (PEG)
    for f in funds:
        if use_avg_dy and pd.notna(avg_dy.get(f.ticker, float("nan"))):
            f.dy_medio = avg_dy[f.ticker]

    scores = score_universe(funds, pl_min=suspect_pl_min, dy_max=suspect_dy_max)
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

    # payout aproximado (dividendo/lucro) = DY médio 5a × P/L (só quando ambos válidos)
    df["payout"] = [
        (float(dv) * float(pl)) if (pd.notna(dv) and pd.notna(pl) and pl > 0 and dv > 0)
        else float("nan")
        for dv, pl in zip(df.get("dy_div", pd.Series(index=df.index)),
                          df.get("pl", pd.Series(index=df.index)))
    ]

    chk_rows, ceil_rows = {}, {}
    for tk in df.index:
        row = df.loc[tk]
        ch = evaluate(row, smeans, selic, market_cap=mcap.get(tk),
                      insider_sell_relevante=insider.get(tk),
                      is_financial=fin_map.get(tk, False),
                      require_roe_roic_selic=require_roe_roic_selic,
                      marketcap_min=min_marketcap)
        chk_rows[tk] = ch.as_dict()
        # DY para o valuation: média de 5 anos (suaviza dividendos extraordinários);
        # cai no DY corrente se não houver histórico.
        dy_ceil = avg_dy.get(tk)
        if dy_ceil is None or (isinstance(dy_ceil, float) and pd.isna(dy_ceil)):
            dy_ceil = row.get("dy")
        # crescimento p/ o valuation: sustentável (ROE×(1−payout)); fallback CAGR receita
        g_val = row.get("growth_est")
        if g_val is None or (isinstance(g_val, float) and pd.isna(g_val)):
            g_val = row.get("cresc_5a")
        cc = compute_ceilings(row.get("close"), row.get("pl"), row.get("pvp"),
                              dy_ceil, g_val, selic_pct=selic,
                              bazin_yield=(bazin_yield_pct / 100.0
                                           if bazin_yield_pct > 0 else None),
                              safety_discount=teto_desconto_pct / 100.0,
                              outlier_mult=teto_outlier_mult,
                              is_financial=fin_map.get(tk, False),
                              max_upside=teto_max_upside, raw_disp_max=teto_disp_max)
        ceil_rows[tk] = {"teto_bazin": cc.bazin, "teto_graham": cc.graham,
                         "teto_gordon": cc.gordon, "teto_dcf": cc.dcf,
                         "teto_lynch": cc.lynch, "teto_medio": cc.media,
                         "teto_mediana": cc.mediana, "teto_ajustado": cc.ajustado,
                         "teto_n_metodos": cc.n_metodos,
                         "teto_confiavel": cc.confiavel, "teto_dispersao": round(cc.dispersao, 1)
                         if pd.notna(cc.dispersao) else None,
                         "teto_upside_pct": cc.upside_pct,
                         "teto_upside_media_pct": cc.upside_media_pct,
                         "dy_teto": round(dy_ceil, 2) if pd.notna(dy_ceil) else None}
    df = df.join(pd.DataFrame(chk_rows).T).join(pd.DataFrame(ceil_rows).T)

    # ---- Safety das financeiras via Índice de Basileia (IF.data / BC) ----
    df["basileia"] = float("nan")
    _mexeu_safety = False
    if use_basileia:
        try:
            from basileia import fetch_basileia_map, basileia_safety
            fins = [t for t in df.index if fin_map.get(t, False)]
            bmap = fetch_basileia_map(fins)
            for tk, pct in (bmap or {}).items():
                if tk in df.index:
                    df.loc[tk, "basileia"] = pct
                    df.loc[tk, "safety"] = basileia_safety(pct)
            _mexeu_safety = bool(bmap)
        except Exception as e:
            print(f"[basileia] ignorado ({e}).")

    # ---- Safety das SEGURADORAS via índice de solvência (tabela manual) ----
    df["solvencia"] = float("nan")
    try:
        from solvencia import fetch_solvencia_map, solvencia_safety
        segs = [t for t in df.index if fin_map.get(t, False)]
        smap = fetch_solvencia_map(segs)
        for tk, idx in (smap or {}).items():
            if tk in df.index:
                df.loc[tk, "solvencia"] = idx
                df.loc[tk, "safety"] = solvencia_safety(idx)
        _mexeu_safety = _mexeu_safety or bool(smap)
    except Exception as e:
        print(f"[solvencia] ignorado ({e}).")

    # ---- Penalidade de ciclicidade no Safety (setores cíclicos -> Safety menor) ----
    from scoring import cyclicality
    df["ciclicidade"] = df["setor"].map(cyclicality)
    if cyclical_penalty and cyclical_penalty > 0:
        fin_series = pd.Series({t: fin_map.get(t, False) for t in df.index})
        fator = (1.0 - cyclical_penalty * df["ciclicidade"]).clip(lower=0.0)
        # aplica só a não-financeiras (financeiras têm Safety da Basileia) e onde há Safety
        aplica = (~fin_series) & df["safety"].notna()
        df.loc[aplica, "safety"] = (df.loc[aplica, "safety"] * fator[aplica]).round(2)
        _mexeu_safety = _mexeu_safety or bool(aplica.any())

    if _mexeu_safety:
        from scoring import investment_series
        df["investment"] = investment_series(df).round(2)

    # ---- Consistência (8 critérios) e mescla na nota ----
    from criteria import consistency as _consistency
    cons_rows = {}
    for tk in df.index:
        ni = profit_hist.get(tk, ([], []))
        cc2 = _consistency(df.loc[tk], listed_y.get(tk), div_ge5.get(tk),
                           ni[0], ni[1], is_financial=fin_map.get(tk, False),
                           div_no_cut=div_nocut.get(tk))
        cons_rows[tk] = cc2.as_dict()
    df = df.join(pd.DataFrame(cons_rows).T.rename(columns={"score": "consistencia"}))
    df["investment_base"] = df["investment"]
    wc = float(consistency_weight)
    cons = pd.to_numeric(df["consistencia"], errors="coerce")
    base = pd.to_numeric(df["investment"], errors="coerce")
    blended = (1 - wc) * base + wc * cons
    df["investment"] = np.where(cons.notna(), blended, base).round(2)
    df = df.sort_values("investment", ascending=False)
    df["rank_invest"] = range(1, len(df) + 1)

    # grupo por origem (para separar as listas e cortar por percentil dentro de cada uma)
    df["grupo"] = df["origem"].apply(
        lambda o: "BOVA11" if "BOVA11" in str(o) else "SMALL11")

    # ---- Seleção em CASCATA ----
    # 1) cortes duros primeiro (qualidade/solidez); 2) percentil por grupo nos SOBREVIVENTES.
    fin_series = pd.Series({t: fin_map.get(t, False) for t in df.index})
    hard = pd.Series(True, index=df.index)

    # exige cotação válida: sem preço (ticker fantasma/sem dados) não é selecionável
    close_ok = pd.to_numeric(df.get("close"), errors="coerce") > 0
    df["preco_ok"] = close_ok.fillna(False)
    hard &= df["preco_ok"]

    if mktcap_filter:
        hard &= (df["marketcap_ok"] == True)                   # noqa: E712 (NaN reprova)

    # Dív.Líq/EBITDA <= teto (alavancagem), exceto financeiras
    if max_leverage and max_leverage > 0:
        lev = df["div_liq_ebitda"]
        muito_endividada = (~fin_series) & lev.notna() & (lev > max_leverage)
        df["alavancagem_ok"] = ~muito_endividada
        hard &= ~muito_endividada
    else:
        df["alavancagem_ok"] = True

    # Dív.Líq/Patrim (derivada) <= teto, exceto financeiras
    from criteria import net_debt_to_equity
    df["div_liq_patrim"] = pd.to_numeric(
        df.apply(lambda r: net_debt_to_equity(r.get("pvp"), r.get("ev_ebitda"),
                                              r.get("div_liq_ebitda")), axis=1),
        errors="coerce").round(2)
    if max_net_debt_equity and max_net_debt_equity > 0:
        nde = df["div_liq_patrim"]
        endivid_patrim = (~fin_series) & nde.notna() & (nde > max_net_debt_equity)
        df["nde_ok"] = ~endivid_patrim
        hard &= ~endivid_patrim
    else:
        df["nde_ok"] = True

    if strict_criteria:
        hard &= (df["passa_checklist"] == True)                # noqa: E712
    hard = hard.fillna(False)

    # 2) percentil por grupo, calculado SÓ entre os sobreviventes dos cortes duros
    frac = group_top if (group_top is not None) else top_quantile
    surv = df[hard]
    if min_invest is not None:
        fund_ok = hard & (df["investment"] >= float(min_invest))
    elif split_by_origin:
        thr = surv.groupby("grupo")["investment"].transform(
            lambda s: s.quantile(1 - frac))
        thr_full = pd.Series(index=df.index, dtype=float)
        thr_full.loc[surv.index] = thr
        fund_ok = hard & df["investment"].ge(thr_full)
    else:
        thr = surv["investment"].quantile(1 - top_quantile) if len(surv) else float("inf")
        fund_ok = hard & (df["investment"] >= thr)
    fund_ok = fund_ok.fillna(False)

    df["fund_ok"] = fund_ok
    df["breakout"] = df["signal"].fillna(False).astype(bool)
    df["aprovado"] = df["fund_ok"] & df["breakout"]
    # FLAG de oportunidade gráfica: mostra o papel de qualquer forma e sinaliza o rompimento
    strat = df["strategy"].fillna("") if "strategy" in df.columns else ""
    df["oportunidade_grafica"] = np.where(
        df["breakout"] & (strat.astype(str) != ""), strat.astype(str), "Não")

    hoje = dt.date.today().isoformat()
    # marca wishlist/carteira (sempre exibidos) e a posição da carteira
    df["in_wishlist"] = df.index.isin(wl)
    df["in_carteira"] = df.index.isin(cart)
    df["preco_medio"] = [cart.get(t) for t in df.index]
    df["var_pm_pct"] = [
        ((df.at[t, "close"] / cart[t] - 1) * 100.0)
        if (t in cart and cart.get(t) and pd.notna(df.at[t, "close"]) and cart[t] > 0)
        else float("nan") for t in df.index
    ]

    # ---- enriquecimento: agenda + tese IA ----
    df["prox_resultado"] = "n/d"
    df["ex_dividendo"] = "n/d"
    df["ex_tipo"] = ""
    df["tese_ia"] = ""
    if enrich:
        from enrich import get_events, generate_theses
        # agenda: selecionados + wishlist + carteira
        ag_idx = list(df.index[df["fund_ok"] | df["in_wishlist"] | df["in_carteira"]])
        for tk in ag_idx:
            try:
                ev = get_events(tk)
                df.at[tk, "prox_resultado"] = ev.get("prox_resultado") or "n/d"
                df.at[tk, "ex_dividendo"] = ev.get("ex_dividendo") or "n/d"
                df.at[tk, "ex_tipo"] = ev.get("ex_tipo") or ""
            except Exception as e:
                print(f"  [agenda] {tk}: {e}")
            time.sleep(0.2)
        # IA: aprovados + TODA a wishlist + TODA a carteira
        ia_mask = df["aprovado"] | df["in_wishlist"] | df["in_carteira"]
        teses = generate_theses(df[ia_mask], hoje, outdir, force=force_ia)
        for tk, txt in teses.items():
            df.at[tk, "tese_ia"] = txt

    os.makedirs(outdir, exist_ok=True)

    cols = [
            "origem", "grupo", "setor", "investment", "investment_base", "consistencia",
            "basileia", "solvencia", "ciclicidade", "dado_suspeito",
            "quality", "value", "safety", "dividend",
            "rank_invest", "oportunidade_grafica", "criterios_ok", "criterios_aplicaveis",
            "passa_checklist", "mais_5a_bolsa", "sem_prejuizo_anual", "lucro_20t",
            "div_ge5_5a", "div_sem_corte", "roe_ge_10", "divida_menor_patrim", "cresc_receita_5a",
            "cresc_lucro_5a", "n_ok", "n_aplic",
            "roe_roic_ge_selic", "roe_ge_setor", "roic_ge_setor",
            "margem_ge_15", "cagr_ge_setor", "divida_ok", "marketcap_ok", "insider_ok",
            "alavancagem_ok", "div_liq_patrim", "nde_ok",
            "market_cap", "pl", "pvp", "dy", "dy_teto", "roe", "roic", "mrg_liq",
            "ev_ebitda", "div_liq_ebitda",
            "liq_corr", "div_patrim", "peg", "payout", "cresc_5a", "close",
            "teto_bazin", "teto_gordon",
            "teto_dcf", "teto_graham", "teto_lynch", "teto_medio", "teto_mediana",
            "teto_ajustado", "teto_n_metodos", "teto_confiavel", "teto_dispersao",
            "teto_upside_pct",
            "teto_upside_media_pct", "prox_resultado",
            "ex_dividendo", "ex_tipo", "tese_ia", "strategy",
            "in_wishlist", "in_carteira", "preco_medio", "var_pm_pct",
            "trend", "breakout_level", "pct_to_level", "dist_52w_high_pct",
            "fund_ok", "breakout", "aprovado", "note"]
    cols = [c for c in cols if c in df.columns]
    full = df[cols].round(2)
    full.to_csv(f"{outdir}/screener_{hoje}.csv", encoding="utf-8-sig")

    # medianas por setor (universo do dia) dos indicadores exibidos no e-mail
    _ind_cols = ["pl", "pvp", "peg", "ev_ebitda", "div_liq_ebitda", "div_liq_patrim",
                 "roe", "roic", "payout", "mrg_liq", "liq_corr", "cresc_5a"]
    setor_medians = {}
    for setor, g in df.groupby(df["setor"].fillna("")):
        setor_medians[str(setor)] = {c: float(g[c].median(skipna=True))
                                     for c in _ind_cols if c in df.columns
                                     and pd.notna(g[c].median(skipna=True))}

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
            from market import market_summary, market_mood
            resumo = market_summary(selic)          # Selic + índices (YTD/MTD)
            humor = market_mood(full)               # % alta/baixa por índice e setor
            html = build_html(selecionados, hoje, dict(universe=universe,
                              top_quantile=top_quantile, min_invest=min_invest),
                              market=resumo, mood=humor,
                              group_pct=(int(round(frac * 100)) if split_by_origin
                                         and min_invest is None else None),
                              defensive_cyc=defensive_max_cyc,
                              setor_medians=setor_medians,
                              wishlist_df=full[full["in_wishlist"]].sort_values(
                                  "investment", ascending=False),
                              carteira_df=full[full["in_carteira"]].sort_values(
                                  "investment", ascending=False))
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
    p.add_argument("--vol-mult", type=float, default=1.5,
                   help="volume mínimo no rompimento, em x da média de 20 dias")
    p.add_argument("--breakout-consol-pct", type=float, default=10.0,
                   help="amplitude máx. da consolidação p/ rompimento (%%, default 10)")
    p.add_argument("--breakout-margin-pct", type=float, default=1.5,
                   help="margem mínima acima do topo p/ validar rompimento (%%, default 1.5)")
    p.add_argument("--dy-years", type=int, default=5,
                   help="janela (anos) do DY médio usado no preço-teto (default 5)")
    p.add_argument("--no-avg-dy", action="store_true",
                   help="usar o DY de 12 meses no preço-teto (em vez do DY médio de N anos)")
    p.add_argument("--bazin-yield", type=float, default=0.0,
                   help="yield-alvo do Bazin em %% (0 = amarrar à Selic, default)")
    p.add_argument("--teto-desconto", type=float, default=10.0,
                   help="desconto de segurança sobre o teto consolidado (%%, default 10)")
    p.add_argument("--teto-outlier-mult", type=float, default=2.5,
                   help="descarta método além de Nx a mediana antes de consolidar "
                        "(default 2.5; 0 desliga)")
    p.add_argument("--no-roe-roic-selic", action="store_true",
                   help="desativa o critério 'ROE ou ROIC >= Selic' (ativo por padrão)")
    p.add_argument("--max-leverage", type=float, default=3.0,
                   help="remove não-financeiras com Dív.Líq/EBITDA acima disso "
                        "(default 3.0; 0 desliga)")
    p.add_argument("--min-marketcap", type=float, default=500.0,
                   help="piso de market cap em R$ milhões (default 500)")
    p.add_argument("--consistency-weight", type=float, default=0.15,
                   help="peso do bloco de consistência na nota final (0-1, default 0.15)")
    p.add_argument("--max-net-debt-equity", type=float, default=1.5,
                   help="remove não-financeiras com Dív.Líq/Patrim (derivada) acima disso "
                        "(default 1.5; 0 desliga)")
    p.add_argument("--group-top", type=float, default=None,
                   help="override do percentil por grupo BOVA11/SMALL11 "
                        "(default: usa --top-quantile)")
    p.add_argument("--no-split", action="store_true",
                   help="não separar por grupo; usa --top-quantile no universo inteiro")
    p.add_argument("--no-basileia", action="store_true",
                   help="não buscar Índice de Basileia (IF.data) p/ o Safety das financeiras")
    p.add_argument("--cyclical-penalty", type=float, default=0.25,
                   help="penalidade máx. no Safety p/ setores cíclicos (0-1; default 0.25; "
                        "0 desliga). Ex.: setor cíclico=1,0 com 0.25 perde 25%% do Safety.")
    p.add_argument("--defensive-max-cyc", type=float, default=0.4,
                   help="teto de ciclicidade p/ a seção 'Defensivas/não-cíclicas' no e-mail "
                        "(default 0.4)")
    p.add_argument("--teto-max-upside", type=float, default=200.0,
                   help="acima deste upside %% o teto é marcado não confiável -> n/d "
                        "(default 200; 0 desliga)")
    p.add_argument("--teto-disp-max", type=float, default=8.0,
                   help="se os métodos discordarem mais que isso (max/min), teto vira n/d "
                        "(default 8; 0 desliga)")
    p.add_argument("--suspect-pl-min", type=float, default=2.0,
                   help="P/L de não-financeira abaixo disso é dado suspeito -> sai do Value "
                        "(default 2.0; 0 desliga)")
    p.add_argument("--suspect-dy-max", type=float, default=20.0,
                   help="DY médio (5a) acima/igual disso é suspeito -> sai do Dividend "
                        "(default 20; 0 desliga)")
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
    p.add_argument("--force-ia", action="store_true",
                   help="ignora o cache e regenera todas as teses por IA")
    p.add_argument("--outdir", default="reports")
    return p.parse_args()


if __name__ == "__main__":
    a = parse_args()
    run(universe=a.universe, top_quantile=a.top_quantile, min_invest=a.min_invest,
        lookback=a.lookback, vol_mult=a.vol_mult, require_trend=not a.no_trend,
        require_volume=not a.no_volume, require_contraction=a.require_contraction,
        sleep=a.sleep, outdir=a.outdir, limit=a.limit, send_email=not a.no_email,
        strict_criteria=a.strict_criteria, mktcap_filter=not a.no_mktcap_filter,
        enrich=not a.no_enrich, force_ia=a.force_ia,
        breakout_consol_pct=a.breakout_consol_pct,
        breakout_margin_pct=a.breakout_margin_pct,
        dy_years=a.dy_years, use_avg_dy=not a.no_avg_dy,
        bazin_yield_pct=a.bazin_yield, teto_desconto_pct=a.teto_desconto,
        teto_outlier_mult=a.teto_outlier_mult,
        require_roe_roic_selic=not a.no_roe_roic_selic, max_leverage=a.max_leverage,
        min_marketcap=a.min_marketcap * 1_000_000,
        consistency_weight=a.consistency_weight,
        max_net_debt_equity=a.max_net_debt_equity,
        split_by_origin=not a.no_split, group_top=a.group_top,
        use_basileia=not a.no_basileia, cyclical_penalty=a.cyclical_penalty,
        defensive_max_cyc=a.defensive_max_cyc,
        teto_max_upside=a.teto_max_upside, teto_disp_max=a.teto_disp_max,
        suspect_pl_min=a.suspect_pl_min, suspect_dy_max=a.suspect_dy_max)
