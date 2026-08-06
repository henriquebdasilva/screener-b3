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
            "<th>Graham</th><th>Lynch</th><th>Média</th><th>Mediana</th>"
            "<th>Ajust.</th><th>Upside*</th></tr>")
    rows = []
    for _, r in df.iterrows():
        up = r.get("teto_upside_pct")
        up_s = f"{float(up):+.0f}%" if pd.notna(up) else "—"
        rows.append(
            f"<tr><td><b>{r.name}</b></td><td>{num(r.get('close'))}</td>"
            f"<td>{num(r.get('teto_bazin'))}</td><td>{num(r.get('teto_gordon'))}</td>"
            f"<td>{num(r.get('teto_dcf'))}</td><td>{num(r.get('teto_graham'))}</td>"
            f"<td>{num(r.get('teto_lynch'))}</td><td>{num(r.get('teto_medio'))}</td>"
            f"<td>{num(r.get('teto_mediana'))}</td>"
            f"<td><b>{num(r.get('teto_ajustado'))}</b></td><td>{up_s}</td></tr>")
    return f"<table>{head}{''.join(rows)}</table>"


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


def _teses_block(df: pd.DataFrame) -> str:
    itens = []
    for _, r in df.iterrows():
        t = str(r.get("tese_ia") or "").strip()
        if t:
            itens.append(f'<p style="margin:8px 0"><b>{r.name}</b> — {t}</p>')
    if not itens:
        return ""
    return (
        '<h2 style="font-size:15px;margin:20px 0 6px">Teses (geradas por IA)</h2>'
        '<p class="sub" style="margin:0 0 8px">Resumo automático ancorado apenas nos '
        'números deste screener (aprovados = fundamentos + rompimento). Pode conter erros; '
        '<b>não é recomendação</b>.</p>' + "".join(itens))


_H2 = 'font-size:15px;margin:20px 0 6px'


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


def _mood_block(mood: dict) -> str:
    if not mood or (not mood.get("indices") and not mood.get("setores")):
        return ""

    def bar(b):
        return (f'{b["alta"]}% em alta · {b["lateral"]}% lateral · '
                f'{b["baixa"]}% em baixa <span class="sub">(n={b["n"]})</span>')
    rows = []
    for k, b in (mood.get("indices") or {}).items():
        rows.append(f"<tr><td><b>{k}</b></td><td>{bar(b)}</td></tr>")
    for setor, b in sorted((mood.get("setores") or {}).items(),
                           key=lambda kv: -kv[1]["alta"]):
        rows.append(f"<tr><td>{setor}</td><td>{bar(b)}</td></tr>")
    head = '<tr><th>Grupo / Setor</th><th>Tendência dos papéis (MM21)</th></tr>'
    return (f'<h2 style="{_H2}">Humor do mercado</h2>'
            f'<p class="sub" style="margin:0 0 8px">Percentual dos papéis do universo '
            f'(BOVA11 + SMALL11) em alta/lateral/baixa pela média móvel de 21 pregões.</p>'
            f'<table>{head}{"".join(rows)}</table>')


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


def build_html(selecionados: pd.DataFrame, hoje: str, meta: dict,
               market: dict = None, mood: dict = None) -> str:
    topo = _market_block(market) + _mood_block(mood)
    if selecionados is None or selecionados.empty:
        body = topo + '<p class="empty">Nenhum papel passou no corte hoje.</p>'
        n_graf = 0
    else:
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
        agenda = ""
        if "prox_resultado" in selecionados.columns or "ex_dividendo" in selecionados.columns:
            agenda = (f'<h2 style="{_H2}">Agenda &amp; dividendos</h2>'
                      + _agenda_table(selecionados))
        body = (
            topo
            + _main_table(bova, "BOVA11 / Ibovespa (top 30%)")
            + _main_table(small, "SMALL11 / Small Caps (top 30%)")
            + f'<h2 style="{_H2}">Preços-teto (R$)</h2>'
            + '<p class="sub" style="margin:0 0 8px">Cinco métodos — Bazin (yield-alvo '
              '= Selic), Gordon (dividendos), DCF (lucros), Graham e Lynch/PEGY — mais a '
              '<b>Média</b> e a <b>Mediana</b>. <b>Ajust.</b> = mediana com desconto de '
              'segurança; *Upside vs. o Ajust. Bazin e Gordon usam o <b>DY médio de ~5 '
              'anos</b>. Método muito fora (além de ~2,5× a mediana) é descartado; em '
              'bancos/seguros, Graham e Lynch também. Estimativas — não são gatilho.</p>'
            + _teto_table(selecionados)
            + agenda
            + _teses_block(selecionados)
        )
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{_CSS}</style></head>
<body><div class="card">
<h1>Screener B3 — {hoje}</h1>
<p class="sub">Listas <b>BOVA11</b> e <b>SMALL11</b> separadas, com os <b>30% melhores</b> por
Investment Score em cada. Corte fundamentalista + oportunidade gráfica (Rompimento/Pivô/Não)
por papel. {n_graf} com sinal gráfico hoje. Parâmetros: {meta}</p>
{body}
<p class="warn">Material analítico gerado automaticamente. <b>Não é recomendação de
investimento.</b> Dados de fontes públicas podem conter erros/defasagem; "vs setor" usa a
média do universo varrido; insiders e índices são best-effort. A planilha completa segue
anexada.</p>
</div></body></html>"""


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
