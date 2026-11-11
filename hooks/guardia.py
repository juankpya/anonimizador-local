#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Hook PreToolUse: ningun documento llega a Claude sin anonimizar.

Para una lectura (Read) de un documento o de un fichero de carpeta protegida:
  1. lo convierte a Markdown y lo anonimiza en local (o reutiliza la cache), y
  2. cambia la ruta de la lectura por la de la copia anonimizada, usando el
     campo documentado `updatedInput`.
Claude nunca recibe el original.

Para el resto de herramientas hace de guardia: deniega lo que leeria datos sin
anonimizar por otro camino (Edit, Grep, Bash...).

FALLO CERRADO: ante cualquier error se deniega la llamada. Es preferible que
Claude no pueda leer un fichero a que lo lea sin anonimizar.

Solo biblioteca estandar. El trabajo pesado corre como subproceso en el
entorno virtual.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from anonimizador import cache, config  # noqa: E402

EVENTO = "PreToolUse"
SEPARADORES = re.compile(r"[;&|`\n]|\$\(")


def responder(decision: str | None = None, motivo: str = "", **extra) -> None:
    salida = {"hookEventName": EVENTO}
    if decision:
        salida["permissionDecision"] = decision
        salida["permissionDecisionReason"] = motivo
    salida.update(extra)
    print(json.dumps({"hookSpecificOutput": salida}, ensure_ascii=False))
    sys.exit(0)


def denegar(motivo: str) -> None:
    responder("deny", "[Anonimizador] " + motivo)


def absoluta(ruta: str, cwd: str) -> str:
    ruta = os.path.expanduser(ruta)
    return ruta if os.path.isabs(ruta) else os.path.join(cwd, ruta)


# --------------------------------------------------------------------------- #
# Read
# --------------------------------------------------------------------------- #

def anonimizar(proyecto: str, fichero: str, cfg: dict) -> dict:
    previo = cache.vigente(proyecto, fichero, cfg)
    if previo:
        return previo

    interprete = config.python_del_entorno()
    if interprete is None:
        denegar(
            "El plugin aun no esta instalado del todo: faltan las dependencias "
            "locales (Presidio, spaCy, MarkItDown). Pide al usuario que ejecute "
            "/anonimizador:instalar. Hasta entonces este fichero no se puede leer."
        )
    entorno = dict(os.environ, PYTHONPATH=str(RAIZ), PYTHONIOENCODING="utf-8",
                   PYTHONUTF8="1")
    proceso = subprocess.run(
        [str(interprete), "-m", "anonimizador.tuberia", "--proyecto", proyecto, fichero],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(RAIZ), env=entorno, timeout=280,
    )
    lineas = [l for l in proceso.stdout.splitlines() if l.startswith("{")]
    try:
        resultado = json.loads(lineas[-1])
    except (IndexError, ValueError):
        cola = (proceso.stderr or proceso.stdout).strip().splitlines()[-3:]
        denegar("No se pudo anonimizar el fichero: " + " | ".join(cola))
    if "error" in resultado:
        denegar("No se pudo anonimizar el fichero. " + resultado["error"])
    return resultado


