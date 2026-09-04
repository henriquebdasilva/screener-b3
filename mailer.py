# -*- coding: utf-8 -*-
"""
Envio de e-mail do screener.

- Credenciais e destinatários vêm de VARIÁVEIS DE AMBIENTE (GitHub Secrets):
    SMTP_HOST   (default: smtp.gmail.com)
    SMTP_PORT   (default: 465, SSL)
    SMTP_USER   remetente / login
    SMTP_PASS   senha de app (NUNCA commitar; use Secrets)
    MAIL_TO     destinatário(s), separados por vírgula
    MAIL_FROM   (opcional; default = SMTP_USER)
  Se SMTP_USER / SMTP_PASS / MAIL_TO não estiverem definidos, o envio é PULADO
  (o app continua gerando os relatórios em disco normalmente).

- Corpo do e-mail: relatório HTML com a tabela dos ativos aprovados.
- Anexo: a planilha .xlsx com os ativos que atendem aos critérios (+ CSV, se existir).
"""
from __future__ import annotations

import os
import math
import smtplib
import ssl
import mimetypes
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Optional

import pandas as pd


@dataclass
class MailConfig:
    host: str = "smtp.gmail.com"
    port: int = 465
    user: str = ""
    password: str = ""
    mail_to: str = ""
    mail_from: str = ""

    @property
    def enabled(self) -> bool:
        return bool(self.user and self.password and self.mail_to)

    @property
    def recipients(self) -> list[str]:
        return [x.strip() for x in self.mail_to.split(",") if x.strip()]


def config_from_env() -> MailConfig:
    c = MailConfig(
        host=(os.getenv("SMTP_HOST") or "smtp.gmail.com").strip(),
        port=int(os.getenv("SMTP_PORT") or 465),
        user=(os.getenv("SMTP_USER") or "").strip(),
        password=(os.getenv("SMTP_PASS") or "").strip(),
        mail_to=(os.getenv("MAIL_TO") or "").strip(),
        mail_from=(os.getenv("MAIL_FROM") or "").strip(),
    )
    if not c.mail_from:
        c.mail_from = c.user
    return c


# ---------------- relatório HTML ----------------
_CSS = """
body{font-family:Arial,Helvetica,sans-serif;color:#1f2937;margin:0;padding:24px;background:#f8fafc}
.card{max-width:900px;margin:auto;background:#fff;border-radius:12px;padding:24px;
      box-shadow:0 1px 4px rgba(0,0,0,.08)}
h1{font-size:20px;margin:0 0 4px}.sub{color:#6b7280;font-size:13px;margin:0 0 16px}
table{border-collapse:collapse;width:100%;font-size:13px}
th{background:#1f3864;color:#fff;text-align:left;padding:8px}
td{padding:7px 8px;border-bottom:1px solid #e5e7eb}
.ind table{font-size:11px}
.ind th{padding:4px 5px}
.ind td{padding:3px 5px}
td.r,th.r{text-align:right}.g{color:#16a34a}.rd{color:#dc2626}.mut{color:#9ca3af}
tr:nth-child(even) td{background:#f3f4f6}
.tag{display:inline-block;padding:2px 8px;border-radius:9999px;font-size:11px;font-weight:700}
.romp{background:#dcfce7;color:#166534}.piv{background:#fef9c3;color:#854d0e}
.nao{background:#e5e7eb;color:#4b5563}
.pad{background:#dbeafe;color:#1e40af}
.cand{background:#fff;color:#6b7280;border:1px dashed #cbd5e1;font-style:italic;
      font-weight:normal}
.warn{color:#6b7280;font-size:12px;margin-top:16px}
.empty{color:#6b7280;font-style:italic}
/* ---- faixa de título de seção (barra colorida) ---- */
.secbar{background:#1f3864;color:#fff;padding:7px 12px;font-size:14px;font-weight:bold;
        margin:20px 0 0}
.secbar .cnt{color:#c7d2fe;font-weight:normal;font-size:12px}
.secsub{background:#eef2ff;color:#3730a3;font-size:11px;padding:5px 12px;margin:0 0 8px}
/* ---- cartões de KPI (via tabela, compatível com xhtml2pdf) ---- */
.kpi{width:100%;border-collapse:separate;border-spacing:6px 0;margin:2px 0 14px}
.kpi td{border:none;padding:9px 10px;text-align:center;background:#f1f5f9}
.kpi .lbl{font-size:10px;color:#475569;text-transform:uppercase}
.kpi .val{font-size:17px;font-weight:bold;color:#0f172a}
/* ---- escala de score (fundo colorido por faixa) ---- */
.s5{background:#166534;color:#fff}.s4{background:#86efac;color:#14532d}
.s3{background:#fef08a;color:#713f12}.s2{background:#fed7aa;color:#7c2d12}
.s1{background:#fecaca;color:#7f1d1d}
.scr{display:inline-block;min-width:26px;padding:2px 5px;border-radius:4px;
     font-weight:bold;font-size:11px;text-align:center}
"""


def _scr(v, casas: int = 0) -> str:
    """Score 0-100 como badge colorido (verde escuro = ótimo ... vermelho = fraco)."""
    try:
        x = float(v)
    except Exception:
        return '<span class="mut">—</span>'
    if math.isnan(x):
        return '<span class="mut">—</span>'
    cls = "s5" if x >= 80 else "s4" if x >= 65 else "s3" if x >= 50 else "s2" if x >= 35 else "s1"
    return f'<span class="scr {cls}">{x:.{casas}f}</span>'


def _kpi_bar(itens) -> str:
    """Linha de cartões KPI (label + valor). `itens` = lista de (label, valor[, cor])."""
    if not itens:
        return ""
    tds = []
    for it in itens:
        lbl, val = it[0], it[1]
        cor = it[2] if len(it) > 2 else "#0f172a"
        tds.append(f'<td><div class="lbl">{lbl}</div>'
                   f'<div class="val" style="color:{cor}">{val}</div></td>')
    return f'<table class="kpi"><tr>{"".join(tds)}</tr></table>'


def _secbar(titulo: str, cnt: str = "", sub: str = "") -> str:
    """Faixa colorida de título de seção (+ subtítulo opcional)."""
    c = f' <span class="cnt">{cnt}</span>' if cnt else ""
    s = f'<div class="secsub">{sub}</div>' if sub else ""
    return f'<div class="secbar">{titulo}{c}</div>{s}'


def _trend_cell(trend) -> str:
    """Tendência (Em Alta/Lateral/Em Baixa) com cor: verde/cinza/vermelho."""
    t = str(trend or "").strip()
    if t == "Em Alta":
        return f'<span style="color:#16a34a;font-weight:bold">▲ {t}</span>'
    if t == "Em Baixa":
        return f'<span style="color:#dc2626;font-weight:bold">▼ {t}</span>'
    if t == "Lateral":
        return f'<span style="color:#6b7280">▬ {t}</span>'
    return t or '<span class="mut">—</span>'


def _fmt_row(r) -> str:
    flag = str(r.get("oportunidade_grafica", "") or "")
    if not flag:  # compat: deriva de strategy/breakout se a flag não veio
        strat = str(r.get("strategy", "") or "")
        flag = strat if (r.get("breakout") and strat) else "Não"
    cls = "romp" if "Romp" in flag else ("piv" if "Piv" in flag else "nao")
    tag = f'<span class="tag {cls}">{flag}</span>'
    # candidato pré-confirmação e virada de tendência: badges extras (só quando NÃO há sinal
    # confirmado — senão o rompimento/pivô/padrão já é a informação principal)
    extra_tags = []
    if flag == "Não":
        cand = str(r.get("candidato_padrao", "") or "")
        if cand:
            cand_nota = str(r.get("candidato_nota", "") or cand)
            extra_tags.append(f'<span class="tag cand" title="{cand_nota}">{cand} (quase)</span>')
        if r.get("virada_alta"):
            extra_tags.append('<span class="tag cand">Virada p/ Alta</span>')
    if extra_tags:
        tag = tag + "<br>" + " ".join(extra_tags)
    def num(x, d=1):
        try:
            return f"{float(x):.{d}f}"
        except Exception:
            return "—"
    crit = "—"
    try:
        if pd.notna(r.get("criterios_ok")) and pd.notna(r.get("criterios_aplicaveis")):
            crit = f"{int(r.get('criterios_ok'))}/{int(r.get('criterios_aplicaveis'))}"
    except Exception:
        pass
    taj = r.get("teto_ajustado")
    up = r.get("teto_upside_pct")
    teto_cell = "—"
    if pd.notna(taj):
        up_s = f" ({float(up):+.0f}%)" if pd.notna(up) else ""
        teto_cell = f"{float(taj):.2f}{up_s}"
    cons_cell = "—"
    try:
        if pd.notna(r.get("consistencia")):
            ck = ""
            if pd.notna(r.get("n_ok")) and pd.notna(r.get("n_aplic")):
                ck = f" ({int(r.get('n_ok'))}/{int(r.get('n_aplic'))})"
            cons_cell = f"{int(round(float(r.get('consistencia'))))}{ck}"
    except Exception:
        pass
    return (
        f"<tr><td><b>{r.name}</b></td><td>{r.get('origem','')}</td>"
        f"<td>{r.get('setor','')}</td><td>{_scr(r.get('investment'))}</td>"
        f"<td>{_scr(r.get('quality'))}</td><td>{_scr(r.get('value'))}</td>"
        f"<td>{_scr(r.get('safety'))}</td><td>{_scr(r.get('dividend'))}</td>"
        f"<td>{cons_cell}</td>"
        f"<td>{crit}</td><td>{tag}</td><td>{_trend_cell(r.get('trend',''))}</td>"
        f"<td>{num(r.get('close'),2)}</td><td>{teto_cell}</td></tr>"
    )


