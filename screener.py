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
        breakout_max_ext=0.03, require_base_structure=True, base_edge_frac=0.30,
        base_min_toques=2, pivot_max_ext=0.04, flag_max_ext=0.04, pivot_lower_frac=0.5, pivot_range_pct=5.0,
        pattern_max_ext=0.10,
        flag_min_dias=7, flag_pole_min=0.12, flag_min_retrace=0.05, trend_ma_long=30,
        pattern_max_sep=45, no_pattern_virada=False,
        dy_years=5, use_avg_dy=True, bazin_yield_pct=0.0, teto_desconto_pct=10.0,
        teto_outlier_mult=2.5, require_roe_roic_selic=True, max_leverage=3.0,
        min_marketcap=500_000_000.0, consistency_weight=0.15,
        max_net_debt_equity=1.5, split_by_origin=True, group_top=None,
        q_bluechip=0.60, q_smallcap=0.50, q_defensive=0.70,
        use_basileia=True, cyclical_penalty=0.25, defensive_max_cyc=0.4,
        teto_max_upside=200.0, teto_disp_max=8.0,
        suspect_pl_min=2.0, suspect_dy_max=20.0, teto_proj_yield=6.0,
        min_margin=8.0, min_roe=10.0,
        defensive_lev_mult=1.8, defensive_lev_cyc=0.2):

    try:
        import breakout as _bk
        _bld = getattr(_bk, "__build__", "ANTIGA (sem marcador — atualize o breakout.py!)")
        print(f"[build] breakout: {_bld}")
    except Exception:
        pass

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
                          dividends_no_cut, avg_payout, price_stats, beta_corr,
                          get_ibov_close, get_balance_metrics)
    selic = get_selic()
    print(f"Universo: {len(items)} tickers ({universe}). Selic usada: {selic:.2f}%")

    funds, breaks, origem, mcap, insider, avg_dy = [], {}, {}, {}, {}, {}
    listed_y, div_ge5, profit_hist, div_nocut, payout_med = {}, {}, {}, {}, {}
    pstats, risco, growth_hist, balanco = {}, {}, {}, {}
    roe_med = {}
    ibov_close = get_ibov_close()                # p/ beta e correlação com o Ibovespa
    if ibov_close is None:
        print("[risco] Ibovespa (^BVSP) indisponível — beta/correlação ficarão n/d.")
    for i, (tk, orig) in enumerate(items, 1):
        origem[tk] = "+".join(orig)
        try:
            f = get_fundamentals(tk, sector_hint=ishares_setores.get(tk, ""))
            funds.append(f)
            mcap[tk] = f.market_cap
        except Exception as e:
            print(f"  [fund] {tk}: {e}")
        px = None
        try:
            px = get_prices(tk)
            breaks[tk] = detect_breakout(
                px, ticker=tk, vol_mult=vol_mult,
                require_trend=require_trend, require_volume=require_volume,
                breakout_consol_pct=breakout_consol_pct,
                min_breakout_margin_pct=breakout_margin_pct,
                breakout_max_ext=breakout_max_ext,
                require_base_structure=require_base_structure,
                base_edge_frac=base_edge_frac,
                base_min_toques=base_min_toques,
                pivot_max_ext=pivot_max_ext,
                flag_max_ext=flag_max_ext,
                pivot_lower_frac=pivot_lower_frac,
                pivot_range_pct=pivot_range_pct,
                pattern_max_ext=pattern_max_ext,
                flag_min_dias=flag_min_dias,
                flag_pole_min=flag_pole_min,
                flag_min_retrace=flag_min_retrace,
                trend_ma_long=trend_ma_long,
                pattern_max_sep=pattern_max_sep,
                pattern_exigir_virada=not no_pattern_virada,
            )
            if use_avg_dy:
                avg_dy[tk] = avg_annual_dy(px, dy_years)
            listed_y[tk] = listed_years(px)
            div_ge5[tk] = paid_dividends_ge(px, 5, 5.0)
            div_nocut[tk] = dividends_no_cut(px, 5, 0.20)
            pstats[tk] = price_stats(px)
            b, cr = beta_corr(px, ibov_close)
            risco[tk] = {"beta": b, "corr_ibov": cr}
        except Exception as e:
            print(f"  [preço] {tk}: {e}")
        try:
            insider[tk] = get_insider_sells(tk)
        except Exception:
            insider[tk] = None
        try:
            ni_a, ni_q, eps_year, ebitda_year, margem_year = get_net_income_history(tk)
            profit_hist[tk] = (ni_a, ni_q)
            payout_med[tk] = avg_payout(eps_year, px)           # payout médio (5a), best-effort
            growth_hist[tk] = {"ebitda": ebitda_year, "margem": margem_year}
        except Exception:
            profit_hist[tk] = ([], [])
            growth_hist[tk] = {}
        try:
            bm = get_balance_metrics(tk)
            balanco[tk] = bm
            # ROE por ano = lucro anual / patrimônio anual (best-effort)
            eq = bm.get("equity_by_year") or {}
            ni_y = {}
            if ni_a:
                # alinha os lucros anuais aos anos do patrimônio (mesma ordem recente->antigo)
                anos = sorted(eq.keys(), reverse=True)
                for k, yr in enumerate(anos):
                    if k < len(ni_a):
                        ni_y[yr] = ni_a[k]
            roe_year = {yr: (ni_y[yr] / eq[yr] * 100) for yr in eq
                        if yr in ni_y and eq[yr] and eq[yr] > 0}
            growth_hist.setdefault(tk, {})["roe"] = roe_year
            # ROE médio dos últimos anos (>=2 anos) — usado no corte de qualidade
            _vals = list(roe_year.values())
            roe_med[tk] = (sum(_vals) / len(_vals)) if len(_vals) >= 2 else float("nan")
        except Exception:
            balanco[tk] = {}
        if i % 10 == 0:
            print(f"  ...{i}/{len(items)}")
        time.sleep(sleep)

    # DY médio (5 anos) alimenta o score de Dividend e o crescimento sustentável (PEG)
    for f in funds:
        if use_avg_dy and pd.notna(avg_dy.get(f.ticker, float("nan"))):
            f.dy_medio = avg_dy[f.ticker]

    scores = score_universe(funds, pl_min=suspect_pl_min, dy_max=suspect_dy_max,
                            selic=selic, roe_med=roe_med, reg_cyc=defensive_lev_cyc)
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
    # métricas técnicas / de risco por papel
    for _c in ("min_52s", "max_52s", "dist_min52", "dist_max52", "dist_mm100"):
        df[_c] = [pstats.get(t, {}).get(_c, float("nan")) for t in df.index]
    df["beta"] = [risco.get(t, {}).get("beta", float("nan")) for t in df.index]
    df["corr_ibov"] = [risco.get(t, {}).get("corr_ibov", float("nan")) for t in df.index]
    for _c in ("liq_geral", "grau_endiv", "indep_fin"):
        df[_c] = [balanco.get(t, {}).get(_c, float("nan")) for t in df.index]
    df["roe_medio"] = [roe_med.get(t, float("nan")) for t in df.index]

    chk_rows, ceil_rows = {}, {}
    # múltiplo-alvo EV/EBITDA = mediana do setor (não-financeiras), limitado a [3, 15];
    # fallback = mediana geral. Serve de âncora do método de múltiplo-alvo.
    _nf = df[~df.index.map(lambda t: fin_map.get(t, False))]
    _ev_geral = pd.to_numeric(_nf.get("ev_ebitda"), errors="coerce")
    _ev_geral = _ev_geral[(_ev_geral > 0) & (_ev_geral < 50)]
    ev_alvo_geral = float(_ev_geral.median()) if len(_ev_geral) else 7.0
    ev_alvo_setor = {}
    if "ev_ebitda" in _nf.columns:
        for setor, g in _nf.groupby(_nf["setor"].fillna("")):
            vv = pd.to_numeric(g["ev_ebitda"], errors="coerce")
            vv = vv[(vv > 0) & (vv < 50)]
            if len(vv) >= 3:
                ev_alvo_setor[str(setor)] = float(vv.median())

    def _ev_target(tk):
        if fin_map.get(tk, False):
            return None
        alvo = ev_alvo_setor.get(str(df.at[tk, "setor"]), ev_alvo_geral)
        return min(max(alvo, 3.0), 15.0)          # âncora sensata (evita mediana ruim)

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
                              max_upside=teto_max_upside, raw_disp_max=teto_disp_max,
                              eps_real=row.get("lpa"),
                              payout=(payout_med.get(tk)
                                      if pd.notna(payout_med.get(tk, float("nan")))
                                      else (row.get("payout_ratio")
                                            if pd.notna(row.get("payout_ratio")) else None)),
                              proj_yield=teto_proj_yield / 100.0,
                              ev_ebitda=row.get("ev_ebitda"),
                              div_liq_ebitda=row.get("div_liq_ebitda"),
                              target_ev_ebitda=_ev_target(tk))
        ceil_rows[tk] = {"teto_bazin": cc.bazin, "teto_graham": cc.graham,
                         "teto_gordon": cc.gordon, "teto_dcf": cc.dcf,
                         "teto_lynch": cc.lynch, "teto_projetivo": cc.projetivo,
                         "teto_graham_selic": cc.graham_selic,
                         "teto_mult_ebitda": cc.mult_ebitda,
                         "teto_medio": cc.media,
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
        gh = growth_hist.get(tk, {})
        cc2 = _consistency(df.loc[tk], listed_y.get(tk), div_ge5.get(tk),
                           ni[0], ni[1], is_financial=fin_map.get(tk, False),
                           div_no_cut=div_nocut.get(tk),
                           ebitda_by_year=gh.get("ebitda"), margem_by_year=gh.get("margem"),
                           roe_by_year=gh.get("roe"))
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

    # setores defensivos/regulados (baixa ciclicidade: utilities, elétricas, saneamento)
    # toleram MAIS dívida — fluxo de caixa estável/regulado. Limite = base × multiplicador.
    defensivo = df["ciclicidade"] <= defensive_lev_cyc

    # Dív.Líq/EBITDA <= teto (alavancagem), exceto financeiras
    if max_leverage and max_leverage > 0:
        lev = df["div_liq_ebitda"]
        lim_lev = pd.Series(float(max_leverage), index=df.index)
        lim_lev[defensivo] = float(max_leverage) * defensive_lev_mult
        muito_endividada = (~fin_series) & lev.notna() & (lev > lim_lev)
        df["alavancagem_ok"] = ~muito_endividada
        hard &= ~muito_endividada
    else:
        df["alavancagem_ok"] = True

    # Dív.Líq/Patrim: usa o valor do yfinance (dívida líq./patrimônio); onde faltar,
    # deriva dos índices (Dív.Líq/EBITDA × P/VP) / (EV/EBITDA − Dív.Líq/EBITDA).
    from criteria import net_debt_to_equity
    derivada = pd.to_numeric(
        df.apply(lambda r: net_debt_to_equity(r.get("pvp"), r.get("ev_ebitda"),
                                              r.get("div_liq_ebitda")), axis=1),
        errors="coerce")
    base = pd.to_numeric(df.get("div_liq_patrim_src"), errors="coerce") \
        if "div_liq_patrim_src" in df.columns else pd.Series(index=df.index, dtype=float)
    df["div_liq_patrim"] = base.fillna(derivada).round(2)
    if max_net_debt_equity and max_net_debt_equity > 0:
        nde = df["div_liq_patrim"]
        lim_nde = pd.Series(float(max_net_debt_equity), index=df.index)
        lim_nde[defensivo] = float(max_net_debt_equity) * defensive_lev_mult
        endivid_patrim = (~fin_series) & nde.notna() & (nde > lim_nde)
        df["nde_ok"] = ~endivid_patrim
        hard &= ~endivid_patrim
    else:
        df["nde_ok"] = True

    if strict_criteria:
        hard &= (df["passa_checklist"] == True)                # noqa: E712

    # margem líquida mínima (só não-financeiras; margem não se aplica a bancos/seguros)
    if min_margin and min_margin > 0:
        mrg = pd.to_numeric(df.get("mrg_liq"), errors="coerce")
        margem_baixa = (~fin_series) & mrg.notna() & (mrg < min_margin)
        df["margem_ok"] = ~margem_baixa                        # dado ausente não reprova
        hard &= ~margem_baixa
    else:
        df["margem_ok"] = True

    # ROE mínimo: usa o ROE MÉDIO dos últimos anos quando disponível (evita reprovar por um
    # único ano ruim); onde não há histórico, cai no ROE atual. Vale para todos os setores.
    if min_roe and min_roe > 0:
        roe_med_col = pd.to_numeric(df.get("roe_medio"), errors="coerce")
        roe_atual = pd.to_numeric(df.get("roe"), errors="coerce")
        roe_ref = roe_med_col.fillna(roe_atual)               # média 5a; senão ROE atual
        roe_baixo = roe_ref.notna() & (roe_ref < min_roe)
        df["roe_ok"] = ~roe_baixo                             # dado ausente não reprova
        hard &= ~roe_baixo
    else:
        df["roe_ok"] = True
        df["roe_ok"] = True

    hard = hard.fillna(False)

    # 2) percentil por SEGMENTO, calculado só entre os sobreviventes dos cortes duros.
    #    Frações ajustáveis: blue chips (BOVA11), small caps (SMALL11) e um pool DEFENSIVO
    #    (baixa ciclicidade) mais permissivo. group_top, se dado, sobrepõe tudo (retrocompat.).
    surv = df[hard]
    if min_invest is not None:
        fund_ok = hard & (df["investment"] >= float(min_invest))
    elif split_by_origin:
        q_map = {"BOVA11": q_bluechip, "SMALL11": q_smallcap}
        if group_top is not None:                     # força a mesma fração em tudo
            q_map = {}
        # limiar por grupo, cada grupo com sua fração
        thr_full = pd.Series(index=df.index, dtype=float)
        for g, sub in surv.groupby("grupo"):
            fr = group_top if group_top is not None else q_map.get(g, top_quantile)
            thr_full.loc[sub.index] = sub["investment"].quantile(1 - fr)
        passa_grupo = df["investment"].ge(thr_full).fillna(False)
        # pool DEFENSIVO: fração própria (mais permissiva) — SÓ para blue chips (BOVA11).
        # Smallcaps defensivas seguem no corte do SMALL11 (não ganham a folga de 70%).
        passa_def = pd.Series(False, index=df.index)
        if group_top is None and "ciclicidade" in df.columns:
            eh_bluechip = df["grupo"] == "BOVA11"
            is_def = (df["ciclicidade"] <= defensive_max_cyc) & eh_bluechip
            def_surv = surv[(surv["ciclicidade"] <= defensive_max_cyc)
                            & (surv["grupo"] == "BOVA11")]
            if len(def_surv):
                thr_def = def_surv["investment"].quantile(1 - q_defensive)
                passa_def = (is_def & df["investment"].ge(thr_def)).fillna(False)
        fund_ok = hard & (passa_grupo | passa_def)
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
            "quality", "value", "safety", "dividend", "regulado",
            "rank_invest", "oportunidade_grafica", "criterios_ok", "criterios_aplicaveis",
            "passa_checklist", "mais_5a_bolsa", "sem_prejuizo_anual", "lucro_20t",
            "div_ge5_5a", "div_sem_corte", "roe_ge_10", "divida_menor_patrim", "cresc_receita_5a",
            "cresc_lucro_5a", "n_ok", "n_aplic",
            "roe_roic_ge_selic", "roe_ge_setor", "roic_ge_setor",
            "margem_ge_15", "cagr_ge_setor", "divida_ok", "marketcap_ok", "insider_ok",
            "margem_ok", "roe_ok",
            "alavancagem_ok", "div_liq_patrim", "nde_ok",
            "market_cap", "pl", "pvp", "dy", "dy_teto", "roe", "roe_medio", "roic", "mrg_liq",
            "ev_ebitda", "div_liq_ebitda", "lev_roic_adj",
            "liq_corr", "div_patrim", "peg", "payout", "cresc_5a", "pl_fut",
            "roa", "liq_geral", "grau_endiv", "indep_fin",
            "min_52s", "max_52s", "dist_min52", "dist_max52", "dist_mm100",
            "beta", "corr_ibov", "close",
            "teto_bazin", "teto_gordon",
            "teto_dcf", "teto_graham", "teto_lynch", "teto_projetivo",
            "teto_graham_selic", "teto_mult_ebitda",
            "teto_medio", "teto_mediana",
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
                 "roe", "roic", "payout", "mrg_liq", "liq_corr", "cresc_5a", "pl_fut",
                 "roa", "liq_geral", "grau_endiv", "indep_fin"]
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
            # Put/Call ratio (COTAHIST/B3) por ativo, setor e mercado
            opcoes_data = None
            try:
                from opcoes import fetch_opcoes
                tk_setor = {str(t): full.loc[t, "setor"] for t in full.index
                            if "setor" in full.columns}
                opcoes_data = fetch_opcoes(ticker_setor=tk_setor)
                from posicoes import fetch_open_interest, fetch_aluguel
                oi_data = fetch_open_interest(ticker_setor=tk_setor)
                aluguel_data = fetch_aluguel(ticker_setor=tk_setor)
                if opcoes_data is not None and oi_data is not None:
                    opcoes_data["oi"] = oi_data      # anexa o open interest ao pacote de opções
                    # resolve o strike do maior OI cruzando com o strike limpo do COTAHIST
                    try:
                        from posicoes import resolver_destaques_oi
                        opcoes_data["destaque_oi"] = resolver_destaques_oi(
                            oi_data.get("maior_oi"), opcoes_data.get("strike_map"),
                            opcoes_data.get("spot"))
                    except Exception as e:
                        print(f"[oi] strike do destaque: {e}")
                elif oi_data is not None:
                    opcoes_data = {"oi": oi_data,
                                   "destaque_oi": (oi_data.get("maior_oi") or {})}
                if aluguel_data is not None:
                    opcoes_data = opcoes_data or {}
                    opcoes_data["aluguel"] = aluguel_data
            except Exception as e:
                print(f"[opcoes] indisponível: {e}")
            # panorama macro (BCB/Focus/yfinance) + Índice de Regime Brasil
            macro_data, regime = {}, {}
            try:
                from macro import fetch_macro, regime_brasil, render_report
                macro_data = fetch_macro(selic)
                breadth = None
                try:
                    idx = (humor or {}).get("indices", {})
                    vals = [v.get("alta") for v in idx.values() if v]
                    breadth = sum(vals) / len(vals) if vals else None
                except Exception:
                    breadth = None
                regime = regime_brasil(macro_data, breadth_alta=breadth)
                _n = sum(1 for k, v in (macro_data or {}).items()
                         if isinstance(v, dict) and v.get("val") is not None)
                _sc = regime.get("score") if regime else None
                print(f"[macro] {_n} indicadores obtidos do BCB/yfinance; "
                      f"Focus IPCA={'ok' if (macro_data.get('focus_ipca') or {}).get('hoje') is not None else 'n/d'}; "
                      f"regime={_sc if _sc is not None else 'n/d'}.")
                if _n == 0:
                    print("[macro] ATENÇÃO: nenhum indicador retornou — as APIs do BCB/Focus "
                          "podem estar indisponíveis ou bloqueadas no runner.")
                macro_html = render_report(macro_data, regime, hoje)
                macro_path = f"{outdir}/macro_{hoje}.html"
                with open(macro_path, "w", encoding="utf-8") as fh:
                    fh.write(macro_html)
            except Exception as e:
                print(f"[macro] indisponível: {e}")
                macro_path = None
            n_graf = int((selecionados["oportunidade_grafica"] != "Não").sum()) \
                if len(selecionados) else 0
            meta_dict = dict(universe=universe, top_quantile=top_quantile,
                             min_invest=min_invest)
            gpct = None
            if split_by_origin and min_invest is None:
                if group_top is not None:
                    _p = int(round(group_top * 100))
                    gpct = {"BOVA11": _p, "SMALL11": _p}
                else:
                    gpct = {"BOVA11": int(round(q_bluechip * 100)),
                            "SMALL11": int(round(q_smallcap * 100))}
            wl_df = full[full["in_wishlist"]].sort_values("investment", ascending=False)
            ca_df = full[full["in_carteira"]].sort_values("investment", ascending=False)

            # PDF: relatório COMPLETO (sem cortes) como anexo — evita o limite do Gmail
            import os as _os
            pdf_path = None
            if _os.getenv("EMAIL_PDF", "1") != "0":
                from mailer import html_to_pdf
                full_html = build_html(selecionados, hoje, meta_dict, market=resumo,
                                       mood=humor, group_pct=gpct,
                                       defensive_cyc=defensive_max_cyc,
                                       setor_medians=setor_medians, macro=macro_data,
                                       regime=regime, wishlist_df=wl_df, carteira_df=ca_df,
                                       for_pdf=True, opcoes=opcoes_data)
                pdf_path = html_to_pdf(full_html, f"{outdir}/relatorio_{hoje}.pdf")

            if pdf_path:            # corpo curto + relatório no PDF anexo
                from mailer import build_email_body
                html = build_email_body(hoje, meta_dict, resumo, humor,
                                        len(selecionados), n_graf, macro=macro_data,
                                        regime=regime, tem_pdf=True, opcoes=opcoes_data)
                print("[email] enviando corpo curto + relatório completo em PDF.")
            else:                   # fallback: relatório no corpo (com guarda de tamanho)
                print("[email] PDF indisponível — enviando relatório no corpo (com guarda "
                      "de tamanho).")
                html = build_html(selecionados, hoje, meta_dict, market=resumo, mood=humor,
                                  group_pct=gpct, defensive_cyc=defensive_max_cyc,
                                  setor_medians=setor_medians, macro=macro_data,
                                  regime=regime, wishlist_df=wl_df, carteira_df=ca_df,
                                  opcoes=opcoes_data)

            subject = (f"[Screener B3] {len(selecionados)} papéis nos critérios "
                       f"({n_graf} com oportunidade gráfica) — {hoje}")
            anexos = [p for p in (pdf_path, xlsx_path,
                                  f"{outdir}/selecionados_{hoje}.csv", macro_path) if p]
            send_report_email(subject, html, anexos)
        except Exception as e:
            import traceback as _tb
            print(f"[email] falhou: {e}")
            print("[email] traceback completo:\n" + _tb.format_exc())

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
                   help="fração superior por Investment Score que passa no fundamentalista "
                        "(fallback p/ grupos sem fração própria)")
    p.add_argument("--q-bluechip", type=float, default=0.60,
                   help="fração superior das blue chips / BOVA11 (default 0.60)")
    p.add_argument("--q-smallcap", type=float, default=0.50,
                   help="fração superior das small caps / SMALL11 (default 0.50)")
    p.add_argument("--q-defensive", type=float, default=0.70,
                   help="fração superior do pool DEFENSIVO (baixa ciclicidade), mais permissiva "
                        "(default 0.70)")
    g.add_argument("--min-invest", type=float, default=None,
                   help="nota mínima de Investment (0-100) em vez de quantil")
    p.add_argument("--lookback", type=int, default=20)
    p.add_argument("--vol-mult", type=float, default=1.5,
                   help="volume mínimo no rompimento, em x da média de 20 dias")
    p.add_argument("--breakout-consol-pct", type=float, default=10.0,
                   help="amplitude máx. da consolidação p/ rompimento (%%, default 10)")
    p.add_argument("--breakout-margin-pct", type=float, default=1.5,
                   help="margem mínima acima do topo p/ validar rompimento (%%, default 1.5)")
    p.add_argument("--no-base-structure", action="store_true",
                   help="desliga a exigência de BASE ESTRUTURADA no rompimento (a base "
                        "precisa ter sido testada nas duas bordas, não vale subida em reta)")
    p.add_argument("--base-edge-frac", type=float, default=0.30,
                   help="fração da faixa que conta como borda (default 0.30)")
    p.add_argument("--base-min-toques", type=int, default=2,
                   help="nº mínimo de transições entre as bordas da base (default 2)")
    p.add_argument("--breakout-max-ext", type=float, default=0.03,
                   help="extensão MÁX. do rompimento acima do topo rompido (fração, "
                        "default 0.04 = 4%%; evita perseguir rompimento esticado)")
    p.add_argument("--pivot-max-ext", type=float, default=0.04,
                   help="extensão máx. do pivô acima do topo da consolidação (default 0.04)")
    p.add_argument("--flag-max-ext", type=float, default=0.04,
                   help="extensão máx. da bandeira acima da linha superior/mastro (default 0.04)")
    p.add_argument("--pivot-range-pct", type=float, default=5.0,
                   help="amplitude máx. (%%) da janela usada para medir a consolidação do "
                        "pivô — isola a pausa recente do rally (default 5)")
    p.add_argument("--pivot-lower-frac", type=float, default=0.5,
                   help="pivô até esta fração da consolidação, medida a partir do fundo "
                        "(default 0.5 = metade inferior; 0.33 = terço inferior; 0.75 = mais folga)")
    p.add_argument("--pattern-max-ext", type=float, default=0.10,
                   help="extensão máx. dos padrões (fundo duplo/triplo, bandeira) acima do "
                        "pescoço/linha (default 0.10 = 10%%)")
    p.add_argument("--flag-min-dias", type=int, default=7,
                   help="mínimo de pregões da consolidação da bandeira (default 7)")
    p.add_argument("--flag-pole-min", type=float, default=0.12,
                   help="alta mínima do mastro da bandeira (fração, default 0.12 = 12%%)")
    p.add_argument("--flag-min-retrace", type=float, default=0.05,
                   help="recuo MÍNIMO da bandeira, fração do mastro (default 0.05 = 5%%)")
    p.add_argument("--trend-ma-long", type=int, default=30,
                   help="período da média móvel LONGA usada na tendência, junto da MM21 "
                        "(default 30)")
    p.add_argument("--no-pattern-virada", action="store_true",
                   help="desliga a exigência de que o fundo duplo represente a VIRADA "
                        "(por padrão, no 2º fundo a tendência não podia já ser de alta)")
    p.add_argument("--pattern-max-sep", type=int, default=45,
                   help="separação MÁXIMA (pregões) entre os fundos de um fundo duplo/triplo "
                        "(default 45; evita casar vales distantes que não formam um W)")
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
    p.add_argument("--teto-proj-yield", type=float, default=6.0,
                   help="DY-alvo (%%) do teto projetivo Bazin: LPA×(1+g)×payout / DY-alvo "
                        "(default 6.0)")
    p.add_argument("--min-margin", type=float, default=8.0,
                   help="Corte duro: margem líquida mínima (%%) p/ não-financeiras "
                        "(default 8; 0 desliga)")
    p.add_argument("--min-roe", type=float, default=10.0,
                   help="Corte duro: ROE médio (5a) mínimo (%%) p/ todos os setores "
                        "(default 10; 0 desliga)")
    p.add_argument("--defensive-lev-mult", type=float, default=1.8,
                   help="Multiplicador do limite de dívida p/ setores defensivos/regulados "
                        "(default 1.8; 1.0 = sem folga)")
    p.add_argument("--defensive-lev-cyc", type=float, default=0.2,
                   help="Ciclicidade máx. p/ ganhar a folga de dívida de defensivo "
                        "(default 0.2; utilities/elétricas/saneamento têm 0.1)")
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
        breakout_max_ext=a.breakout_max_ext,
        require_base_structure=not a.no_base_structure,
        base_edge_frac=a.base_edge_frac,
        base_min_toques=a.base_min_toques,
        pivot_max_ext=a.pivot_max_ext,
        flag_max_ext=a.flag_max_ext,
        pivot_lower_frac=a.pivot_lower_frac,
        pivot_range_pct=a.pivot_range_pct,
        pattern_max_ext=a.pattern_max_ext,
        flag_min_dias=a.flag_min_dias,
        flag_pole_min=a.flag_pole_min,
        flag_min_retrace=a.flag_min_retrace,
        trend_ma_long=a.trend_ma_long,
        pattern_max_sep=a.pattern_max_sep,
        no_pattern_virada=a.no_pattern_virada,
        dy_years=a.dy_years, use_avg_dy=not a.no_avg_dy,
        bazin_yield_pct=a.bazin_yield, teto_desconto_pct=a.teto_desconto,
        teto_outlier_mult=a.teto_outlier_mult,
        require_roe_roic_selic=not a.no_roe_roic_selic, max_leverage=a.max_leverage,
        min_marketcap=a.min_marketcap * 1_000_000,
        consistency_weight=a.consistency_weight,
        max_net_debt_equity=a.max_net_debt_equity,
        split_by_origin=not a.no_split, group_top=a.group_top,
        q_bluechip=a.q_bluechip, q_smallcap=a.q_smallcap, q_defensive=a.q_defensive,
        use_basileia=not a.no_basileia, cyclical_penalty=a.cyclical_penalty,
        defensive_max_cyc=a.defensive_max_cyc,
        teto_max_upside=a.teto_max_upside, teto_disp_max=a.teto_disp_max,
        suspect_pl_min=a.suspect_pl_min, suspect_dy_max=a.suspect_dy_max,
        teto_proj_yield=a.teto_proj_yield,
        min_margin=a.min_margin, min_roe=a.min_roe,
        defensive_lev_mult=a.defensive_lev_mult, defensive_lev_cyc=a.defensive_lev_cyc)
