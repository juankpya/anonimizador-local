#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Hook SessionStart: explica a Claude las reglas y avisa si falta instalar.

Corre en cada sesion, asi que no carga ningun modelo. No puede bloquear nada:
la proteccion real la dan los hooks de lectura.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from anonimizador import config  # noqa: E402


def main() -> None:
    config.utf8()
    try:
        carga = json.load(sys.stdin)
    except ValueError:
        carga = {}
    proyecto = config.proyecto_actual(carga)
    cfg = config.cargar(proyecto)
    documentos = ", ".join(cfg["extensiones_documento"])
    carpetas = ", ".join(cfg["carpetas_protegidas"]) or "(ninguna)"

    lineas = [
        "Plugin «anonimizador» activo. Reglas para esta sesion:",
        f"- Para leer documentos ({documentos}) o cualquier fichero de las carpetas "
        f"protegidas ({carpetas}) usa SIEMPRE la herramienta Read con la ruta "
        f"original. El plugin los convierte a Markdown, los anonimiza en local y te "
        f"entrega esa copia. No los abras con Bash, PowerShell, scripts ni otras "
        f"herramientas: se denegara o se pedira confirmacion al usuario.",
        "- En esas copias veras identificadores como PERSONA_1, NIF_2 o CORREO_1. "
        "Son valores opacos y estables en todo el proyecto: escribelos exactamente "
        "igual, sin traducirlos, abreviarlos ni intentar deducir el dato real.",
        "- El usuario ve los datos reales en su pantalla, porque el plugin sustituye "
        "los identificadores al mostrar tus respuestas. No hace falta que le "
        "expliques los identificadores salvo que pregunte.",
        "- Los ficheros que escribas contendran identificadores. El usuario puede "
        "restaurar los datos reales con /anonimizador:revelar <fichero>.",
        "- No leas ~/.anonimizador, ni ficheros '.revelado.', ni modifiques "
        ".anonimizador.json.",
    ]
    salida = {"hookSpecificOutput": {"hookEventName": "SessionStart",
                                     "additionalContext": "\n".join(lineas)}}

    if config.python_del_entorno() is None:
        salida["systemMessage"] = (
            "Anonimizador: faltan las dependencias locales. Ejecuta "
            "/anonimizador:instalar (una sola vez, descarga ~1 GB). Hasta entonces "
            "los documentos protegidos no se podrán leer."
        )
        salida["hookSpecificOutput"]["additionalContext"] += (
            "\n- AVISO: el plugin no esta instalado del todo. Si el usuario pide "
            "leer un documento, indicale que ejecute /anonimizador:instalar."
        )
    print(json.dumps(salida, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"anonimizador/sesion: {exc!r}", file=sys.stderr)
        sys.exit(0)
