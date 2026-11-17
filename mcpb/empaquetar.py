#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Empaqueta el servidor MCP como extension de Claude Desktop (.mcpb).

    python mcpb/empaquetar.py            -> dist/anonimizador-local-<version>.mcpb

Un .mcpb es un ZIP con manifest.json en la raiz
(https://github.com/modelcontextprotocol/mcpb). El paquete lleva solo el
servidor y el codigo del anonimizador, que usan la biblioteca estandar: el
motor (Presidio, spaCy, OCR; ~1 GB con binarios por plataforma) no cabe en un
paquete portable. El servidor lo ofrece instalar la primera vez que se lee un
documento, y si ya esta instalado (por el plugin de Claude Code o por
instalar.py) lo usa directamente.

El manifiesto se genera aqui, con la version y la lista de herramientas del
propio servidor, para que no se desincronicen.

Solo biblioteca estandar.
"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent
sys.path.insert(0, str(RAIZ))

from anonimizador import __version__  # noqa: E402
from servidor_mcp import HERRAMIENTAS  # noqa: E402

REPOSITORIO = "https://github.com/juankpya/anonimizador-local"

# (origen relativo a la raiz del repositorio, ruta dentro del paquete)
FICHEROS = [
    ("servidor_mcp.py", "servidor_mcp.py"),
    ("instalar.py", "instalar.py"),
    ("requirements.txt", "requirements.txt"),
    ("LICENSE", "LICENSE"),
    ("mcpb/icono.png", "icon.png"),
]

DESCRIPCION_LARGA = """\
Lee documentos con datos personales sin que esos datos lleguen a Claude. \
Word, PDF (tambien escaneados), Excel, ficheros de texto e imagenes se \
convierten y se anonimizan en tu equipo: los nombres, NIF, correos, \
telefonos, IBAN... se sustituyen por identificadores (PERSONA_1, NIF_1). \
Claude trabaja con esos identificadores y guarda los resultados con los datos \
reales restaurados en ficheros .revelado que solo abres tu.

**La primera vez** que Claude lea un documento te preguntara si instala el \
motor de deteccion (~1 GB, una sola vez; necesita Python 3.10 a 3.13). \
**Cada carpeta nueva** necesita tu confirmacion en una ventana de tu sistema.

**Limites:** la deteccion es probabilistica y puede dejar escapar algun dato. \
No adjuntes ni pegues documentos en el chat: llegan sin anonimizar. Guia: \
""" + REPOSITORIO + "/blob/main/GUIA.md"


def manifiesto() -> dict:
    return {
        "manifest_version": "0.3",
        "name": "anonimizador-local",
        "display_name": "Anonimizador local",
        "version": __version__,
        "description": "Anonimiza en tu equipo los documentos (Word, PDF, Excel, "
                       "texto e imagenes) antes de que Claude los lea.",
        "long_description": DESCRIPCION_LARGA,
        "author": {"name": "juankpya", "url": "https://github.com/juankpya"},
        "repository": {"type": "git", "url": REPOSITORIO + ".git"},
        "homepage": REPOSITORIO,
        "documentation": REPOSITORIO + "/blob/main/GUIA.md",
        "support": REPOSITORIO + "/issues",
        "icon": "icon.png",
        "server": {
            "type": "python",
            "entry_point": "servidor_mcp.py",
            "mcp_config": {
                "command": "python",
                "args": ["${__dirname}/servidor_mcp.py", "${user_config.carpetas}"],
                "env": {"PYTHONIOENCODING": "utf-8"},
            },
        },
        "tools": [{"name": h["name"], "description": h["description"]}
                  for h in HERRAMIENTAS],
        "tools_generated": False,
        "prompts_generated": False,
        "keywords": ["privacidad", "anonimizacion", "pii", "rgpd", "gdpr",
                     "documentos", "ocr"],
        "license": "MIT",
        "user_config": {
            "carpetas": {
                "type": "directory",
                "title": "Carpetas con acceso directo (opcional)",
                "description": "Carpetas que el anonimizador puede leer sin preguntar. "
                               "Para cualquier otra se te pedira confirmacion en una "
                               "ventana la primera vez. La primera carpeta de la lista "
                               "comparte identificadores con el plugin de Claude Code.",
                "multiple": True,
                "required": False,
            },
        },
        "compatibility": {
            "platforms": ["win32", "darwin", "linux"],
            "runtimes": {"python": ">=3.10.0 <4"},
        },
    }


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    salida = (Path(argv[0]).resolve() if argv
              else RAIZ / "dist" / f"anonimizador-local-{__version__}.mcpb")
    salida.parent.mkdir(parents=True, exist_ok=True)
    datos = manifiesto()
    contenido: list[tuple[Path, str]] = [(RAIZ / o, d) for o, d in FICHEROS]
    contenido += [(p, f"anonimizador/{p.name}")
                  for p in sorted((RAIZ / "anonimizador").glob("*.py"))]
    for origen, _ in contenido:
        if not origen.is_file():
            print(f"Falta {origen}", file=sys.stderr)
            return 1
    with zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.writestr("manifest.json", json.dumps(datos, ensure_ascii=False, indent=2) + "\n")
        for origen, destino in contenido:
            z.write(origen, destino)
    print(f"{salida}  ({salida.stat().st_size // 1024} KB, "
          f"{len(contenido) + 1} ficheros, version {__version__})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
