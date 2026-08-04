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
_PROMPT = """Você é um analista fundamentalista sênior. Escreva uma análise de investimento
de 8 a 10 frases, em português, sobre o papel {ticker}, com base EXCLUSIVAMENTE nos dados
abaixo.

COMO ESCREVER (correlacione os indicadores — não os liste soltos):
- Posicione cada indicador relevante FRENTE À MÉDIA DO SETOR informada entre parênteses
  (acima/abaixo dos pares) e diga o que isso sugere.
- Relacione qualidade × preço (ROE/ROIC altos convivem com P/L e P/VP baixos?),
  rentabilidade × endividamento (o retorno vem com alavancagem controlada?) e
  dividendo × sustentabilidade (o DY é coerente com o lucro, o payout e a dívida?).
- Comente o crescimento (CAGR vs setor) e o que o checklist de critérios revela.
- Trate a faixa de preço-teto (métodos, média/mediana e upside) como referência de
  valuation — apontando dispersão entre os métodos, se houver.
- Encerre com um balanço claro de PRÓS e CONTRAS que os dados sugerem.

REGRAS OBRIGATÓRIAS:
- Use SOMENTE os dados abaixo. NÃO use conhecimento externo nem memória sobre a empresa.
- NÃO invente fatos, notícias, eventos, números ou preço-alvo além dos fornecidos.
- NÃO recomende comprar, vender ou manter. Seja objetivo, neutro e analítico.
- "Média do setor" = média dos pares DESTE screener (amostra limitada), não do setor inteiro.

DADOS:
{dados}

Responda apenas com a análise."""


def _v(x, d=2):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    if isinstance(x, float):
        return round(x, d)
    return x


def _cmp(val, med, unit="", d=1):
    """'12.3% (setor 9.0%, acima)' — ou None se não houver valor."""
    v = _v(val, d)
    if v is None:
        return None
    s = f"{v}{unit}"
    m = _v(med, d)
    if m is not None:
        rel = "acima" if float(val) >= float(med) else "abaixo"
        s += f" (setor {m}{unit}, {rel})"
    return s


def _flag(x):
    return "n/d" if x is None or (isinstance(x, float) and pd.isna(x)) else ("Sim" if x else "Não")


def _fmt_metrics(r: pd.Series) -> str:
    L = []
    def add(label, s):
        if s is not None:
            L.append(f"- {label}: {s}")

    add("Setor", r.get("setor"))
    add("Scores (0-100)", f"Investment {_v(r.get('investment'),0)} | Quality "
        f"{_v(r.get('quality'),0)} | Value {_v(r.get('value'),0)} | Safety "
        f"{_v(r.get('safety'),0)} | Dividend {_v(r.get('dividend'),0)}")
    add("ROE", _cmp(r.get("roe"), r.get("roe_setor_med"), "%"))
    add("ROIC", _cmp(r.get("roic"), r.get("roic_setor_med"), "%"))
    add("Margem líquida", None if _v(r.get("mrg_liq")) is None else f"{_v(r.get('mrg_liq'))}%")
    add("P/L", _v(r.get("pl")))
    add("P/VP", _v(r.get("pvp")))
    add("PEG", _v(r.get("peg")))
    add("EV/EBITDA", _v(r.get("ev_ebitda")))
    add("Dív.Líq/EBITDA", _cmp(r.get("div_liq_ebitda"), r.get("div_setor_med"), "", 2))
    add("Dív/Patrimônio", _v(r.get("div_patrim")))
    add("Liquidez corrente", _v(r.get("liq_corr")))
    add("CAGR receita 5a", _cmp(r.get("cresc_5a"), r.get("cagr_setor_med"), "%"))
    add("DY", None if _v(r.get("dy")) is None else f"{_v(r.get('dy'))}%")
    add("Market cap (R$)", _v(r.get("market_cap"), 0))
    # checklist item a item
    chk = (f"ROE≥Selic {_flag(r.get('roe_ge_selic'))} | ROE≥setor "
           f"{_flag(r.get('roe_ge_setor'))} | ROIC≥setor {_flag(r.get('roic_ge_setor'))} | "
           f"margem≥15% {_flag(r.get('margem_ge_15'))} | CAGR≥setor "
           f"{_flag(r.get('cagr_ge_setor'))} | Dív.Líq/EBITDA<3 e ≤setor "
           f"{_flag(r.get('divida_ok'))} | market cap≥300mi {_flag(r.get('marketcap_ok'))} | "
           f"sem venda de insiders {_flag(r.get('insider_ok'))}")
    add("Checklist", chk)
    add("Critérios atendidos", None if _v(r.get("criterios_ok")) is None else
        f"{int(r.get('criterios_ok'))} de {int(r.get('criterios_aplicaveis'))}")
    add("Sinal gráfico", r.get("oportunidade_grafica"))
    add("Tendência", r.get("trend"))
    add("Preço atual (R$)", _v(r.get("close")))
    add("Preços-teto (R$)", f"Bazin {_v(r.get('teto_bazin'))} | Gordon "
        f"{_v(r.get('teto_gordon'))} | DCF {_v(r.get('teto_dcf'))} | Graham "
        f"{_v(r.get('teto_graham'))} | Lynch {_v(r.get('teto_lynch'))} | Média "
        f"{_v(r.get('teto_medio'))} | Mediana {_v(r.get('teto_mediana'))} | Upside vs "
        f"mediana {_v(r.get('teto_upside_pct'),1)}%")
    add("Próximo resultado", None if str(r.get("prox_resultado") or "n/d") == "n/d"
        else r.get("prox_resultado"))
    add("Ex-dividendo", None if str(r.get("ex_dividendo") or "n/d") == "n/d" else
        f"{r.get('ex_dividendo')} ({r.get('ex_tipo')})")
    return "\n".join(L)


def _gemini(prompt: str, api_key: str, model: str, timeout: int = 40) -> Optional[str]:
    import requests
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent?key={api_key}")
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 700},
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
