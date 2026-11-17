#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Lanza la bateria de pruebas y mide cuantos datos se escapan.

    python pruebas/bateria/lanzar.py                 todos los casos
    python pruebas/bateria/lanzar.py 2 foto          solo los ficheros cuyo nombre contiene "2" o "foto"
    python pruebas/bateria/lanzar.py --casos DIR     otra carpeta con su propio esperado.json

Pasa cada fichero por el anonimizador (el mismo codigo que usan el plugin y el
servidor MCP) y busca en la copia anonimizada cada dato que deberia haber
desaparecido. Usa una carpeta temporal en lugar de ~/.anonimizador: no toca tu
mapa ni tu cache.

Resultado por dato:
  FUGA          aparece tal cual en la copia (o con otros espacios o guiones)
  FUGA PARCIAL  aparece un apellido o una parte del dato
  ERRATA        aparece algo muy parecido: el OCR lo leyo mal y el detector
                no lo reconocio. Para quien lea la copia sigue siendo el dato.
  limite        dato de un tipo que el detector no cubre (direcciones, fechas,
                Seguridad Social...): aviso, no fallo.

Deja un informe en pruebas/bateria/resultados/<fecha>/ con las copias
anonimizadas, para revisarlas a mano. Termina con codigo 1 si hay fugas.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
from datetime import datetime
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent.parent
sys.path.insert(0, str(RAIZ))

from anonimizador import config  # noqa: E402

# Palabras de un nombre que no identifican a nadie por si solas.
_VACIAS = {"de", "del", "la", "las", "los", "el", "y", "san", "santa", "sra", "sr"}


def _relanzar() -> None:
    try:
        import markitdown  # noqa: F401
        import presidio_analyzer  # noqa: F401
    except ImportError:
        interprete = config.python_del_entorno()
        if interprete is None or Path(sys.executable).resolve() == interprete.resolve():
            sys.exit("Faltan dependencias. Ejecuta primero:  python instalar.py")
        sys.exit(subprocess.call([str(interprete), str(Path(__file__).resolve()), *sys.argv[1:]]))


def plano(texto: str) -> str:
    """Minusculas y sin tildes."""
    t = unicodedata.normalize("NFKD", texto.casefold())
    return "".join(c for c in t if not unicodedata.combining(c))


def compacto(texto: str) -> str:
    return re.sub(r"[^0-9a-z@.+]", "", plano(texto))


def evaluar(valor: str, tipo: str, salida: str, ocr: bool, exacto: bool = False) -> tuple[str, str]:
    """(veredicto, detalle) de un dato frente a la copia anonimizada."""
    s_plano, v_plano = plano(salida), plano(valor)
    if v_plano in s_plano:
        return "FUGA", ""
    if exacto:
        return "ok", ""
    v_comp = compacto(valor)
    if len(v_comp) >= 6 and v_comp in compacto(salida):
        return "FUGA", "con otros separadores"
    if tipo in ("PERSONA", "NOMBRE_SUELTO"):
        sueltas = [p for p in re.findall(r"\w+", v_plano) if len(p) >= 4 and p not in _VACIAS]
        vistas = [p for p in sueltas if re.search(rf"(?<!\w){re.escape(p)}(?!\w)", s_plano)]
        if vistas and len(sueltas) > 1:
            return "FUGA PARCIAL", ", ".join(vistas)
        return "ok", ""
    # Numeros y codigos: una parte larga, o algo casi igual (erratas del OCR).
    if len(v_comp) >= 8:
        tokens = re.findall(r"[0-9a-z@.+]{6,}", compacto_conservando(salida))
        for t in tokens:
            if len(t) >= 8 and t in v_comp:
                return "FUGA PARCIAL", t
        if ocr:
            for t in tokens:
                r = difflib.SequenceMatcher(None, t, v_comp).ratio()
                if r >= 0.8:
                    return "ERRATA", f"«{t}» ({r:.0%} parecido)"
    return "ok", ""


