#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Hook MessageDisplay: muestra los datos reales en TU pantalla.

Sustituye cada identificador (PERSONA_1, NIF_1...) por su valor real en el
texto que Claude Code pinta. Segun la documentacion oficial este evento es
"display-only": Claude y la transcripcion siguen teniendo los identificadores,
nunca los datos reales.

Solo biblioteca estandar: se ejecuta varias veces por respuesta.
Si falla, Claude Code muestra el texto original (con identificadores).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from anonimizador import config  # noqa: E402
from anonimizador.mapa import Mapa, hay_mapa  # noqa: E402


def main() -> None:
    config.utf8()
    carga = json.load(sys.stdin)
    delta = carga.get("delta") or ""
    proyecto = config.proyecto_actual(carga)
    if not delta or not hay_mapa(proyecto):
        sys.exit(0)
    if not config.cargar(proyecto).get("revelar_en_pantalla", True):
        sys.exit(0)
    texto, cambios = Mapa(proyecto).revelar(delta)
    if cambios:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "MessageDisplay",
            "displayContent": texto,
        }}, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"anonimizador/pantalla: {exc!r}", file=sys.stderr)
        sys.exit(0)
