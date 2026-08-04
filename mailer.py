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
        host=os.getenv("SMTP_HOST", "smtp.gmail.com"),
        port=int(os.getenv("SMTP_PORT", "465")),
        user=os.getenv("SMTP_USER", ""),
        password=os.getenv("SMTP_PASS", ""),
        mail_to=os.getenv("MAIL_TO", ""),
        mail_from=os.getenv("MAIL_FROM", ""),
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
    return (
        f"<tr><td><b>{r.name}</b></td><td>{r.get('origem','')}</td>"
        f"<td>{r.get('setor','')}</td><td>{num(r.get('investment'),0)}</td>"
        f"<td>{num(r.get('quality'),0)}</td><td>{num(r.get('value'),0)}</td>"
        f"<td>{num(r.get('safety'),0)}</td><td>{num(r.get('dividend'),0)}</td>"
        f"<td>{tag}</td><td>{r.get('trend','')}</td>"
        f"<td>{num(r.get('close'),2)}</td></tr>"
    )


def build_html(selecionados: pd.DataFrame, hoje: str, meta: dict) -> str:
    if selecionados is None or selecionados.empty:
        body = '<p class="empty">Nenhum papel passou no corte fundamentalista hoje.</p>'
        n_graf = 0
    else:
        n_graf = int((selecionados.get("oportunidade_grafica", "Não") != "Não").sum())
        head = ("<tr><th>Ativo</th><th>Origem</th><th>Setor</th><th>Invest.</th>"
                "<th>Qual.</th><th>Value</th><th>Safety</th><th>Div.</th>"
                "<th>Oport. gráfica</th><th>Tendência</th><th>Preço</th></tr>")
        rows = "".join(_fmt_row(r) for _, r in selecionados.iterrows())
        body = f"<table>{head}{rows}</table>"
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{_CSS}</style></head>
<body><div class="card">
<h1>Screener B3 — {hoje}</h1>
<p class="sub">Papéis que atendem aos <b>critérios fundamentalistas</b>, com a
<b>oportunidade gráfica</b> sinalizada por papel (Rompimento / Pivô de alta / Não).
{n_graf} com sinal gráfico hoje. Parâmetros: {meta}</p>
{body}
<p class="warn">Material analítico gerado automaticamente. <b>Não é recomendação de
investimento.</b> Preços e fundamentos vêm de fontes públicas e podem conter erros ou
defasagem. A oportunidade gráfica é um sinal de <b>timing</b>, não de qualidade. A planilha
completa (Selecionados + Universo) segue anexada.</p>
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
    with smtplib.SMTP_SSL(cfg.host, cfg.port, context=context) as srv:
        srv.login(cfg.user, cfg.password)
        srv.send_message(msg)
    print(f"E-mail enviado para: {', '.join(cfg.recipients)}")
    return True
