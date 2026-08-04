# -*- coding: utf-8 -*-
"""
Enriquecimento opcional dos papéis:

  • AGENDA (via yfinance): data do próximo resultado e data ex-dividendo (última/próxima).
    Cobertura da B3 no Yahoo é irregular -> devolve "n/d" quando não houver.

  • TESE POR IA (Gemini Flash, free tier): um parágrafo curto ANCORADO EXCLUSIVAMENTE nos
    números que o app já coletou. O prompt proíbe inventar fatos/notícias/preço-alvo e
    proíbe recomendar. Só roda se GEMINI_API_KEY estiver definido; tem cache em disco e
    limite de chamadas por execução (respeita a cota do free tier). Roda apenas para os
    papéis indicados (aqui, os aprovados).

Nada aqui é recomendação de investimento. A tese é um resumo automático e pode conter erros.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import time
from typing import Optional

import pandas as pd

from universe import to_yahoo


# ----------------- AGENDA (yfinance) -----------------
def _as_date(x):
    try:
        d = pd.to_datetime(x, errors="coerce")
        if pd.isna(d):
            return None
        return d.date() if hasattr(d, "date") else d
    except Exception:
        return None


def get_events(ticker: str) -> dict:
    """Próximo resultado e ex-dividendo via yfinance (defensivo)."""
    out = {"prox_resultado": None, "ex_dividendo": None, "ex_tipo": ""}
    try:
        import yfinance as yf
        t = yf.Ticker(to_yahoo(ticker))
        hoje = dt.date.today()

        cal = None
        try:
            cal = t.calendar
        except Exception:
            cal = None

        def _get(cal, key):
            if cal is None:
                return None
            if isinstance(cal, dict):
                return cal.get(key)
            try:
                if key in cal.index:      # DataFrame (versões antigas)
                    return cal.loc[key].tolist()
            except Exception:
                pass
            return None

        # próximo resultado
        ed = _get(cal, "Earnings Date")
        dates = [d for d in (map(_as_date, ed if isinstance(ed, (list, tuple)) else [ed]))
                 if d] if ed is not None else []
        fut = sorted([d for d in dates if d >= hoje])
        if fut:
            out["prox_resultado"] = fut[0].isoformat()
        elif dates:
            out["prox_resultado"] = sorted(dates)[-1].isoformat()

        # ex-dividendo
        exd = _get(cal, "Ex-Dividend Date")
        exd = exd[0] if isinstance(exd, (list, tuple)) and exd else exd
        exdate = _as_date(exd)
        if exdate is None:
            try:
                div = t.dividends
                if div is not None and len(div):
                    exdate = _as_date(div.index[-1])
            except Exception:
                pass
        if exdate:
            out["ex_dividendo"] = exdate.isoformat()
            out["ex_tipo"] = "próxima" if exdate >= hoje else "última"
    except Exception:
        pass
    return out


# ----------------- TESE POR IA (Gemini) -----------------
_PROMPT = """Você é um analista fundamentalista. Com base EXCLUSIVAMENTE nos dados abaixo,
escreva em português uma tese de investimento curta (2 a 4 frases).

REGRAS OBRIGATÓRIAS:
- NÃO use conhecimento externo nem memória sobre a empresa.
- NÃO invente fatos, notícias, eventos, números, preço-alvo ou datas.
- NÃO recomende comprar, vender ou manter. Descreva prós e contras que OS DADOS sugerem.
- Se algo não estiver nos dados, não comente. Seja objetivo e neutro.

DADOS DO PAPEL {ticker}:
{dados}

Responda apenas com o parágrafo da tese."""


def _fmt_metrics(row: pd.Series) -> str:
    campos = [
        ("Setor", "setor"), ("Investment Score", "investment"), ("Quality", "quality"),
        ("Value", "value"), ("Safety", "safety"), ("Dividend", "dividend"),
        ("P/L", "pl"), ("P/VP", "pvp"), ("DY %", "dy"), ("ROE %", "roe"),
        ("ROIC %", "roic"), ("Margem líquida %", "mrg_liq"),
        ("Dív.Líq/EBITDA", "div_liq_ebitda"), ("Liquidez corrente", "liq_corr"),
        ("Cresc. receita 5a %", "cresc_5a"), ("Critérios atendidos", "criterios_ok"),
        ("Oportunidade gráfica", "oportunidade_grafica"), ("Tendência", "trend"),
        ("Preço", "close"), ("Teto médio R$", "teto_medio"),
        ("Teto mediana R$", "teto_mediana"), ("Upside vs mediana %", "teto_upside_pct"),
    ]
    linhas = []
    for label, key in campos:
        v = row.get(key)
        if v is None or (isinstance(v, float) and pd.isna(v)):
            continue
        if isinstance(v, float):
            v = round(v, 2)
        linhas.append(f"- {label}: {v}")
    return "\n".join(linhas)


def _gemini(prompt: str, api_key: str, model: str, timeout: int = 40) -> Optional[str]:
    import requests
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent?key={api_key}")
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 260},
    }
    r = requests.post(url, json=body, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    return data["candidates"][0]["content"]["parts"][0]["text"].strip()


def generate_theses(df: pd.DataFrame, hoje: str, outdir: str = "reports") -> dict:
    """Gera teses (ancoradas nos dados) para os papéis em df. Retorna {ticker: texto}.

    Requer env GEMINI_API_KEY. Env opcionais: GEMINI_MODEL (default gemini-2.0-flash),
    AI_MAX_CALLS (default 40). Usa cache em reports/cache_tese.json.
    """
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key or df is None or df.empty:
        if not api_key:
            print("Tese por IA desativada (defina GEMINI_API_KEY) — teses ficam 'n/d'.")
        return {}

    model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash").strip()
    max_calls = int(os.getenv("AI_MAX_CALLS", "40"))
    cache_path = os.path.join(outdir, "cache_tese.json")
    try:
        cache = json.load(open(cache_path, encoding="utf-8"))
    except Exception:
        cache = {}

    out, calls = {}, 0
    for tk in df.index:
        key = f"{tk}:{hoje}"
        if key in cache:
            out[tk] = cache[key]
            continue
        if calls >= max_calls:
            out[tk] = ""
            continue
        prompt = _PROMPT.format(ticker=tk, dados=_fmt_metrics(df.loc[tk]))
        try:
            txt = _gemini(prompt, api_key, model)
            out[tk] = txt or ""
            cache[key] = out[tk]
            calls += 1
            time.sleep(4.0)          # respeita rate limit do free tier
        except Exception as e:
            print(f"  [tese] {tk}: {e}")
            out[tk] = ""
    try:
        os.makedirs(outdir, exist_ok=True)
        json.dump(cache, open(cache_path, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:
        pass
    if calls:
        print(f"Teses geradas por IA: {calls} (modelo {model}).")
    return out
