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
import math
import os
import re
from urllib.request import Request, urlopen

__build__ = "2026-09-04e-filtro-sanidade-delta"   # marcador de versão (aparece no log)


def _bdi_pdf_url(dataobj, capitulo="02"):
    d = dataobj
    return (f"https://arquivos.b3.com.br/bdi/download/bdi/{d.strftime('%Y-%m-%d')}/"
            f"BDI_{capitulo}_{d.strftime('%Y%m%d')}.pdf")


def _pdf_text(fonte) -> str:
    import pymupdf
    doc = pymupdf.open(stream=fonte, filetype="pdf") if isinstance(fonte, (bytes, bytearray)) \
        else pymupdf.open(fonte)
    return "\n".join(p.get_text() for p in doc)


def _pdf_page_count(raw_bytes) -> int:
    """Nº de páginas do PDF — diagnóstico: se um arquivo de tamanho grande tiver poucas
    páginas OU poucas páginas com texto extraível, é sinal de download truncado/corrompido,
    não de mudança de layout."""
    try:
        import pymupdf
        doc = pymupdf.open(stream=bytes(raw_bytes), filetype="pdf")
        return doc.page_count
    except Exception:
        return -1


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
    'Comportamento no Dia' da mesma linha), o que quebra regex sobre texto puro.
    Mantém (x, texto) — não só o texto — porque vários índices dividem a MESMA linha (y),
    lado a lado; sem o x não dá pra saber qual coluna pertence a qual índice."""
    import pymupdf
    from collections import defaultdict
    doc = pymupdf.open(stream=fonte, filetype="pdf") if isinstance(fonte, (bytes, bytearray)) \
        else pymupdf.open(fonte)
    linhas = []                      # lista de (pagina, y, [(x, texto), ...]) — ORDENADO por x
    for pi, page in enumerate(doc):
        L = defaultdict(list)
        for w in page.get_text("words"):                 # (x0,y0,x1,y1,texto,...)
            L[round(w[1] / 2) * 2].append((w[0], w[4]))
        for y in sorted(L):
            linhas.append((pi, y, sorted(L[y])))          # mantém (x, texto)
    return linhas


def _achar_bloco_indice(linhas, nome_indice: str, largura_col: float = 265):
    """Localiza o bloco 'Comportamento no Dia' de um índice específico (ex.: 'IFIX'). Como até
    3 painéis de índice dividem a MESMA linha (y) lado a lado, o título pode estar em QUALQUER
    posição da linha — buscamos por texto em qualquer x, pegamos a coordenada dele, e usamos
    essa faixa de x para filtrar SÓ os tokens daquela coluna nas linhas seguintes (evita pegar
    o Fechamento/percentuais de um índice vizinho que compartilha a mesma linha)."""
    x_titulo = None
    idx_titulo = None
    for i, (pi, y, cells) in enumerate(linhas):
        for x, t in cells:
            if t.strip() == nome_indice:
                seguinte = " ".join(t2 for _, _, cs in linhas[i:i + 3] for _, t2 in cs)
                if "Comportamento" in seguinte or "Pontos" in seguinte:
                    idx_titulo, x_titulo = i, x
                    break
        if idx_titulo is not None:
            break
    if idx_titulo is None or x_titulo is None:
        return []
    x_lo, x_hi = x_titulo - 15, x_titulo + largura_col
    out = []
    for pi, y, cells in linhas[idx_titulo:idx_titulo + 30]:
        filtrado = [t for x, t in cells if x_lo <= x <= x_hi]
        if filtrado:
            out.append((pi, y, filtrado))
    return out


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
            out["fechamento"] = _num_br(flat[i + 1]) if i + 1 < len(flat) else None
        # percentuais: procura 'Do', 'dia', '%', ... ancorado por 'No' 'mês' e 'No' 'ano'
        try:
            j = flat.index("Do")
            # padrão: Do dia X% Ontem X% Na semana X% Em uma semana X% No mês X% ... No ano X%
            def pct_apos(chave_seq):
                for k in range(len(flat) - len(chave_seq)):
                    if flat[k:k + len(chave_seq)] == chave_seq:
                        val = flat[k + len(chave_seq)]
                        return _num_br(val.replace("%", ""))
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
        out = {"fechamento": _num_br(m.group(1))}
        m2 = re.search(r"IFIX\s*\(%\)\s*Do dia\s+([\-\d,\.]+)%.*?No mês\s+([\-\d,\.]+)%"
                       r".*?No ano\s+([\-\d,\.]+)%", texto, re.S)
        if m2:
            out["var_dia_pct"] = _num_br(m2.group(1))
            out["var_mes_pct"] = _num_br(m2.group(2))
            out["var_ano_pct"] = _num_br(m2.group(3))
        return out if out["fechamento"] is not None else None
    return None


def parse_fluxo_acumulado(texto=None, linhas=None) -> dict | None:
    """Extrai 'Participação dos Investidores' (compras/vendas ACUMULADAS do mês) do
    Investidor Estrangeiro. Aceita `linhas` (coordenadas, formato (pi,y,[(x,texto),...]) de
    _pdf_lines) ou `texto` corrido — ou os DOIS juntos (compras/vendas via `linhas` se vier,
    mas a data real sempre via `texto` se disponível). O BDI publica a coluna em 'R$ MIL' —
    convertemos para R$ MILHÕES aqui (÷1000) para bater com o rótulo 'R$ mi' usado no
    relatório; sem essa conversão o valor aparecia 1000x maior do que deveria (ex.:
    '-18.697.049 R$ mi' em vez de '-18.697 R$ mi', quando na real R$ mil já é o valor bruto,
    ~R$18,7 bi).

    IMPORTANTE — a data real dos dados NÃO é a data do arquivo: a seção 'Participação dos
    Investidores' do BDI vem com 2-4 pregões de ATRASO (confirmado com arquivos reais: o
    boletim 'de 31/08' carrega dados 'do início do mês até o dia 27/08'; o 'de 01/09' carrega
    'até o dia 28/08'). Por isso extraímos a data real de dentro do texto ("até o dia
    DD/MM/AAAA") em vez de assumir que é a data do arquivo baixado — usar a data do arquivo
    aqui causava deltas errados e a impressão de que o fluxo "não avançava"."""
    def _extrai_data_base(txt):
        if not txt:
            return None
        dm = re.search(r"até o dia (\d{2}/\d{2}/\d{4})", txt)
        if not dm:
            return None
        try:
            return dt.datetime.strptime(dm.group(1), "%d/%m/%Y").date()
        except Exception:
            return None

    if linhas:
        for _, _, cells_xy in linhas:
            cells = [t for _, t in cells_xy] if cells_xy and isinstance(cells_xy[0], tuple) \
                else cells_xy                             # aceita bruto (x,t) ou já-texto
            if len(cells) >= 2 and cells[0] == "Investidor" and cells[1] == "Estrangeiro":
                nums = [_num_br(c) for c in cells[2:] if _num_br(c) is not None]
                if len(nums) >= 2:
                    compras, vendas = nums[0], nums[1] if len(nums) < 4 else nums[2]
                    # layout: Compras | Participação% | Vendas | Participação%
                    if len(nums) >= 3:
                        compras, vendas = nums[0], nums[2]
                    compras, vendas = compras / 1000.0, vendas / 1000.0    # R$ mil -> R$ mi
                    return {"compras_acum_mes": compras, "vendas_acum_mes": vendas,
                            "saldo_acum_mes": compras - vendas,
                            "data_base": _extrai_data_base(texto)}
        return None
    if texto:
        m = re.search(r"Investidor Estrangeiro\s+([\d.,]+)\s+([\d,]+)\s+([\d.,]+)\s+([\d,]+)",
                      texto)
        if not m:
            return None
        compras, vendas = _num_br(m.group(1)), _num_br(m.group(3))
        if compras is None or vendas is None:
            return None
        compras, vendas = compras / 1000.0, vendas / 1000.0                # R$ mil -> R$ mi
        return {"compras_acum_mes": compras, "vendas_acum_mes": vendas,
                "saldo_acum_mes": compras - vendas, "data_base": _extrai_data_base(texto)}
    return None


def _fetch_bdi02(dias_tentativa: int = 6, min_chars: int = 20000):
    """Baixa o BDI_02 mais recente e COMPLETO. Retorna (bytes_pdf, texto, data) ou
    (None, None, None). Devolve os bytes para permitir tanto o parser por coordenadas quanto
    o de texto corrido (fallback).

    Os arquivos do BDI são publicados de forma PROGRESSIVA ao longo da noite — o do dia
    corrente pode existir e baixar normalmente (200 OK, tamanho razoável) mas ainda estar
    incompleto (só a parte administrativa inicial, sem a seção 'Evolução dos índices', que é
    processada/publicada depois). Por isso validamos o CONTEÚDO, não só o download: se o texto
    extraído for muito curto ou não tiver o marco 'Evolução dos índices', tratamos como
    indisponível e caímos para o dia anterior — igual fazemos quando o download falha de vez."""
    for i in range(dias_tentativa):
        d = dt.date.today() - dt.timedelta(days=i)
        url = _bdi_pdf_url(d)
        try:
            req = Request(url, headers={"User-Agent": "Mozilla/5.0 (screener-b3)"})
            with urlopen(req, timeout=90) as r:
                raw = r.read()
            if raw[:4] != b"%PDF":
                continue
            texto = _pdf_text(bytes(raw))
            if len(texto) < min_chars or "Evolução dos índices" not in texto:
                print(f"[bdi_indices] BDI_02 de {d}: baixou ({len(raw)} bytes) mas parece "
                      f"INCOMPLETO ({len(texto)} caracteres, marco 'Evolução dos índices' "
                      f"{'presente' if 'Evolução dos índices' in texto else 'ausente'}) — "
                      f"provável publicação ainda em andamento; tentando dia anterior.")
                continue
            return bytes(raw), texto, d
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
    print(f"[bdi_indices] build: {__build__}")
    if os.getenv("BDI_INDICES", "1") == "0":
        return None
    raw, texto, d = _fetch_bdi02()
    if not raw:
        print(f"[bdi_indices] IFIX: não consegui baixar o BDI_02 (tentei "
              f"{dt.date.today()} e {dt.date.today() - dt.timedelta(days=1)}, entre outras "
              f"datas recentes). Verifique se a URL abre no navegador: "
              f"{_bdi_pdf_url(dt.date.today())}")
        return None
    ifix = None
    try:
        ifix = parse_ifix(linhas=_pdf_lines(raw))
    except Exception as e:
        print(f"[bdi_indices] IFIX: parser por coordenadas falhou ({e}); tentando texto corrido.")
    if not ifix:
        ifix = parse_ifix(texto=texto)
    if not ifix:
        _pags = _pdf_page_count(raw)
        print(f"[bdi_indices] IFIX: layout não reconhecido no BDI_02 (nem por coordenadas, "
              f"nem por texto). Arquivo usado: data={d}, {len(raw)} bytes, {_pags} páginas, "
              f"{len(texto)} caracteres de texto extraído "
              f"({len(texto)/max(_pags,1):.0f} car./página em média).")
        if os.getenv("BDI_DEBUG", "0") == "1":
            print("[bdi_indices][debug] trecho ao redor de 'IFIX': "
                  + _debug_snippet(texto, "IFIX"))
            print("[bdi_indices][debug] INÍCIO do texto extraído (800 car.): "
                  + texto[:800].replace("\n", " | "))
            print("[bdi_indices][debug] FIM do texto extraído (800 car.): "
                  + texto[-800:].replace("\n", " | "))
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
        acc = parse_fluxo_acumulado(linhas=_pdf_lines(raw), texto=texto)
    except Exception as e:
        print(f"[bdi_indices] fluxo estrangeiro: parser por coordenadas falhou ({e}); "
              f"tentando texto corrido.")
    if not acc:
        acc = parse_fluxo_acumulado(texto=texto)
    if not acc:
        _pags = _pdf_page_count(raw)
        print(f"[bdi_indices] fluxo estrangeiro: layout não reconhecido no BDI_02. "
              f"Arquivo usado: data={d}, {len(raw)} bytes, {_pags} páginas, "
              f"{len(texto)} caracteres de texto extraído "
              f"({len(texto)/max(_pags,1):.0f} car./página em média).")
        if os.getenv("BDI_DEBUG", "0") == "1":
            print("[bdi_indices][debug] trecho ao redor de 'Investidor Estrangeiro': "
                  + _debug_snippet(texto, "Investidor Estrangeiro"))
            print("[bdi_indices][debug] INÍCIO do texto extraído (800 car.): "
                  + texto[:800].replace("\n", " | "))
            print("[bdi_indices][debug] FIM do texto extraído (800 car.): "
                  + texto[-800:].replace("\n", " | "))
        return None
    data_ref = acc.get("data_base") or d

    cache_abs = os.path.abspath(cache_path)
    cache = {}
    existia = os.path.exists(cache_path)
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            cache = json.load(f)
        print(f"[bdi_indices] fluxo: cache LIDO de {cache_abs} "
              f"(último dia salvo: {cache.get('ultimo', {}).get('data', '?')})")
    except FileNotFoundError:
        print(f"[bdi_indices] fluxo: cache NÃO EXISTE em {cache_abs} "
              f"(normal só no 1º dia; se aparecer todo dia, o cache não está persistindo "
              f"entre execuções — confira se 'reports/.fluxo_cache.json' não está sendo "
              f"ignorado pelo .gitignore ou pelo passo de commit do workflow)")
    except Exception as e:
        print(f"[bdi_indices] fluxo: cache existia ({existia}) mas falhou ao ler "
              f"{cache_abs}: {e}")

    resultado = {"acum_mes": acc["saldo_acum_mes"], "data": data_ref, "dia": None, "mes": None}
    prev = cache.get("ultimo")
    if prev:
        prev_data = dt.date.fromisoformat(prev["data"]) if prev.get("data") else None
        mesmo_mes = prev_data and prev_data.year == data_ref.year and prev_data.month == data_ref.month
        if mesmo_mes and prev_data < data_ref:
            delta = acc["saldo_acum_mes"] - prev["acum_mes"]
            # FILTRO DE SANIDADE: a seção 'Participação dos Investidores' do BDI às vezes é
            # REVISADA pela B3 depois de publicada (valores de uma mesma data 'até o dia X'
            # mudam entre publicações) — comparar uma leitura antiga com uma leitura revisada
            # pode gerar um delta sem sentido (já vimos +R$18.927mi num dia, quando o normal
            # fica entre ~R$50-2.600mi). Em vez de publicar um número absurdo, descarta e
            # marca como indisponível — nunca inventa/aceita um valor implausível.
            LIMITE_DIA = 8000.0                   # R$ mi — generoso, mas corta outliers óbvios
            if abs(delta) > LIMITE_DIA:
                print(f"[bdi_indices] fluxo estrangeiro: delta de {prev_data} a {data_ref} "
                      f"veio implausível (R$ {delta:+,.0f} mi, limite ±{LIMITE_DIA:,.0f}) — "
                      f"provável revisão de dados pela B3 entre publicações; descartando o "
                      f"'dia' desta execução (fica indisponível, não inventa).")
            else:
                resultado["dia"] = delta
        resultado["mes"] = acc["saldo_acum_mes"]  # acumulado do mês corrente, sempre disponível

    # grava o cache para o próximo dia (best-effort; não quebra o fluxo se falhar)
    try:
        os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({"ultimo": {"data": data_ref.isoformat(),
                                  "acum_mes": acc["saldo_acum_mes"]}}, f)
        tam = os.path.getsize(cache_path)
        print(f"[bdi_indices] fluxo: cache GRAVADO em {cache_abs} ({tam} bytes, "
              f"data={data_ref.isoformat()}) — precisa estar em 'reports/' (ou onde o "
              f"workflow faz 'git add') para o commit do fim do job pegá-lo")
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


def atualizar_historico_bdi(fluxo_dia=None, fluxo_acum_mes=None, oi_pc_mercado=None,
                            data_ref=None, cache_path: str = None, manter: int = 15,
                            **extras) -> list:
    """Mantém um histórico ROLANTE dos últimos `manter` BDIs (default 15) com o fluxo
    estrangeiro do dia, o Put/Call de posições em aberto (open interest) do mercado, e
    quaisquer campos extras passados em `**extras` (ex.: pc_vol_mercado, breadth_bova11_alta,
    breadth_small11_alta) — para os gráficos de evolução/tendência de curto prazo. Cada
    execução grava/atualiza a entrada do dia corrente (idempotente: rodar de novo no mesmo
    dia sobrescreve, não duplica; campos não informados numa execução preservam o valor já
    salvo de execuções anteriores no mesmo dia, em vez de apagar). Retorna a lista ordenada
    por data (mais antiga primeiro). Cache persiste via os relatórios versionados no repo
    (env HIST_BDI_PATH, default 'reports/.historico_bdi.json')."""
    cache_path = cache_path or os.getenv("HIST_BDI_PATH", "reports/.historico_bdi.json")
    cache_abs = os.path.abspath(cache_path)
    hist = []
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            hist = json.load(f).get("dias", [])
        print(f"[bdi_indices] histórico: cache LIDO de {cache_abs} ({len(hist)} dias já salvos)")
    except FileNotFoundError:
        print(f"[bdi_indices] histórico: cache NÃO EXISTE em {cache_abs} "
              f"(normal só no 1º dia; se aparecer todo dia, o cache não está persistindo — "
              f"confira o .gitignore e o passo 'git add reports/' do workflow)")
    except Exception as e:
        print(f"[bdi_indices] histórico: falha ao ler {cache_abs}: {e}")
    data_ref = data_ref or dt.date.today()
    ds = data_ref.isoformat() if hasattr(data_ref, "isoformat") else str(data_ref)

    # Se a data de referência de HOJE não é mais recente que a última já salva, não há dado
    # novo de verdade (a B3 ainda não publicou o BDI completo do dia — caiu no fallback pro
    # mesmo dia de uma execução anterior). Em vez de sobrescrever a entrada mais recente
    # (arriscando apagar um 'fluxo_dia' que já tinha sido calculado corretamente antes, ou
    # gravar 'n/d' por cima de um dado bom), simplesmente NÃO MEXE no histórico — ele
    # continua contando a partir do último dia que realmente teve dado novo, "para trás".
    datas_existentes = [d["data"] for d in hist if d.get("data")]
    data_mais_recente = max(datas_existentes) if datas_existentes else None
    if data_mais_recente is not None and ds <= data_mais_recente:
        print(f"[bdi_indices] histórico: {ds} não é mais recente que o último dia já salvo "
              f"({data_mais_recente}) — sem avanço real hoje (BDI ainda incompleto/repetido); "
              f"histórico mantido como está, contando a partir do último dia disponível.")
        return hist

    campos = {"fluxo_dia": fluxo_dia, "fluxo_acum_mes": fluxo_acum_mes,
             "oi_pc_mercado": oi_pc_mercado, **extras}
    campos = {k: v for k, v in campos.items() if v is not None}
    existente = next((d for d in hist if d.get("data") == ds), None)
    hist = [d for d in hist if d.get("data") != ds]         # remove p/ substituir abaixo
    novo = {"data": ds, **(existente or {}), **campos}      # preserva o que já tinha, atualiza
    if len(novo) > 1:                                        # tem algo além da data
        hist.append(novo)
    else:
        print(f"[bdi_indices] histórico: nada p/ gravar hoje ({ds}) — todos os campos vieram None")
    hist.sort(key=lambda d: d["data"])
    hist = hist[-manter:]
    try:
        os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({"dias": hist}, f)
        tam = os.path.getsize(cache_path)
        print(f"[bdi_indices] histórico: cache GRAVADO em {cache_abs} ({tam} bytes, "
              f"{len(hist)} dias) — precisa estar em 'reports/' p/ o commit do workflow pegá-lo")
    except Exception as e:
        print(f"[bdi_indices] histórico: falha ao gravar cache: {e}")
    print(f"[bdi_indices] histórico: {len(hist)}/{manter} dias no cache "
          f"({hist[0]['data'] if hist else '—'} a {hist[-1]['data'] if hist else '—'})")
    return hist


def _fetch_bdi_data_especifica(d, capitulo: str = "02", min_chars: int = 20000,
                               exigir_marco: bool = True):
    """Baixa e valida o BDI de uma DATA ESPECÍFICA (sem fallback — usado pela busca
    retroativa, que já varre as datas ela mesma). Retorna (raw, texto) ou (None, None).
    `exigir_marco` só faz sentido pro capítulo 02 (Evolução dos índices); os demais
    capítulos (03-4, 04-2) não têm esse marco, então só validamos o tamanho mínimo."""
    url = _bdi_pdf_url(d, capitulo)
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0 (screener-b3)"})
        with urlopen(req, timeout=90) as r:
            raw = r.read()
        if raw[:4] != b"%PDF":
            return None, None
        if capitulo == "02":
            texto = _pdf_text(bytes(raw))
            if len(texto) < min_chars or (exigir_marco and "Evolução dos índices" not in texto):
                return None, None
            return bytes(raw), texto
        return bytes(raw), None                          # 03-4/04-2: parser próprio (binário)
    except Exception:
        return None, None


def preencher_historico_retroativo(janela: int = 15, cache_path: str = None,
                                   max_calendario: int = 21,
                                   ticker_setor: dict = None) -> list:
    """Busca RETROATIVAMENTE, nos últimos `janela` pregões, o fluxo estrangeiro diário (via
    BDI_02) e o Put/Call de posições em aberto do mercado (via BDI_03-4) — para preencher o
    gráfico de evolução de uma vez, sem depender de esperar `janela` execuções diárias
    naturais (útil na 1ª vez rodando, ou se o cache do git foi perdido/resetado).

    Só faz o trabalho pesado (baixa até ~2x`janela` PDFs) se o cache JÁ SALVO tiver MENOS que
    `janela` dias — senão, não baixa nada e devolve o cache existente sem alteração. Isso evita
    refazer a busca pesada todo santo dia depois que o histórico natural já se formou.

    O fluxo estrangeiro do BDI é um ACUMULADO DO MÊS (não um valor isolado do dia) — por isso
    buscamos `janela+1` dias de acumulado e calculamos os deltas dia-a-dia nós mesmos (só
    dentro do mesmo mês; na virada do mês, aquele ponto fica sem o 'fluxo_dia', só o
    acumulado). O OI Put/Call já é um retrato do dia (não precisa de dia anterior)."""
    cache_path = cache_path or os.getenv("HIST_BDI_PATH", "reports/.historico_bdi.json")
    hist_atual = []
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            hist_atual = json.load(f).get("dias", [])
    except Exception:
        pass

    def _cobertura(campo):
        return sum(1 for d in hist_atual if d.get(campo) is not None)

    cob_fluxo = _cobertura("fluxo_dia")   # é o "dia" que importa pro gráfico, não o acumulado
                                          # (que quase sempre está presente, mesmo sem 'dia')
    cob_oi = _cobertura("oi_pc_mercado")
    cob_pcvol = _cobertura("pc_vol_mercado")
    precisa_fluxo = cob_fluxo < janela
    precisa_oi = cob_oi < janela
    precisa_pcvol = cob_pcvol < janela
    if not (precisa_fluxo or precisa_oi or precisa_pcvol):
        print(f"[bdi_indices] histórico retroativo: já tem {len(hist_atual)}/{janela} dias "
              f"salvos, com fluxo/OI/P-C-volume todos cobertos — sem necessidade de buscar "
              f"retroativamente.")
        return hist_atual
    print(f"[bdi_indices] histórico retroativo: cobertura atual — fluxo {cob_fluxo}/{janela}, "
          f"OI {cob_oi}/{janela}, P/C volume {cob_pcvol}/{janela} — buscando o que falta "
          f"(até {janela} pregões)...")

    # 1) FLUXO ESTRANGEIRO: precisa de janela+1 acumulados p/ calcular janela deltas.
    # Chave = data do ARQUIVO (representa "o dia em que um relatório teria sido gerado"),
    # não a data real dos dados (que fica atrasada 2-4 pregões — ver parse_fluxo_acumulado).
    # Isso mantém consistência com o histórico "ao vivo" (atualizar_historico_bdi chamado do
    # screener.py com data_ref=hoje) — o histórico representa "o que sabíamos em cada dia",
    # não "a data que cada dado individualmente descreve".
    acumulados = {}                          # 'AAAA-MM-DD do arquivo' -> (data_real, saldo)
    if precisa_fluxo:
        d, tentativas = dt.date.today(), 0
        while len(acumulados) < janela + 1 and tentativas < max_calendario:
            raw, texto = _fetch_bdi_data_especifica(d, capitulo="02")
            if raw:
                acc = None
                try:
                    acc = parse_fluxo_acumulado(linhas=_pdf_lines(raw), texto=texto)
                except Exception:
                    pass
                if not acc:
                    acc = parse_fluxo_acumulado(texto=texto)
                if acc:
                    data_real = acc.get("data_base") or d
                    acumulados[d.isoformat()] = (data_real, acc["saldo_acum_mes"])
            d -= dt.timedelta(days=1)
            tentativas += 1
        print(f"[bdi_indices] histórico retroativo: fluxo — {len(acumulados)} dias de "
              f"acumulado encontrados em {tentativas} tentativas de calendário.")

    # 2) OI PUT/CALL DO MERCADO: 1 retrato por dia (não precisa de dia anterior)
    ois = {}
    if precisa_oi:
        try:
            from posicoes import parse_oi_pdf, oi_ratios
            d, tentativas = dt.date.today(), 0
            while len(ois) < janela and tentativas < max_calendario:
                raw_oi, _ = _fetch_bdi_data_especifica(d, capitulo="03-4", exigir_marco=False)
                if raw_oi:
                    try:
                        pos = parse_oi_pdf(raw_oi)
                        if pos:
                            r_oi = oi_ratios(pos, ticker_setor=ticker_setor)
                            pc = (r_oi.get("mercado") or {}).get("oi_ratio")
                            if pc is not None and not (isinstance(pc, float) and math.isnan(pc)):
                                ois[d.isoformat()] = pc
                    except Exception as e:
                        print(f"[bdi_indices] histórico retroativo: falha ao parsear OI de "
                              f"{d}: {e}")
                d -= dt.timedelta(days=1)
                tentativas += 1
            print(f"[bdi_indices] histórico retroativo: OI — {len(ois)} dias encontrados em "
                  f"{tentativas} tentativas de calendário.")
        except Exception as e:
            print(f"[bdi_indices] histórico retroativo: OI indisponível ({e}) — só fluxo.")

    # 3) P/C POR VOLUME DO MERCADO: 1 retrato por dia, via COTAHIST (arquivo diário da B3,
    # DIFERENTE do BDI — é o mesmo arquivo que o opcoes.py já usa no dia a dia)
    pcs_vol = {}
    if precisa_pcvol:
        try:
            from opcoes import _baixar_cotahist, parse_cotahist
            d, tentativas = dt.date.today(), 0
            while len(pcs_vol) < janela and tentativas < max_calendario:
                try:
                    texto = _baixar_cotahist(d)
                    opts, _ = parse_cotahist(texto)
                    call_vol = sum(o["volume"] for o in opts if o["tipo"] == "C")
                    put_vol = sum(o["volume"] for o in opts if o["tipo"] == "P")
                    if call_vol > 0:
                        pcs_vol[d.isoformat()] = put_vol / call_vol
                except Exception:
                    pass                                   # dia sem pregão/arquivo -> ignora
                d -= dt.timedelta(days=1)
                tentativas += 1
            print(f"[bdi_indices] histórico retroativo: P/C volume — {len(pcs_vol)} dias "
                  f"encontrados em {tentativas} tentativas de calendário.")
        except Exception as e:
            print(f"[bdi_indices] histórico retroativo: P/C volume indisponível ({e}).")

    # 3) monta as entradas: fluxo_dia = diferença entre acumulados CONSECUTIVOS, usando as
    # DATAS REAIS (não as datas de arquivo) pra decidir "mesmo mês" e "é dado novo mesmo" —
    # mas a entrada final fica salva sob a data do ARQUIVO (dia do relatório).
    LIMITE_DIA_RETRO = 8000.0    # R$ mi — mesmo filtro de sanidade do cálculo diário
    datas_ordenadas = sorted(acumulados.keys())              # datas de ARQUIVO
    novo = {}
    for i, ds in enumerate(datas_ordenadas):
        data_real_cur, saldo_cur = acumulados[ds]
        entry = {"data": ds, "fluxo_acum_mes": saldo_cur}
        if i > 0:
            data_real_prev, saldo_prev = acumulados[datas_ordenadas[i - 1]]
            mesmo_mes = (data_real_prev.year == data_real_cur.year
                        and data_real_prev.month == data_real_cur.month)
            avancou = data_real_cur > data_real_prev      # evita delta=0 quando a data
            if mesmo_mes and avancou:                      # real repete entre 2 arquivos
                delta = saldo_cur - saldo_prev
                if abs(delta) > LIMITE_DIA_RETRO:
                    print(f"[bdi_indices] histórico retroativo: delta de {data_real_prev} a "
                          f"{data_real_cur} implausível (R$ {delta:+,.0f} mi) — descartado "
                          f"(provável revisão de dados pela B3).")
                else:
                    entry["fluxo_dia"] = delta
        novo[ds] = entry
    for ds, pc in ois.items():
        novo.setdefault(ds, {"data": ds})["oi_pc_mercado"] = pc
    for ds, pc in pcs_vol.items():
        novo.setdefault(ds, {"data": ds})["pc_vol_mercado"] = pc

    # funde com o que já existia no cache (existente tem prioridade sobre o retroativo)
    por_data = {e["data"]: dict(e) for e in hist_atual}
    for ds, entry in novo.items():
        if ds not in por_data:
            por_data[ds] = entry
        else:
            for k, v in entry.items():
                por_data[ds].setdefault(k, v)
    hist_final = sorted(por_data.values(), key=lambda e: e["data"])[-janela:]

    try:
        os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({"dias": hist_final}, f)
        print(f"[bdi_indices] histórico retroativo: cache preenchido com {len(hist_final)} "
              f"dias ({hist_final[0]['data'] if hist_final else '—'} a "
              f"{hist_final[-1]['data'] if hist_final else '—'})")
    except Exception as e:
        print(f"[bdi_indices] histórico retroativo: falha ao gravar cache: {e}")
    return hist_final
