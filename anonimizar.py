#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Anonimizador local de documentos - uso desde la linea de comandos.

    python anonimizar.py contrato.docx            anonimiza un fichero
    python anonimizar.py carpeta/                 anonimiza una carpeta
    python anonimizar.py --revelar respuesta.md   restaura los datos reales
    python anonimizar.py --estado                 resumen del proyecto actual
    python anonimizar.py --config-escritorio DIR  configuracion para Claude Desktop

Word, PDF y Excel se convierten a Markdown antes de anonimizar; de las
imagenes y los PDF escaneados se extrae el texto por OCR; los ficheros de
texto (.txt .md .json .xml .csv ...) se anonimizan tal cual.

La salida va a ./anonimizados (o --salida). El mapa de reidentificacion se
guarda en ~/.anonimizador, nunca junto a la salida. El "proyecto" es la
carpeta actual (o --proyecto): comparte mapa con el plugin de Claude Code
cuando se usa en la misma carpeta.

AVISO: la deteccion es probabilistica. Revisa la salida antes de compartirla.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))

from anonimizador import config  # noqa: E402
from anonimizador.mapa import Mapa, hay_mapa  # noqa: E402

EXT_REVELABLES = {".txt", ".md", ".json", ".xml", ".csv", ".log", ".yaml", ".yml",
                  ".html", ".htm", ".eml", ".tex", ".rst"}


def revelar(proyecto: str, ficheros: list[str]) -> int:
    if not hay_mapa(proyecto):
        print(f"No hay mapa para el proyecto {proyecto}. ¿Es la carpeta correcta? "
              f"Usa --proyecto.", file=sys.stderr)
        return 2
    mapa = Mapa(proyecto)
    estado = 0
    for nombre in ficheros:
        origen = Path(nombre)
        if not origen.is_file():
            print(f"[omitido] no existe: {origen}", file=sys.stderr)
            estado = 2
            continue
        if origen.suffix.lower() not in EXT_REVELABLES:
            print(f"[omitido] {origen.name}: solo se revelan ficheros de texto "
                  f"({' '.join(sorted(EXT_REVELABLES))})", file=sys.stderr)
            estado = 2
            continue
        texto, cambios = mapa.revelar(origen.read_text(encoding="utf-8", errors="replace"))
        destino = origen.with_name(f"{origen.stem}.revelado{origen.suffix}")
        destino.write_text(texto, encoding="utf-8")
        # Solo recuentos: esta salida puede acabar en el contexto de Claude.
        print(f"{origen.name}: {cambios} identificador(es) restaurados -> {destino.name}")
    return estado


def estado(proyecto: str) -> int:
    cfg = config.cargar(proyecto)
    interprete = config.python_del_entorno()
    print(f"Proyecto:            {proyecto}")
    print(f"Carpeta privada:     {config.dir_proyecto(proyecto)}")
    print(f"Entorno instalado:   {'si (' + str(interprete) + ')' if interprete else 'NO - ejecuta instalar.py'}")
    print(f"Carpetas protegidas: {', '.join(cfg['carpetas_protegidas'])}")
    print(f"Documentos:          {', '.join(cfg['extensiones_documento'])}"
          f"{' (en cualquier carpeta)' if cfg['documentos_en_todas_partes'] else ''}")
    if hay_mapa(proyecto):
        mapa = Mapa(proyecto)
        por_tipo: dict[str, int] = {}
        for tipo in mapa.tipos.values():
            por_tipo[tipo] = por_tipo.get(tipo, 0) + 1
        resumen = ", ".join(f"{t}: {n}" for t, n in sorted(por_tipo.items()))
        print(f"Datos en el mapa:    {len(mapa.reales)} ({resumen})")
    else:
        print("Datos en el mapa:    0 (todavia no se ha anonimizado nada aqui)")
    copias = config.dir_cache(proyecto)
    n = len([f for f in copias.glob("*") if not f.name.endswith(".meta.json")]) \
        if copias.is_dir() else 0
    print(f"Copias en cache:     {n}")
    return 0


def _relanzar_en_entorno() -> int | None:
    """None si este Python ya tiene las dependencias; si no, relanza la misma
    orden dentro del entorno virtual y devuelve su codigo de salida."""
    try:
        import markitdown  # noqa: F401
        import presidio_analyzer  # noqa: F401
        import spacy  # noqa: F401
        return None
    except ImportError:
        interprete = config.python_del_entorno()
        if interprete is None or Path(sys.executable).resolve() == interprete.resolve():
            print("Faltan las dependencias. Ejecuta primero:  python instalar.py",
                  file=sys.stderr)
            return 2
        return subprocess.call([str(interprete), str(Path(__file__).resolve()), *sys.argv[1:]])


def preparar(proyecto: str, ficheros: list[str]) -> int:
    """Anonimiza en la cache y dice donde esta la copia. Lo usa Claude para los
    formatos que su herramienta Read rechaza antes de consultar a los hooks
    (.docx, .xlsx). La salida solo lleva rutas y recuentos."""
    codigo = _relanzar_en_entorno()
    if codigo is not None:
        return codigo
    from anonimizador import tuberia

    cfg = config.cargar(proyecto)
    estado = 0
    for nombre in ficheros:
        try:
            if config.clasificar(nombre, proyecto, cfg) != config.ANONIMIZAR:
                raise ValueError("no es un documento que el plugin anonimice")
            resultado = tuberia.procesar(proyecto, str(Path(nombre).resolve()), cfg)
            print(f"COPIA ANONIMIZADA: {resultado['salida']}  "
                  f"({resultado['entidades']} dato(s) sustituidos)")
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: {type(exc).__name__}: {exc}")
            estado = 1
    return estado