def compacto_conservando(texto: str) -> str:
    """Como compacto(), pero los espacios entre palabras cortan los tokens
    salvo los que separan grupos de cifras ("2100 0418")."""
    t = plano(texto)
    t = re.sub(r"(?<=[0-9a-z])[ \-.](?=[0-9])", "", t)
    return re.sub(r"[^0-9a-z@.+]+", " ", t)


def main(argv: list[str] | None = None) -> int:
    _relanzar()
    config.utf8()
    ap = argparse.ArgumentParser(description="Bateria de pruebas del anonimizador.")
    ap.add_argument("filtro", nargs="*", help="Solo los casos cuyo nombre contenga alguno de estos textos")
    ap.add_argument("--casos", action="append",
                    help="Carpeta con ficheros y esperado.json (repetible). Por defecto, casos/ "
                         "y, si se han descargado, externos/")
    args = ap.parse_args(argv)

    carpetas = [Path(c).resolve() for c in args.casos] if args.casos else \
        [d for d in (AQUI / "casos", AQUI / "externos") if (d / "esperado.json").is_file()]
    if not carpetas:
        print("No hay casos. Genéralos con:  python pruebas/bateria/generar.py")
        return 2
    casos = []
    for carpeta in carpetas:
        esperado = carpeta / "esperado.json"
        if not esperado.is_file():
            print(f"No existe {esperado}")
            return 2
        for c in json.loads(esperado.read_text(encoding="utf-8"))["casos"]:
            c["_ruta"] = str(carpeta / c["fichero"])
            casos.append(c)
    casos_dir = ", ".join(str(c) for c in carpetas)
    if args.filtro:
        casos = [c for c in casos if any(f.lower() in c["fichero"].lower() for f in args.filtro)]

    # Carpeta temporal en lugar de ~/.anonimizador, y proyecto propio.
    tmp = Path(tempfile.mkdtemp(prefix="anonimizador-bateria-"))
    os.environ["ANONIMIZADOR_HOME"] = str(tmp / "home")
    proyecto = str(tmp / "proyecto")
    Path(proyecto).mkdir()
    from anonimizador import conversion, tuberia  # noqa: E402

    salida_dir = AQUI / "resultados" / datetime.now().strftime("%Y-%m-%d_%H%M%S")
    (salida_dir / "copias").mkdir(parents=True)
    cfg = config.cargar(proyecto)

    print(f"Batería: {len(casos)} casos de {casos_dir}")
    print("(la primera lectura carga el modelo de lenguaje y tarda unos segundos)\n")
    filas, informe = [], []
    totales = {"ocultar": 0, "FUGA": 0, "FUGA PARCIAL": 0, "ERRATA": 0, "limite": 0, "limite_fuga": 0,
               "quedar": 0, "quedar_perdidas": 0}
    fallos_casos = 0
    for c in casos:
        fichero = Path(c["_ruta"])
        inicio = time.time()
        error, texto = None, ""
        try:
            r = tuberia.procesar(proyecto, str(fichero), cfg)
            texto = Path(r["salida"]).read_text(encoding="utf-8")
        except conversion.SinTexto:
            error = "sin texto"
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
        segundos = time.time() - inicio

        problemas = []
        if c.get("sin_texto"):
            estado = "OK" if error == "sin texto" else "FALLO"
            if estado == "FALLO":
                problemas.append(f"- Se esperaba «sin texto» y se obtuvo: {error or 'texto'}")
        elif error:
            estado = "ERROR"
            problemas.append(f"- No se pudo procesar: {error}")
        else:
            estado = "OK"
            for d in c["ocultar"]:
                totales["ocultar"] += 1
                veredicto, detalle = evaluar(d["valor"], d["tipo"], texto, c["ocr"], c.get("solo_exacto", False))
                if veredicto != "ok":
                    totales[veredicto] += 1
                    estado = "FUGAS"
                    problemas.append(f"- **{veredicto}** {d['tipo']}: `{d['valor']}`"
                                     + (f" — {detalle}" if detalle else ""))
            for d in c["limite"]:
                totales["limite"] += 1
                veredicto, detalle = evaluar(d["valor"], d["tipo"], texto, c["ocr"])
                if veredicto != "ok":
                    totales["limite_fuga"] += 1
                    problemas.append(f"- límite ({d['tipo']}): `{d['valor']}` sigue visible")
            for palabra in c["deben_quedar"]:
                totales["quedar"] += 1
                if plano(palabra) not in plano(texto):
                    totales["quedar_perdidas"] += 1
                    problemas.append(f"- exceso: ha desaparecido «{palabra}»")
            (salida_dir / "copias" / (c["fichero"] + ".md")).write_text(texto, encoding="utf-8")
        if estado in ("FUGAS", "FALLO", "ERROR"):
            fallos_casos += 1

        fugas = sum(1 for p in problemas if p.startswith("- **"))
        filas.append((c["fichero"], estado, fugas, len(c["ocultar"]), segundos))
        marca = {"OK": "  ok ", "FUGAS": "FUGAS", "FALLO": "FALLO", "ERROR": "ERROR"}[estado]
        print(f"[{marca}] {c['fichero']:<34} {len(c['ocultar']) - fugas:>3}/{len(c['ocultar']):<3} "
              f"ocultos  {segundos:5.1f} s")
        for p in problemas:
            if p.startswith("- **"):
                print("         " + p[2:].replace("**", "").replace("`", ""))
        informe.append(f"### {c['fichero']} — {estado}\n\n{c['descripcion']}"
                       + (f"\n\n> {c['notas']}" if c.get("notas") else "") + "\n\n"
                       + ("\n".join(problemas) if problemas else "Sin incidencias.") + "\n")

    ocultos = totales["ocultar"] - totales["FUGA"] - totales["FUGA PARCIAL"] - totales["ERRATA"]
    porcentaje = 100 * ocultos / totales["ocultar"] if totales["ocultar"] else 100
    resumen = [
        f"Datos que debían sustituirse: {totales['ocultar']}",
        f"  sustituidos:     {ocultos} ({porcentaje:.1f} %)",
        f"  FUGA:            {totales['FUGA']}",
        f"  FUGA PARCIAL:    {totales['FUGA PARCIAL']}",
        f"  ERRATA del OCR:  {totales['ERRATA']}",
        f"Tipos no cubiertos (direcciones, fechas, NSS...): {totales['limite_fuga']} de "
        f"{totales['limite']} siguen visibles (esperado)",
        f"Palabras normales perdidas por exceso de celo: {totales['quedar_perdidas']} de {totales['quedar']}",
        f"Casos con problemas: {fallos_casos} de {len(casos)}",
    ]
    print("\n" + "\n".join(resumen))

    tabla = ["| Fichero | Estado | Ocultos | Segundos |", "|---|---|---|---|"] + [
        f"| {f} | {e} | {n - k}/{n} | {s:.1f} |" for f, e, k, n, s in filas]
    (salida_dir / "informe.md").write_text(
        f"# Batería de pruebas — {datetime.now():%d/%m/%Y %H:%M}\n\n"
        "Todos los datos son ficticios. En `copias/` está lo que recibiría Claude.\n\n"
        "## Resumen\n\n```\n" + "\n".join(resumen) + "\n```\n\n" + "\n".join(tabla)
        + "\n\n## Detalle\n\n" + "\n".join(informe), encoding="utf-8")
    print(f"\nInforme y copias anonimizadas: {salida_dir}")
    shutil.rmtree(tmp, ignore_errors=True)
    return 1 if totales["FUGA"] + totales["FUGA PARCIAL"] + totales["ERRATA"] else 0


if __name__ == "__main__":
    sys.exit(main())
