#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Descarga documentos de muestra reales de Wikimedia Commons.

    python pruebas/bateria/descargar.py

Son "specimen" oficiales: documentos de identidad que los propios gobiernos
publican con una persona ficticia para que se reconozca el diseno. Sirven para
probar el OCR con diseños reales (fondos de seguridad, campos en mayusculas,
zona de lectura mecanica), que las imagenes generadas no reproducen.

Se guardan en pruebas/bateria/externos/ junto a su esperado.json; lanzar.py los
incluye automaticamente. No se suben al repositorio: cada fichero conserva su
licencia (indicada abajo) y hay que citar al autor si se redistribuye.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

AQUI = Path(__file__).resolve().parent
DESTINO = AQUI / "externos"
AGENTE = "anonimizador-local-bateria/1.0 (pruebas de OCR con documentos specimen)"

FICHEROS = [
    {
        "fichero": "argentina_dni_anverso.png",
        "url": "https://upload.wikimedia.org/wikipedia/commons/c/cb/Biometric_Argentine_DNI_for_Citizens-Foreigners.png",
        "pagina": "https://commons.wikimedia.org/wiki/File:Biometric_Argentine_DNI_for_Citizens-Foreigners.png",
        "licencia": "CC BY 4.0 (Gobierno de Argentina)",
        "descripcion": "DNI argentino specimen, anverso: campos en mayusculas en lineas separadas",
        "ocultar": [{"valor": "PORTILLO", "tipo": "PERSONA"}, {"valor": "VIRGILIO", "tipo": "PERSONA"}],
        "limite": [{"valor": "99.999.999", "tipo": "DOCUMENTO_EXTRANJERO"},
                   {"valor": "20.04.1950", "tipo": "FECHA_NACIMIENTO"}],
    },
    {
        "fichero": "argentina_dni_reverso.png",
        "url": "https://upload.wikimedia.org/wikipedia/commons/7/7a/Biometric_Argentine_DNI_for_Citizens-Foreigners_back.png",
        "pagina": "https://commons.wikimedia.org/wiki/File:Biometric_Argentine_DNI_for_Citizens-Foreigners_back.png",
        "licencia": "CC BY 4.0 (Gobierno de Argentina)",
        "descripcion": "DNI argentino specimen, reverso: domicilio y zona de lectura mecanica (MRZ)",
        "ocultar": [{"valor": "MARIANA", "tipo": "PERSONA"}, {"valor": "GONZALEZ", "tipo": "PERSONA"}],
        "limite": [{"valor": "SAN MARTÍN 2538", "tipo": "DIRECCION"},
                   {"valor": "27-99999999-0", "tipo": "DOCUMENTO_EXTRANJERO"}],
    },
    {
        "fichero": "ecuador_cedula.png",
        "url": "https://upload.wikimedia.org/wikipedia/commons/f/f3/C%C3%A9dula_electr%C3%B3nica_Ecuador_%28Enero_2021%29.png",
        "pagina": "https://commons.wikimedia.org/wiki/File:C%C3%A9dula_electr%C3%B3nica_Ecuador_(Enero_2021).png",
        "licencia": "Dominio publico",
        "descripcion": "Cedula ecuatoriana specimen: apellidos y nombres en lineas separadas",
        "ocultar": [{"valor": "JARAMILLO", "tipo": "PERSONA"}, {"valor": "ALVEAR", "tipo": "PERSONA"},
                    {"valor": "PATRICIO RAMIRO", "tipo": "PERSONA"}],
        "limite": [{"valor": "1719142905", "tipo": "DOCUMENTO_EXTRANJERO"},
                   {"valor": "04 JUL 1995", "tipo": "FECHA_NACIMIENTO"}],
    },
    {
        "fichero": "italia_cie.png",
        "url": "https://upload.wikimedia.org/wikipedia/commons/f/ff/Italian_electronic_ID_card.png",
        "pagina": "https://commons.wikimedia.org/wiki/File:Italian_electronic_ID_card.png",
        "licencia": "CC0",
        "descripcion": "Carta d'identita italiana specimen: otro idioma, sello FAC-SIMILE cruzado",
        "ocultar": [{"valor": "ROSSI", "tipo": "PERSONA"}, {"valor": "BIANCA", "tipo": "PERSONA"}],
        "limite": [{"valor": "CA00000AA", "tipo": "DOCUMENTO_EXTRANJERO"},
                   {"valor": "30.12.1964", "tipo": "FECHA_NACIMIENTO"}],
    },
]


def main() -> int:
    DESTINO.mkdir(exist_ok=True)
    casos = []
    for f in FICHEROS:
        ruta = DESTINO / f["fichero"]
        if not ruta.is_file():
            peticion = urllib.request.Request(f["url"], headers={"User-Agent": AGENTE})
            try:
                with urllib.request.urlopen(peticion, timeout=60) as r:
                    ruta.write_bytes(r.read())
            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    # Wikimedia a veces bloquea un fichero concreto para una
                    # conexion durante horas, miniaturas incluidas. Insistir
                    # no sirve: se puede bajar a mano desde el navegador.
                    print(f"[bloqueado] {f['fichero']}: Wikimedia responde 429 (demasiadas peticiones).\n"
                          f"    Descargalo a mano desde {f['pagina']}\n"
                          f"    (boton 'Descargar', tamano original) y guardalo como:\n"
                          f"    {ruta}\n"
                          f"    Al volver a lanzar este script se usara el fichero guardado.")
                else:
                    print(f"[error] {f['fichero']}: {exc}")
                continue
            except OSError as exc:
                print(f"[error] {f['fichero']}: {exc}")
                continue
        print(f"{f['fichero']:<28} {ruta.stat().st_size // 1024:>5} KB  {f['licencia']}")
        casos.append({"fichero": f["fichero"], "descripcion": f["descripcion"], "ocr": True,
                      "notas": f"Fuente: {f['pagina']} ({f['licencia']}). Persona ficticia.",
                      "ocultar": f["ocultar"], "limite": f["limite"], "deben_quedar": []})
    (DESTINO / "esperado.json").write_text(json.dumps(
        {"aviso": "Documentos specimen con personas ficticias, de Wikimedia Commons.", "casos": casos},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{len(casos)} ficheros en {DESTINO}. Se incluyen solos en:  python pruebas/bateria/lanzar.py")
    return 0 if len(casos) == len(FICHEROS) else 1


if __name__ == "__main__":
    sys.exit(main())
