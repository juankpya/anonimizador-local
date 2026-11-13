#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Servidor MCP del anonimizador, para Claude Desktop y otros clientes MCP.

    python servidor_mcp.py [--carpeta "C:/Clientes" ...]

Claude Desktop no tiene hooks: no se puede interceptar lo que lee ni cambiar lo
que muestra. Este servidor ofrece lo que si es posible alli: herramientas con
las que Claude lee los documentos YA anonimizados y guarda sus resultados con
los datos reales restaurados, sin llegar a verlos.

El usuario pide los documentos por su ruta, esten donde esten. La primera vez
que se toca una carpeta, el servidor abre una ventana del sistema para que el
usuario diga si confia en ella; la respuesta se recuerda en
~/.anonimizador/confianza.json. Esa ventana no pasa por Claude.

Con --carpeta se da acceso de antemano, sin preguntar. La primera es el
"proyecto": decide que mapa de identificadores se usa (el mismo que usa el
plugin de Claude Code en esa carpeta) y donde se busca .anonimizador.json. Sin
ninguna, el servidor usa un mapa propio, comun a todas las carpetas.

Habla MCP por la entrada y la salida estandar (JSON-RPC, una linea por
mensaje). El protocolo esta implementado con la biblioteca estandar; el motor
de deteccion necesita el entorno que crea instalar.py, y se carga en la
primera lectura.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))

from anonimizador import __version__, config  # noqa: E402
from anonimizador.mapa import Mapa, hay_mapa  # noqa: E402

VERSIONES_MCP = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"]
EXT_REVELABLES = {".txt", ".md", ".json", ".xml", ".csv", ".log", ".yaml", ".yml",
                  ".html", ".htm", ".eml", ".tex", ".rst"}
TROZO = 100_000  # caracteres por llamada a leer_documento
ESPERA_MS = 120_000  # tiempo para responder a la ventana de confianza

INSTRUCCIONES = """\
Este servidor permite trabajar con documentos que contienen datos personales \
sin que esos datos lleguen a ti.
- Para leer un documento usa SIEMPRE leer_documento con su ruta. Recibes el \
texto con identificadores (PERSONA_1, NIF_2, CORREO_1...) en lugar de los datos \
reales. No pidas al usuario que pegue o adjunte el documento en el chat: asi \
llegaria sin anonimizar.
- Los identificadores son opacos y estables: escribelos exactamente igual, sin \
traducirlos ni abreviarlos, y no intentes deducir el dato real.
- En esta aplicacion tus respuestas se muestran tal cual, con identificadores. \
Cuando el usuario necesite un resultado con los datos reales (un resumen, una \
carta, un informe), escribelo con identificadores y guardalo con \
guardar_revelado: el fichero resultante lleva los datos reales y el usuario lo \
abre en su equipo. Tu solo recibes un recuento.
- No puedes leer los ficheros '.revelado.' ni el mapa de identificadores.
- Usa rutas completas. La primera vez que accedes a una carpeta, el usuario ve \
en su equipo una ventana que le pregunta si confia en ella; avisale de que la \
vera. Si la rechaza, no insistas."""


class Rechazo(Exception):
    """Error que se devuelve a Claude como resultado de la herramienta."""


# --------------------------------------------------------------------------- #
# Carpetas y rutas
# --------------------------------------------------------------------------- #

