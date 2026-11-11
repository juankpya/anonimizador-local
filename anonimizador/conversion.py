# -*- coding: utf-8 -*-
"""Conversion de documentos a Markdown con MarkItDown (MIT), todo en local."""

from __future__ import annotations

from pathlib import Path


class SinTexto(Exception):
    """El documento no contiene texto extraible (p. ej. un PDF escaneado)."""


def a_markdown(fichero: Path) -> str:
    from markitdown import MarkItDown

    # enable_plugins=False: sin extensiones de terceros. No se le pasa ningun
    # cliente de LLM, asi que no puede hacer ninguna llamada de red.
    resultado = MarkItDown(enable_plugins=False).convert(str(fichero))
    texto = (resultado.text_content or "").strip()
    if len(texto) < 20:
        raise SinTexto(
            f"'{fichero.name}' no contiene texto extraible. Si es un documento "
            f"escaneado necesita OCR, que llegara en la version 0.2."
        )
    return texto + "\n"


def leer_texto(fichero: Path) -> str:
    datos = fichero.read_bytes()
    for codificacion in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            return datos.decode(codificacion)
        except UnicodeError:
            continue
    return datos.decode("utf-8", errors="replace")
