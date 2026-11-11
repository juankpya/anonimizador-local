#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Hook UserPromptSubmit: avisa antes de enviar algo que no se puede anonimizar.

Claude Code no permite reescribir un prompt (la documentacion oficial dice:
"UserPromptSubmit: can't replace the prompt"), asi que lo que escribes, pegas o
adjuntas en el mensaje viaja tal cual. Este hook lo detiene y te deja decidir:

  - modificarlo, o
  - enviarlo igualmente: basta con reenviar EXACTAMENTE el mismo mensaje.

Se detiene cuando el mensaje contiene:
  - un NIF/NIE, IBAN o tarjeta con digito de control valido, un correo o un
    telefono;
  - un valor real que el proyecto ya conoce por un documento anonimizado;
  - una imagen adjunta, o un fichero citado con @ que deberia anonimizarse
    (las menciones con @ incrustan el contenido sin pasar por la lectura).

Solo biblioteca estandar: se ejecuta en cada mensaje y debe ser inmediato.
Si este hook falla, el mensaje se envia (no bloquea la sesion).
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from anonimizador import config, sensibles  # noqa: E402
from anonimizador.mapa import Mapa, hay_mapa  # noqa: E402


def conocidos(prompt: str, proyecto: str, permitidos: set[str]) -> list[tuple[str, str]]:
    """Valores reales ya vistos en documentos del proyecto.

    Se descartan los lugares y los nombres de una sola palabra: son los que mas
    falsas alarmas dan ("Cordoba", "Toma") y pararian mensajes inocentes.
    """
    if not hay_mapa(proyecto):
        return []
    salida = []
    for literal, tipo in Mapa(proyecto).buscar_reales(prompt):
        if literal.casefold() in permitidos or tipo == "LOCATION":
            continue
        if tipo == "PERSON" and len(literal.split()) < 2:
            continue
        salida.append(("dato de un documento anonimizado", literal))
    return salida


def adjuntos(prompt: str, proyecto: str, cwd: str, cfg: dict) -> list[str]:
    avisos = []
    n = sensibles.imagenes_adjuntas(prompt)
    if n:
        avisos.append(f"{n} imagen(es) adjunta(s): las imágenes no se pueden anonimizar")
    for con_arroba, ruta in sensibles.rutas_mencionadas(prompt):
        if not con_arroba:
            continue  # una ruta sin @ la leera Claude con Read, y ahi si se anonimiza
        absoluta = ruta if os.path.isabs(ruta) else os.path.join(cwd, ruta)
        if not os.path.isfile(absoluta):
            continue
        if config.clasificar(absoluta, proyecto, cfg) != config.LIBRE:
            avisos.append(
                f"fichero adjunto con @ ({os.path.basename(ruta)}): se enviaría sin "
                f"anonimizar. Escribe su ruta sin la @ y Claude lo leerá anonimizado"
            )
    return avisos


def main() -> None:
    config.utf8()
    carga = json.load(sys.stdin)
    prompt = carga.get("prompt") or ""
    if not prompt.strip():
        sys.exit(0)
    cwd = carga.get("cwd") or os.getcwd()
    proyecto = config.proyecto_actual(carga)
    cfg = config.cargar(proyecto)
    if not cfg.get("avisar_prompt", True):
        sys.exit(0)

    permitidos = {p.casefold() for p in cfg.get("permitidos", [])}
    datos = sensibles.detectar(prompt, permitidos)
    ya_listados = {v.casefold() for _, v in datos}
    datos += [d for d in conocidos(prompt, proyecto, permitidos)
              if d[1].casefold() not in ya_listados]
    avisos = [f"{tipo}: {sensibles.enmascarar(valor)}" for tipo, valor in datos]
    avisos += adjuntos(prompt, proyecto, cwd, cfg)
    if not avisos:
        sys.exit(0)

    # Confirmacion: reenviar el mismo mensaje dentro del plazo lo deja pasar.
    # Solo se guarda un hash, nunca el texto.
    huella = hashlib.sha256(prompt.strip().encode("utf-8")).hexdigest()
    minutos = float(cfg.get("minutos_confirmacion", 10))
    registro = config.dir_proyecto(proyecto) / "confirmacion.json"
    try:
        previo = json.loads(registro.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        previo = {}
    if previo.get("huella") == huella and time.time() - previo.get("t", 0) < minutos * 60:
        try:
            registro.unlink()
        except OSError:
            pass
        sys.exit(0)  # confirmado por el usuario: se envia tal cual

    registro.parent.mkdir(parents=True, exist_ok=True)
    registro.write_text(json.dumps({"huella": huella, "t": time.time()}), encoding="utf-8")

    lista = "\n".join(f"  • {a}" for a in avisos[:12])
    if len(avisos) > 12:
        lista += f"\n  • … y {len(avisos) - 12} más"
    motivo = (
        "🔒 Anonimizador: mensaje NO enviado.\n"
        "Contiene datos que no se pueden anonimizar porque van en el propio "
        "mensaje (solo se anonimizan los ficheros que lee Claude):\n"
        f"{lista}\n\n"
        "Tú decides:\n"
        "  1. Modificarlo: quita esos datos, o guárdalos en un fichero y pide a "
        "Claude que lo lea.\n"
        f"  2. Enviarlo igualmente: reenvía exactamente el mismo mensaje en los "
        f"próximos {minutos:g} minutos y pasará sin cambios."
    )
    print(json.dumps({"decision": "block", "reason": motivo}, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - un aviso roto no debe parar la sesion
        print(f"anonimizador/prompt: {exc!r}", file=sys.stderr)
        sys.exit(0)