def _teto_table(df: pd.DataFrame) -> str:
    def num(x, d=2):
        try:
            v = float(x)
            return f"{v:.{d}f}" if not (v != v) else "—"
        except Exception:
            return "—"
    head = ("<tr><th>Ativo</th><th>Preço</th><th>Bazin</th><th>Gordon</th><th>DCF</th>"
            "<th>Graham</th><th>Grah.Selic</th><th>Lynch</th><th>Projet.</th>"
            "<th>Múlt.EV</th><th>Média</th><th>Mediana</th>"
            "<th>Ajust.</th><th>Upside*</th></tr>")
    rows = []
    for _, r in df.iterrows():
        up = r.get("teto_upside_pct")
        up_s = f"{float(up):+.0f}%" if pd.notna(up) else "—"
        rows.append(
            f"<tr><td><b>{r.name}</b></td><td>{num(r.get('close'))}</td>"
            f"<td>{num(r.get('teto_bazin'))}</td><td>{num(r.get('teto_gordon'))}</td>"
            f"<td>{num(r.get('teto_dcf'))}</td><td>{num(r.get('teto_graham'))}</td>"
            f"<td>{num(r.get('teto_graham_selic'))}</td>"
            f"<td>{num(r.get('teto_lynch'))}</td><td>{num(r.get('teto_projetivo'))}</td>"
            f"<td>{num(r.get('teto_mult_ebitda'))}</td>"
            f"<td>{num(r.get('teto_medio'))}</td>"
            f"<td>{num(r.get('teto_mediana'))}</td>"
            f"<td><b>{num(r.get('teto_ajustado'))}</b></td><td>{up_s}</td></tr>")
    return f'<div class="ind"><table>{head}{"".join(rows)}</table></div>'


def _agenda_table(df: pd.DataFrame) -> str:
    def val(x):
        return "—" if (x is None or (isinstance(x, float) and pd.isna(x))
                       or str(x) in ("", "n/d")) else str(x)
    def num(x, d=1):
        try:
            return f"{float(x):.{d}f}"
        except Exception:
            return "—"
    head = ("<tr><th>Ativo</th><th>DY %</th><th>Próx. resultado</th>"
            "<th>Ex-dividendo</th></tr>")
    rows = []
    for _, r in df.iterrows():
        ex = val(r.get("ex_dividendo"))
        tipo = str(r.get("ex_tipo") or "")
        if ex != "—" and tipo:
            ex = f"{ex} ({tipo})"
        rows.append(f"<tr><td><b>{r.name}</b></td><td>{num(r.get('dy'))}</td>"
                    f"<td>{val(r.get('prox_resultado'))}</td><td>{ex}</td></tr>")
    return f"<table>{head}{''.join(rows)}</table>"


def _teses_block(df: pd.DataFrame, tese_max: int = 0) -> str:
    itens = []
    for _, r in df.iterrows():
        t = str(r.get("tese_ia") or "").strip()
        if t:
            if tese_max and len(t) > tese_max:
                t = t[:tese_max].rsplit(" ", 1)[0] + "…"
            itens.append(f'<p style="margin:8px 0"><b>{r.name}</b> — {t}</p>')
    if not itens:
        return ""
    return (
        '<h2 style="font-size:15px;margin:20px 0 6px">Teses (geradas por IA)</h2>'
        '<p class="sub" style="margin:0 0 8px">Resumo automático ancorado apenas nos '
        'números deste screener (aprovados = fundamentos + rompimento). Pode conter erros; '
        '<b>não é recomendação</b>.</p>' + "".join(itens))


_H2 = 'font-size:15px;margin:22px 0 6px;color:#0f172a'
_H3 = 'font-size:12.5px;margin:14px 0 4px;color:#475569;text-transform:uppercase'

_MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
          "agosto", "setembro", "outubro", "novembro", "dezembro"]


def _fmt_date(hoje: str) -> str:
    try:
        import datetime as _dt
        d = _dt.datetime.strptime(hoje, "%Y-%m-%d")
        return f"{d.day:02d} de {_MESES[d.month - 1]} de {d.year}"
    except Exception:
        return hoje


_TETO_NOTE = (
    'Cinco métodos — Bazin (yield-alvo = Selic), Gordon (dividendos), DCF (lucros), Graham '
    'e Lynch/PEGY — mais a Média e a Mediana. <b>Ajust.</b> = mediana com desconto de '
    'segurança; *Upside calculado sobre o Ajust. Bazin e Gordon usam o DY médio de ~5 anos. '
    'Método muito fora (além de ~2,5× a mediana) é descartado; em bancos/seguros, Graham e '
    'Lynch também. Estimativas sensíveis às premissas — referência, não gatilho.'
)


def _ret_str(v):
    return "n/d" if (v is None or (isinstance(v, float) and math.isnan(v))) else f"{v:+.1f}%"


def _market_block(m: dict, macro: dict = None, opcoes: dict = None) -> str:
    if not m:
        return ""
    rows = [f"<tr><td><b>Selic</b></td><td>{m.get('selic', float('nan')):.2f}% a.a.</td>"
            f"<td>—</td></tr>"]
    for name, tup in (m.get("indices") or {}).items():
        ytd, mtd = (tup if tup else (math.nan, math.nan))
        rows.append(f"<tr><td><b>{name}</b></td><td>{_ret_str(ytd)}</td>"
                    f"<td>{_ret_str(mtd)}</td></tr>")

    ifix = (macro or {}).get("ifix")
    if ifix and ifix.get("fechamento") is not None:
        rows.append(f"<tr><td><b>IFIX</b></td>"
                    f"<td>{_ret_str(ifix.get('var_ano_pct'))}</td>"
                    f"<td>{_ret_str(ifix.get('var_mes_pct'))}</td></tr>")
    else:
        rows.append('<tr><td><b>IFIX</b></td><td colspan="2">n/d</td></tr>')

    fx = (macro or {}).get("fluxo_estrangeiro")
    if fx and fx.get("dia") is not None:
        cor = "#16a34a" if fx["dia"] >= 0 else "#dc2626"
        rows.append(f'<tr><td><b>Fluxo estrangeiro</b></td>'
                    f'<td colspan="2"><span style="color:{cor}">'
                    f'R$ {fx["dia"]:+,.0f} mi</span> no dia '
                    f'<span class="sub">(fonte: BDI/B3)</span></td></tr>')
    elif fx and fx.get("acum_mes") is not None:
        cor = "#16a34a" if fx["acum_mes"] >= 0 else "#dc2626"
        fb = fx.get("dia_fallback")
        if fb and fb.get("valor") is not None:
            # BDI de hoje ainda incompleto/repetido: mostra o ÚLTIMO dia que teve dado real,
            # rotulado com a data dele — em vez de 'n/d'. Data vem como 'AAAA-MM-DD' (ISO).
            partes = str(fb.get("data", "")).split("-")
            data_txt = f"{partes[2]}/{partes[1]}/{partes[0]}" if len(partes) == 3 else "—"
            cor_fb = "#16a34a" if fb["valor"] >= 0 else "#dc2626"
            rows.append(f'<tr><td><b>Fluxo estrangeiro</b></td>'
                        f'<td colspan="2"><span style="color:{cor_fb}">'
                        f'R$ {fb["valor"]:+,.0f} mi</span> '
                        f'<span class="sub">(último dado disp., {data_txt})</span> · '
                        f'acum. mês <span style="color:{cor}">'
                        f'R$ {fx["acum_mes"]:+,.0f} mi</span></td></tr>')
        else:
            rows.append(f'<tr><td><b>Fluxo estrangeiro</b></td>'
                        f'<td colspan="2">acum. mês <span style="color:{cor}">'
                        f'R$ {fx["acum_mes"]:+,.0f} mi</span> '
                        f'<span class="sub">(valor do dia disponível amanhã)</span></td></tr>')
    else:
        rows.append('<tr><td><b>Fluxo estrangeiro</b></td>'
                    '<td colspan="2">n/d — BDI indisponível hoje</td></tr>')

    top = (opcoes or {}).get("top_negociadas") or []
    if top:
        itens = []
        for o in top[:5]:
            tp = "CALL" if o["tipo"] == "C" else "PUT"
            cor = "#16a34a" if o["tipo"] == "C" else "#dc2626"
            vol = f"{o['volume']/1e6:.1f}M" if o["volume"] >= 1e6 else f"{o['volume']/1e3:.0f}k"
            itens.append(f'{o["base"]} <span style="color:{cor}">{tp}</span> '
                        f'{_fmt_strike(o.get("strike"))} <span class="sub">({vol})</span>')
        rows.append(f'<tr><td><b>Opções mais negociadas</b></td>'
                    f'<td colspan="2">{" · ".join(itens)}</td></tr>')
    else:
        rows.append('<tr><td><b>Opções mais negociadas</b></td>'
                    '<td colspan="2">n/d — COTAHIST indisponível hoje</td></tr>')
    head = '<tr><th>Indicador</th><th>No ano</th><th>No mês</th></tr>'
    return (f'<h2 style="{_H2}">Resumo de mercado</h2>'
            f'<table>{head}{"".join(rows)}</table>')


