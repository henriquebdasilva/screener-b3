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

# Suba esta versão sempre que o prompt/lógica da tese mudar: invalida o cache antigo
# automaticamente (o usuário não precisa apagar reports/cache_tese.json).
PROMPT_VERSION = "v2"


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
_PROMPT = """Você é um analista fundamentalista sênior escrevendo em português do Brasil.
Escreva uma análise de investimento fluida e bem desenvolvida, de 8 a 10 frases, sobre o
papel {ticker}, baseada SOMENTE nos dados fornecidos no fim.

Correlacione os indicadores (não os liste): posicione cada número relevante frente à média
do setor informada entre parênteses (acima/abaixo dos pares) e diga o que sugere; relacione
qualidade × preço (ROE/ROIC altos convivem com P/L e P/VP baixos?), rentabilidade ×
endividamento e dividendo × sustentabilidade (o DY é coerente com lucro, payout e dívida?);
comente o crescimento (CAGR vs setor) e o que o checklist de critérios revela; trate a faixa
de preço-teto (métodos, média/mediana e upside) como referência de valuation, apontando
dispersão entre os métodos. Encerre com um balanço claro de prós e contras.

Restrições: não recomende comprar, vender ou manter; não invente fatos, notícias, datas ou
preço-alvo além dos dados; "média do setor" é a dos pares deste screener (amostra limitada).
Escreva em português, em texto corrido — NÃO repita estas instruções, NÃO repita os rótulos
dos dados, NÃO use listas numeradas ou marcadores, NÃO use inglês. Comece direto pela análise.

DADOS DE {ticker}:
{dados}"""


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
        f"{_v(r.get('teto_medio'))} | Mediana {_v(r.get('teto_mediana'))} | Ajustado "
        f"(c/ margem de segurança) {_v(r.get('teto_ajustado'))} | Upside vs ajustado "
        f"{_v(r.get('teto_upside_pct'),1)}%")
    add("Próximo resultado", None if str(r.get("prox_resultado") or "n/d") == "n/d"
        else r.get("prox_resultado"))
    add("Ex-dividendo", None if str(r.get("ex_dividendo") or "n/d") == "n/d" else
        f"{r.get('ex_dividendo')} ({r.get('ex_tipo')})")
    return "\n".join(L)


def _gemini(prompt: str, api_key: str, model: str, timeout: int = 60,
            debug: bool = False, max_tokens: int = 1024, retries: int = 3) -> str:
    import requests
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent?key={api_key}")

    def _post(with_thinking_off: bool):
        gen = {"temperature": 0.3, "maxOutputTokens": max_tokens}
        if with_thinking_off:
            gen["thinkingConfig"] = {"thinkingBudget": 0}
        body = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": gen}
        return requests.post(url, json=body, timeout=timeout)

    r = None
    for attempt in range(retries + 1):
        r = _post(True)
        if r.status_code == 400 and "thinking" in r.text.lower():
            r = _post(False)          # modelo não aceita thinkingConfig -> tenta sem
        if r.status_code in (429, 503) and attempt < retries:
            # respeita Retry-After se vier; senão backoff crescente
            ra = r.headers.get("Retry-After")
            wait = int(ra) if (ra and str(ra).isdigit()) else 15 * (attempt + 1)
            print(f"   [IA] HTTP {r.status_code} (cota/indisponível) — aguardando {wait}s "
                  f"e tentando de novo ({attempt + 1}/{retries}).")
            time.sleep(wait)
            continue
        break

    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:400]}")
    data = r.json()
    if debug:
        print("   [IA debug] resposta bruta:", str(data)[:600])
    cands = data.get("candidates") or []
    if not cands:
        raise RuntimeError(f"sem 'candidates' (promptFeedback={data.get('promptFeedback')})")
    fr = cands[0].get("finishReason")
    parts = (cands[0].get("content") or {}).get("parts") or []
    txt = "".join(p.get("text", "") for p in parts).strip()
    if not txt:
        raise RuntimeError(f"texto vazio (finishReason={fr}). Se for MAX_TOKENS, aumente "
                           f"AI_MAX_TOKENS ou confirme que o thinking foi desligado.")
    if fr == "MAX_TOKENS" and debug:
        print("   [IA debug] atenção: resposta cortada por MAX_TOKENS.")
    return txt


