# -*- coding: utf-8 -*-
"""Configuracion y clasificacion de rutas. Solo biblioteca estandar.

Donde vive cada cosa:
    ~/.anonimizador/                    (o $ANONIMIZADOR_HOME)
        config.json                     configuracion global, opcional
        venv/                           entorno con Presidio, spaCy y MarkItDown
        proyectos/<id>/mapa.json        mapa pseudonimo <-> valor real  (SENSIBLE)
        proyectos/<id>/detecciones/     informes CSV                    (SENSIBLE)
        proyectos/<id>/cache/           copias anonimizadas (lo unico que lee Claude)
    <proyecto>/.anonimizador.json       configuracion del proyecto, opcional

Nada sensible se guarda dentro del proyecto ni dentro del plugin.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

NOMBRE_CONFIG_PROYECTO = ".anonimizador.json"

EXT_IMAGEN = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".heic"}

POR_DEFECTO = {
    # Carpetas (relativas a la raiz del proyecto, o absolutas) cuyo contenido
    # se anonimiza SIEMPRE, sea cual sea la extension.
    "carpetas_protegidas": ["originales", "privado", "confidencial"],
    # Documentos de oficina: se convierten a Markdown y se anonimizan esten
    # donde esten, porque nunca son codigo fuente.
    "documentos_en_todas_partes": True,
    "extensiones_documento": [".docx", ".pdf", ".xlsx"],
    # Texto plano: solo se anonimiza dentro de las carpetas protegidas.
    "extensiones_texto": [".txt", ".md", ".json", ".xml", ".csv", ".log",
                          ".yaml", ".yml", ".eml", ".html", ".htm"],
    # Imagenes fuera de carpetas protegidas: "preguntar" | "permitir" | "bloquear".
    # Dentro de una carpeta protegida siempre se bloquean (sin OCR no hay forma
    # de anonimizarlas).
    "imagenes": "preguntar",
    # Aviso antes de enviar un prompt con datos sensibles o adjuntos.
    "avisar_prompt": True,
    "minutos_confirmacion": 10,
    # Sustituir en pantalla los pseudonimos por los valores reales.
    "revelar_en_pantalla": True,
    # Literales que nunca deben anonimizarse / que deben anonimizarse siempre.
    "permitidos": [],
    "terminos": [],
    # Motor de deteccion.
    "idioma": "es",
    "modelo": "es_core_news_lg",
    "umbral": 0.35,
    "entidades": [
        "PERSON", "ES_NIF", "ES_NIE", "ES_PASSPORT", "EMAIL_ADDRESS",
        "PHONE_NUMBER", "IBAN_CODE", "CREDIT_CARD", "IP_ADDRESS", "LOCATION",
        "MEDICAL_LICENSE", "CRYPTO",
    ],
}


def home() -> Path:
    personalizado = os.environ.get("ANONIMIZADOR_HOME")
    return Path(personalizado) if personalizado else Path.home() / ".anonimizador"


def raiz_plugin() -> Path:
    return Path(__file__).resolve().parent.parent


def normalizar(ruta: str | os.PathLike) -> str:
    """Ruta absoluta comparable: sin '..', separador '/', minusculas en Windows."""
    texto = os.path.normpath(os.path.abspath(os.path.expanduser(str(ruta))))
    texto = texto.replace("\\", "/")
    return texto.lower() if os.name == "nt" else texto


def dentro_de(ruta: str | os.PathLike, carpeta: str | os.PathLike) -> bool:
    r, c = normalizar(ruta), normalizar(carpeta).rstrip("/")
    return r == c or r.startswith(c + "/")


def id_proyecto(proyecto: str | os.PathLike) -> str:
    return hashlib.sha256(normalizar(proyecto).encode("utf-8")).hexdigest()[:16]


def dir_proyecto(proyecto: str | os.PathLike) -> Path:
    return home() / "proyectos" / id_proyecto(proyecto)


def dir_cache(proyecto: str | os.PathLike) -> Path:
    return dir_proyecto(proyecto) / "cache"


def _leer_json(ruta: Path) -> dict:
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8-sig"))
        return datos if isinstance(datos, dict) else {}
    except (OSError, ValueError):
        return {}


def cargar(proyecto: str | os.PathLike) -> dict:
    """Valores por defecto < config global < config del proyecto."""
    cfg = dict(POR_DEFECTO)
    cfg.update(_leer_json(home() / "config.json"))
    cfg.update(_leer_json(Path(proyecto) / NOMBRE_CONFIG_PROYECTO))
    for clave in ("extensiones_documento", "extensiones_texto"):
        cfg[clave] = [e.lower() if e.startswith(".") else "." + e.lower()
                      for e in cfg.get(clave, [])]
    return cfg


def carpetas_protegidas(proyecto: str | os.PathLike, cfg: dict) -> list[str]:
    """Rutas normalizadas de las carpetas protegidas."""
    salida = []
    for carpeta in cfg.get("carpetas_protegidas", []):
        p = Path(os.path.expanduser(str(carpeta)))
        if not p.is_absolute():
            p = Path(proyecto) / p
        salida.append(normalizar(p))
    return salida


def en_protegida(ruta: str | os.PathLike, proyecto: str | os.PathLike, cfg: dict) -> bool:
    return any(dentro_de(ruta, c) for c in carpetas_protegidas(proyecto, cfg))


# Veredictos de clasificar()
LIBRE = "libre"            # no es asunto del plugin
ANONIMIZAR = "anonimizar"  # convertir/anonimizar y redirigir la lectura
IMAGEN = "imagen"          # imagen fuera de carpeta protegida
BLOQUEAR = "bloquear"      # no debe entrar nunca en el contexto
CACHE = "cache"            # copia ya anonimizada


def clasificar(ruta: str | os.PathLike, proyecto: str | os.PathLike, cfg: dict) -> str:
    r = normalizar(ruta)
    nombre = r.rsplit("/", 1)[-1]
    sufijo = os.path.splitext(nombre)[1]

    if dentro_de(r, home()):
        # Dentro de la carpeta del plugin solo se puede leer la cache.
        return CACHE if "/cache/" in r else BLOQUEAR
    if ".revelado." in nombre or nombre.endswith(".revelado"):
        return BLOQUEAR  # ficheros con los datos reales restaurados

    protegida = en_protegida(r, proyecto, cfg)
    if sufijo in cfg["extensiones_documento"]:
        if protegida or cfg.get("documentos_en_todas_partes", True):
            return ANONIMIZAR
        return LIBRE
    if sufijo in EXT_IMAGEN:
        if protegida:
            return BLOQUEAR
        return LIBRE if cfg.get("imagenes") == "permitir" else IMAGEN
    if protegida:
        return ANONIMIZAR if sufijo in cfg["extensiones_texto"] else BLOQUEAR
    return LIBRE


def python_del_entorno() -> Path | None:
    """Interprete con las dependencias pesadas instaladas, o None si no hay."""
    candidatos = []
    forzado = os.environ.get("ANONIMIZADOR_PYTHON")
    if forzado:
        candidatos.append(Path(forzado))
    sub = ("Scripts", "python.exe") if os.name == "nt" else ("bin", "python")
    candidatos.append(home() / "venv" / sub[0] / sub[1])
    candidatos.append(raiz_plugin() / ".venv" / sub[0] / sub[1])  # desarrollo
    for c in candidatos:
        if c.is_file():
            return c
    return None


def proyecto_actual(carga: dict | None = None) -> str:
    """Raiz del proyecto para un hook: variable de entorno, o el cwd recibido."""
    return (os.environ.get("CLAUDE_PROJECT_DIR")
            or (carga or {}).get("cwd")
            or os.getcwd())


def utf8() -> None:
    """Fuerza UTF-8 en la E/S estandar (Windows usa cp1252 por defecto)."""
    for flujo in (sys.stdin, sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
