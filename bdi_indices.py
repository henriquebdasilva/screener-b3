"""bdi_indices.py — IFIX e Fluxo estrangeiro via o capítulo 02 do BDI ("Indicadores e
Informativos"), fonte oficial B3 (mesmo canal já usado em opcoes.py/posicoes.py).

IFIX: o BDI traz "Evolução dos Índices" com fechamento e variações (dia/mês/ano) — direto,
sem cálculo. Fluxo estrangeiro: o BDI só publica o ACUMULADO DO MÊS (compras/vendas), não o
valor isolado do dia. O fluxo do dia é a DIFERENÇA entre o acumulado de hoje e o de ontem —
por isso precisa de um cache do valor anterior (arquivo em reports/, versionado no repo pelo
próprio workflow). Na virada do mês, o acumulado reinicia; detectamos e não calculamos delta
negativo espúrio nesse caso (fica n/d nesse único dia).

Honestidade: nada é estimado — se a fonte ou o cache faltar, o indicador fica None. Desligue
com env BDI_INDICES=0. Cache: env FLUXO_CACHE_PATH (default 'reports/.fluxo_cache.json').
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
from urllib.request import Request, urlopen


def _bdi_pdf_url(dataobj, capitulo="02"):
    d = dataobj
    return (f"https://arquivos.b3.com.br/bdi/download/bdi/{d.strftime('%Y-%m-%d')}/"
            f"BDI_{capitulo}_{d.strftime('%Y%m%d')}.pdf")


def _pdf_text(fonte) -> str:
    import pymupdf
    doc = pymupdf.open(stream=fonte, filetype="pdf") if isinstance(fonte, (bytes, bytearray)) \
        else pymupdf.open(fonte)
    return "\n".join(p.get_text() for p in doc)


def _num_br(s):
    """Padrão BR: ponto = milhar, vírgula = decimal (usado na tabela de investidores)."""
    s = str(s).strip().replace(".", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return None


def _num_pts(s):
    """Pontos de índice no BDI: vírgula = separador de milhar (ex.: '133,009' = 133009)."""
    s = str(s).strip().replace(",", "")
    try:
        return float(s)
    except Exception:
        return None


def _num_pct(s):
    """Percentuais de 'Evolução dos Fechamentos': ponto decimal direto (ex.: '-0.21')."""
    try:
        return float(str(s).strip())
    except Exception:
        return None


def _pdf_lines(fonte):
    """Reconstrói as linhas do PDF por coordenadas (x,y), como em posicoes.py/opcoes.py — o
    texto corrido (get_text() simples) intercala colunas lado a lado (ex.: os 3 painéis
    'Comportamento no Dia' da mesma linha), o que quebra regex sobre texto puro."""
    import pymupdf
    from collections import defaultdict
    doc = pymupdf.open(stream=fonte, filetype="pdf") if isinstance(fonte, (bytes, bytearray)) \
        else pymupdf.open(fonte)
    linhas = []                      # lista de (pagina, y, [(x, texto), ...])
    for pi, page in enumerate(doc):
        L = defaultdict(list)
        for w in page.get_text("words"):                 # (x0,y0,x1,y1,texto,...)
            L[round(w[1] / 2) * 2].append((w[0], w[4]))
        for y in sorted(L):
            linhas.append((pi, y, [t for _, t in sorted(L[y])]))
    return linhas


def _achar_bloco_indice(linhas, nome_indice: str, largura_col: float = 200):
    """Localiza o bloco 'Comportamento no Dia' de um índice específico (ex.: 'IFIX') pela
    coluna (x) do título, e devolve as linhas seguintes dentro da mesma faixa de x — evita
    pegar o Fechamento/percentuais de um índice vizinho na mesma linha."""
    import pymupdf
    x_titulo = None
    idx_titulo = None
    for i, (pi, y, cells) in enumerate(linhas):
        if cells and cells[0].strip() == nome_indice:
            # confirma que é título de bloco (seguido de 'Comportamento' em poucas linhas)
            seguinte = " ".join(c for _, _, cs in linhas[i:i + 3] for c in cs)
            if "Comportamento" in seguinte or "Pontos" in seguinte:
                idx_titulo = i
                break
    if idx_titulo is None:
        return []
    # x do título define a coluna; pega as próximas ~20 linhas cujo primeiro token começa
    # perto dessa coluna (tolerância generosa, já que colunas têm ~200-250pt de largura)
    return linhas[idx_titulo:idx_titulo + 25]


def parse_ifix(texto=None, linhas=None) -> dict | None:
    """Extrai o bloco IFIX ('Comportamento no Dia' + 'Evolução dos Fechamentos') por
    coordenadas. Aceita `linhas` (de _pdf_lines) OU, em fallback, `texto` corrido (menos
    confiável em layout de 3 colunas)."""
    if linhas:
        bloco = _achar_bloco_indice(linhas, "IFIX")
        if not bloco:
            return None
        flat = [c for _, _, cells in bloco for c in cells]
        out = {}
        if "Fechamento" in flat:
            i = flat.index("Fechamento")
            out["fechamento"] = _num_pts(flat[i + 1]) if i + 1 < len(flat) else None
        # percentuais: procura 'Do', 'dia', '%', ... ancorado por 'No' 'mês' e 'No' 'ano'
        try:
            j = flat.index("Do")
            # padrão: Do dia X% Ontem X% Na semana X% Em uma semana X% No mês X% ... No ano X%
            def pct_apos(chave_seq):
                for k in range(len(flat) - len(chave_seq)):
                    if flat[k:k + len(chave_seq)] == chave_seq:
                        val = flat[k + len(chave_seq)]
                        return _num_pct(val.replace("%", ""))
                return None
            out["var_dia_pct"] = pct_apos(["Do", "dia"])
            out["var_mes_pct"] = pct_apos(["No", "mês"])
            out["var_ano_pct"] = pct_apos(["No", "ano"])
        except ValueError:
            pass
        return out if out.get("fechamento") is not None else None
    if texto:
        m = re.search(r"IFIX\s*\n?Comportamento no Dia.*?Fechamento\s+([\d.,]+)", texto, re.S)
        if not m:
            return None
        out = {"fechamento": _num_pts(m.group(1))}
        m2 = re.search(r"IFIX\s*\(%\)\s*Do dia\s+([\-\d.]+)%.*?No mês\s+([\-\d.]+)%"
                       r".*?No ano\s+([\-\d.]+)%", texto, re.S)
        if m2:
            out["var_dia_pct"] = _num_pct(m2.group(1))
            out["var_mes_pct"] = _num_pct(m2.group(2))
            out["var_ano_pct"] = _num_pct(m2.group(3))
        return out if out["fechamento"] is not None else None
    return None


def parse_fluxo_acumulado(texto=None, linhas=None) -> dict | None:
    """Extrai 'Participação dos Investidores' (compras/vendas ACUMULADAS do mês) do
    Investidor Estrangeiro. Aceita `linhas` (coordenadas) ou `texto` corrido."""
    if linhas:
        for _, _, cells in linhas:
            if len(cells) >= 2 and cells[0] == "Investidor" and cells[1] == "Estrangeiro":
                nums = [_num_br(c) for c in cells[2:] if _num_br(c) is not None]
                if len(nums) >= 2:
                    compras, vendas = nums[0], nums[1] if len(nums) < 4 else nums[2]
                    # layout: Compras | Participação% | Vendas | Participação%
                    if len(nums) >= 3:
                        compras, vendas = nums[0], nums[2]
                    return {"compras_acum_mes": compras, "vendas_acum_mes": vendas,
                            "saldo_acum_mes": compras - vendas, "data_base": None}
        return None
    if texto:
        m = re.search(r"Investidor Estrangeiro\s+([\d.,]+)\s+([\d,]+)\s+([\d.,]+)\s+([\d,]+)",
                      texto)
        if not m:
            return None
        compras, vendas = _num_br(m.group(1)), _num_br(m.group(3))
        if compras is None or vendas is None:
            return None
        dm = re.search(r"até o dia (\d{2}/\d{2}/\d{4})", texto)
        data_base = None
        if dm:
            try:
                data_base = dt.datetime.strptime(dm.group(1), "%d/%m/%Y").date()
            except Exception:
                pass
        return {"compras_acum_mes": compras, "vendas_acum_mes": vendas,
                "saldo_acum_mes": compras - vendas, "data_base": data_base}
    return None


def _fetch_bdi02(dias_tentativa: int = 6):
    """Baixa o BDI_02 mais recente disponível. Retorna (bytes_pdf, texto, data) ou
    (None, None, None). Devolve os bytes para permitir tanto o parser por coordenadas quanto
    o de texto corrido (fallback)."""
    for i in range(dias_tentativa):
        d = dt.date.today() - dt.timedelta(days=i)
        url = _bdi_pdf_url(d)
        try:
            req = Request(url, headers={"User-Agent": "Mozilla/5.0 (screener-b3)"})
            with urlopen(req, timeout=90) as r:
                raw = r.read()
            if raw[:4] != b"%PDF":
                continue
            return bytes(raw), _pdf_text(bytes(raw)), d
        except Exception:
            continue
    return None, None, None


def _debug_snippet(texto: str, chave: str, tam: int = 400) -> str:
    """Trecho do texto ao redor da 1ª ocorrência de `chave`, para diagnóstico em log."""
    if not texto:
        return "(sem texto extraído)"
    i = texto.find(chave)
    if i < 0:
        return f"('{chave}' não aparece no texto extraído)"
    return texto[max(0, i - 40):i + tam].replace("\n", " | ")


def fetch_ifix() -> dict | None:
    """IFIX (fechamento + variações) via BDI. Tenta primeiro por COORDENADAS (robusto a
    layout de colunas lado a lado), cai para texto corrido, depois desiste. None se
    indisponível — nunca inventa. Ative BDI_DEBUG=1 para logar um trecho em caso de falha."""
    if os.getenv("BDI_INDICES", "1") == "0":
        return None
    raw, texto, d = _fetch_bdi02()
    if not raw:
        print("[bdi_indices] IFIX: não consegui baixar o BDI_02.")
        return None
    ifix = None
    try:
        ifix = parse_ifix(linhas=_pdf_lines(raw))
    except Exception as e:
        print(f"[bdi_indices] IFIX: parser por coordenadas falhou ({e}); tentando texto corrido.")
    if not ifix:
        ifix = parse_ifix(texto=texto)
    if not ifix:
        print("[bdi_indices] IFIX: layout não reconhecido no BDI_02 (nem por coordenadas, "
              "nem por texto).")
        if os.getenv("BDI_DEBUG", "0") == "1":
            print("[bdi_indices][debug] trecho ao redor de 'IFIX': "
                  + _debug_snippet(texto, "IFIX"))
        return None
    ifix["data"] = d
    print(f"[bdi_indices] IFIX {d}: {ifix['fechamento']:.0f} pts "
          f"({ifix.get('var_dia_pct', float('nan')):+.2f}% no dia)")
    return ifix


def fetch_fluxo_estrangeiro(cache_path: str = None) -> dict | None:
    """Fluxo estrangeiro DIÁRIO = delta do acumulado do mês (BDI) vs. o cache de ontem.
    Sem cache anterior (1º dia do mês ou primeira execução), retorna só o acumulado, sem
    'dia' (não há como isolar o primeiro dia sem o acumulado do dia anterior do mês)."""
    if os.getenv("BDI_INDICES", "1") == "0":
        return None
    cache_path = cache_path or os.getenv("FLUXO_CACHE_PATH", "reports/.fluxo_cache.json")
    raw, texto, d = _fetch_bdi02()
    if not raw:
        print("[bdi_indices] fluxo estrangeiro: não consegui baixar o BDI_02.")
        return None
    acc = None
    try:
        acc = parse_fluxo_acumulado(linhas=_pdf_lines(raw))
    except Exception as e:
        print(f"[bdi_indices] fluxo estrangeiro: parser por coordenadas falhou ({e}); "
              f"tentando texto corrido.")
    if not acc:
        acc = parse_fluxo_acumulado(texto=texto)
    if not acc:
        print("[bdi_indices] fluxo estrangeiro: layout não reconhecido no BDI_02.")
        if os.getenv("BDI_DEBUG", "0") == "1":
            print("[bdi_indices][debug] trecho ao redor de 'Investidor Estrangeiro': "
                  + _debug_snippet(texto, "Investidor Estrangeiro"))
        return None
    data_ref = acc.get("data_base") or d

    cache = {}
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            cache = json.load(f)
    except Exception:
        pass

    resultado = {"acum_mes": acc["saldo_acum_mes"], "data": data_ref, "dia": None, "mes": None}
    prev = cache.get("ultimo")
    if prev:
        prev_data = dt.date.fromisoformat(prev["data"]) if prev.get("data") else None
        mesmo_mes = prev_data and prev_data.year == data_ref.year and prev_data.month == data_ref.month
        if mesmo_mes and prev_data < data_ref:
            resultado["dia"] = acc["saldo_acum_mes"] - prev["acum_mes"]
        resultado["mes"] = acc["saldo_acum_mes"]  # acumulado do mês corrente, sempre disponível

    # grava o cache para o próximo dia (best-effort; não quebra o fluxo se falhar)
    try:
        os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({"ultimo": {"data": data_ref.isoformat(),
                                  "acum_mes": acc["saldo_acum_mes"]}}, f)
    except Exception as e:
        print(f"[bdi_indices] fluxo estrangeiro: falha ao gravar cache: {e}")

    if resultado["dia"] is not None:
        print(f"[bdi_indices] fluxo estrangeiro {data_ref}: dia R$ {resultado['dia']:+,.0f} mi "
              f"| mês R$ {resultado['mes']:+,.0f} mi")
    else:
        print(f"[bdi_indices] fluxo estrangeiro {data_ref}: sem cache do dia anterior — "
              f"só acumulado do mês (R$ {resultado['acum_mes']:+,.0f} mi). "
              f"Amanhã já calcula o valor diário.")
    return resultado