def preguntar_confianza(carpeta: str) -> bool:
    """Pregunta AL USUARIO, con una ventana del sistema, si confia en una
    carpeta. No pasa por Claude: el modelo no puede responder por el usuario.
    Sin respuesta en dos minutos, o si no se puede mostrar la ventana, es NO."""
    forzado = os.environ.get("ANONIMIZADOR_CONFIANZA")  # solo para las pruebas
    if forzado:
        return forzado == "si"
    titulo = "Anonimizador local"
    texto = ("Claude quiere leer documentos de esta carpeta:\n\n"
             f"{carpeta}\n\n"
             "¿Confías en ella? Si aceptas, el anonimizador podrá leer sus "
             "ficheros y subcarpetas (Claude recibirá solo las copias "
             "anonimizadas) y guardar resultados en ella, ahora y en adelante.")
    try:
        if os.name == "nt":
            import ctypes
            # SI/NO | icono de pregunta | NO por defecto | siempre delante
            estilo = 0x04 | 0x20 | 0x100 | 0x1000 | 0x10000
            try:
                r = ctypes.windll.user32.MessageBoxTimeoutW(
                    None, texto, titulo, estilo, 0, ESPERA_MS)
            except AttributeError:
                r = ctypes.windll.user32.MessageBoxW(None, texto, titulo, estilo)
            return r == 6  # IDYES
        import shutil
        import subprocess
        if sys.platform == "darwin":
            guion = ('display dialog (item 1 of argv) with title (item 2 of argv) '
                     'buttons {"No", "Sí"} default button "No" giving up after 120')
            r = subprocess.run(["osascript", "-e", f"on run argv\n{guion}\nend run",
                                texto, titulo], capture_output=True, text=True, timeout=130)
            return "Sí" in r.stdout
        if shutil.which("zenity"):
            return subprocess.run(["zenity", "--question", "--default-cancel",
                                   "--title", titulo, "--text", texto, "--timeout", "120"],
                                  timeout=130).returncode == 0
        if shutil.which("kdialog"):
            return subprocess.run(["kdialog", "--title", titulo, "--warningyesno", texto],
                                  timeout=130).returncode == 0
    except Exception as exc:  # noqa: BLE001 - sin ventana no hay confianza
        print(f"anonimizador/mcp: no se pudo preguntar: {exc!r}", file=sys.stderr, flush=True)
    return False


def demasiado_amplia(carpeta: str) -> bool:
    """Raices de disco, la carpeta personal (o una superior) y las del sistema:
    confiar en ellas equivaldria a no tener limite."""
    p = Path(carpeta)
    if p == Path(p.anchor) or config.dentro_de(Path.home(), carpeta):
        return True
    sistema = [os.environ.get(v) for v in ("SystemRoot", "ProgramFiles",
                                           "ProgramFiles(x86)", "ProgramData")]
    sistema += ["/etc", "/usr", "/bin", "/var", "/System", "/Library"] if os.name != "nt" else []
    return any(s and config.dentro_de(carpeta, s) for s in sistema)


