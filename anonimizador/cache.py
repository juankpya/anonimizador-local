# -*- coding: utf-8 -*-
"""Cache de copias anonimizadas. Solo biblioteca estandar.

Cada original tiene una copia en ~/.anonimizador/proyectos/<id>/cache/ cuyo
nombre es un hash de la ruta: el nombre del fichero original (que a menudo
lleva el nombre de una persona) no aparece en ella.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from . import __version__, config


def ruta_copia(proyecto: str | os.PathLike, fichero: str | os.PathLike, cfg: dict) -> Path:
    sufijo = Path(fichero).suffix.lower()
    extension = ".md" if sufijo in cfg["extensiones_documento"] else sufijo
    huella = hashlib.sha256(config.normalizar(fichero).encode("utf-8")).hexdigest()[:20]
    return config.dir_cache(proyecto) / f"{huella}{extension}"


def _firma(fichero: str | os.PathLike, cfg: dict) -> dict:
    estado = os.stat(fichero)
    ajustes = json.dumps([cfg.get(k) for k in ("idioma", "modelo", "umbral", "entidades",
                                               "permitidos", "terminos")],
                         ensure_ascii=False, sort_keys=True)
    return {
        "version": __version__,
        "mtime_ns": estado.st_mtime_ns,
        "tamano": estado.st_size,
        "ajustes": hashlib.sha256(ajustes.encode("utf-8")).hexdigest()[:16],
    }


def vigente(proyecto: str | os.PathLike, fichero: str | os.PathLike, cfg: dict) -> dict | None:
    """Metadatos de la copia si existe y el original no ha cambiado; si no, None."""
    copia = ruta_copia(proyecto, fichero, cfg)
    meta = copia.with_name(copia.name + ".meta.json")
    try:
        datos = json.loads(meta.read_text(encoding="utf-8"))
        if copia.is_file() and datos.get("firma") == _firma(fichero, cfg):
            datos["salida"] = str(copia)
            return datos
    except (OSError, ValueError):
        pass
    return None


def anotar(proyecto: str | os.PathLike, fichero: str | os.PathLike, cfg: dict,
           entidades: int, convertido: bool) -> dict:
    copia = ruta_copia(proyecto, fichero, cfg)
    datos = {"firma": _firma(fichero, cfg), "entidades": entidades, "convertido": convertido}
    copia.with_name(copia.name + ".meta.json").write_text(
        json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    datos["salida"] = str(copia)
    return datos