def _breadth_bar(b: dict) -> str:
    """Barra empilhada verde/cinza/vermelho (via tabela; renderiza no PDF e no e-mail)."""
    def seg(pct, cor, txt_cor):
        if not pct:
            return ""
        return (f'<td style="width:{pct}%;background:{cor};color:{txt_cor};font-size:10px;'
                f'font-weight:bold;text-align:center;padding:3px 0">{pct}%</td>')
    cells = (seg(b["alta"], "#16a34a", "#fff") + seg(b["lateral"], "#cbd5e1", "#334155")
             + seg(b["baixa"], "#dc2626", "#fff"))
    return (f'<table style="width:150px;border-collapse:collapse;table-layout:fixed;'
            f'border-radius:3px;overflow:hidden"><tr>{cells}</tr></table>')


def _pc_cell(pc) -> str:
    """Put/Call ratio como badge colorido (vermelho ≥1.2 baixista, verde ≤0.8 altista,
    cinza neutro) — mesmo tratamento visual dos scores, para destacar de relance."""
    if pc is None or (isinstance(pc, float) and math.isnan(pc)):
        return '<span class="mut">n/d</span>'
    if pc >= 1.2:
        bg, fg = "#fecaca", "#7f1d1d"
    elif pc <= 0.8:
        bg, fg = "#bbf7d0", "#14532d"
    else:
        bg, fg = "#e2e8f0", "#334155"
    return (f'<span style="display:inline-block;min-width:34px;padding:2px 5px;'
            f'border-radius:4px;background:{bg};color:{fg};font-weight:bold;'
            f'font-size:11px;text-align:center">{pc:.2f}</span>')


def _fmt_strike(s):
    if s is None or (isinstance(s, float) and math.isnan(s)):
        return "?"
    return f"{s:.2f}".rstrip("0").rstrip(".") if s < 1000 else f"{s:.0f}"


def _dest_oi_cell(ticker) -> str:
    """Opção de maior open interest do ativo: tipo + strike (OI em milhões embaixo)."""
    d = _DEST_OI.get(_raiz_tk(ticker))
    if not d or d.get("oi") is None:
        return '<span class="sub">n/d</span>'
    tp = "CALL" if d.get("tipo") == "C" else "PUT"
    cor = "#16a34a" if d.get("tipo") == "C" else "#dc2626"
    oi = d["oi"]
    oi_txt = f"{oi/1e6:.1f}M" if oi >= 1e6 else f"{oi/1e3:.0f}k"
    return (f'<span style="color:{cor}">{tp}</span> {_fmt_strike(d.get("strike"))}'
            f'<br><span class="sub">{oi_txt}</span>')


def _dest_neg_cell(ticker) -> str:
    """Opção mais negociada do ativo: tipo + strike (volume R$ e nº de negócios embaixo)."""
    d = _DEST_NEG.get(_raiz_tk(ticker))
    if not d or d.get("volume") is None:
        return '<span class="sub">n/d</span>'
    tp = "CALL" if d.get("tipo") == "C" else "PUT"
    cor = "#16a34a" if d.get("tipo") == "C" else "#dc2626"
    vol = d["volume"]
    vol_txt = (f"R${vol/1e6:.1f}M" if vol >= 1e6 else f"R${vol/1e3:.0f}k")
    neg = d.get("negocios") or 0
    return (f'<span style="color:{cor}">{tp}</span> {_fmt_strike(d.get("strike"))}'
            f'<br><span class="sub">{vol_txt} · {neg:.0f} neg</span>')


def _aluguel_cell(ticker, row) -> str:
    """% das ações em circulação que estão em aluguel (posição em aberto) = pressão vendedora.
    Ações em circulação ~ market_cap / preço. Mostra só a quantidade se não der o %."""
    info = _ALUGUEL.get(str(ticker))
    if not info or not info.get("qtd"):
        return '<span class="sub">n/d</span>'
    qtd = info["qtd"]
    mcap = row.get("market_cap")
    preco = row.get("close")
    try:
        if mcap and preco and preco > 0:
            shares = mcap / preco
            pct = qtd / shares * 100 if shares > 0 else None
            if pct is not None:
                cor = "#dc2626" if pct >= 5 else ("#b45309" if pct >= 2 else "#334155")
                return f'<span style="color:{cor}">{pct:.1f}%</span>'
    except Exception:
        pass
    return f'<span class="sub">{qtd/1e6:.1f}M</span>'      # fallback: milhões de ações


def _historico_chart(hist: list) -> str:
    """Gráfico de evolução (barras VERTICAIS via matplotlib, embutidas como imagem — mais
    robusto que CSS/tabela no xhtml2pdf) do fluxo estrangeiro diário e do Put/Call de
    posições em aberto (open interest) do mercado, nos últimos BDIs no cache local (preenche
    aos poucos até a janela configurada)."""
    if not hist:
        return ""
    try:
        import charts
    except Exception as e:
        return f'<p class="sub">Gráfico de evolução indisponível ({e}).</p>'

    dias = [d.get("data", "")[5:] for d in hist]          # MM-DD
    fluxos = [d.get("fluxo_dia") for d in hist]
    ois = [d.get("oi_pc_mercado") for d in hist]

    img_fluxo = charts.barras_verticais(
        dias, fluxos, titulo="Fluxo estrangeiro (R$ mi/dia)", ylabel="R$ mi",
        cor_por_sinal=True, fmt_valor="{:+,.0f}")
    img_oi = charts.barras_verticais(
        dias, ois, titulo="OI Put/Call (mercado)", ylabel="razão",
        cor_por_sinal=False, linha_referencia=1.0, fmt_valor="{:.2f}")

    return (_secbar(f"Evolução — últimos {len(hist)} BDIs")
            + '<p class="sub" style="margin:0 0 8px">Fluxo estrangeiro do dia (R$ mi) e Put/'
              'Call de posições em aberto (open interest) do mercado, acumulados a cada '
              'execução do relatório — enche aos poucos até a janela configurada.</p>'
            + img_fluxo + img_oi)


def _ranking_opcoes(opcoes: dict = None, hist: list = None) -> str:
    """Dois gráficos de barras (ranking, top-10): opções mais negociadas do dia por VOLUME
    financeiro (COTAHIST) e por NÚMERO DE POSIÇÕES EM ABERTO — open interest (BDI). Se `hist`
    (histórico de dias anteriores) for passado, mostra também a EVOLUÇÃO do Put/Call por
    volume do mercado nos últimos dias — dá noção de tendência de curto prazo (o ranking do
    dia sozinho é uma fotografia; a série mostra se o mercado está ficando mais defensivo ou
    mais comprado nas últimas sessões)."""
    if not opcoes:
        return ""
    top_vol = opcoes.get("top_negociadas") or []
    top_pos = ((opcoes.get("oi") or {}).get("top_oi")) or []
    if not top_vol and not top_pos:
        return ""
    try:
        import charts
    except Exception as e:
        return f'<p class="sub">Ranking de opções indisponível ({e}).</p>'

    def rotulo(d):
        tp = "CALL" if d.get("tipo") == "C" else "PUT"
        st = d.get("strike")
        st_txt = f"{st:.2f}".rstrip("0").rstrip(".") if st is not None else "?"
        return f"{d.get('base', '?')} {tp} {st_txt}"

    partes = [_secbar("Opções — rankings do dia")]
    pc_vals = [d.get("pc_vol_mercado") for d in (hist or [])]
    if hist and any(v is not None for v in pc_vals):
        dias = [d.get("data", "")[5:] for d in hist]
        partes.append(charts.barras_verticais(
            dias, pc_vals, titulo="Tendência — P/C por volume (mercado), últimos dias",
            ylabel="razão", cor_por_sinal=False, linha_referencia=1.0, fmt_valor="{:.2f}"))
    if top_vol:
        labels = [rotulo(d) for d in top_vol[:10]]
        vols = [d.get("volume", 0) for d in top_vol[:10]]
        cores = ["#16a34a" if d.get("tipo") == "C" else "#dc2626" for d in top_vol[:10]]
        partes.append(charts.barras_ranking(
            labels, vols, cores=cores, titulo="Top 10 por volume financeiro",
            xlabel="Volume (R$)", fmt_valor=lambda v: f"R${v/1e6:.1f}M" if v >= 1e6
            else f"R${v/1e3:.0f}k"))
    if top_pos:
        labels = [rotulo(d) for d in top_pos[:10]]
        ois = [d.get("oi", 0) for d in top_pos[:10]]
        cores = ["#16a34a" if d.get("tipo") == "C" else "#dc2626" for d in top_pos[:10]]
        partes.append(charts.barras_ranking(
            labels, ois, cores=cores, titulo="Top 10 por posições em aberto (open interest)",
            xlabel="Contratos em aberto",
            fmt_valor=lambda v: f"{v/1e6:.1f}M" if v >= 1e6 else f"{v/1e3:.0f}k"))
    partes.append('<p class="sub" style="margin:4px 0 0">'
                  '<span style="color:#16a34a">CALL</span> / '
                  '<span style="color:#dc2626">PUT</span>. Volume via COTAHIST/B3 (giro do '
                  'dia); posições em aberto via BDI/B3 (contratos em aberto, mais '
                  'estrutural).</p>')
    return "".join(partes)


