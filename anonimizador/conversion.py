# -*- coding: utf-8 -*-
"""Conversion de documentos e imagenes a Markdown, todo en local.

- Word, Excel y PDF con texto: MarkItDown (MIT).
- Imagenes y PDF escaneados: OCR con RapidOCR (Apache-2.0) sobre ONNX Runtime,
  en CPU. Los modelos se descargan una sola vez, durante la instalacion.

Ninguna de las dos rutas hace llamadas de red al convertir.
"""

from __future__ import annotations

from pathlib import Path

# Formatos de imagen que sabe abrir el OCR.
EXT_OCR = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}

# Por debajo de esta confianza el texto reconocido suele ser ruido.
CONFIANZA_MINIMA = 0.5
# Una pagina de PDF con menos caracteres que esto se considera escaneada.
MIN_CARACTERES_PAGINA = 25
# Resolucion al convertir una pagina de PDF en imagen (2 = ~144 ppp).
ESCALA_PDF = 2.0


class SinTexto(Exception):
    """El documento no contiene texto, ni extraible ni reconocible por OCR."""


# --------------------------------------------------------------------------- #
# OCR
# --------------------------------------------------------------------------- #

_motor_ocr = None


def _ocr():
    global _motor_ocr
    if _motor_ocr is None:
        from rapidocr import RapidOCR
        _motor_ocr = RapidOCR(params={"Global.log_level": "error"})
    return _motor_ocr


def _componer(cajas, textos, confianzas) -> str:
    """Ordena los fragmentos reconocidos en lineas y parrafos de lectura."""
    piezas = []
    for caja, texto, confianza in zip(cajas, textos, confianzas):
        if not texto or not texto.strip() or confianza < CONFIANZA_MINIMA:
            continue
        xs, ys = [p[0] for p in caja], [p[1] for p in caja]
        piezas.append({"x": min(xs), "arriba": min(ys), "abajo": max(ys),
                       "centro": (min(ys) + max(ys)) / 2, "texto": texto.strip()})
    if not piezas:
        return ""

    piezas.sort(key=lambda p: p["centro"])
    lineas: list[list[dict]] = []
    for pieza in piezas:
        ultima = lineas[-1] if lineas else None
        alto = pieza["abajo"] - pieza["arriba"]
        # Misma linea si su centro cae dentro de la altura de la linea actual.
        if ultima and abs(pieza["centro"] - ultima[0]["centro"]) < 0.6 * max(
                alto, ultima[0]["abajo"] - ultima[0]["arriba"]):
            ultima.append(pieza)
        else:
            lineas.append([pieza])

    salida: list[str] = []
    previa = None
    for linea in lineas:
        linea.sort(key=lambda p: p["x"])
        arriba = min(p["arriba"] for p in linea)
        abajo = max(p["abajo"] for p in linea)
        # Un hueco vertical mayor que una linea separa parrafos.
        if previa is not None and arriba - previa > 0.9 * (abajo - arriba):
            salida.append("")
        salida.append("  ".join(p["texto"] for p in linea))
        previa = abajo
    return "\n".join(salida)


def ocr_imagen(imagen) -> str:
    """Texto de una imagen (ruta o imagen PIL). Cadena vacia si no hay texto."""
    resultado = _ocr()(imagen)
    if resultado is None or not getattr(resultado, "txts", None):
        return ""
    return _componer(resultado.boxes, resultado.txts, resultado.scores)


# --------------------------------------------------------------------------- #
# PDF
# --------------------------------------------------------------------------- #

def _paginas_escaneadas(fichero: Path) -> tuple[list[int], int]:
    """Indices de las paginas sin capa de texto, y numero total de paginas."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(fichero))
    try:
        vacias = []
        for i in range(len(pdf)):
            capa = pdf[i].get_textpage()
            if len(capa.get_text_range().strip()) < MIN_CARACTERES_PAGINA:
                vacias.append(i)
        return vacias, len(pdf)
    finally:
        pdf.close()


def _ocr_paginas(fichero: Path, indices: list[int]) -> str:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(fichero))
    try:
        bloques = []
        for i in indices:
            imagen = pdf[i].render(scale=ESCALA_PDF).to_pil().convert("RGB")
            texto = ocr_imagen(imagen)
            if texto:
                bloques.append(f"## Página {i + 1}\n\n{texto}")
        return "\n\n".join(bloques)
    finally:
        pdf.close()


def _pdf(fichero: Path) -> tuple[str, bool]:
    escaneadas, total = _paginas_escaneadas(fichero)
    if total and len(escaneadas) == total:
        return _ocr_paginas(fichero, escaneadas), True
    texto = _markitdown(fichero)
    if escaneadas:  # documento mixto: paginas con texto y paginas escaneadas
        extra = _ocr_paginas(fichero, escaneadas)
        if extra:
            return f"{texto}\n\n---\n\n# Páginas escaneadas (texto obtenido por OCR)\n\n{extra}", True
    return texto, False


# --------------------------------------------------------------------------- #

def _markitdown(fichero: Path) -> str:
    from markitdown import MarkItDown

    # enable_plugins=False: sin extensiones de terceros. No se le pasa ningun
    # cliente de LLM, asi que no puede hacer ninguna llamada de red.
    return (MarkItDown(enable_plugins=False).convert(str(fichero)).text_content or "").strip()


def a_markdown(fichero: Path) -> tuple[str, bool]:
    """Devuelve (markdown, se_uso_ocr)."""
    sufijo = fichero.suffix.lower()
    if sufijo in EXT_OCR:
        texto, ocr = ocr_imagen(str(fichero)), True
    elif sufijo == ".pdf":
        texto, ocr = _pdf(fichero)
    else:
        texto, ocr = _markitdown(fichero), False

    if len(texto.strip()) < 3:
        raise SinTexto(f"'{fichero.name}' no contiene texto"
                       f"{' reconocible' if ocr else ' extraible'}.")
    return texto.strip() + "\n", ocr


def leer_texto(fichero: Path) -> str:
    datos = fichero.read_bytes()
    for codificacion in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            return datos.decode(codificacion)
        except UnicodeError:
            continue
    return datos.decode("utf-8", errors="replace")
