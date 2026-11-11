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
    carpetas = ", ".join(cfg["carpetas_protegidas"]) or "(ninguna)"
    # Read rechaza estos formatos como "binarios" ANTES de consultar a los
    # hooks, asi que no se pueden redirigir: necesitan un paso previo.
    binarios = [e for e in cfg["extensiones_documento"] if e != ".pdf"]
    guion = str(RAIZ / "anonimizar.py").replace("\\", "/")
    carpeta = str(Path(proyecto)).replace("\\", "/")
    orden = f'python "{guion}" --proyecto "{carpeta}" --preparar "<ruta del documento>"'

    lineas = [
        "Plugin «anonimizador» activo. Reglas para esta sesion:",
        f"- Documentos {', '.join(binarios)}: la herramienta Read no puede abrirlos. "
        f"Para leer uno ejecuta EXACTAMENTE esta orden, sola, sin encadenar nada "
        f"(esta autorizada, no pide permiso):\n    {orden}\n"
        f"  Convierte el documento a Markdown, lo anonimiza en local e imprime "
        f"«COPIA ANONIMIZADA: <ruta>». Lee despues esa ruta con Read. Admite varias "
        f"rutas a la vez.",
        f"- Documentos .pdf, imagenes y cualquier fichero de las carpetas protegidas "
        f"({carpetas}): leelos directamente con Read usando su ruta original; el "
        f"plugin te entrega automaticamente la copia anonimizada. De las imagenes y "
        f"los PDF escaneados recibes el texto reconocido por OCR, no la imagen.",
        "- No abras esos documentos de ninguna otra forma (cat, type, pandoc, "
        "scripts, skills de docx/pdf/xlsx...): se denegara o se pedira "
        "confirmacion al usuario, porque le llegarian a Anthropic sin anonimizar.",
        "- En esas copias veras identificadores como PERSONA_1, NIF_2 o CORREO_1. "
        "Son valores opacos y estables en todo el proyecto: escribelos exactamente "
        "igual, sin traducirlos, abreviarlos ni intentar deducir el dato real.",
        "- El usuario ve los datos reales en su pantalla, porque el plugin sustituye "
        "los identificadores al mostrar tus respuestas. No hace falta que le "
        "expliques los identificadores salvo que pregunte.",
        "- Los ficheros que escribas contendran identificadores. El usuario puede "
        "restaurar los datos reales con /anonimizador:revelar <fichero>.",
        "- De ~/.anonimizador solo puedes leer las copias anonimizadas (las rutas "
        "«COPIA ANONIMIZADA» de su subcarpeta cache, autorizadas sin pedir "
        "permiso); el resto contiene datos reales. No leas ficheros '.revelado.' "
        "ni modifiques .anonimizador.json.",
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