class Servidor:
    def __init__(self, carpetas: list[str]):
        self.fijas = [os.path.realpath(os.path.expanduser(c)) for c in carpetas]
        # Sin carpeta principal, el mapa de identificadores es uno propio del
        # servidor, comun a todas las carpetas en las que se confie.
        self.proyecto = self.fijas[0] if self.fijas else str(config.home() / "escritorio")
        self.actual = self.fijas[0] if self.fijas else None  # base de las rutas relativas
        self.tuberia = None

    # -- carpetas de confianza ---------------------------------------------- #

    @property
    def _fichero_confianza(self) -> Path:
        return config.home() / "confianza.json"

    def confiadas(self) -> list[str]:
        try:
            datos = json.loads(self._fichero_confianza.read_text(encoding="utf-8"))
            return [c for c in datos.get("carpetas", []) if isinstance(c, str)]
        except (OSError, ValueError, AttributeError):
            return []

    @property
    def carpetas(self) -> list[str]:
        return self.fijas + [c for c in self.confiadas() if c not in self.fijas]

    def pedir_confianza(self, ruta: str) -> None:
        """Pide al usuario que confie en la carpeta de 'ruta'; Rechazo si no."""
        carpeta = ruta if os.path.isdir(ruta) else os.path.dirname(ruta)
        if not os.path.isdir(carpeta):
            raise Rechazo("No existe esa carpeta.")
        if demasiado_amplia(carpeta):
            raise Rechazo("Esa carpeta es demasiado amplia para darle acceso (una raiz "
                          "de disco, la carpeta personal o una del sistema). Pide al "
                          "usuario que mueva los documentos a una carpeta de trabajo.")
        if not preguntar_confianza(carpeta):
            raise Rechazo("El usuario no ha dado su confianza a esa carpeta (ha "
                          "respondido que no, o no ha respondido a la ventana de "
                          "confirmacion). No insistas: preguntale si quiere usarla.")
        lista = self.confiadas()
        if carpeta not in lista:
            lista.append(carpeta)
            config.home().mkdir(parents=True, exist_ok=True)
            temporal = self._fichero_confianza.with_suffix(".tmp")
            temporal.write_text(json.dumps({"carpetas": lista}, ensure_ascii=False, indent=1),
                                encoding="utf-8")
            os.replace(temporal, self._fichero_confianza)

    def cfg(self) -> dict:
        return config.cargar(self.proyecto)

    def mapa(self) -> Mapa | None:
        return Mapa(self.proyecto) if hay_mapa(self.proyecto) else None

    def ocultar(self, texto: str) -> str:
        """Sustituye los datos ya conocidos (p. ej. en nombres de fichero)."""
        mapa = self.mapa()
        return mapa.sustituir(texto) if mapa else texto

    def permitida(self, ruta: str) -> bool:
        return any(config.dentro_de(ruta, c) for c in self.carpetas)

    def resolver(self, ruta: str, debe_existir: bool = True) -> str:
        """Ruta real dentro de las carpetas permitidas. Acepta rutas relativas
        a la carpeta principal y nombres con identificadores (tal como los
        muestra listar_carpeta)."""
        if not isinstance(ruta, str) or not ruta.strip():
            raise Rechazo("Falta la ruta.")
        candidatas = [ruta.strip()]
        mapa = self.mapa()
        if mapa:
            revelada, cambios = mapa.revelar(candidatas[0])
            if cambios:
                candidatas.append(revelada)
        elegida = None
        for c in candidatas:
            c = os.path.expanduser(c)
            if not os.path.isabs(c):
                if self.actual is None:
                    raise Rechazo("Indica la ruta completa del fichero o de la carpeta "
                                  "(por ejemplo C:\\Clientes\\contrato.docx): todavia no "
                                  "hay ninguna carpeta de trabajo.")
                c = os.path.join(self.actual, c)
            # realpath resuelve '..' y enlaces simbolicos. Si ninguna existe
            # (fichero nuevo), vale la ultima: la del nombre real.
            elegida = os.path.realpath(c)
            if os.path.exists(elegida):
                break
        nombre = os.path.basename(elegida).lower()
        if (config.dentro_de(elegida, config.home()) or ".revelado." in nombre
                or nombre.endswith(".revelado") or nombre == config.NOMBRE_CONFIG_PROYECTO):
            raise Rechazo("Ese fichero no se puede leer: contiene datos reales "
                          "restaurados o es un fichero interno del anonimizador.")
        if not self.permitida(elegida):
            # Carpeta nueva: decide el usuario, en una ventana aparte.
            self.pedir_confianza(elegida)
        if debe_existir and not os.path.exists(elegida):
            raise Rechazo("No existe ese fichero o carpeta. Usa `listar_carpeta` para "
                          "ver los nombres disponibles.")
        self.actual = elegida if os.path.isdir(elegida) else os.path.dirname(elegida)
        return elegida

    # ----------------------------------------------------------------------- #
    # Herramientas
    # ----------------------------------------------------------------------- #

    def leer_documento(self, ruta: str, desde: int = 0) -> str:
        fichero = self.resolver(ruta)
        if not os.path.isfile(fichero):
            raise Rechazo("Eso es una carpeta. Usa `listar_carpeta`.")
        cfg = self.cfg()
        sufijo = os.path.splitext(fichero)[1].lower()
        admitidas = (set(cfg["extensiones_documento"]) | set(cfg["extensiones_texto"])
                     | config.EXT_OCR)
        if sufijo not in admitidas:
            raise Rechazo(f"Formato no soportado ({sufijo or 'sin extension'}). Se pueden "
                          f"leer: {' '.join(sorted(admitidas))}")
        if self.tuberia is None:
            try:
                from anonimizador import tuberia
            except ImportError as exc:
                raise Rechazo("El motor de anonimizacion no esta instalado. Pide al "
                              "usuario que ejecute `python instalar.py` en la carpeta "
                              f"del anonimizador. ({exc})") from None
            self.tuberia = tuberia
        from anonimizador import conversion
        try:
            resultado = self.tuberia.procesar(self.proyecto, fichero, cfg)
        except conversion.SinTexto:
            raise Rechazo("El fichero no tiene texto reconocible (una foto, un logotipo "
                          "o un escaneado ilegible). Este servidor no entrega imagenes, "
                          "solo su texto.") from None
        texto = Path(resultado["salida"]).read_text(encoding="utf-8")
        desde = max(0, int(desde or 0))
        trozo = texto[desde:desde + TROZO]
        cabecera = [f"[Copia anonimizada en local: {resultado['entidades']} dato(s) "
                    f"sustituidos por identificadores."]
        if resultado.get("ocr"):
            cabecera.append(" Texto obtenido por OCR: puede tener erratas y no conserva "
                            "tablas ni maquetacion.")
        if desde + TROZO < len(texto):
            cabecera.append(f" Documento largo: esto son los caracteres {desde}-"
                            f"{desde + len(trozo)} de {len(texto)}; sigue con "
                            f"desde={desde + TROZO}.")
        return "".join(cabecera) + "]\n\n" + trozo

    def listar_carpeta(self, ruta: str = "") -> str:
        if not ruta and self.actual is None:
            raise Rechazo("Indica la ruta completa de la carpeta: todavia no hay "
                          "ninguna carpeta de trabajo.")
        carpeta = self.resolver(ruta) if ruta else self.actual
        if not os.path.isdir(carpeta):
            raise Rechazo("Eso no es una carpeta.")
        lineas = []
        for entrada in sorted(os.scandir(carpeta), key=lambda e: e.name.lower()):
            nombre = entrada.name
            minus = nombre.lower()
            if ".revelado." in minus or minus == config.NOMBRE_CONFIG_PROYECTO:
                continue
            if entrada.is_dir():
                lineas.append(self.ocultar(nombre) + "/")
            else:
                lineas.append(f"{self.ocultar(nombre)}  ({entrada.stat().st_size // 1024 + 1} KB)")
        if not lineas:
            return "(carpeta vacia)"
        return ("Los datos personales ya conocidos aparecen como identificadores "
                "tambien en los nombres; usa el nombre tal como se muestra.\n"
                + "\n".join(lineas))

    def _destino_revelado(self, ruta: str, sufijo_defecto: str = ".md") -> tuple[Path, str]:
        """(ruta real del fichero .revelado, nombre a mostrar a Claude)."""
        base = Path(ruta.strip())
        sufijo = base.suffix.lower() or sufijo_defecto
        if sufijo not in EXT_REVELABLES:
            raise Rechazo(f"Solo se guardan ficheros de texto ({' '.join(sorted(EXT_REVELABLES))}).")
        tronco = base.stem if base.suffix else base.name
        if tronco.lower().endswith(".revelado"):
            tronco = tronco[:-len(".revelado")]
        visible = str(base.with_name(f"{tronco}.revelado{sufijo}"))
        # resolver() comprueba la carpeta; el nombre '.revelado.' se anade despues
        # porque resolver() lo rechazaria como fichero ilegible.
        real = Path(self.resolver(str(base.with_name(tronco + sufijo)), debe_existir=False))
        return real.with_name(f"{real.stem}.revelado{sufijo}"), visible

    def guardar_revelado(self, ruta: str, texto: str) -> str:
        if not isinstance(texto, str) or not texto.strip():
            raise Rechazo("Falta el texto.")
        if not isinstance(ruta, str) or not ruta.strip():
            raise Rechazo("Falta la ruta.")
        mapa = self.mapa()
        if mapa is None:
            raise Rechazo("Todavia no hay identificadores en este proyecto: lee antes "
                          "algun documento con `leer_documento`.")
        destino, visible = self._destino_revelado(ruta)
        if not destino.parent.is_dir():
            raise Rechazo("La carpeta de destino no existe.")
        revelado, cambios = mapa.revelar(texto)
        destino.write_text(revelado, encoding="utf-8")
        return (f"Guardado con los datos reales en «{visible}» ({cambios} identificador(es) "
                f"restaurados). Dile al usuario que lo abra en su equipo; tu no puedes "
                f"leerlo.")

    def revelar_fichero(self, ruta: str) -> str:
        origen = Path(self.resolver(ruta))
        if not origen.is_file() or origen.suffix.lower() not in EXT_REVELABLES:
            raise Rechazo(f"Solo se revelan ficheros de texto ({' '.join(sorted(EXT_REVELABLES))}).")
        mapa = self.mapa()
        if mapa is None:
            raise Rechazo("Todavia no hay identificadores en este proyecto.")
        revelado, cambios = mapa.revelar(origen.read_text(encoding="utf-8", errors="replace"))
        destino = origen.with_name(f"{origen.stem}.revelado{origen.suffix}")
        destino.write_text(revelado, encoding="utf-8")
        return (f"{cambios} identificador(es) restaurados en «{self.ocultar(destino.name)}», "
                f"junto al original. Tu no puedes leer ese fichero.")

    def estado(self) -> str:
        cfg = self.cfg()
        lineas = [f"Anonimizador local {__version__} (servidor MCP)",
                  "Carpetas accesibles:"]
        lineas += [f"  - {self.ocultar(c)}" for c in self.carpetas] or ["  (ninguna todavia)"]
        lineas.append("Para cualquier otra carpeta se pide confirmacion al usuario en una "
                      "ventana aparte la primera vez; usa rutas completas.")
        if self.actual:
            lineas.append(f"Las rutas relativas parten de: {self.ocultar(self.actual)}")
        interprete = config.python_del_entorno()
        lineas.append("Motor instalado: " + ("si" if interprete else
                                             "NO (falta ejecutar instalar.py)"))
        admitidas = sorted(set(cfg["extensiones_documento"]) | set(cfg["extensiones_texto"])
                           | config.EXT_OCR)
        lineas.append("Formatos: " + " ".join(admitidas))
        mapa = self.mapa()
        if mapa:
            por_tipo: dict[str, int] = {}
            for pseudo in mapa.reales:
                prefijo = pseudo.rsplit("_", 1)[0]
                por_tipo[prefijo] = por_tipo.get(prefijo, 0) + 1
            resumen = ", ".join(f"{t}: {n}" for t, n in sorted(por_tipo.items()))
            lineas.append(f"Identificadores en el mapa: {len(mapa.reales)} ({resumen})")
        else:
            lineas.append("Identificadores en el mapa: 0")
        return "\n".join(lineas)


