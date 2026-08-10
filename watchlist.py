"""Leitura da wishlist e da carteira a partir de arquivos .txt.

Formato (um ticker por linha; '#' inicia comentário; linhas vazias ignoradas):
    PETR4
    VALE3        # opcional: comentário
    ITSA4  9.50  # carteira: ticker + preço médio (opcional)
    BBSE3, 34.20 # vírgula também aceita como separador

Arquivos (caminho configurável por env):
    wishlist.txt   (env WISHLIST_FILE)
    carteira.txt   (env CARTEIRA_FILE)

Retornam {ticker: preco_medio|None}. Ausência de arquivo -> {} (nada quebra).
"""
from __future__ import annotations

import os
import re

_TK = re.compile(r"^[A-Z]{4}[0-9]{1,2}$")


def _read(path: str) -> dict:
    out: dict[str, float | None] = {}
    if not path or not os.path.exists(path):
        return out
    try:
        with open(path, encoding="utf-8") as fh:
            for raw in fh:
                line = raw.split("#", 1)[0].strip()
                if not line:
                    continue
                parts = line.replace(",", " ").split()
                tk = parts[0].strip().upper()
                if not _TK.match(tk):
                    continue
                pm = None
                if len(parts) > 1:
                    try:
                        pm = float(parts[1].replace(",", "."))
                        if pm <= 0:
                            pm = None
                    except Exception:
                        pm = None
                out[tk] = pm
    except Exception as e:
        print(f"[watchlist] falha lendo {path}: {e}")
    return out


def get_wishlist() -> dict:
    return _read(os.getenv("WISHLIST_FILE", "wishlist.txt"))


def get_carteira() -> dict:
    return _read(os.getenv("CARTEIRA_FILE", "carteira.txt"))
