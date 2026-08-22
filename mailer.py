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
.warn{color:#6b7280;font-size:12px;margin-top:16px}
.empty{color:#6b7280;font-style:italic}
"""


def _fmt_row(r) -> str:
    flag = str(r.get("oportunidade_grafica", "") or "")
    if not flag:  # compat: deriva de strategy/breakout se a flag não veio
        strat = str(r.get("strategy", "") or "")
        flag = strat if (r.get("breakout") and strat) else "Não"
    cls = "romp" if "Romp" in flag else ("piv" if "Piv" in flag else "nao")
    tag = f'<span class="tag {cls}">{flag}</span>'
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
        f"<td>{r.get('setor','')}</td><td>{num(r.get('investment'),0)}</td>"
        f"<td>{num(r.get('quality'),0)}</td><td>{num(r.get('value'),0)}</td>"
        f"<td>{num(r.get('safety'),0)}</td><td>{num(r.get('dividend'),0)}</td>"
        f"<td>{cons_cell}</td>"
        f"<td>{crit}</td><td>{tag}</td><td>{r.get('trend','')}</td>"
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


def _market_block(m: dict) -> str:
    if not m:
        return ""
    rows = [f"<tr><td><b>Selic</b></td><td>{m.get('selic', float('nan')):.2f}% a.a.</td>"
            f"<td>—</td></tr>"]
    for name, tup in (m.get("indices") or {}).items():
        ytd, mtd = (tup if tup else (math.nan, math.nan))
        rows.append(f"<tr><td><b>{name}</b></td><td>{_ret_str(ytd)}</td>"
                    f"<td>{_ret_str(mtd)}</td></tr>")
    rows.append('<tr><td><b>Fluxo estrangeiro</b></td>'
                '<td colspan="2">n/d — sem fonte automática (B3)</td></tr>')
    rows.append('<tr><td><b>Opções mais negociadas</b></td>'
                '<td colspan="2">n/d — sem fonte automática (B3)</td></tr>')
    head = '<tr><th>Indicador</th><th>No ano</th><th>No mês</th></tr>'
    return (f'<h2 style="{_H2}">Resumo de mercado</h2>'
            f'<table>{head}{"".join(rows)}</table>')


def _breadth_bar(b: dict) -> str:
    """Barra empilhada verde/cinza/vermelho (via tabela; renderiza no PDF e no e-mail)."""
    def seg(pct, cor, txt_cor):
        if not pct:
            return ""
        return (f'<td style="width:{pct}%;background:{cor};color:{txt_cor};font-size:9px;'
                f'text-align:center;padding:1px 0">{pct}%</td>')
    cells = (seg(b["alta"], "#16a34a", "#fff") + seg(b["lateral"], "#e2e8f0", "#334155")
             + seg(b["baixa"], "#dc2626", "#fff"))
    return (f'<table style="width:120px;border-collapse:collapse;table-layout:fixed">'
            f'<tr>{cells}</tr></table>')


def _pc_cell(pc) -> str:
    """Formata o Put/Call ratio com cor (>1.2 baixista/vermelho, <0.8 altista/verde)."""
    if pc is None or (isinstance(pc, float) and math.isnan(pc)):
        return '<span class="sub">n/d</span>'
    cor = "#dc2626" if pc >= 1.2 else ("#16a34a" if pc <= 0.8 else "#334155")
    return f'<span style="color:{cor}">{pc:.2f}</span>'


def _mood_block(mood: dict, opcoes: dict = None) -> str:
    if not mood or (not mood.get("indices") and not mood.get("setores")):
        return ""
    por_setor = (opcoes or {}).get("por_setor") or {}
    tem_pc = bool(por_setor)

    def linha(nome, b, pc=None, bold=False):
        rot = f"<b>{nome}</b>" if bold else nome
        txt = (f'{b["alta"]}% alta · {b["lateral"]}% lat · {b["baixa"]}% baixa '
               f'<span class="sub">(n={b["n"]})</span>')
        pc_td = f"<td class='r'>{_pc_cell(pc)}</td>" if tem_pc else ""
        return (f"<tr><td>{rot}</td><td>{_breadth_bar(b)}</td>"
                f"<td>{txt}</td>{pc_td}</tr>")

    rows = []
    for k, b in (mood.get("indices") or {}).items():
        rows.append(linha(k, b, bold=True))
    for setor, b in sorted((mood.get("setores") or {}).items(),
                           key=lambda kv: -kv[1]["alta"]):
        pc = (por_setor.get(setor) or {}).get("pc_ratio")
        rows.append(linha(setor, b, pc=pc))

    pc_head = "<th class='r'>P/C opç.</th>" if tem_pc else ""
    head = (f'<tr><th>Grupo / Setor</th><th>Tendência</th>'
            f'<th>MM21</th>{pc_head}</tr>')
    termo = ""
    merc = (opcoes or {}).get("mercado") or {}
    if merc.get("pc_ratio") is not None and not (isinstance(merc["pc_ratio"], float)
                                                 and math.isnan(merc["pc_ratio"])):
        vies = ("defensivo/baixista" if merc["pc_ratio"] >= 1.2
                else "altista" if merc["pc_ratio"] <= 0.8 else "neutro")
        termo = (f'<p style="margin:6px 0 4px"><b>Termômetro de opções (Put/Call):</b> '
                 f'mercado {_pc_cell(merc["pc_ratio"])} — viés {vies}. '
                 f'<span class="sub">Volume de puts ÷ calls no pregão (COTAHIST/B3). '
                 f'&gt;1 = mais proteção/baixa; &lt;1 = mais aposta em alta.</span></p>')
    return (f'<h2 style="{_H2}">Humor do mercado</h2>'
            f'<p class="sub" style="margin:0 0 6px">Percentual dos papéis do universo '
            f'(BOVA11 + SMALL11) em alta/lateral/baixa pela média móvel de 21 pregões'
            f'{", com o Put/Call ratio por setor" if tem_pc else ""}.</p>'
            f'{termo}<table>{head}{"".join(rows)}</table>')


_SECTOR_MED = {}
_PC_ATIVO = {}                      # raiz do ticker -> {pc_ratio, ...} (opções)


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
            "<th class='r'>Corr.Ibov</th><th class='r'>P/C opç.</th></tr>")
    linhas = []
    for tk, r in df.iterrows():
        linhas.append(
            f"<tr><td><b>{tk}</b></td>{cell(r.get('close'))}"
            f"{cell(r.get('min_52s'))}{cell(r.get('max_52s'))}"
            f"{cell(r.get('dist_min52'), pct=True, sign=True)}"
            f"{cell(r.get('dist_mm100'), pct=True, sign=True)}"
            f"{num_sign(r.get('beta'))}{num_sign(r.get('corr_ibov'))}"
            f"<td class='r'>{_pc_cell((_PC_ATIVO.get(_raiz_tk(tk)) or {}).get('pc_ratio'))}</td></tr>")
    leg = ('<p class="sub" style="margin:4px 0 0">Preço, Mín 52s e Máx 52s em R$ (mínima e '
           'máxima de 52 semanas). vs Min52 = distância da mínima de 52 semanas; vs MM100 = '
           'posição vs média de 100 dias. <span style="color:#16a34a">Verde/+</span> acima, '
           '<span style="color:#dc2626">vermelho/−</span> abaixo. Beta e correlação vs '
           'Ibovespa (retornos diários, ~1 ano; <span style="color:#16a34a">+</span> na '
           'mesma direção do índice, <span style="color:#dc2626">−</span> na direção '
           'oposta). P/C opç. = Put/Call ratio do ativo (volume de puts ÷ calls no pregão, '
           'COTAHIST/B3): <span style="color:#dc2626">≥1,2</span> viés baixista, '
           '<span style="color:#16a34a">≤0,8</span> altista.</p>')
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
        return f'<h2 style="{_H2}">{title}</h2><p class="empty">Nenhum papel neste grupo.</p>'
    rows = "".join(_fmt_row(r) for _, r in df.iterrows())
    return (f'<h2 style="{_H2}">{title} — {len(df)} papéis</h2>'
            f'<table>{_main_head()}{rows}</table>')


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
    if show_teto:
        parts.append(f'<h3 style="{_H3}">Preços-teto (R$)</h3>{_teto_table(df)}')
    if show_agenda and ("prox_resultado" in df.columns or "ex_dividendo" in df.columns):
        parts.append(f'<h3 style="{_H3}">Agenda &amp; dividendos</h3>{_agenda_table(df)}')
    return "".join(parts)


def _defensivas_section(df: pd.DataFrame, thr: float) -> str:
    title = f"Defensivas · não-cíclicas (ciclicidade ≤ {thr:.1f})"
    if df is None or df.empty:
        return (f'<h2 style="{_H2}">{title}</h2>'
                f'<p class="empty">Nenhuma selecionada nesse critério hoje.</p>')
    sub = ('<p class="sub" style="margin:0 0 8px">Recorte das selecionadas (BOVA11 + SMALL11 '
           'juntas) em setores menos sensíveis ao ciclo econômico. Indicadores e preços-teto '
           'destes papéis estão nas seções BOVA11/SMALL11 acima.</p>')
    rows = "".join(_fmt_row(r) for _, r in df.iterrows())
    return (f'<h2 style="{_H2}">{title} — {len(df)} papéis</h2>{sub}'
            f'<table>{_main_head()}{rows}</table>')


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
        return (f'<h2 style="{_H2}">{title}</h2>'
                f'<p class="empty">Nenhum papel — crie/edite o arquivo .txt correspondente.</p>')
    parts = [f'<h2 style="{_H2}">{title} — {len(df)} papéis</h2>',
             f'<p class="sub" style="margin:0 0 8px">{sub}</p>']
    if posicao:
        parts.append(_posicao_table(df))
    parts.append(f'<table>{_main_head()}{"".join(_fmt_row(r) for _, r in df.iterrows())}</table>')
    if show_ind:
        parts.append(_ind_table(df))
    if show_risco:
        parts.append(_risco_table(df))
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
               opcoes: dict = None) -> str:
    global _SECTOR_MED
    _SECTOR_MED = setor_medians or {}
    global _PC_ATIVO
    _PC_ATIVO = (opcoes or {}).get("por_ativo") or {}
    painel = ""
    if macro:
        try:
            from macro import render_panel
            painel = render_panel(macro, regime or {})
        except Exception:
            painel = ""
    topo = painel + _market_block(market) + _mood_block(mood, opcoes)
    suf = f" ({group_pct}% de maior score)" if group_pct else ""

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
            defensivas = selecionados[cyc <= defensive_cyc].sort_values(
                "investment", ascending=False)
        else:
            defensivas = selecionados.iloc[0:0]
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
            + _group_block(bova, f"BOVA11 · Ibovespa{suf}", show_ind, show_risco,
                           show_agenda, show_teto)
            + _group_block(small, f"SMALL11 · Small Caps{suf}", show_ind, show_risco,
                           show_agenda, show_teto)
            + _defensivas_section(defensivas, defensive_cyc)
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
    # no PDF: página deitada (A4 landscape) e fonte de tabela menor p/ caber tabelas largas
    page = ("@page{size:A4 landscape;margin:1.1cm}"
            "body{font-size:12px}table{font-size:9.5px}.ind table{font-size:8.5px}"
            ".card{box-shadow:none;padding:0}" if pdf else "")
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
        f'{painel}{_market_block(market)}{_mood_block(mood, opcoes)}'
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
