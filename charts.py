"""charts.py — gráficos de barras VERTICAIS via matplotlib, embutidos como imagem base64 no
HTML do relatório (PDF e e-mail).

Por quê imagem e não CSS/tabela: o xhtml2pdf (motor do PDF) não sustenta barras verticais via
altura de <div> dentro de célula de tabela de forma confiável (testado — a altura é ignorada
ou quebra o layout internamente). Barras HORIZONTAIS (largura de célula) funcionam bem via
CSS, mas para barras EM PÉ a única forma robusta é gerar a imagem de verdade e embutir com
<img>, que o xhtml2pdf suporta nativamente e sem surpresas.
"""
from __future__ import annotations

import base64
import io


def _fig_to_img_tag(fig, largura_px: int = 680) -> str:
    """Converte uma figura matplotlib em <img> com os bytes embutidos (base64) — não depende
    de nenhum arquivo/URL externo, funciona igual no PDF e no corpo do e-mail.
    IMPORTANTE: usa largura em PIXELS fixos, não % — o xhtml2pdf não interpreta 'width:100%'
    em <img> corretamente (loga 'Not a float' e renderiza a imagem no tamanho natural,
    cortando pra fora da página em vez de encolher)."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=140, bbox_inches="tight", pad_inches=0.15)
    import matplotlib.pyplot as plt
    plt.close(fig)
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode("ascii")
    return (f'<img src="data:image/png;base64,{b64}" width="{largura_px}" '
            f'style="width:{largura_px}px;max-width:100%;display:block;margin:6px 0" />')


def barras_verticais(labels, valores, titulo: str = "", ylabel: str = "",
                     cor_por_sinal: bool = True, cor_fixa: str = "#1f3864",
                     linha_referencia: float = None, fmt_valor: str = "{:+.0f}",
                     figsize=(9, 3.2)) -> str:
    """Gráfico de barras VERTICAIS (em pé). `valores` pode conter None (vira 'n/d', barra
    ausente). `cor_por_sinal`: verde/vermelho conforme positivo/negativo (fluxo); se False,
    usa `cor_fixa` para todas OU um degradê por faixa em torno de `linha_referencia` (ex.:
    Put/Call em torno de 1.0). Retorna a tag <img> pronta para inserir no HTML."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    fig, ax = plt.subplots(figsize=figsize)
    xs = np.arange(len(labels))
    vals_plot = [0 if v is None else v for v in valores]

    if cor_por_sinal:
        cores = ["#16a34a" if (v is not None and v >= 0) else
                ("#dc2626" if v is not None else "#e5e7eb") for v in valores]
    elif linha_referencia is not None:
        cores = []
        for v in valores:
            if v is None:
                cores.append("#e5e7eb")
            elif v >= linha_referencia * 1.2:
                cores.append("#dc2626")
            elif v <= linha_referencia * 0.8:
                cores.append("#16a34a")
            else:
                cores.append("#94a3b8")
    else:
        cores = [cor_fixa if v is not None else "#e5e7eb" for v in valores]

    ax.bar(xs, vals_plot, color=cores, width=0.62, zorder=3)
    if linha_referencia is not None:
        ax.axhline(linha_referencia, color="#6b7280", linewidth=1, linestyle="--", zorder=2)
    ax.axhline(0, color="#9ca3af", linewidth=0.8, zorder=1)
    ax.set_xticks(xs)
    ax.set_xticklabels(labels, fontsize=9, rotation=0)
    ax.set_ylabel(ylabel, fontsize=9)
    if titulo:
        ax.set_title(titulo, fontsize=11, fontweight="bold", loc="left", color="#0f172a")
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(axis="both", labelsize=9, colors="#334155")
    ax.grid(axis="y", color="#e5e7eb", linewidth=0.7, zorder=0)

    for x, v in zip(xs, valores):
        if v is None:
            ax.text(x, 0, "n/d", ha="center", va="bottom", fontsize=8, color="#9ca3af")
        else:
            offset = (max([abs(x) for x in vals_plot] + [1]) * 0.03)
            va = "bottom" if v >= 0 else "top"
            y_txt = v + offset if v >= 0 else v - offset
            ax.text(x, y_txt, fmt_valor.format(v), ha="center", va=va, fontsize=8,
                    color="#1f2937", fontweight="bold")

    fig.tight_layout()
    return _fig_to_img_tag(fig)


def barras_ranking(labels, valores, cores=None, titulo: str = "", xlabel: str = "",
                   fmt_valor=lambda v: f"{v:,.0f}", figsize=(9, 3.6)) -> str:
    """Ranking (top-N) em barras HORIZONTAIS deitadas — mais legível pra nomes de ativos/
    opções longos que não cabem em rótulos verticais. `cores` = lista paralela a `labels`
    (ex.: verde p/ CALL, vermelho p/ PUT); se None, usa uma cor única."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    fig, ax = plt.subplots(figsize=figsize)
    ys = np.arange(len(labels))[::-1]                      # maior valor no topo
    cores = cores or ["#1f3864"] * len(labels)
    ax.barh(ys, valores, color=cores, height=0.62, zorder=3)
    ax.set_yticks(ys)
    ax.set_yticklabels(labels, fontsize=9)
    ax.set_xlabel(xlabel, fontsize=9)
    if titulo:
        ax.set_title(titulo, fontsize=11, fontweight="bold", loc="left", color="#0f172a")
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(axis="both", labelsize=9, colors="#334155")
    ax.grid(axis="x", color="#e5e7eb", linewidth=0.7, zorder=0)
    vmax = max(valores) if valores else 1
    for y, v in zip(ys, valores):
        ax.text(v + vmax * 0.015, y, fmt_valor(v), va="center", fontsize=8,
                color="#1f2937", fontweight="bold")
    fig.tight_layout()
    return _fig_to_img_tag(fig)
