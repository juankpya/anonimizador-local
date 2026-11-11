#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Instalador: crea el entorno local con Presidio, spaCy y MarkItDown.

    python instalar.py            instala en ~/.anonimizador/venv
    python instalar.py --modelo es_core_news_md    modelo mas ligero (~40 MB)

Es el UNICO paso que usa la red: descarga los paquetes de PyPI y el modelo de
lenguaje de spaCy. Despues todo funciona sin conexion.

Solo biblioteca estandar, para poder ejecutarse con cualquier Python.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))

from anonimizador import config  # noqa: E402

# spaCy publica binarios para estas versiones; con otras, pip intentaria
# compilar desde el codigo fuente y fallaria en la mayoria de equipos.
VERSIONES = [(3, 12), (3, 13), (3, 11), (3, 10)]


def _version(orden: list[str]) -> tuple[int, int] | None:
    try:
        salida = subprocess.run(
            orden + ["-c", "import sys; print(sys.version_info[0], sys.version_info[1])"],
            capture_output=True, text=True, timeout=20)
        mayor, menor = salida.stdout.split()
        return int(mayor), int(menor)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def buscar_python() -> list[str] | None:
    """Un interprete compatible: el actual si vale, o uno instalado al lado."""
    if sys.version_info[:2] in VERSIONES:
        return [sys.executable]
    candidatos: list[list[str]] = []
    for mayor, menor in VERSIONES:
        if os.name == "nt" and shutil.which("py"):
            candidatos.append(["py", f"-{mayor}.{menor}"])
        candidatos.append([f"python{mayor}.{menor}"])
    for orden in candidatos:
        if shutil.which(orden[0]) and _version(orden) in VERSIONES:
            return orden
    return None


def ejecutar(orden: list[str]) -> None:
    print("  $ " + " ".join(str(o) for o in orden), flush=True)
    subprocess.run(orden, check=True)


def main() -> int:
    config.utf8()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--modelo", default=None,
                    help="Modelo de spaCy (por defecto, el de la configuracion: es_core_news_lg)")
    args = ap.parse_args()

    modelo = args.modelo or config.cargar(os.getcwd())["modelo"]
    destino = config.home() / "venv"
    sub = ("Scripts", "python.exe") if os.name == "nt" else ("bin", "python")
    interprete = destino / sub[0] / sub[1]

    if not interprete.is_file():
        base = buscar_python()
        if base is None:
            print("No se ha encontrado un Python compatible (3.10 a 3.13). "
                  "Instala Python 3.12 desde https://www.python.org/downloads/ "
                  "y vuelve a ejecutar este instalador.", file=sys.stderr)
            return 2
        print(f"[1/4] Creando el entorno en {destino}")
        destino.parent.mkdir(parents=True, exist_ok=True)
        ejecutar(base + ["-m", "venv", str(destino)])
    else:
        print(f"[1/4] El entorno ya existe en {destino}")

    print("[2/4] Instalando dependencias (Presidio, spaCy, MarkItDown, RapidOCR)")
    ejecutar([str(interprete), "-m", "pip", "install", "--quiet", "--upgrade", "pip"])
    ejecutar([str(interprete), "-m", "pip", "install", "--quiet",
              "-r", str(RAIZ / "requirements.txt")])

    print(f"[3/4] Descargando el modelo de lenguaje {modelo}")
    comprobacion = subprocess.run(
        [str(interprete), "-c", f"import spacy; spacy.load('{modelo}')"],
        capture_output=True)
    if comprobacion.returncode != 0:
        ejecutar([str(interprete), "-m", "spacy", "download", modelo])
    else:
        print("  ya estaba instalado")

    # RapidOCR puede descargar sus modelos en el primer uso: se fuerza ahora
    # para que despues no haga falta la red.
    print("[4/4] Preparando los modelos de OCR")
    ejecutar([str(interprete), "-c",
              "from PIL import Image, ImageDraw; from rapidocr import RapidOCR; "
              "i = Image.new('RGB', (320, 80), 'white'); "
              "ImageDraw.Draw(i).text((10, 30), 'prueba 123', fill='black'); "
              "RapidOCR(params={'Global.log_level': 'error'})(i); print('  listos')"])

    print("\nInstalacion completada. A partir de ahora todo funciona sin conexion.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as exc:
        print(f"\nLa instalacion ha fallado en: {' '.join(str(o) for o in exc.cmd)}",
              file=sys.stderr)
        sys.exit(1)