def _esquema(propiedades: dict, obligatorias: list[str]) -> dict:
    return {"type": "object", "properties": propiedades, "required": obligatorias,
            "additionalProperties": False}


HERRAMIENTAS = [
    {
        "name": "leer_documento",
        "title": "Leer documento anonimizado",
        "description": (
            "Lee un documento (Word, PDF, Excel, imagen o PDF escaneado por OCR, o "
            "fichero de texto) y devuelve su contenido en Markdown con los datos "
            "personales sustituidos por identificadores como PERSONA_1 o NIF_1. La "
            "conversion y el anonimizado se hacen en el equipo del usuario. Es la "
            "unica forma correcta de leer documentos de las carpetas del usuario."),
        "inputSchema": _esquema({
            "ruta": {"type": "string", "description":
                     "Ruta absoluta, o relativa a la carpeta principal."},
            "desde": {"type": "integer", "minimum": 0, "description":
                      "Caracter por el que continuar en documentos largos (por defecto 0)."},
        }, ["ruta"]),
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "listar_carpeta",
        "title": "Listar carpeta",
        "description": (
            "Lista los ficheros de una carpeta accesible. Los datos personales ya "
            "conocidos se muestran como identificadores tambien en los nombres."),
        "inputSchema": _esquema({
            "ruta": {"type": "string", "description":
                     "Carpeta a listar; vacio para la carpeta principal."},
        }, []),
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "guardar_revelado",
        "title": "Guardar con los datos reales",
        "description": (
            "Guarda en el equipo del usuario un texto escrito por ti con "
            "identificadores, sustituyendolos por los datos reales. Usalo para "
            "entregar resumenes, cartas o informes: el fichero se crea como "
            "<nombre>.revelado.md y tu solo recibes el recuento de sustituciones."),
        "inputSchema": _esquema({
            "ruta": {"type": "string", "description":
                     "Nombre o ruta del fichero (p. ej. «resumen.md»), relativa a la "
                     "carpeta principal."},
            "texto": {"type": "string", "description":
                      "Contenido, con los identificadores tal como los recibiste."},
        }, ["ruta", "texto"]),
        "annotations": {"readOnlyHint": False, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "revelar_fichero",
        "title": "Revelar un fichero existente",
        "description": (
            "Crea junto a un fichero de texto con identificadores una copia "
            "<nombre>.revelado.<ext> con los datos reales. Devuelve solo el recuento."),
        "inputSchema": _esquema({"ruta": {"type": "string"}}, ["ruta"]),
        "annotations": {"readOnlyHint": False, "destructiveHint": False,
                        "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "estado",
        "title": "Estado del anonimizador",
        "description": "Carpetas accesibles, formatos admitidos y numero de identificadores.",
        "inputSchema": _esquema({}, []),
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
]


# --------------------------------------------------------------------------- #
# Protocolo
# --------------------------------------------------------------------------- #

def atender(servidor: Servidor, mensaje: dict) -> dict | None:
    """Respuesta JSON-RPC, o None si el mensaje es una notificacion."""
    metodo = mensaje.get("method")
    ident = mensaje.get("id")
    if metodo is None or ident is None:
        return None  # notificacion, o respuesta a algo que no hemos pedido

    def resultado(valor: dict) -> dict:
        return {"jsonrpc": "2.0", "id": ident, "result": valor}

    if metodo == "initialize":
        pedida = (mensaje.get("params") or {}).get("protocolVersion")
        return resultado({
            "protocolVersion": pedida if pedida in VERSIONES_MCP else VERSIONES_MCP[0],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "anonimizador", "title": "Anonimizador local",
                           "version": __version__},
            "instructions": INSTRUCCIONES,
        })
    if metodo == "ping":
        return resultado({})
    if metodo == "tools/list":
        return resultado({"tools": HERRAMIENTAS})
    if metodo == "tools/call":
        params = mensaje.get("params") or {}
        nombre = params.get("name")
        argumentos = params.get("arguments") or {}
        if nombre not in {h["name"] for h in HERRAMIENTAS}:
            return {"jsonrpc": "2.0", "id": ident,
                    "error": {"code": -32602, "message": f"Herramienta desconocida: {nombre}"}}
        try:
            texto, error = getattr(servidor, nombre)(**argumentos), False
        except Rechazo as exc:
            texto, error = str(exc), True
        except TypeError as exc:
            texto, error = f"Argumentos no validos: {exc}", True
        except Exception as exc:  # noqa: BLE001 - fallo cerrado: nunca el original
            texto, error = (f"Error interno ({type(exc).__name__}). No se ha entregado "
                            f"ningun contenido."), True
            print(f"anonimizador/mcp: {exc!r}", file=sys.stderr, flush=True)
        return resultado({"content": [{"type": "text", "text": texto}], "isError": error})
    return {"jsonrpc": "2.0", "id": ident,
            "error": {"code": -32601, "message": f"Metodo no soportado: {metodo}"}}


def servir(servidor: Servidor) -> int:
    # La salida estandar es el canal del protocolo. Se aparta a un descriptor
    # propio y el descriptor 1 se redirige a stderr: asi ninguna biblioteca
    # (spaCy, ONNX Runtime...) puede corromperlo con sus mensajes.
    canal = os.fdopen(os.dup(sys.stdout.fileno()), "wb")
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    sys.stdout = sys.stderr

    for linea in sys.stdin.buffer:
        linea = linea.strip()
        if not linea:
            continue
        try:
            mensaje = json.loads(linea.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            respuestas = [{"jsonrpc": "2.0", "id": None,
                           "error": {"code": -32700, "message": "JSON no valido"}}]
        else:
            lote = mensaje if isinstance(mensaje, list) else [mensaje]
            respuestas = [r for r in (atender(servidor, m) for m in lote
                                      if isinstance(m, dict)) if r is not None]
        for respuesta in respuestas:
            canal.write(json.dumps(respuesta, ensure_ascii=False).encode("utf-8") + b"\n")
            canal.flush()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Servidor MCP del anonimizador local.")
    ap.add_argument("--carpeta", action="append", default=[],
                    help="Carpeta con acceso desde el principio, sin preguntar "
                         "(opcional, repetible). Para las demas se pide "
                         "confirmacion al usuario la primera vez.")
    args = ap.parse_args(argv)
    for carpeta in args.carpeta:
        if not os.path.isdir(os.path.expanduser(carpeta)):
            ap.error(f"no existe la carpeta: {carpeta}")
    return servir(Servidor(args.carpeta))


if __name__ == "__main__":
    sys.exit(main())
