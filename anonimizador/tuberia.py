# -*- coding: utf-8 -*-
"""Tuberia completa: convertir a Markdown -> detectar -> sustituir -> cache.

Se ejecuta dentro del entorno virtual (necesita Presidio, spaCy y MarkItDown).
Los hooks la invocan como subproceso:

    python -m anonimizador.tuberia --proyecto DIR FICHERO [FICHERO...]

y leen de la salida estandar una linea JSON por fichero.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from . import cache, config, conversion
from .mapa import Mapa
from .motor import Detector, crear_analizador

_analizador = None


def _obtener_analizador(cfg: dict):
    global _analizador
    if _analizador is None:
        _analizador = crear_analizador(cfg["idioma"], cfg["modelo"])
    return _analizador


def procesar(proyecto: str, fichero: str, cfg: dict | None = None,
             destino: Path | None = None) -> dict:
    """Anonimiza un fichero. Devuelve {"salida", "entidades", "convertido"}.

    Con 'destino' escribe ahi (uso desde la linea de comandos); sin el, usa la
    cache del proyecto.
    """
    cfg = cfg or config.cargar(proyecto)
    origen = Path(fichero)
    if not origen.is_file():
        raise FileNotFoundError(f"No existe: {origen}")

    if destino is None:
        previo = cache.vigente(proyecto, origen, cfg)
        if previo:
            return previo

    convertido = origen.suffix.lower() in cfg["extensiones_documento"]
    texto = conversion.a_markdown(origen) if convertido else conversion.leer_texto(origen)

    mapa = Mapa(proyecto)
    with mapa.bloqueo():
        detector = Detector(_obtener_analizador(cfg), mapa, cfg)
        detector.observar(texto)
        mapa.guardar()
        limpio = mapa.sustituir(texto)

    salida = destino or cache.ruta_copia(proyecto, origen, cfg)
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(limpio, encoding="utf-8")

    # Informe de detecciones: contiene los valores reales, se queda en la
    # carpeta privada del plugin y nunca junto a la copia anonimizada.
    informes = config.dir_proyecto(proyecto) / "detecciones"
    informes.mkdir(parents=True, exist_ok=True)
    with (informes / (cache.ruta_copia(proyecto, origen, cfg).stem + ".csv")).open(
            "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["pseudonimo", "tipo", "confianza",
                                           "original", "procedencia"])
        w.writeheader()
        w.writerows(detector.detecciones)

    unicas = len({d["pseudonimo"] for d in detector.detecciones})
    if destino is None:
        return cache.anotar(proyecto, origen, cfg, unicas, convertido)
    return {"salida": str(salida), "entidades": unicas, "convertido": convertido}


def main(argv: list[str] | None = None) -> int:
    config.utf8()
    ap = argparse.ArgumentParser(prog="anonimizador.tuberia")
    ap.add_argument("--proyecto", required=True)
    ap.add_argument("ficheros", nargs="+")
    args = ap.parse_args(argv)

    cfg = config.cargar(args.proyecto)
    estado = 0
    for fichero in args.ficheros:
        try:
            print(json.dumps(procesar(args.proyecto, fichero, cfg), ensure_ascii=False))
        except Exception as exc:  # noqa: BLE001 - el error viaja al hook como dato
            print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
            estado = 1
        sys.stdout.flush()
    return estado


if __name__ == "__main__":
    sys.exit(main())