def _mood_block(mood: dict, opcoes: dict = None, hist: list = None) -> str:
    if not mood or (not mood.get("indices") and not mood.get("setores")):
        return ""
    por_setor = (opcoes or {}).get("por_setor") or {}
    por_grupo = (opcoes or {}).get("por_grupo") or {}      # BOVA11/SMALL11 (média por índice)
    oi = (opcoes or {}).get("oi") or {}
    oi_setor = oi.get("por_setor") or {}
    oi_grupo = oi.get("por_grupo") or {}
    tem_pc = bool(por_setor or por_grupo)
    tem_oi = bool(oi_setor or oi_grupo)

    def linha(nome, b, pc=None, oi_pc=None, bold=False):
        rot = f"<b>{nome}</b>" if bold else nome
        bg = ' style="background:#eef2ff"' if bold else ""
        txt = (f'{b["alta"]}% alta · {b["lateral"]}% lat · {b["baixa"]}% baixa '
               f'<span class="sub">(n={b["n"]})</span>')
        pc_td = f"<td class='r'>{_pc_cell(pc)}</td>" if tem_pc else ""
        oi_td = f"<td class='r'>{_pc_cell(oi_pc)}</td>" if tem_oi else ""
        return (f"<tr{bg}><td>{rot}</td><td>{_breadth_bar(b)}</td>"
                f"<td>{txt}</td>{pc_td}{oi_td}</tr>")

    rows = []
    for k, b in (mood.get("indices") or {}).items():
        pc = (por_grupo.get(k) or {}).get("pc_ratio")
        oi_pc = (oi_grupo.get(k) or {}).get("oi_ratio")
        rows.append(linha(k, b, pc=pc, oi_pc=oi_pc, bold=True))
    for setor, b in sorted((mood.get("setores") or {}).items(),
                           key=lambda kv: -kv[1]["alta"]):
        pc = (por_setor.get(setor) or {}).get("pc_ratio")
        oi_pc = (oi_setor.get(setor) or {}).get("oi_ratio")
        rows.append(linha(setor, b, pc=pc, oi_pc=oi_pc))

    pc_head = "<th class='r'>P/C vol.</th>" if tem_pc else ""
    oi_head = "<th class='r'>P/C posições</th>" if tem_oi else ""
    head = (f'<tr><th>Grupo / Setor</th><th>Tendência (MM21)</th>'
            f'<th>Detalhe</th>{pc_head}{oi_head}</tr>')
    termo = ""
    merc = (opcoes or {}).get("mercado") or {}
    oi_merc = oi.get("mercado") or {}
    partes = []
    if merc.get("pc_ratio") is not None and not (isinstance(merc["pc_ratio"], float)
                                                 and math.isnan(merc["pc_ratio"])):
        vies = ("defensivo/baixista" if merc["pc_ratio"] >= 1.2
                else "altista" if merc["pc_ratio"] <= 0.8 else "neutro")
        partes.append(f'volume {_pc_cell(merc["pc_ratio"])} (viés {vies})')
    if oi_merc.get("oi_ratio") is not None and not (isinstance(oi_merc["oi_ratio"], float)
                                                    and math.isnan(oi_merc["oi_ratio"])):
        partes.append(f'posições em aberto {_pc_cell(oi_merc["oi_ratio"])}')
    if partes:
        termo = (f'<div class="kpi" style="margin:6px 0 10px">'
                 f'<table class="kpi"><tr>'
                 + "".join(f'<td><div class="lbl">Termômetro</div><div class="val" '
                          f'style="font-size:13px">{p}</div></td>' for p in partes)
                 + '</tr></table></div>')
        termo += ('<p class="sub" style="margin:-6px 0 8px">Puts ÷ calls. &gt;1 = mais '
                 'proteção/baixa; &lt;1 = mais aposta em alta. Volume = giro do dia; '
                 'posições = open interest (contratos em aberto, mais estrutural).</p>')
    tendencia_html = ""
    bova_vals = [d.get("breadth_bova11_alta") for d in (hist or [])]
    small_vals = [d.get("breadth_small11_alta") for d in (hist or [])]
    if hist and (any(v is not None for v in bova_vals) or any(v is not None for v in small_vals)):
        try:
            import charts
            dias = [d.get("data", "")[5:] for d in hist]
            tendencia_html = (
                '<h3 style="' + _H3 + '">Tendência — % dos papéis em alta (MM21), '
                'últimos dias</h3>'
                + charts.barras_verticais(dias, bova_vals, titulo="BOVA11 — % em alta",
                                          ylabel="%", cor_por_sinal=False, cor_fixa="#1f3864",
                                          fmt_valor="{:.0f}%")
                + charts.barras_verticais(dias, small_vals, titulo="SMALL11 — % em alta",
                                          ylabel="%", cor_por_sinal=False, cor_fixa="#7c3aed",
                                          fmt_valor="{:.0f}%"))
        except Exception:
            pass
    return (_secbar("Humor do mercado")
            + f'<p class="sub" style="margin:0 0 6px">Percentual dos papéis do universo '
            f'(BOVA11 + SMALL11) em alta/lateral/baixa pela média móvel de 21 pregões'
            f'{", com o Put/Call ratio por índice e por setor" if tem_pc else ""}.</p>'
            f'{termo}<table>{head}{"".join(rows)}</table>{tendencia_html}')


_SECTOR_MED = {}
_PC_ATIVO = {}                      # raiz do ticker -> {pc_ratio, ...} (opções)
_ALUGUEL = {}                       # ticker -> {qtd, valor} (posição de aluguel em aberto)
_DEST_OI = {}                       # raiz -> {tipo, strike, oi} (maior open interest)
_DEST_NEG = {}                      # raiz -> {tipo, strike, volume, negocios} (mais negociada)


def _raiz_tk(ticker):
    import re as _re
    m = _re.match(r"^([A-Za-z]+)", str(ticker))
    return m.group(1).upper() if m else str(ticker).upper()
# (coluna, rótulo, direção: 'hi'|'lo'|None, é_percentual)  — None = sem coloração
_IND_METRICS = [
    ("pl", "P/L", "lo", False), ("pvp", "P/VP", "lo", False),
    ("peg", "PEG", "lo", False), ("ev_ebitda", "EV/EB", "lo", False),
    ("div_liq_ebitda", "DL/EB", "lo", False), ("div_liq_patrim", "DL/PL", "lo", False),
    ("roe", "ROE", "hi", True), ("roic", "ROIC", "hi", True),
    ("payout", "Pay.", None, True),           # payout é não-monotônico -> sem cor
    ("mrg_liq", "Mrg", "hi", True), ("liq_corr", "Liq.corr", "hi", False),
    ("liq_geral", "Liq.ger", "hi", False), ("grau_endiv", "Endiv", "lo", True),
    ("indep_fin", "Indep", "hi", True), ("roa", "ROA", "hi", True),
    ("cresc_5a", "Cresc", "hi", True), ("pl_fut", "P/L fut", "lo", False),
]