def tratar_lectura(entrada: dict, proyecto: str, cwd: str, cfg: dict) -> None:
    ruta = entrada.get("file_path") or ""
    if not ruta:
        sys.exit(0)
    ruta = absoluta(ruta, cwd)
    veredicto = config.clasificar(ruta, proyecto, cfg)

    if veredicto in (config.LIBRE, config.CACHE):
        sys.exit(0)
    if veredicto == config.BLOQUEAR:
        denegar(
            "Este fichero no puede entrar en la conversacion: es una imagen o un "
            "formato sin soporte dentro de una carpeta protegida, un fichero con "
            "datos reales restaurados, o un fichero interno del plugin."
        )
    if veredicto == config.IMAGEN:
        if cfg.get("imagenes") == "bloquear":
            denegar("La configuracion bloquea la lectura de imagenes (no se pueden anonimizar).")
        responder("ask", "[Anonimizador] Las imágenes no se pueden anonimizar "
                         "(el OCR llegará en la versión 0.2). Si contiene datos "
                         "personales, llegarán a Claude tal cual. ¿Leerla igualmente?")
    if not os.path.isfile(ruta):
        sys.exit(0)  # que la herramienta de su propio error de fichero inexistente

    resultado = anonimizar(proyecto, ruta, cfg)
    nueva = dict(entrada)
    nueva["file_path"] = resultado["salida"]
    nueva.pop("pages", None)  # la copia es Markdown, no tiene paginas
    aviso = (
        f"Este fichero se ha anonimizado en local antes de llegarte"
        f"{' (convertido a Markdown)' if resultado.get('convertido') else ''}: "
        f"{resultado.get('entidades', 0)} dato(s) sustituidos por identificadores "
        f"como PERSONA_1 o NIF_1. Usalos tal cual, como valores opacos; el usuario "
        f"ve los datos reales en su pantalla."
    )
    responder("allow", "Lectura redirigida a la copia anonimizada.",
              updatedInput=nueva, additionalContext=aviso)


# --------------------------------------------------------------------------- #
# Edit / Write / NotebookEdit
# --------------------------------------------------------------------------- #

def tratar_escritura(entrada: dict, proyecto: str, cwd: str, cfg: dict) -> None:
    ruta = entrada.get("file_path") or entrada.get("notebook_path") or ""
    if not ruta:
        sys.exit(0)
    ruta = absoluta(ruta, cwd)
    if os.path.basename(ruta).lower() == config.NOMBRE_CONFIG_PROYECTO:
        denegar("La configuracion del anonimizador solo la cambia el usuario, a mano.")
    veredicto = config.clasificar(ruta, proyecto, cfg)
    if veredicto in (config.BLOQUEAR, config.CACHE):
        denegar("No se puede escribir en ficheros protegidos ni en la cache del plugin.")
    if veredicto == config.ANONIMIZAR and (
            config.en_protegida(ruta, proyecto, cfg) or os.path.exists(ruta)):
        denegar(
            "No se puede modificar un original protegido: solo conoces su version "
            "anonimizada. Escribe el resultado en un fichero nuevo fuera de las "
            "carpetas protegidas; el usuario puede restaurar los datos reales con "
            "/anonimizador:revelar."
        )
    sys.exit(0)


# --------------------------------------------------------------------------- #
# Grep
# --------------------------------------------------------------------------- #

def tratar_busqueda(entrada: dict, proyecto: str, cwd: str, cfg: dict) -> None:
    raiz = absoluta(entrada.get("path") or cwd, cwd)
    if os.path.isfile(raiz):
        if config.clasificar(raiz, proyecto, cfg) in (config.ANONIMIZAR, config.BLOQUEAR):
            denegar("No se puede buscar dentro de un original. Leelo con Read: "
                    "recibiras la copia anonimizada.")
        sys.exit(0)
    if config.dentro_de(raiz, config.home()) or config.dentro_de(config.home(), raiz):
        if not config.dentro_de(raiz, config.dir_cache(proyecto)):
            denegar("La busqueda alcanzaria la carpeta privada del plugin "
                    "(~/.anonimizador). Limitala a una carpeta concreta del proyecto.")
    for carpeta in config.carpetas_protegidas(proyecto, cfg):
        if not os.path.isdir(carpeta):
            continue
        if config.dentro_de(raiz, carpeta) or config.dentro_de(carpeta, raiz):
            denegar(
                f"La busqueda alcanzaria la carpeta protegida "
                f"'{os.path.basename(carpeta)}', que contiene originales sin "
                f"anonimizar. Limita la busqueda a otra subcarpeta, o lee los "
                f"documentos uno a uno con Read."
            )
    sys.exit(0)


# --------------------------------------------------------------------------- #
# Bash / PowerShell  (mejor esfuerzo: no se interpreta el lenguaje de la shell)
# --------------------------------------------------------------------------- #

