# -*- coding: utf-8 -*-
"""Mapa persistente pseudonimo <-> valor real, uno por proyecto.

Solo biblioteca estandar: lo usan los hooks de prompt y de pantalla, que deben
responder en milisegundos.

El mapa es por PROYECTO y no por documento: "Maria Fernandez" es PERSONA_1 en
todos los ficheros y en todas las sesiones, de modo que Claude puede cruzar
documentos y el revelado en pantalla funciona tambien al reanudar una sesion.

El fichero contiene los datos reales. Vive en ~/.anonimizador, fuera del
proyecto, y los hooks impiden que Claude lo lea.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import time
from pathlib import Path

from . import config

PREFIJOS = {
    "PERSON": "PERSONA",
    "ES_NIF": "NIF",
    "ES_NIE": "NIE",
    "ES_PASSPORT": "PASAPORTE",
    "EMAIL_ADDRESS": "CORREO",
    "PHONE_NUMBER": "TELEFONO",
    "IBAN_CODE": "IBAN",
    "CREDIT_CARD": "TARJETA",
    "IP_ADDRESS": "IP",
    "LOCATION": "LUGAR",
    "MEDICAL_LICENSE": "LICENCIA_MEDICA",
    "CRYPTO": "CRIPTO",
    "DATE_TIME": "FECHA",
    "URL": "URL",
    "NRP": "GRUPO",
    "MAC_ADDRESS": "MAC",
    "UUID": "UUID",
    "TERMINO_PROPIO": "TERMINO",
}

# Literales mas cortos se ignoran: un token de 2 caracteres ("E2") detectado
# como LUGAR destrozaria formulas y referencias. Ningun identificador real es
# tan corto.
LONGITUD_MINIMA = 3

_ALFANUM = "A-Za-z0-9ÁÉÍÓÚÜÑáéíóúüñ"


def clave(literal: str) -> str:
    """Forma canonica: sin distinguir mayusculas ni cantidad de espacios."""
    return " ".join(literal.split()).casefold()


class Mapa:
    def __init__(self, proyecto: str | os.PathLike):
        self.dir = config.dir_proyecto(proyecto)
        self.ruta = self.dir / "mapa.json"
        self.contadores: dict[str, int] = {}
        self.claves: dict[str, str] = {}   # clave canonica -> pseudonimo
        self.reales: dict[str, str] = {}   # pseudonimo -> literal tal como se vio
        self.tipos: dict[str, str] = {}    # pseudonimo -> tipo de entidad
        self._patron_sustituir = None
        self._patron_revelar = None
        self.cargar()

    # -- persistencia ------------------------------------------------------- #

    def cargar(self) -> None:
        try:
            datos = json.loads(self.ruta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        self.contadores = dict(datos.get("contadores", {}))
        self.claves = dict(datos.get("claves", {}))
        self.reales = dict(datos.get("reales", {}))
        self.tipos = dict(datos.get("tipos", {}))
        self._patron_sustituir = self._patron_revelar = None

    def guardar(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        temporal = self.ruta.with_suffix(".tmp")
        temporal.write_text(json.dumps({
            "version": 1,
            "contadores": self.contadores,
            "claves": self.claves,
            "reales": self.reales,
            "tipos": self.tipos,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(temporal, self.ruta)

    @contextlib.contextmanager
    def bloqueo(self, espera: float = 60.0):
        """Exclusion entre procesos para el ciclo cargar-modificar-guardar."""
        self.dir.mkdir(parents=True, exist_ok=True)
        cerrojo = self.dir / "mapa.lock"
        limite = time.time() + espera
        while True:
            try:
                os.close(os.open(cerrojo, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                break
            except FileExistsError:
                try:
                    if time.time() - cerrojo.stat().st_mtime > 120:
                        cerrojo.unlink()  # cerrojo huerfano de un proceso muerto
                        continue
                except OSError:
                    pass
                if time.time() > limite:
                    raise TimeoutError("el mapa esta bloqueado por otro proceso")
                time.sleep(0.1)
        try:
            self.cargar()
            yield self
        finally:
            with contextlib.suppress(OSError):
                cerrojo.unlink()

    # -- registro ----------------------------------------------------------- #

    def registrar(self, literal: str, tipo: str) -> str | None:
        """Devuelve el pseudonimo del literal, creandolo si es nuevo."""
        literal = literal.strip()
        if len(literal) < LONGITUD_MINIMA:
            return None
        k = clave(literal)
        pseudo = self.claves.get(k)
        if pseudo is None:
            self.contadores[tipo] = self.contadores.get(tipo, 0) + 1
            pseudo = f"{PREFIJOS.get(tipo, tipo)}_{self.contadores[tipo]}"
            self.claves[k] = pseudo
            self.reales[pseudo] = literal
            self.tipos[pseudo] = tipo
            self._patron_sustituir = self._patron_revelar = None
        return pseudo

    # -- sustitucion -------------------------------------------------------- #

    def _compilar_sustituir(self):
        if self._patron_sustituir is None and self.claves:
            # Mas largo primero: "Juan Perez" antes que "Juan".
            ordenadas = sorted(self.claves, key=len, reverse=True)
            partes = [re.escape(k).replace(r"\ ", r"[ \t]+") for k in ordenadas]
            # Limites de palabra: sin ellos "Ana" se comeria parte de "Anastasia".
            self._patron_sustituir = re.compile(
                rf"(?<![{_ALFANUM}_])(?:" + "|".join(partes) + rf")(?![{_ALFANUM}_])",
                re.IGNORECASE,
            )
        return self._patron_sustituir

    def sustituir(self, texto: str) -> str:
        patron = self._compilar_sustituir()
        if not texto or patron is None:
            return texto
        return patron.sub(lambda m: self.claves.get(clave(m.group(0)), m.group(0)), texto)

    def buscar_reales(self, texto: str) -> list[tuple[str, str]]:
        """Valores reales ya conocidos que aparecen en el texto: (literal, tipo)."""
        patron = self._compilar_sustituir()
        if not texto or patron is None:
            return []
        vistos, salida = set(), []
        for m in patron.finditer(texto):
            pseudo = self.claves.get(clave(m.group(0)))
            if pseudo and pseudo not in vistos:
                vistos.add(pseudo)
                salida.append((m.group(0), self.tipos.get(pseudo, "")))
        return salida

    # -- revelado ----------------------------------------------------------- #

    def _compilar_revelar(self):
        if self._patron_revelar is None and self.reales:
            prefijos = sorted({p.rsplit("_", 1)[0] for p in self.reales},
                              key=len, reverse=True)
            # Admite el guion bajo escapado ("PERSONA\_1") que a veces produce
            # el Markdown, y exige que no haya letras ni digitos pegados.
            self._patron_revelar = re.compile(
                r"(?<![A-Za-z0-9])(" + "|".join(re.escape(p) for p in prefijos)
                + r")\\?_(\d+)(?![A-Za-z0-9])"
            )
        return self._patron_revelar

    def revelar(self, texto: str) -> tuple[str, int]:
        """Restaura los valores reales. Devuelve (texto, numero de cambios)."""
        patron = self._compilar_revelar()
        if not texto or patron is None:
            return texto, 0
        cambios = 0

        def _cambio(m):
            nonlocal cambios
            real = self.reales.get(f"{m.group(1)}_{m.group(2)}")
            if real is None:
                return m.group(0)
            cambios += 1
            return real

        return patron.sub(_cambio, texto), cambios


def hay_mapa(proyecto: str | os.PathLike) -> bool:
    return (config.dir_proyecto(proyecto) / "mapa.json").is_file()