def _stats_table(df: pd.DataFrame) -> str:
    """Tabela de estatísticas anuais por papel: preço atual, retorno no ano (YTD) e vs.
    Ibovespa, mínima/máxima do ano, drawdown máximo, volatilidade anualizada, desvio padrão
    diário, momentum 12-1, Value at Risk, Índice de Sharpe, média e mediana do preço (1a) e
    correlação com o Ibovespa e com o dólar."""
    def cell(v, casas=2, sufixo=""):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return "<td class='r mut'>—</td>"
        return f"<td class='r'>{float(v):.{casas}f}{sufixo}</td>"

    def pct_sign(v, invert_color=False):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return "<td class='r mut'>—</td>"
        x = float(v)
        pos = x < 0 if invert_color else x >= 0     # drawdown: negativo é "neutro", não "ruim"
        cls = "g" if pos else "rd"
        return f"<td class='r {cls}'>{x:+.1f}%</td>"

    head = ("<tr><th>Ativo</th><th class='r'>Preço</th><th class='r'>Retorno no ano</th>"
            "<th class='r'>vs Ibov (ano)</th><th class='r'>Mín (ano)</th>"
            "<th class='r'>Máx (ano)</th><th class='r'>Drawdown máx (1a)</th>"
            "<th class='r'>Volatilidade (1a)</th><th class='r'>Desv. padrão (dia)</th>"
            "<th class='r'>Momentum (12-1)</th><th class='r'>VaR 95% (1d)</th>"
            "<th class='r'>Sharpe</th>"
            "<th class='r'>Média (1a)</th><th class='r'>Mediana (1a)</th>"
            "<th class='r'>Corr. Ibov</th><th class='r'>Corr. USD</th></tr>")
    linhas = []
    for tk, r in df.iterrows():
        dd = r.get("max_drawdown")
        dd_cell = (f"<td class='r rd'>{float(dd):.1f}%</td>"
                  if pd.notna(dd) else "<td class='r mut'>—</td>")
        var95 = r.get("var_95")
        var_cell = (f"<td class='r rd'>{float(var95):+.1f}%</td>"
                   if pd.notna(var95) else "<td class='r mut'>—</td>")
        sharpe = r.get("sharpe")
        sharpe_cell = (f"<td class='r {'g' if float(sharpe) >= 0 else 'rd'}'>"
                       f"{float(sharpe):+.2f}</td>"
                       if pd.notna(sharpe) else "<td class='r mut'>—</td>")
        linhas.append(
            f"<tr><td><b>{tk}</b></td>"
            f"{cell(r.get('close'), 2)}"
            f"{pct_sign(r.get('ret_ytd'))}"
            f"{pct_sign(r.get('rel_ibov_ytd'))}"
            f"{cell(r.get('min_ytd'), 2)}"
            f"{cell(r.get('max_ytd'), 2)}"
            f"{dd_cell}"
            f"{cell(r.get('vol_anual'), 1, sufixo='%')}"
            f"{cell(r.get('desvio_padrao'), 2, sufixo='%')}"
            f"{pct_sign(r.get('momentum_12_1'))}"
            f"{var_cell}"
            f"{sharpe_cell}"
            f"{cell(r.get('media_1a'), 2)}"
            f"{cell(r.get('mediana_1a'), 2)}"
            f"{_num_sign_cell(r.get('corr_ibov'))}"
            f"{_num_sign_cell(r.get('corr_usd'))}</tr>")
    leg = ('<p class="sub" style="margin:4px 0 0">Preço em R$. Retorno no ano e vs Ibov (ano) = '
           'desempenho do papel no ano corrente e a diferença em pontos percentuais frente ao '
           'Ibovespa no mesmo período. Mín/Máx (ano) = mínima e máxima do PRÓPRIO ano corrente '
           '(1º de janeiro até hoje — diferente de Mín/Máx 52s da tabela acima, que é janela '
           'móvel de 12 meses). Drawdown máx = maior queda pico→vale nos últimos ~12 meses, '
           'medida sobre o PREÇO em si (não sobre média/mediana): a maior queda percentual do '
           'preço em relação ao pico mais recente até aquele ponto. Volatilidade = '
           'desvio-padrão ANUALIZADO dos retornos diários (~1 ano); Desv. padrão (dia) é o '
           'mesmo número sem anualizar — o "cru". Momentum (12-1) = retorno dos últimos 12 '
           'meses EXCLUINDO o último mês (fator clássico de momentum — evita capturar reversão '
           'de curtíssimo prazo). VaR 95% (1d) = Value at Risk histórico de 1 dia: no pior "1 '
           'em cada 20 dias" (percentil 5 dos retornos diários reais, não assume distribuição '
           'normal), a perda estimada é essa. Sharpe = (retorno anualizado − Selic) ÷ '
           'volatilidade anualizada — retorno ajustado ao risco; maior é melhor, negativo '
           'significa que nem cobriu a taxa livre de risco. Média e Mediana (1a) = preço médio '
           'e mediano do último ano (a mediana é mais robusta a picos/mínimas pontuais). '
           'Corr. Ibov/USD = correlação dos retornos diários (~1 ano) com o Ibovespa e com o '
           'dólar (USD/BRL): <span style="color:#16a34a">+</span> na mesma direção, '
           '<span style="color:#dc2626">−</span> na direção oposta — correlação com o dólar '
           'positiva sugere exportadora/commodity, negativa sugere consumo doméstico/'
           'importadora.</p>')
    return f'<h3 style="{_H3}">Estatísticas do ano</h3><table>{head}{"".join(linhas)}</table>{leg}'