def tratar_orden(entrada: dict, proyecto: str, cwd: str, cfg: dict) -> None:
    orden = str(entrada.get("command") or "")
    if not orden:
        sys.exit(0)
    plana = orden.replace("\\", "/").lower()

    # Las ordenes propias del plugin (preparar, revelar, estado, instalar) son
    # el camino previsto: se autorizan sin preguntar, siempre que el guion sea
    # el de ESTE plugin y no lleven nada encadenado ni redirigido.
    propio = re.search(r"""["']?([^"'\s]*(?:anonimizar|instalar)\.py)["']?""", orden)
    if propio and not SEPARADORES.search(orden) and "<" not in orden and ">" not in orden:
        guion = re.search(r"""["']([^"']*(?:anonimizar|instalar)\.py)["']""", orden)
        ruta_guion = guion.group(1) if guion else propio.group(1)
        if config.dentro_de(absoluta(ruta_guion, cwd), RAIZ):
            responder("allow", "Orden propia del plugin anonimizador.")

    if ".anonimizador" in plana or ".revelado" in plana:
        denegar("Esta orden toca la carpeta privada del plugin, su configuracion o "
                "un fichero con datos reales restaurados.")

    for carpeta in config.carpetas_protegidas(proyecto, cfg):
        if not os.path.isdir(carpeta):
            continue
        nombre = re.escape(os.path.basename(carpeta))
        relativa = re.escape(os.path.relpath(carpeta, cwd).replace("\\", "/").lower()) \
            if config.dentro_de(carpeta, cwd) else None
        if carpeta in plana \
                or (relativa and re.search(rf"(?<![\w.-]){relativa}(?![\w.-])", plana)) \
                or re.search(rf"(?<![\w.-]){nombre}/", plana):
            denegar(
                f"Esta orden hace referencia a la carpeta protegida "
                f"'{os.path.basename(carpeta)}'. Sus ficheros solo pueden leerse "
                f"con Read, que entrega la copia anonimizada."
            )

    extensiones = "|".join(re.escape(e.lstrip(".")) for e in cfg["extensiones_documento"])
    patron = re.compile(
        rf"""["']([^"'\n]+\.(?:{extensiones}))["']|([^\s"'<>|;&()]+\.(?:{extensiones}))(?![\w.])""",
        re.IGNORECASE)
    for m in patron.finditer(orden):
        candidata = absoluta(m.group(1) or m.group(2), cwd)
        if os.path.isfile(candidata) and \
                config.clasificar(candidata, proyecto, cfg) == config.ANONIMIZAR:
            responder(
                "ask",
                f"[Anonimizador] Esta orden usa el documento "
                f"'{os.path.basename(candidata)}' directamente, sin pasar por el "
                f"anonimizado. Si muestra su contenido, llegará a Claude tal cual. "
                f"¿Ejecutarla igualmente?",
            )
    sys.exit(0)


# --------------------------------------------------------------------------- #

def main() -> None:
    config.utf8()
    carga = json.load(sys.stdin)
    herramienta = carga.get("tool_name", "")
    entrada = carga.get("tool_input") or {}
    cwd = carga.get("cwd") or os.getcwd()
    proyecto = config.proyecto_actual(carga)
    cfg = config.cargar(proyecto)

    if herramienta == "Read":
        tratar_lectura(entrada, proyecto, cwd, cfg)
    elif herramienta in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        tratar_escritura(entrada, proyecto, cwd, cfg)
    elif herramienta == "Grep":
        tratar_busqueda(entrada, proyecto, cwd, cfg)
    elif herramienta in ("Bash", "PowerShell"):
        tratar_orden(entrada, proyecto, cwd, cfg)
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001 - fallo cerrado
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": EVENTO,
            "permissionDecision": "deny",
            "permissionDecisionReason":
                f"[Anonimizador] Error interno del hook ({type(exc).__name__}: {exc}). "
                f"Por seguridad se deniega la llamada.",
        }}, ensure_ascii=False))
        sys.exit(0)