def generate_theses(df: pd.DataFrame, hoje: str, outdir: str = "reports",
                    force: bool = False) -> dict:
    """Gera teses (ancoradas nos dados) para os papéis em df. Retorna {ticker: texto}.

    Requer env GEMINI_API_KEY. Env opcionais: GEMINI_MODEL (default gemini-2.5-flash),
    AI_MAX_CALLS (40), AI_MAX_TOKENS (1024), AI_DEBUG (1). Cache versionado em
    reports/cache_tese.json. force=True ignora o cache (regenera tudo).
    """
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    raw_model = os.getenv("GEMINI_MODEL", "").strip()
    # sanitiza: remove aspas, espaços e um eventual prefixo "models/"
    model = raw_model.strip().strip('"').strip("'").strip()
    if model.lower().startswith("models/"):
        model = model.split("/", 1)[1]
    if " " in model or not model:
        # nome com espaço (ex.: "Gemini 2.5 Flash") ou vazio -> usa default seguro
        if model:
            print(f"[IA] GEMINI_MODEL inválido (tinha espaço/vazio) — usando default. "
                  f"Use um id como 'gemini-2.5-flash'.")
        model = "gemini-2.5-flash"
    debug = os.getenv("AI_DEBUG", "0") == "1"
    n = 0 if df is None else len(df)
    masked = f"{api_key[:4]}…({len(api_key)} chars)" if api_key else "VAZIA"
    print(f"[IA] chave: {masked} | papéis p/ tese: {n} | debug={debug}")
    print(f"[IA] modelo: {len(model)} chars | tem_barra={'/' in model} | "
          f"tem_espaco={' ' in model} (o valor pode aparecer como *** por ser secret)")
    if not api_key:
        print("[IA] GEMINI_API_KEY não chegou ao processo. Cheque: (1) o secret existe? "
              "(2) o workflow injeta 'GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}' no "
              "env do passo? Secrets não são expostos automaticamente ao processo.")
        return {}
    if df is None or df.empty:
        print("[IA] 0 papéis aprovados hoje (fundamentos + rompimento) — nada a gerar.")
        return {}

    max_calls = int(os.getenv("AI_MAX_CALLS", "40") or 40)
    max_tokens = int(os.getenv("AI_MAX_TOKENS", "1024") or 1024)
    sleep_s = float(os.getenv("AI_SLEEP", "30") or 30)   # 30s entre chamadas (~2/min)
    cache_path = os.path.join(outdir, "cache_tese.json")
    try:
        cache = json.load(open(cache_path, encoding="utf-8"))
    except Exception:
        cache = {}

    out, calls, erros = {}, 0, 0
    for tk in df.index:
        key = f"{tk}:{hoje}:{PROMPT_VERSION}"
        if not force and key in cache:
            out[tk] = cache[key]
            continue
        if calls >= max_calls:
            out[tk] = ""
            print(f"  [IA] teto de {max_calls} chamadas atingido (AI_MAX_CALLS) — {tk} sem tese.")
            continue
        prompt = _PROMPT.format(ticker=tk, dados=_fmt_metrics(df.loc[tk]))
        try:
            txt = _gemini(prompt, api_key, model, debug=debug, max_tokens=max_tokens)
            out[tk] = txt or ""
            cache[key] = out[tk]
            calls += 1
            if debug:
                print(f"  [IA] {tk}: OK ({len(out[tk])} chars)")
            time.sleep(sleep_s)          # respeita rate limit do free tier
        except Exception as e:
            erros += 1
            print(f"  [IA] {tk}: FALHOU -> {e}")
            out[tk] = ""
    try:
        os.makedirs(outdir, exist_ok=True)
        json.dump(cache, open(cache_path, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:
        pass
    print(f"[IA] resumo: {calls} tese(s) gerada(s), {erros} falha(s), "
          f"{sum(1 for v in out.values() if v)} com texto (modelo {model}).")
    if erros:
        print("[IA] Houve falhas. Se forem HTTP 429, é cota do free tier (por minuto ou "
              "diária) — aumente AI_SLEEP, reduza o universo, use um modelo Flash-Lite "
              "(mais RPM) ou rode amanhã (o cache preserva as que já saíram). Modelo "
              "inválido = 404; chave inválida = 400. Rode com AI_DEBUG=1 para detalhes.")
    return out