def anonimizar(proyecto: str, entrada: Path, salida: Path) -> int:
    codigo = _relanzar_en_entorno()
    if codigo is not None:
        return codigo
    from anonimizador import tuberia

    cfg = config.cargar(proyecto)
    admitidas = (set(cfg["extensiones_documento"]) | set(cfg["extensiones_texto"])
                 | config.EXT_OCR)
    ficheros = sorted(f for f in entrada.iterdir() if f.is_file()) if entrada.is_dir() else [entrada]
    if not ficheros:
        print("No hay ficheros que procesar.")
        return 0

    print(f"Cargando el modelo {cfg['modelo']} ...")
    hechos = 0
    for fichero in ficheros:
        sufijo = fichero.suffix.lower()
        if sufijo not in admitidas:
            print(f"[omitido] {fichero.name}: formato no soportado")
            continue
        # "contrato.docx" -> "contrato.docx.md": conservar la extension de origen
        # evita que contrato.docx y contrato.pdf se pisen entre si.
        extension = sufijo + ".md" if config.se_convierte(fichero, cfg) else sufijo
        try:
            # Primero a un nombre provisional: el nombre definitivo tambien se
            # anonimiza, y para eso hay que haber detectado antes las entidades.
            provisional = salida / f".{os.getpid()}.tmp"
            resultado = tuberia.procesar(proyecto, str(fichero), cfg, destino=provisional)
            nombre = Mapa(proyecto).sustituir(fichero.stem) + extension
            definitivo = salida / nombre
            os.replace(provisional, definitivo)
        except Exception as exc:  # noqa: BLE001
            print(f"[ERROR] {fichero.name}: {exc}")
            continue
        hechos += 1
        print(f"{fichero.name} -> {definitivo}  ({resultado['entidades']} dato(s) sustituidos)")

    print(f"\n{hechos}/{len(ficheros)} fichero(s) procesados.")
    print(f"Informes de deteccion (con datos reales): {config.dir_proyecto(proyecto) / 'detecciones'}")
    print("REVISA la salida antes de compartirla: la deteccion no es infalible.")
    return 0 if hechos else 1


def config_escritorio(carpetas: list[str]) -> int:
    """Imprime el bloque que hay que anadir a claude_desktop_config.json."""
    import json

    interprete = config.python_del_entorno()
    if interprete is None:
        print("Falta el entorno. Ejecuta primero:  python instalar.py", file=sys.stderr)
        return 2
    argumentos = [str(RAIZ / "servidor_mcp.py")]
    for carpeta in carpetas:
        ruta = Path(carpeta).expanduser().resolve()
        if not ruta.is_dir():
            print(f"No existe la carpeta: {ruta}", file=sys.stderr)
            return 2
        argumentos += ["--carpeta", str(ruta)]
    bloque = {"mcpServers": {"anonimizador": {"command": str(interprete),
                                              "args": argumentos}}}
    if os.name == "nt":
        destino = r"%APPDATA%\Claude\claude_desktop_config.json"
    elif sys.platform == "darwin":
        destino = "~/Library/Application Support/Claude/claude_desktop_config.json"
    else:
        destino = "~/.config/Claude/claude_desktop_config.json"
    print(f"Anade esto a {destino}\n(si ya tiene «mcpServers», anade solo la entrada "
          f"«anonimizador») y reinicia Claude Desktop:\n", file=sys.stderr)
    print(json.dumps(bloque, ensure_ascii=False, indent=2))
    if "plugins" in RAIZ.parts and "cache" in RAIZ.parts:
        print("\nAVISO: esta copia es la que gestiona Claude Code y su ruta cambia al "
              "actualizar el plugin. Para Claude Desktop conviene clonar el "
              "repositorio en una carpeta fija.", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    config.utf8()
    ap = argparse.ArgumentParser(
        description="Anonimiza documentos en local antes de enviarlos a una IA.")
    ap.add_argument("entrada", nargs="*", help="Fichero o carpeta a anonimizar")
    ap.add_argument("--revelar", action="store_true",
                    help="Restaura los datos reales en los ficheros indicados "
                         "(crea <nombre>.revelado.<ext>)")
    ap.add_argument("--preparar", action="store_true",
                    help="Anonimiza en la cache e imprime la ruta de la copia "
                         "(lo usa el plugin de Claude Code)")
    ap.add_argument("--estado", action="store_true", help="Muestra el estado del proyecto")
    ap.add_argument("--config-escritorio", action="store_true",
                    help="Imprime la configuracion del servidor MCP para Claude "
                         "Desktop; indica la carpeta o carpetas de documentos")
    ap.add_argument("--proyecto", default=os.getcwd(),
                    help="Carpeta del proyecto (por defecto, la actual)")
    ap.add_argument("--salida", default="anonimizados",
                    help="Carpeta de salida (por defecto ./anonimizados)")
    args = ap.parse_args(argv)
    proyecto = str(Path(args.proyecto).resolve())

    if args.estado:
        return estado(proyecto)
    if not args.entrada:
        ap.error("indica un fichero o carpeta")
    if args.config_escritorio:
        return config_escritorio(args.entrada)
    if args.revelar:
        return revelar(proyecto, args.entrada)
    if args.preparar:
        return preparar(proyecto, args.entrada)
    if len(args.entrada) != 1:
        ap.error("indica un solo fichero o carpeta a anonimizar")
    entrada = Path(args.entrada[0])
    if not entrada.exists():
        print(f"No existe: {entrada}", file=sys.stderr)
        return 2
    salida = Path(args.salida)
    salida.mkdir(parents=True, exist_ok=True)
    return anonimizar(proyecto, entrada, salida)


if __name__ == "__main__":
    sys.exit(main())
