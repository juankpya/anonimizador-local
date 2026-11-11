# -*- coding: utf-8 -*-
"""Deteccion rapida de datos sensibles en un prompt. Solo biblioteca estandar.

Se ejecuta en cada mensaje que escribes, asi que no puede cargar ningun modelo:
usa expresiones regulares con digito de control (pocas falsas alarmas) y los
valores reales que el proyecto ya conoce por documentos anteriores.

LIMITE CONOCIDO: un nombre propio que no haya aparecido antes en ningun
documento anonimizado NO se detecta aqui. Para eso haria falta el modelo de
lenguaje, que tarda varios segundos en cargar.
"""

from __future__ import annotations

import re

_LETRAS_NIF = "TRWAGMYFPDXBNJZSQVHLCKE"

_RE_NIF = re.compile(r"(?<![A-Za-z0-9])(\d{8})[ -]?([A-Za-z])(?![A-Za-z0-9])")
_RE_NIE = re.compile(r"(?<![A-Za-z0-9])([XYZxyz])[ -]?(\d{7})[ -]?([A-Za-z])(?![A-Za-z0-9])")
_RE_IBAN = re.compile(r"(?<![A-Za-z0-9])([A-Za-z]{2}\d{2}(?:[ -]?[A-Za-z0-9]{4}){2,7}(?:[ -]?[A-Za-z0-9]{1,3})?)(?![A-Za-z0-9])")
_RE_CORREO = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_RE_TELEFONO = re.compile(
    r"(?<![\d+])(?:(?:\+|00)34[ .-]?)?[6789]\d{2}(?:[ .-]?\d{3}){2}(?!\d)"
    r"|(?<![\d+])(?:(?:\+|00)34[ .-]?)?[6789]\d{2}(?:[ .-]?\d{2}){3}(?!\d)"
)
_RE_TARJETA = re.compile(r"(?<![\d])(?:\d[ -]?){12,18}\d(?!\d)")
_RE_IMAGEN = re.compile(r"\[(?:Image|Imagen|Pasted image)[^\]\n]{0,40}#?\d+\]", re.IGNORECASE)
# Ruta mencionada con @ (Claude Code incrusta el contenido sin pasar por la
# herramienta de lectura) o ruta suelta, con o sin comillas.
_RE_RUTA = re.compile(
    r"""(@?)(?:"([^"\n]+\.[A-Za-z0-9]{2,5})"|'([^'\n]+\.[A-Za-z0-9]{2,5})'|((?:[A-Za-z]:)?[^\s"'<>|*?]+\.[A-Za-z0-9]{2,5}))"""
)


def _nif_valido(numero: str, letra: str) -> bool:
    return _LETRAS_NIF[int(numero) % 23] == letra.upper()


def _iban_valido(iban: str) -> bool:
    limpio = re.sub(r"[ -]", "", iban).upper()
    if not 15 <= len(limpio) <= 34:
        return False
    reordenado = limpio[4:] + limpio[:4]
    try:
        return int("".join(str(int(c, 36)) for c in reordenado)) % 97 == 1
    except ValueError:
        return False


def _luhn(numero: str) -> bool:
    digitos = [int(c) for c in numero if c.isdigit()]
    if not 13 <= len(digitos) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digitos)):
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def enmascarar(valor: str) -> str:
    """Muestra lo justo para que reconozcas el dato sin repetirlo entero."""
    v = valor.strip()
    if len(v) <= 4:
        return v[0] + "…"
    return f"{v[:2]}…{v[-2:]}"


def detectar(texto: str, permitidos: set[str] = frozenset()) -> list[tuple[str, str]]:
    """Devuelve [(tipo, valor)] sin repetidos, en orden de aparicion."""
    hallazgos: list[tuple[str, str]] = []
    vistos: set[str] = set()
    ocupados: list[tuple[int, int]] = []

    def anotar(tipo: str, m: re.Match) -> None:
        valor = m.group(0).strip()
        if valor.casefold() in permitidos or valor.casefold() in vistos:
            return
        if any(a < m.end() and m.start() < b for a, b in ocupados):
            return  # ya contado dentro de otro dato (un telefono dentro de un IBAN)
        vistos.add(valor.casefold())
        ocupados.append(m.span())
        hallazgos.append((tipo, valor))

    for m in _RE_IBAN.finditer(texto):
        if _iban_valido(m.group(1)):
            anotar("IBAN", m)
    for m in _RE_TARJETA.finditer(texto):
        if _luhn(m.group(0)):
            anotar("tarjeta", m)
    for m in _RE_NIF.finditer(texto):
        if _nif_valido(m.group(1), m.group(2)):
            anotar("NIF", m)
    for m in _RE_NIE.finditer(texto):
        if _nif_valido(str("XYZ".index(m.group(1).upper())) + m.group(2), m.group(3)):
            anotar("NIE", m)
    for m in _RE_CORREO.finditer(texto):
        anotar("correo", m)
    for m in _RE_TELEFONO.finditer(texto):
        anotar("teléfono", m)
    return hallazgos


def imagenes_adjuntas(texto: str) -> int:
    return len(_RE_IMAGEN.findall(texto))


def rutas_mencionadas(texto: str) -> list[tuple[bool, str]]:
    """Rutas de fichero citadas en el prompt: [(con_arroba, ruta)]."""
    salida = []
    for m in _RE_RUTA.finditer(texto):
        ruta = m.group(2) or m.group(3) or m.group(4)
        if ruta and "://" not in ruta:
            salida.append((bool(m.group(1)), ruta.rstrip(".,;:)")))
    return salida