def _num_sign_cell(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "<td class='r mut'>—</td>"
    cls = "g" if float(v) >= 0 else "rd"
    return f"<td class='r {cls}'>{float(v):+.2f}</td>"


def _risco_table(df: pd.DataFrame) -> str:
    """Tabela técnica/risco: preço atual, mínima e máxima de 52 semanas (R$), distância da
    mínima 52s (com sinal/cor), posição vs MM100 (acima/abaixo), beta e correlação c/ Ibov."""
    def cell(v, pct=False, sign=False):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return "<td class='r mut'>—</td>"
        if pct:
            cls = ""
            if sign:
                cls = "g" if float(v) >= 0 else "rd"
            s = f"{float(v):+.1f}%" if sign else f"{float(v):.1f}%"
            return f"<td class='r {cls}'>{s}</td>" if cls else f"<td class='r'>{s}</td>"
        return f"<td class='r'>{float(v):.2f}</td>"

    def num_sign(v):
        """Número com sinal explícito e cor (verde + / vermelho −) — p/ beta e correlação."""
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return "<td class='r mut'>—</td>"
        cls = "g" if float(v) >= 0 else "rd"
        return f"<td class='r {cls}'>{float(v):+.2f}</td>"

    head = ("<tr><th>Ativo</th><th class='r'>Preço</th>"
            "<th class='r'>Mín 52s</th><th class='r'>Máx 52s</th>"
            "<th class='r'>vs Min52</th>"
            "<th class='r'>vs MM100</th><th class='r'>Beta</th>"
            "<th class='r'>P/C opç.</th>"
            "<th class='r'>Aluguel</th><th class='r'>Maior OI</th>"
            "<th class='r'>Mais neg.</th></tr>")
    linhas = []
    for tk, r in df.iterrows():
        linhas.append(
            f"<tr><td><b>{tk}</b></td>{cell(r.get('close'))}"
            f"{cell(r.get('min_52s'))}{cell(r.get('max_52s'))}"
            f"{cell(r.get('dist_min52'), pct=True, sign=True)}"
            f"{cell(r.get('dist_mm100'), pct=True, sign=True)}"
            f"{num_sign(r.get('beta'))}"
            f"<td class='r'>{_pc_cell((_PC_ATIVO.get(_raiz_tk(tk)) or {}).get('pc_ratio'))}</td>"
            f"<td class='r'>{_aluguel_cell(tk, r)}</td>"
            f"<td class='r'>{_dest_oi_cell(tk)}</td>"
            f"<td class='r'>{_dest_neg_cell(tk)}</td></tr>")
    leg = ('<p class="sub" style="margin:4px 0 0">Preço, Mín 52s e Máx 52s em R$ (mínima e '
           'máxima de 52 semanas). vs Min52 = distância da mínima de 52 semanas; vs MM100 = '
           'posição vs média de 100 dias. <span style="color:#16a34a">Verde/+</span> acima, '
           '<span style="color:#dc2626">vermelho/−</span> abaixo. Beta vs Ibovespa (retornos '
           'diários, ~1 ano) — correlação com o Ibovespa e com o dólar estão na tabela '
           '"Estatísticas do ano", logo abaixo. P/C opç. = Put/Call ratio do ativo (volume de '
           'puts ÷ calls no pregão, COTAHIST/B3): <span style="color:#dc2626">≥1,2</span> viés '
           'baixista, <span style="color:#16a34a">≤0,8</span> altista. Aluguel = % das ações em '
           'circulação em posição de aluguel em aberto (BDI/B3), proxy de pressão vendedora: '
           '<span style="color:#dc2626">≥5%</span> alta, <span style="color:#b45309">2–5%</span> '
           'moderada. Maior OI = opção com maior posição em aberto do ativo (tipo + strike, OI '
           'embaixo; BDI/B3). Mais neg. = opção mais negociada em volume (tipo + strike, volume '
           'R$ e nº de negócios; COTAHIST/B3). <span style="color:#16a34a">CALL</span> / '
           '<span style="color:#dc2626">PUT</span>.</p>')
    return (f'<h3 style="{_H3}">Preço &amp; risco</h3>'
            f'<div class="ind"><table>{head}{"".join(linhas)}</table></div>{leg}')


def _ind_cell(val, med, direc, pct) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "<td class='r mut'>—</td>"
    txt = f"{float(val):.1f}%" if pct else f"{float(val):.2f}"
    cls = ""
    if direc and med is not None and not (isinstance(med, float) and pd.isna(med)):
        melhor = (val > med) if direc == "hi" else (val < med)
        cls = "g" if melhor else "rd"
    return f"<td class='r {cls}'>{txt}</td>" if cls else f"<td class='r'>{txt}</td>"


def _ind_table(df: pd.DataFrame) -> str:
    head = ("<tr><th>Ativo</th>"
            + "".join(f"<th class='r'>{lbl}</th>"
                      for _, lbl, _, _ in _IND_METRICS) + "</tr>")
    linhas = []
    for tk, r in df.iterrows():
        med = _SECTOR_MED.get(str(r.get("setor", "")), {})
        cells = "".join(_ind_cell(r.get(col), med.get(col), direc, pct)
                        for col, _, direc, pct in _IND_METRICS)
        linhas.append(f"<tr><td><b>{tk}</b></td>{cells}</tr>")
    leg = ('<p class="sub" style="margin:4px 0 0">EV/EB = EV/EBITDA; DL/EB = Dív.líq./EBITDA; '
           'DL/PL = Dív.líq./Patrimônio; Pay. = payout; Mrg = margem líq.; Liq.corr = liquidez '
           'corrente; Liq.ger = liquidez geral; Endiv = grau de endividamento (Passivo/Ativo); '
           'Indep = independência financeira (PL/Ativo); ROA = retorno s/ ativos; Cresc = '
           'cresc. receita 5a. ROE/ROIC/Mrg/Cresc/Pay./Endiv/Indep/ROA em %. '
           '<span style="color:#16a34a">Verde</span> = melhor que a mediana do setor; '
           '<span style="color:#dc2626">vermelho</span> = pior (payout sem cor por ser '
           'não-monotônico). Alguns campos dependem do balanço (yfinance) e podem vir (—).</p>')
    return (f'<h3 style="{_H3}">Indicadores fundamentalistas</h3>'
            f'<div class="ind"><table>{head}{"".join(linhas)}</table></div>{leg}')


def _main_head() -> str:
    return ("<tr><th>Ativo</th><th>Origem</th><th>Setor</th><th>Invest.</th>"
            "<th>Qual.</th><th>Value</th><th>Safety</th><th>Div.</th><th>Consist.</th>"
            "<th>Critérios</th><th>Oport. gráfica</th><th>Tendência</th><th>Preço</th>"
            "<th>Teto (aj.)</th></tr>")


def _main_table(df: pd.DataFrame, title: str) -> str:
    if df is None or df.empty:
        return _secbar(title) + '<p class="empty">Nenhum papel neste grupo.</p>'
    rows = "".join(_fmt_row(r) for _, r in df.iterrows())
    # KPIs do grupo: nº de papéis, score médio, quantos com sinal gráfico, upside mediano
    kpis = []
    try:
        kpis.append(("Papéis", f"{len(df)}"))
        inv = pd.to_numeric(df.get("investment"), errors="coerce")
        if inv.notna().any():
            kpis.append(("Score médio", f"{inv.mean():.0f}"))
        flag = df.get("oportunidade_grafica")
        if flag is not None:
            n_sig = int((flag.astype(str).str.strip().str.lower() != "não").sum())
            kpis.append(("Com sinal gráfico", f"{n_sig}",
                         "#16a34a" if n_sig else "#64748b"))
        ups = pd.to_numeric(df.get("teto_upside_pct"), errors="coerce")
        if ups.notna().any():
            m = ups.median()
            kpis.append(("Upside mediano", f"{m:+.0f}%",
                         "#16a34a" if m > 0 else "#dc2626"))
    except Exception:
        pass
    return (_secbar(title, f"— {len(df)} papéis") + _kpi_bar(kpis)
            + f'<table>{_main_head()}{rows}</table>' + _legenda_scores())


def _legenda_scores() -> str:
    """Legenda explicativa dos scores da tabela principal (Invest./Qual./Value/Safety/Div./
    Consist./Critérios) — reaproveitada em toda tabela que usa _main_head()."""
    return ('<p class="sub" style="margin:4px 0 14px">'
           '<b>Invest.</b> (Investment, 0-100) = combinação ponderada dos 4 blocos abaixo: '
           '35% Qualidade + 30% Value + 20% Safety + 15% Dividendos (pesos re-normalizados '
           'quando um bloco não se aplica, ex.: bancos sem Safety). '
           '<b>Qual.</b> (Quality) = média de ROE, ROIC e margem líquida, comparados ao '
           'restante do universo (setores regulados usam o ROE médio de 5 anos, mais estável). '
           '<b>Value</b> = média de P/L, P/VP, PEG e EV/EBITDA comparados ao universo — quanto '
           'maior, mais descontado o papel. <b>Safety</b> = média de Dívida líq./EBITDA '
           '(cruzada com o ROIC), liquidez corrente e Dívida/Patrimônio (só não-financeiras). '
           '<b>Div.</b> (Dividend) = nota do dividend yield médio de 5 anos frente ao universo. '
           '<b>Consist.</b> = % dos critérios de CRESCIMENTO consistente ao longo de 5 anos '
           '(EBITDA, margem, ROE, ROIC em tendência de alta) que foram atendidos — X/Y entre '
           'parênteses = atendidos/aplicáveis. <b>Critérios</b> = checklist fundamentalista de '
           '8 regras (ROE ≥ Selic, ROE e ROIC ≥ média do setor, margem ≥ 15%, CAGR ≥ setor, '
           'dívida controlada, market cap ≥ R$300mi, sem venda relevante de insider) — X/Y = '
           'atendidos/aplicáveis (alguns não se aplicam a bancos/seguros).</p>')


def _group_block(df: pd.DataFrame, title: str, show_ind: bool = True,
                 show_risco: bool = True, show_agenda: bool = True,
                 show_teto: bool = True) -> str:
    if df is None or df.empty:
        return (f'<h2 style="{_H2}">{title}</h2>'
                f'<p class="empty">Nenhum papel neste grupo hoje.</p>')
    parts = [_main_table(df, title)]
    if show_ind:
        parts.append(_ind_table(df))
    if show_risco:
        parts.append(_risco_table(df))
        parts.append(_stats_table(df))
    if show_teto:
        parts.append(f'<h3 style="{_H3}">Preços-teto (R$)</h3>{_teto_table(df)}')
    if show_agenda and ("prox_resultado" in df.columns or "ex_dividendo" in df.columns):
        parts.append(f'<h3 style="{_H3}">Agenda &amp; dividendos</h3>{_agenda_table(df)}')
    return "".join(parts)


def _defensivas_section(df: pd.DataFrame, thr: float) -> str:
    title = f"Defensivas · não-cíclicas (ciclicidade ≤ {thr:.1f})"
    if df is None or df.empty:
        return (_secbar(title)
                + '<p class="empty">Nenhuma selecionada nesse critério hoje.</p>')
    sub = ('<p class="sub" style="margin:0 0 8px">Recorte das <b>blue chips</b> selecionadas '
           '(BOVA11) em setores menos sensíveis ao ciclo econômico. Small caps ficam fora '
           'desta seção.</p>')
    parts = [_main_table(df, title), sub, _ind_table(df), _risco_table(df), _stats_table(df),
             f'<h3 style="{_H3}">Preços-teto (R$)</h3>{_teto_table(df)}']
    if "prox_resultado" in df.columns or "ex_dividendo" in df.columns:
        parts.append(f'<h3 style="{_H3}">Agenda &amp; dividendos</h3>{_agenda_table(df)}')
    return "".join(parts)


def _dividendos_qualidade_section(df: pd.DataFrame, q_divo: float) -> str:
    """Recorte de ações de ALTA QUALIDADE e BOAS PAGADORAS DE DIVIDENDOS: extraído do
    universo DIVO11 (índice IDIV — dividendos da B3), top `q_divo` por Investment Score
    dentro do próprio DIVO11 (mesmos cortes fundamentalistas e mesmo cálculo das demais
    listas — BOVA11/SMALL11), com o filtro adicional de ter pago DY >= 5% em TODOS os
    últimos 5 anos civis completos (não só na média). Ordenado pelo DY médio de 5a, maior
    primeiro. `df` já vem PRÉ-FILTRADO do screener.py — esta função só formata/exibe."""
    title = f"Qualidade + dividendos (DIVO11 · top {q_divo*100:.0f}% · DY ≥5% em todos os últimos 5 anos)"
    if df is None or df.empty:
        return (_secbar(title)
                + '<p class="empty">Nenhuma selecionada nesse critério hoje.</p>')
    sub = ('<p class="sub" style="margin:0 0 8px">Recorte do universo <b>DIVO11</b> (índice '
           'IDIV — ações de destaque em dividendos da B3): mesmos cortes fundamentalistas '
           f'duros e mesmo cálculo de Investment Score das demais listas, top {q_divo*100:.0f}% '
           'do DIVO11 por Investment Score, MAIS o filtro de ter pago dividend yield ≥ 5% em '
           '<b>cada um</b> dos últimos 5 anos civis completos — não a média (um ano '
           'excepcional não compensa 4 anos fracos). Ordenado pelo DY médio de 5 anos, maior '
           'primeiro.</p>')
    parts = [_main_table(df, title), sub, _ind_table(df), _risco_table(df), _stats_table(df),
             f'<h3 style="{_H3}">Preços-teto (R$)</h3>{_teto_table(df)}']
    if "prox_resultado" in df.columns or "ex_dividendo" in df.columns:
        parts.append(f'<h3 style="{_H3}">Agenda &amp; dividendos</h3>{_agenda_table(df)}')
    return "".join(parts)


def _auvp_section(df: pd.DataFrame, q_auvp: float) -> str:
    """Recorte dos MELHORES ATIVOS do universo AUVP11 (replica o Índice Teva Ações
    Fundamentos — IAFD, metodologia 100% fundamentalista: rentabilidade, eficiência
    operacional e baixa alavancagem, com exclusão setorial de Varejo/Proteína Animal/
    Transporte Aéreo): top `q_auvp` por Investment Score dentro do próprio AUVP11, mesmos
    cortes fundamentalistas duros e mesmo cálculo das demais listas — BOVA11/SMALL11/DIVO11.
    `df` já vem PRÉ-FILTRADO do screener.py — esta função só formata/exibe."""
    title = f"Melhores do AUVP11 (top {q_auvp*100:.0f}% por Investment Score)"
    if df is None or df.empty:
        return (_secbar(title)
                + '<p class="empty">Nenhuma selecionada nesse critério hoje.</p>')
    sub = ('<p class="sub" style="margin:0 0 8px">Recorte do universo <b>AUVP11</b> (replica '
           'o Índice Teva Ações Fundamentos — IAFD, metodologia 100% fundamentalista: '
           'rentabilidade, eficiência operacional e baixa alavancagem consistentes, com '
           'exclusão setorial de Varejo, Proteína Animal e Transporte Aéreo): mesmos cortes '
           f'fundamentalistas duros e mesmo cálculo de Investment Score das demais listas, '
           f'top {q_auvp*100:.0f}% do AUVP11 por Investment Score. Ordenado pelo Investment '
           'Score, maior primeiro.</p>')
    parts = [_main_table(df, title), sub, _ind_table(df), _risco_table(df), _stats_table(df),
             f'<h3 style="{_H3}">Preços-teto (R$)</h3>{_teto_table(df)}']
    if "prox_resultado" in df.columns or "ex_dividendo" in df.columns:
        parts.append(f'<h3 style="{_H3}">Agenda &amp; dividendos</h3>{_agenda_table(df)}')
    return "".join(parts)


def _posicao_table(df: pd.DataFrame) -> str:
    """Mini-tabela de posição da carteira: preço médio, atual e variação."""
    linhas = []
    for tk, r in df.iterrows():
        pm = r.get("preco_medio")
        if pd.isna(pm) if hasattr(pd, "isna") else (pm is None):
            continue
        close = r.get("close")
        var = r.get("var_pm_pct")
        var_s = "—" if pd.isna(var) else f"{float(var):+.1f}%"
        cor = "#16a34a" if (pd.notna(var) and var >= 0) else "#dc2626"
        linhas.append(
            f"<tr><td><b>{tk}</b></td><td>{float(pm):.2f}</td>"
            f"<td>{'' if pd.isna(close) else f'{float(close):.2f}'}</td>"
            f"<td style='color:{cor}'>{var_s}</td></tr>")
    if not linhas:
        return ""
    head = ("<tr><th>Ativo</th><th>Preço médio</th><th>Preço atual</th>"
            "<th>Variação</th></tr>")
    return (f'<h3 style="{_H3}">Posição</h3><table>{head}{"".join(linhas)}</table>')


def _watch_block(df: pd.DataFrame, title: str, sub: str, posicao: bool = False,
                 show_ind: bool = True, show_risco: bool = True,
                 show_agenda: bool = True, tese_max: int = 0,
                 show_teto: bool = True) -> str:
    if df is None or df.empty:
        return (_secbar(title)
                + '<p class="empty">Nenhum papel — crie/edite o arquivo .txt correspondente.</p>')
    parts = [_secbar(title, f"— {len(df)} papéis"),
             f'<p class="sub" style="margin:0 0 8px">{sub}</p>']
    if posicao:
        parts.append(_posicao_table(df))
    parts.append(f'<table>{_main_head()}{"".join(_fmt_row(r) for _, r in df.iterrows())}</table>')
    if show_ind:
        parts.append(_ind_table(df))
    if show_risco:
        parts.append(_risco_table(df))
        parts.append(_stats_table(df))
    if show_teto:
        parts.append(f'<h3 style="{_H3}">Preços-teto (R$)</h3>{_teto_table(df)}')
    if show_agenda and ("prox_resultado" in df.columns or "ex_dividendo" in df.columns):
        parts.append(f'<h3 style="{_H3}">Agenda &amp; dividendos</h3>{_agenda_table(df)}')
    parts.append(_teses_block(df, tese_max=tese_max))          # IA para todos deste bloco
    return "".join(parts)


def build_html(selecionados: pd.DataFrame, hoje: str, meta: dict,
               market: dict = None, mood: dict = None, group_pct: int = None,
               defensive_cyc: float = 0.4, wishlist_df: pd.DataFrame = None,
               carteira_df: pd.DataFrame = None, setor_medians: dict = None,
               macro: dict = None, regime: dict = None, for_pdf: bool = False,
               opcoes: dict = None, divo_df: pd.DataFrame = None,
               q_divo: float = 0.50, auvp_df: pd.DataFrame = None,
               q_auvp: float = 0.70) -> str:
    global _SECTOR_MED
    _SECTOR_MED = setor_medians or {}
    global _PC_ATIVO
    _PC_ATIVO = (opcoes or {}).get("por_ativo") or {}
    global _ALUGUEL
    _ALUGUEL = ((opcoes or {}).get("aluguel") or {}).get("por_ativo") or {}
    global _DEST_OI, _DEST_NEG
    _DEST_OI = (opcoes or {}).get("destaque_oi") or {}
    _DEST_NEG = (opcoes or {}).get("mais_negociada") or {}
    painel = ""
    if macro:
        try:
            from macro import render_panel
            painel = render_panel(macro, regime or {})
        except Exception:
            painel = ""
    resumo_kpi = ""
    try:
        n_tot = len(selecionados) if selecionados is not None else 0
        flag = selecionados.get("oportunidade_grafica") if selecionados is not None else None
        n_sig = (int((flag.astype(str).str.strip().str.lower() != "não").sum())
                 if flag is not None else 0)
        ups = (pd.to_numeric(selecionados.get("teto_upside_pct"), errors="coerce")
               if selecionados is not None else None)
        ups_txt = f"{ups.median():+.0f}%" if (ups is not None and ups.notna().any()) else "—"
        ups_cor = ("#16a34a" if (ups is not None and ups.notna().any() and ups.median() > 0)
                   else "#dc2626")
        resumo_kpi = _kpi_bar([
            ("Selecionados", str(n_tot)),
            ("Com sinal gráfico", str(n_sig), "#16a34a" if n_sig else "#64748b"),
            ("Upside mediano", ups_txt, ups_cor),
        ])
    except Exception:
        resumo_kpi = ""
    topo = (resumo_kpi + painel + _market_block(market, macro, opcoes)
            + _historico_chart((macro or {}).get("historico_bdi"))
            + _ranking_opcoes(opcoes, (macro or {}).get("historico_bdi"))
            + _mood_block(mood, opcoes, (macro or {}).get("historico_bdi")))
    def _suf(g):
        p = group_pct.get(g) if isinstance(group_pct, dict) else group_pct
        return f" ({p}% de maior score)" if p else ""

    # monta o corpo com verbosidade controlável (para caber no limite de ~102 KB do Gmail)
    def assemble(show_ind, show_risco, show_agenda, tese_max=0, show_teto=True):
        watch = ""
        if carteira_df is not None and not carteira_df.empty:
            watch += _watch_block(carteira_df, "Minha carteira",
                                  "Todos os papéis da sua carteira (arquivo carteira.txt), com "
                                  "dados, preços-teto e análise por IA — independentemente dos "
                                  "filtros.", posicao=True, show_ind=show_ind,
                                  show_risco=show_risco, show_agenda=show_agenda,
                                  tese_max=tese_max, show_teto=show_teto)
        if wishlist_df is not None and not wishlist_df.empty:
            watch += _watch_block(wishlist_df, "Wishlist",
                                 "Papéis que você quer acompanhar (arquivo wishlist.txt), com "
                                 "dados, preços-teto e análise por IA — mesmo reprovados no "
                                 "corte.", show_ind=show_ind, show_risco=show_risco,
                                 show_agenda=show_agenda, tese_max=tese_max,
                                 show_teto=show_teto)
        if selecionados is None or selecionados.empty:
            return (topo + '<p class="empty">Nenhum papel passou no corte fundamentalista '
                    'hoje.</p>' + watch), 0
        og = selecionados["oportunidade_grafica"] if "oportunidade_grafica" \
            in selecionados.columns else pd.Series("Não", index=selecionados.index)
        n_graf = int((og != "Não").sum())
        if "grupo" in selecionados.columns:
            grp = selecionados["grupo"].astype(str)
        else:
            grp = selecionados["origem"].astype(str).apply(
                lambda o: "BOVA11" if "BOVA11" in o else "SMALL11")
        bova = selecionados[grp == "BOVA11"]
        small = selecionados[grp == "SMALL11"]
        if "ciclicidade" in selecionados.columns:
            cyc = pd.to_numeric(selecionados["ciclicidade"], errors="coerce")
            # Defensivas = baixa ciclicidade E blue chip (BOVA11); smallcaps ficam fora
            defensivas = selecionados[(cyc <= defensive_cyc) & (grp == "BOVA11")].sort_values(
                "investment", ascending=False)
        else:
            defensivas = selecionados.iloc[0:0]
        # Qualidade + dividendos: já vem PRÉ-FILTRADO do screener.py (universo DIVO11, top
        # q_divo% + DY>=5% em todos os últimos 5 anos) — não recalcula nada aqui.
        div_qual = divo_df if divo_df is not None else selecionados.iloc[0:0]
        nota_trim = ""
        if not (show_ind and show_risco and show_agenda and show_teto):
            faltando = []
            if not show_ind:
                faltando.append("indicadores")
            if not show_risco:
                faltando.append("preço &amp; risco")
            if not show_teto:
                faltando.append("preços-teto")
            if not show_agenda:
                faltando.append("agenda")
            nota_trim = (f'<p class="sub" style="margin:8px 0 0">Para caber no e-mail, as '
                         f'tabelas de <b>{", ".join(faltando)}</b> foram omitidas aqui — o '
                         f'detalhe completo está na <b>planilha anexa</b>.</p>')
        body = (
            topo + nota_trim
            + _group_block(bova, f"BOVA11 · Ibovespa{_suf('BOVA11')}", show_ind, show_risco,
                           show_agenda, show_teto)
            + _group_block(small, f"SMALL11 · Small Caps{_suf('SMALL11')}", show_ind, show_risco,
                           show_agenda, show_teto)
            + _defensivas_section(defensivas, defensive_cyc)
            + _dividendos_qualidade_section(div_qual, q_divo)
            + _auvp_section(auvp_df if auvp_df is not None else selecionados.iloc[0:0], q_auvp)
            + f'<p class="sub" style="margin:14px 0 0">{_TETO_NOTE}</p>'
            + _teses_block(selecionados, tese_max=tese_max)
            + watch
        )
        return body, n_graf

    # PDF (anexo) não tem limite de tamanho: monta o relatório COMPLETO, sem cortes.
    if for_pdf:
        body, n_graf = assemble(True, True, True, 0, True)
        return _wrap(body, hoje, meta, n_graf, pdf=True)

    # tenta cheio; se passar do orçamento, corta na ordem: agenda -> trunca teses -> risco ->
    # preços-teto -> indicadores. Fundamentos são os ÚLTIMOS a cair (tudo está na planilha).
    budget = 100 * 1024
    niveis = ((True, True, True, 0, True), (True, True, False, 0, True),
              (True, True, False, 240, True), (True, True, False, 120, True),
              (True, False, False, 120, True), (True, False, False, 120, False),
              (False, False, False, 120, False))
    for nivel in niveis:
        si, sr, sa, tmax, st = nivel
        body, n_graf = assemble(si, sr, sa, tmax, st)
        html = _wrap(body, hoje, meta, n_graf)
        if len(html.encode("utf-8")) <= budget or nivel == niveis[-1]:
            return html
    return html


def _wrap(body: str, hoje: str, meta: dict, n_graf: int, pdf: bool = False) -> str:
    # no PDF: página CONTÍNUA (sem quebra) — largura igual à A4 landscape, mas altura enorme
    # pra caber o relatório inteiro numa única "folha". Isso evita cortar cabeçalho de tabela
    # longe dos valores quando a tabela atravessa o limite de uma página A4 normal.
    page = ("@page{size:29.7cm 1000cm;margin:1.1cm}"
            "body{font-size:12px}table{font-size:9.5px}.ind table{font-size:8.5px}"
            ".card{box-shadow:none;padding:0}"
            "table{page-break-inside:avoid}tr{page-break-inside:avoid}" if pdf else "")
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{_CSS}{page}</style></head>
<body><div class="card">
<h1>Relatório Quantitativo · Ações B3</h1>
<p class="sub" style="margin:0 0 14px">{_fmt_date(hoje)}</p>
<p style="margin:0 0 6px">Rastreamento sistemático que combina <b>qualidade fundamentalista</b>,
<b>valuation</b> e <b>sinal técnico</b>. As carteiras <b>BOVA11</b> (large caps) e
<b>SMALL11</b> (small caps) são avaliadas de forma independente; apresentam-se abaixo os
papéis de maior <b>Investment Score</b> em cada uma, com a oportunidade gráfica
(Rompimento/Pivô) sinalizada por ativo. {n_graf} papéis com sinal gráfico na data.</p>
{body}
<p class="warn">Material analítico gerado automaticamente. <b>Não constitui recomendação de
investimento.</b> Dados de fontes públicas podem conter erros ou defasagem; "vs. setor" usa
a média do universo varrido; insiders e índices de mercado são <i>best-effort</i>. A planilha
completa (Selecionados + Universo) segue anexada.</p>
<p class="sub" style="margin-top:8px;font-size:11px;color:#94a3b8">Parâmetros: {meta}</p>
</div></body></html>"""


def html_to_pdf(html: str, path: str) -> str | None:
    """Converte o HTML do relatório em PDF (xhtml2pdf, pura Python). Retorna o caminho ou
    None em falha (aí o pipeline segue só com o corpo/planilha)."""
    try:
        from xhtml2pdf import pisa
    except Exception:
        print("[pdf] xhtml2pdf NÃO instalado — rode 'pip install -r requirements.txt' "
              "(ou pip install xhtml2pdf) no workflow. Enviando relatório no corpo.")
        return None
    try:
        with open(path, "wb") as fh:
            status = pisa.CreatePDF(html, dest=fh, encoding="utf-8")
        if status.err:
            print("[pdf] xhtml2pdf reportou erro ao gerar o PDF.")
            return None
        print(f"[pdf] PDF gerado: {path}")
        return path
    except Exception as e:
        print(f"[pdf] falha ao gerar PDF: {e}")
        return None


def build_email_body(hoje: str, meta: dict, market: dict, mood: dict, n_sel: int,
                     n_graf: int, macro: dict = None, regime: dict = None,
                     tem_pdf: bool = True, opcoes: dict = None) -> str:
    """Corpo CURTO do e-mail: panorama macro + resumo de mercado + aviso de anexos.
    O relatório completo (todas as tabelas) vai no PDF anexo — sem risco de corte."""
    global _SECTOR_MED
    global _PC_ATIVO
    _PC_ATIVO = (opcoes or {}).get("por_ativo") or {}
    global _ALUGUEL
    _ALUGUEL = ((opcoes or {}).get("aluguel") or {}).get("por_ativo") or {}
    global _DEST_OI, _DEST_NEG
    _DEST_OI = (opcoes or {}).get("destaque_oi") or {}
    _DEST_NEG = (opcoes or {}).get("mais_negociada") or {}
    painel = ""
    if macro:
        try:
            from macro import render_panel
            painel = render_panel(macro, regime or {})
        except Exception:
            painel = ""
    anexos = ("<b>relatório completo em PDF</b> (todas as tabelas, preços-teto e teses), "
              "além da planilha (.xlsx) e do .csv" if tem_pdf
              else "a planilha (.xlsx) e o .csv")
    corpo = (
        f'<h1>Relatório Quantitativo · Ações B3</h1>'
        f'<p class="sub" style="margin:0 0 14px">{_fmt_date(hoje)}</p>'
        f"{painel}{_market_block(market, macro, opcoes)}"
        f"{_historico_chart((macro or {}).get('historico_bdi'))}"
        f"{_ranking_opcoes(opcoes, (macro or {}).get('historico_bdi'))}"
        f'<p style="margin:12px 0 6px"><b>{n_sel} papéis</b> passaram no corte '
        f'fundamentalista hoje ({n_graf} com oportunidade gráfica). O detalhamento — '
        f'fundamentos, preço &amp; risco e preços-teto por papel — está no {anexos}, '
        f'em anexo.</p>'
        f'<p class="warn">Material analítico automático. <b>Não é recomendação de '
        f'investimento.</b> Dados públicos podem ter erros/defasagem.</p>'
        f'<p class="sub" style="font-size:11px;color:#94a3b8">Parâmetros: {meta}</p>')
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{_CSS}</style></head>
<body><div class="card">{corpo}</div></body></html>"""


# ---------------- exportação da planilha ----------------
def export_xlsx(full: pd.DataFrame, selecionados: pd.DataFrame, path: str) -> str:
    """Gera a planilha com abas 'Selecionados' (passam nos critérios) e 'Universo' (todos).

    Ambas trazem a coluna 'oportunidade_grafica' (Rompimento | Pivô de alta | Não).
    """
    with pd.ExcelWriter(path, engine="openpyxl") as xls:
        (selecionados if not selecionados.empty else full.head(0)).to_excel(
            xls, sheet_name="Selecionados")
        full.to_excel(xls, sheet_name="Universo")
    return path


# ---------------- envio ----------------
def _attach(msg: EmailMessage, path: str):
    if not path or not os.path.exists(path):
        return
    ctype, _ = mimetypes.guess_type(path)
    maintype, subtype = (ctype.split("/", 1) if ctype else
                         ("application", "octet-stream"))
    with open(path, "rb") as fh:
        msg.add_attachment(fh.read(), maintype=maintype, subtype=subtype,
                           filename=os.path.basename(path))


def send_report_email(subject: str, html: str, attachments: list[str],
                      cfg: Optional[MailConfig] = None) -> bool:
    cfg = cfg or config_from_env()
    if not cfg.enabled:
        print("E-mail não configurado (defina SMTP_USER/SMTP_PASS/MAIL_TO) — envio pulado.")
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg.mail_from
    msg["To"] = ", ".join(cfg.recipients)
    msg.set_content("Seu leitor não suporta HTML. Veja a planilha anexa.")
    msg.add_alternative(html, subtype="html")
    for a in attachments or []:
        _attach(msg, a)

    context = ssl.create_default_context()
    if int(cfg.port) == 587:                       # STARTTLS
        with smtplib.SMTP(cfg.host, cfg.port, timeout=60) as srv:
            srv.ehlo()
            srv.starttls(context=context)
            srv.ehlo()
            srv.login(cfg.user, cfg.password)
            srv.send_message(msg)
    else:                                          # SSL direto (465, padrão)
        with smtplib.SMTP_SSL(cfg.host, cfg.port, context=context, timeout=60) as srv:
            srv.login(cfg.user, cfg.password)
            srv.send_message(msg)
    print(f"E-mail enviado para: {', '.join(cfg.recipients)}")
    return True
