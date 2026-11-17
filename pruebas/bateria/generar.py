#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Genera la bateria de pruebas: documentos con datos personales INVENTADOS.

    python pruebas/bateria/generar.py

Crea pruebas/bateria/casos/ con unos 30 ficheros (texto, Word, Excel, PDF,
imagenes degradadas, capturas de pantalla simuladas) y casos/esperado.json, que
dice que datos contiene cada uno. lanzar.py usa ese fichero para comprobar que
no se escapa ninguno.

Todos los datos son ficticios: nombres inventados, NIF/NIE/IBAN con digito de
control valido pero generados aqui, tarjetas de prueba publicas (4111...),
correos en dominios reservados (example.com/.org/.net). Se puede regenerar
cuando se quiera: el resultado es siempre el mismo.

Necesita el entorno del anonimizador (Pillow, numpy, OpenCV y openpyxl ya
vienen con el); si se lanza con otro Python, se relanza solo dentro de el.
"""

from __future__ import annotations

import io
import json
import os
import random
import re
import subprocess
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent.parent
sys.path.insert(0, str(RAIZ))
CASOS = AQUI / "casos"


def _relanzar() -> None:
    try:
        import cv2  # noqa: F401
        import numpy  # noqa: F401
        import openpyxl  # noqa: F401
        import PIL  # noqa: F401
    except ImportError:
        from anonimizador import config
        interprete = config.python_del_entorno()
        if interprete is None or Path(sys.executable).resolve() == interprete.resolve():
            sys.exit("Faltan dependencias. Ejecuta primero:  python instalar.py")
        sys.exit(subprocess.call([str(interprete), str(Path(__file__).resolve()), *sys.argv[1:]]))


# --------------------------------------------------------------------------- #
# Datos ficticios con digito de control valido
# --------------------------------------------------------------------------- #

LETRAS_NIF = "TRWAGMYFPDXBNJZSQVHLCKE"


def nif(numero: int) -> str:
    return f"{numero:08d}{LETRAS_NIF[numero % 23]}"


def nie(prefijo: str, numero: int) -> str:
    return f"{prefijo}{numero:07d}{LETRAS_NIF[int('XYZ'.index(prefijo) * 10**7 + numero) % 23]}"


def iban_es(banco: str, oficina: str, cuenta: str) -> str:
    bban = f"{banco}{oficina}00{cuenta}"
    numero = int(bban + "142800")  # E=14 S=28 00
    return f"ES{98 - numero % 97:02d}{bban}"


def agrupar(texto: str, n: int = 4, sep: str = " ") -> str:
    return sep.join(texto[i:i + n] for i in range(0, len(texto), n))


PERSONAS = [
    # nombre, documento, correo, movil, iban
    dict(nombre="Lucía Martín Sanz", doc=nif(48291736), correo="lucia.martin@example.com",
         movil="+34 612 345 678", iban=iban_es("2100", "0418", "4502051332")),
    dict(nombre="Javier Ortega de la Fuente", doc=nie("X", 1234567), correo="j.ortega@example.org",
         movil="634 112 908", iban=iban_es("0049", "1500", "0512345678")),
    dict(nombre="María José Ibáñez Peña", doc=nif(30561278), correo="mjibanez@example.net",
         movil="699 487 221", iban=iban_es("0182", "2370", "4201234567")),
    dict(nombre="Xabier Etxeberria Goikoetxea", doc=nif(72849153), correo="xetxeberria@example.com",
         movil="688 902 145", iban=iban_es("2095", "0611", "0912345678")),
    dict(nombre="Ahmed El Amrani", doc=nie("Y", 4567890), correo="ahmed.elamrani@example.org",
         movil="622 718 330", iban=iban_es("1465", "0100", "9912345678")),
    dict(nombre="Rocío Domínguez Cano", doc=nif(26014587), correo="rocio.dominguez@example.net",
         movil="655 230 871", iban=iban_es("0081", "0216", "7300012345")),
]
L, J, M, X, A, R = PERSONAS

TARJETAS = ["4111 1111 1111 1111", "5555 5555 5555 4444"]
DIRECCIONES = ["Calle del Almendro 14, 3.º B, 14005 Córdoba",
               "Avenida de la Constitución 221, 41001 Sevilla"]
NACIMIENTOS = ["17/03/1984", "02/11/1979"]
NSS = ["28 1234567840", "41 7654321002"]
IPS = ["192.168.10.24", "83.44.120.7"]

# Catalogo: (literal, tipo, categoria)
#   ocultar     el plugin DEBE sustituirlo: si aparece en la salida es un FALLO
#   limite      tipos que el detector no cubre (direcciones, fechas, NSS...):
#               si aparecen es un AVISO, documentado en el README
CATALOGO: list[tuple[str, str, str]] = []
for p in PERSONAS:
    CATALOGO += [(p["nombre"], "PERSONA", "ocultar"),
                 (p["doc"], "NIF/NIE", "ocultar"),
                 (p["correo"], "CORREO", "ocultar"),
                 (p["movil"], "TELEFONO", "ocultar"),
                 (p["iban"], "IBAN", "ocultar"),
                 (agrupar(p["iban"]), "IBAN", "ocultar")]
CATALOGO += [(t, "TARJETA", "ocultar") for t in TARJETAS]
CATALOGO += [(t.replace(" ", ""), "TARJETA", "ocultar") for t in TARJETAS]
CATALOGO += [(i, "IP", "ocultar") for i in IPS]
CATALOGO += [(d, "DIRECCION", "limite") for d in DIRECCIONES]
CATALOGO += [(n, "FECHA_NACIMIENTO", "limite") for n in NACIMIENTOS]
CATALOGO += [(n, "SEGURIDAD_SOCIAL", "limite") for n in NSS]
# Menciones sueltas de un nombre de pila o un apodo: dificiles para el detector.
CATALOGO += [("Lucía", "NOMBRE_SUELTO", "limite"), ("Javi", "NOMBRE_SUELTO", "limite"), ("Rocío", "NOMBRE_SUELTO", "limite"),
             ("Xabier", "NOMBRE_SUELTO", "limite"), ("Sra. Domínguez", "PERSONA", "ocultar")]

# Palabras normales que NO deben desaparecer (para medir el exceso de celo).
DEBEN_QUEDAR = ["arrendamiento", "Importe", "Total", "factura", "Tornillo", "reunión",
                "vencimiento", "transferencia", "Nómina", "pedido", "Asunto", "presupuesto"]

# Variantes de formato: el mismo dato escrito de otras maneras.
VARIANTES = [
    (f"{L['doc'][:8]}-{L['doc'][8]}", "NIF/NIE"),
    (f"{L['doc'][:2]}.{L['doc'][2:5]}.{L['doc'][5:8]}-{L['doc'][8]}", "NIF/NIE"),
    (L["doc"].lower(), "NIF/NIE"),
    (f"{L['doc'][:8]} {L['doc'][8]}", "NIF/NIE"),
    (f"{J['doc'][0]}-{J['doc'][1:8]}-{J['doc'][8]}", "NIF/NIE"),
    (agrupar(M["iban"], 4, "-"), "IBAN"),
    (M["iban"].lower(), "IBAN"),
    ("0034612345678", "TELEFONO"),
    ("612-345-678", "TELEFONO"),
    ("(+34) 612 34 56 78", "TELEFONO"),
    ("612.345.678", "TELEFONO"),
    ("957 412 380", "TELEFONO"),
    ("4111-1111-1111-1111", "TARJETA"),
    ("3782 822463 10005", "TARJETA"),
    ("LUCIA.MARTIN@EXAMPLE.COM", "CORREO"),
    ("lucia+facturas@example.org", "CORREO"),
    ("2001:db8:85a3::8a2e:370:7334", "IP"),
]
CATALOGO += [(v, t, "ocultar") for v, t in VARIANTES]


# --------------------------------------------------------------------------- #
# Textos base
# --------------------------------------------------------------------------- #

def lineas_contrato() -> list[str]:
    return [
        "CONTRATO DE ARRENDAMIENTO DE VIVIENDA",
        "",
        f"En Córdoba, a 3 de marzo de 2026. De una parte, {R['nombre']}, con NIF {R['doc']},",
        f"en calidad de arrendadora. De otra, {L['nombre']}, con NIF {L['doc']},",
        f"nacida el {NACIMIENTOS[0]} y con domicilio en {DIRECCIONES[0]}.",
        "",
        "PRIMERA. La renta mensual es de 750 euros, pagadera por transferencia",
        f"a la cuenta {agrupar(R['iban'])} antes del día 5 de cada mes.",
        f"SEGUNDA. Notificaciones: {L['correo']} / teléfono {L['movil']}.",
        "TERCERA. El vencimiento del contrato será el 2 de marzo de 2027.",
        "",
        f"Firmado: {R['nombre']}            Firmado: {L['nombre']}",
    ]


def lineas_factura() -> list[str]:
    return [
        "FACTURA N.º 2026-0417",
        "Suministros Industriales del Sur S.L. - Polígono La Torrecilla, nave 7",
        "",
        f"Cliente: {X['nombre']}",
        f"NIF: {X['doc']}     Tel.: {X['movil']}",
        f"Correo: {X['correo']}",
        "",
        "Concepto                      Cant.   Precio    Importe",
        "Tornillo M8 x 40 (caja)         12     4,50      54,00",
        "Arandela plana M8 (caja)         6     2,10      12,60",
        "Total con IVA                                    79,86",
        "",
        f"Pago con tarjeta {TARJETAS[0]} o por transferencia a {X['iban']}",
    ]


def lineas_ficha() -> list[str]:
    return [
        "FICHA DE CLIENTE",
        f"Nombre y apellidos: {M['nombre']}",
        f"Documento: {M['doc']}",
        f"Fecha de nacimiento: {NACIMIENTOS[1]}",
        f"N.º Seguridad Social: {NSS[1]}",
        f"Domicilio: {DIRECCIONES[1]}",
        f"Teléfono: {M['movil']}   Correo: {M['correo']}",
        f"Cuenta de cargo: {agrupar(M['iban'])}",
        "Observaciones: prefiere contacto por la tarde.",
    ]


# --------------------------------------------------------------------------- #
# Escritores sin dependencias: DOCX y PDF
# --------------------------------------------------------------------------- #

def escribir_docx(ruta: Path, cuerpo: str, cabecera: str = "", autor: str = "") -> None:
    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" ' \
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    partes = {
        "[Content_Types].xml":
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '<Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>'
            '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
            '</Types>',
        "_rels/.rels":
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
            '</Relationships>',
        "word/_rels/document.xml.rels":
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>'
            '</Relationships>',
        "word/header1.xml":
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:hdr {w}>'
            f'<w:p><w:r><w:t xml:space="preserve">{escape(cabecera)}</w:t></w:r></w:p></w:hdr>',
        "word/document.xml":
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {w}><w:body>'
            f'{cuerpo}<w:sectPr><w:headerReference w:type="default" r:id="rId1"/></w:sectPr>'
            '</w:body></w:document>',
        "docProps/core.xml":
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/">'
            f'<dc:creator>{escape(autor)}</dc:creator></cp:coreProperties>',
    }
    with zipfile.ZipFile(ruta, "w", zipfile.ZIP_DEFLATED) as z:
        for nombre, contenido in partes.items():
            z.writestr(nombre, contenido)


def w_parrafo(*trozos, estilo: str = "") -> str:
    """trozos: texto, o (texto, 'b') en negrita, o (texto, 'del'/'ins') con control de cambios."""
    ppr = f'<w:pPr><w:pStyle w:val="{estilo}"/></w:pPr>' if estilo else ""
    salida = []
    for t in trozos:
        texto, marca = (t, "") if isinstance(t, str) else t
        rpr = "<w:rPr><w:b/></w:rPr>" if marca == "b" else ""
        if marca == "del":
            salida.append(f'<w:del w:id="1" w:author="Revisor" w:date="2026-03-01T10:00:00Z"><w:r>'
                          f'<w:delText xml:space="preserve">{escape(texto)}</w:delText></w:r></w:del>')
        elif marca == "ins":
            salida.append(f'<w:ins w:id="2" w:author="Revisor" w:date="2026-03-01T10:00:00Z"><w:r>'
                          f'<w:t xml:space="preserve">{escape(texto)}</w:t></w:r></w:ins>')
        else:
            salida.append(f'<w:r>{rpr}<w:t xml:space="preserve">{escape(texto)}</w:t></w:r>')
    return f"<w:p>{ppr}{''.join(salida)}</w:p>"


def w_tabla(filas: list[list[str]]) -> str:
    celdas = "".join(
        "<w:tr>" + "".join(f'<w:tc><w:p><w:r><w:t xml:space="preserve">{escape(c)}</w:t></w:r></w:p></w:tc>'
                           for c in fila) + "</w:tr>" for fila in filas)
    return ('<w:tbl><w:tblPr><w:tblBorders><w:top w:val="single" w:sz="4"/><w:bottom w:val="single" w:sz="4"/>'
            '<w:insideH w:val="single" w:sz="4"/><w:insideV w:val="single" w:sz="4"/></w:tblBorders></w:tblPr>'
            f"{celdas}</w:tbl>")


def escribir_pdf(ruta: Path, paginas: list[list[tuple]]) -> None:
    """PDF minimo con capa de texto. Cada pagina es una lista de
    ('t', x, y, tamano, texto[, negrita]) o ('img', bytes_jpeg, ancho, alto)."""
    objetos: list[bytes] = []

    def nuevo(contenido: bytes) -> int:
        objetos.append(contenido)
        return len(objetos)

    nuevo(b"")  # 1 catalogo (se rellena al final)
    nuevo(b"")  # 2 arbol de paginas
    f1 = nuevo(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    f2 = nuevo(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    hijos = []
    for elementos in paginas:
        flujo, recursos_img = [], []
        for e in elementos:
            if e[0] == "t":
                _, x, y, tam, texto, *neg = e
                t = texto.encode("cp1252").replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
                fuente = "F2" if neg and neg[0] else "F1"
                flujo.append(f"BT /{fuente} {tam} Tf {x} {y} Td (".encode() + t + b") Tj ET")
            else:
                _, datos, ancho, alto = e
                n = nuevo(f"<< /Type /XObject /Subtype /Image /Width {ancho} /Height {alto} "
                          f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode "
                          f"/Length {len(datos)} >>\nstream\n".encode() + datos + b"\nendstream")
                nombre = f"Im{len(recursos_img) + 1}"
                recursos_img.append(f"/{nombre} {n} 0 R")
                flujo.append(f"q 595 0 0 842 0 0 cm /{nombre} Do Q".encode())
        cuerpo = b"\n".join(flujo)
        contenido = nuevo(f"<< /Length {len(cuerpo)} >>\nstream\n".encode() + cuerpo + b"\nendstream")
        xo = f" /XObject << {' '.join(recursos_img)} >>" if recursos_img else ""
        hijos.append(nuevo(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents {contenido} 0 R "
            f"/Resources << /Font << /F1 {f1} 0 R /F2 {f2} 0 R >>{xo} >> >>".encode()))
    objetos[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objetos[1] = (f"<< /Type /Pages /Count {len(hijos)} /Kids [" +
                  " ".join(f"{h} 0 R" for h in hijos) + "] >>").encode()

    salida = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    posiciones = []
    for i, obj in enumerate(objetos, 1):
        posiciones.append(len(salida))
        salida += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(salida)
    salida += f"xref\n0 {len(objetos) + 1}\n0000000000 65535 f \n".encode()
    salida += b"".join(f"{p:010d} 00000 n \n".encode() for p in posiciones)
    salida += f"trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    ruta.write_bytes(bytes(salida))


def pdf_lineas(lineas: list[str], y0: int = 790, tam: int = 11) -> list[tuple]:
    salida = []
    for i, linea in enumerate(lineas):
        if linea:
            salida.append(("t", 56, y0 - i * 18, tam + (3 if i == 0 else 0), linea, i == 0))
    return salida


# --------------------------------------------------------------------------- #
# Imagenes
# --------------------------------------------------------------------------- #

def fuente(nombres: list[str], tam: int):
    from PIL import ImageFont
    dirs = [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts", Path("/usr/share/fonts/truetype/dejavu"),
            Path("/Library/Fonts"), Path("/System/Library/Fonts/Supplemental")]
    for n in nombres + ["arial.ttf", "DejaVuSans.ttf", "Arial.ttf"]:
        for d in dirs:
            if (d / n).is_file():
                return ImageFont.truetype(str(d / n), tam)
    return ImageFont.load_default(tam)


def pagina(lineas: list[str], tipo: list[str] | None = None, tam: int = 26, ancho: int = 1240,
           alto: int = 1754, fondo=(255, 255, 255), tinta=(25, 25, 25), interlinea: float = 1.55,
           temblor: int = 0):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (ancho, alto), fondo)
    d = ImageDraw.Draw(img)
    normal = fuente(tipo or ["arial.ttf"], tam)
    tipo = tipo or ["arial.ttf"]
    negritas = [n.replace(".ttf", s) for n in tipo for s in ("bd.ttf", "b.ttf")]
    titulo = fuente(negritas + tipo, int(tam * 1.25))
    azar = random.Random(7)
    y = 110
    for i, linea in enumerate(lineas):
        f = titulo if i == 0 else normal
        if temblor:
            x = 90
            for palabra in linea.split(" "):
                d.text((x, y + azar.randint(-temblor, temblor)), palabra, font=f, fill=tinta)
                x += d.textlength(palabra + " ", font=f) + azar.randint(0, temblor)
        else:
            d.text((90, y), linea, font=f, fill=tinta)
        y += int(tam * interlinea) + (12 if i == 0 else 0)
    return img


def recortar(img, margen: int = 60):
    import numpy as np
    from PIL import Image
    gris = np.asarray(img.convert("L"))
    filas = np.where(gris.min(axis=1) < 200)[0]
    if not len(filas):
        return img
    abajo = min(img.height, filas.max() + margen)
    return img.crop((0, 0, img.width, abajo)) if isinstance(img, Image.Image) else img


def foto_inclinada(img):
    """Foto de movil: perspectiva, giro leve, sombra y compresion JPEG."""
    import cv2
    import numpy as np
    from PIL import Image
    a = np.asarray(img.convert("RGB")).astype(np.float32)
    h, w = a.shape[:2]
    origen = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    destino = np.float32([[w * .06, h * .03], [w * .96, 0], [w * .99, h * .97], [w * .02, h * .99]])
    m = cv2.getPerspectiveTransform(origen, destino)
    a = cv2.warpPerspective(a, m, (w, h), borderValue=(92, 84, 70))  # mesa de madera
    sombra = np.linspace(1.0, 0.72, w, dtype=np.float32)[None, :, None]
    a = np.clip(a * sombra * np.float32([1.0, 0.97, 0.9]), 0, 255).astype(np.uint8)
    img = Image.fromarray(a).rotate(-2.5, expand=False, fillcolor=(92, 84, 70))
    return img


def borrosa(img):
    from PIL import ImageFilter
    return img.filter(ImageFilter.GaussianBlur(2.2))


def baja_resolucion(img):
    pequena = img.resize((img.width // 3, img.height // 3))
    return pequena


def escaner_sucio(img):
    import numpy as np
    from PIL import Image
    a = np.asarray(img.convert("L")).astype(np.int16)
    azar = np.random.default_rng(3)
    a = a * 0.86 + 20 + azar.normal(0, 18, a.shape)          # fondo gris y grano
    motas = azar.random(a.shape)
    a[motas < 0.004] = 0                                      # puntos negros
    a[motas > 0.996] = 255
    img = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).convert("RGB")
    return img.rotate(1.2, expand=False, fillcolor=(235, 235, 235))


def jpeg(img, calidad: int) -> bytes:
    b = io.BytesIO()
    img.convert("RGB").save(b, "JPEG", quality=calidad)
    return b.getvalue()


def captura_correo():
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (1366, 768), (243, 243, 243))
    d = ImageDraw.Draw(img)
    ui, uib = fuente(["segoeui.ttf"], 15), fuente(["segoeuib.ttf"], 15)
    d.rectangle((0, 0, 1366, 46), fill=(40, 90, 160))
    d.text((18, 13), "Correo - Bandeja de entrada", font=uib, fill="white")
    d.rectangle((0, 46, 420, 768), fill=(255, 255, 255))
    for i, (de, asunto) in enumerate([(J["nombre"], "Presupuesto reforma cocina"),
                                      (L["nombre"], "Contrato firmado"),
                                      (A["nombre"], "Factura pendiente de pago"),
                                      ("Boletín semanal", "Novedades de noviembre")]):
        y = 60 + i * 74
        if i == 1:
            d.rectangle((0, y - 8, 420, y + 62), fill=(220, 232, 247))
        d.text((20, y), de, font=uib, fill=(30, 30, 30))
        d.text((20, y + 24), asunto, font=ui, fill=(90, 90, 90))
    x = 450
    d.text((x, 64), "Asunto: Contrato firmado", font=fuente(["segoeuib.ttf"], 20), fill=(20, 20, 20))
    d.text((x, 104), f"De: {L['nombre']} <{L['correo']}>", font=ui, fill=(60, 60, 60))
    d.text((x, 128), f"Para: {R['correo']}", font=ui, fill=(60, 60, 60))
    cuerpo = ["Hola, Rocío:", "",
              "Te adjunto el contrato firmado. Para la fianza he hecho la",
              f"transferencia desde mi cuenta {agrupar(L['iban'])}.",
              f"Mi NIF es {L['doc']}, por si lo necesitas para el recibo.",
              "", f"Cualquier cosa, llámame al {L['movil']}.", "", "Un saludo,", L["nombre"]]
    for i, linea in enumerate(cuerpo):
        d.text((x, 176 + i * 26), linea, font=fuente(["segoeui.ttf"], 17), fill=(30, 30, 30))
    return img


def captura_hoja():
    from PIL import Image, ImageDraw
    filas = [["Nombre", "Documento", "Teléfono", "Correo", "Importe"]] + [
        [p["nombre"], p["doc"], p["movil"], p["correo"], f"{120 + 37 * i},00"] for i, p in enumerate(PERSONAS)]
    anchos = [300, 140, 170, 300, 110]
    img = Image.new("RGB", (60 + sum(anchos) + 20, 70 + 30 * (len(filas) + 4)), "white")
    d = ImageDraw.Draw(img)
    f, fb = fuente(["calibri.ttf"], 16), fuente(["calibrib.ttf"], 16)
    d.rectangle((0, 0, img.width, 34), fill=(33, 115, 70))
    d.text((12, 8), "Clientes.xlsx - Hoja de cálculo", font=fb, fill="white")
    y0 = 50
    for c, letra in enumerate("ABCDE"):
        x = 60 + sum(anchos[:c])
        d.rectangle((x, y0, x + anchos[c], y0 + 26), fill=(230, 230, 230), outline=(200, 200, 200))
        d.text((x + anchos[c] // 2 - 4, y0 + 4), letra, font=f, fill=(80, 80, 80))
    for r, fila in enumerate(filas):
        y = y0 + 26 + r * 30
        d.rectangle((0, y, 60, y + 30), fill=(230, 230, 230), outline=(200, 200, 200))
        d.text((24, y + 6), str(r + 1), font=f, fill=(80, 80, 80))
        for c, valor in enumerate(fila):
            x = 60 + sum(anchos[:c])
            d.rectangle((x, y, x + anchos[c], y + 30), outline=(215, 215, 215))
            d.text((x + 6, y + 6), valor, font=fb if r == 0 else f, fill=(20, 20, 20))
    return img


def captura_chat():
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (540, 960), (236, 229, 221))
    d = ImageDraw.Draw(img)
    f, fb = fuente(["segoeui.ttf"], 19), fuente(["segoeuib.ttf"], 20)
    d.rectangle((0, 0, 540, 70), fill=(7, 94, 84))
    d.text((24, 22), "Javi Ortega", font=fb, fill="white")
    mensajes = [
        (False, "Hola! Te paso los datos para el seguro"),
        (False, f"{J['nombre']}, NIE {J['doc']}"),
        (False, f"Cuenta: {agrupar(J['iban'])}"),
        (True, "Perfecto, gracias Javi"),
        (True, "¿Me confirmas tu correo?"),
        (False, J["correo"]),
        (False, f"y el móvil por si acaso: {J['movil']}"),
        (True, "Recibido 👍"),
    ]
    y = 100
    for propio, texto in mensajes:
        ancho = int(d.textlength(texto, font=f)) + 32
        x = 540 - ancho - 16 if propio else 16
        d.rounded_rectangle((x, y, x + ancho, y + 46), 12, fill=(220, 248, 198) if propio else "white")
        d.text((x + 16, y + 11), texto, font=f, fill=(20, 20, 20))
        y += 62
    return img


def ficha_tarjeta():
    """Tarjeta de socio generica (NO imita ningun documento oficial)."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (1012, 638), (250, 250, 246))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((8, 8, 1004, 630), 36, outline=(30, 80, 140), width=6)
    d.rectangle((8, 8, 1004, 110), fill=(30, 80, 140))
    d.text((40, 36), "CLUB DEPORTIVO LOS ALAMOS - TARJETA DE SOCIO", font=fuente(["arialbd.ttf"], 34), fill="white")
    d.rectangle((40, 150, 290, 460), fill=(200, 205, 215))
    f, fb = fuente(["arial.ttf"], 22), fuente(["arialbd.ttf"], 30)
    campos = [("APELLIDOS", "ETXEBERRIA GOIKOETXEA"), ("NOMBRE", "XABIER"),
              ("DNI", X["doc"]), ("NACIMIENTO", "05 06 1990"), ("SOCIO N.º", "004512")]
    for i, (etiqueta, valor) in enumerate(campos):
        d.text((330, 150 + i * 88), etiqueta, font=f, fill=(90, 90, 90))
        d.text((330, 176 + i * 88), valor, font=fb, fill=(20, 20, 20))
    return img


# --------------------------------------------------------------------------- #
# Generacion
# --------------------------------------------------------------------------- #

def generar() -> list[dict]:
    from PIL import Image
    CASOS.mkdir(parents=True, exist_ok=True)
    for viejo in CASOS.iterdir():
        if viejo.is_file():
            viejo.unlink()
    casos: list[dict] = []

    def caso(nombre: str, descripcion: str, fuente_texto: str, ocr: bool = False, **extra):
        casos.append({"fichero": nombre, "descripcion": descripcion, "ocr": ocr,
                      "texto_fuente": fuente_texto, **extra})

    # ---- Texto plano ------------------------------------------------------- #
    texto = (f"From: \"{L['nombre']}\" <{L['correo']}>\nTo: \"{R['nombre']}\" <{R['correo']}>\n"
             f"Cc: {J['correo']}\nSubject: Contrato de arrendamiento firmado\n"
             "Date: Tue, 03 Mar 2026 10:14:00 +0100\nContent-Type: text/plain; charset=utf-8\n\n"
             f"Hola, Sra. Domínguez:\n\nLe adjunto el contrato firmado. La fianza la he transferido desde\n"
             f"mi cuenta {agrupar(L['iban'])}. Mi NIF es {L['doc']}.\n\n"
             f"Para la reunión del jueves puede llamarme al {L['movil']}.\n\nUn saludo,\n"
             f"Lucía\n--\n{L['nombre']}\n{DIRECCIONES[0]}\n")
    (CASOS / "01_correo.eml").write_text(texto, encoding="utf-8")
    caso("01_correo.eml", "Correo con cabeceras, firma y nombre de pila suelto", texto)

    datos = {"pedido": "PED-2026-0098", "cliente": {"nombre": A["nombre"], "nie": A["doc"],
             "contacto": {"correo": A["correo"], "telefono": A["movil"]},
             "pago": {"iban": A["iban"], "tarjeta": TARJETAS[1]}},
             "lineas": [{"producto": "Tornillo M8", "cantidad": 12}],
             "notas": [f"Entregar a {A['nombre']} en mano", "Total pendiente: 54,00"]}
    texto = json.dumps(datos, ensure_ascii=False, indent=2)
    (CASOS / "02_pedido.json").write_text(texto, encoding="utf-8")
    caso("02_pedido.json", "JSON anidado con listas", texto)

    texto = ("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<expediente id=\"EXP-77\">\n"
             f"  <titular dni=\"{M['doc']}\">\n    <nombre>{M['nombre']}</nombre>\n"
             f"    <email>{M['correo']}</email>\n    <telefono>{M['movil']}</telefono>\n"
             f"    <nacimiento>{NACIMIENTOS[1]}</nacimiento>\n  </titular>\n"
             f"  <cuenta>{agrupar(M['iban'])}</cuenta>\n  <asunto>Nómina de marzo</asunto>\n</expediente>\n")
    (CASOS / "03_expediente.xml").write_text(texto, encoding="utf-8")
    caso("03_expediente.xml", "XML con datos en atributos y en elementos", texto)

    filas = ["nombre;documento;correo;telefono;iban;importe"] + [
        f"\"{p['nombre']}\";{p['doc']};{p['correo']};{p['movil']};{p['iban']};{100 + i * 15},50"
        for i, p in enumerate(PERSONAS)]
    texto = "\n".join(filas) + "\n"
    (CASOS / "04_clientes.csv").write_text(texto, encoding="utf-8")
    caso("04_clientes.csv", "CSV con separador ; y comillas, seis clientes", texto)

    texto = (f"# Acta de la reunión del 12 de marzo\n\nAsistentes: {L['nombre']}, {J['nombre']} (Javi) "
             f"y {X['nombre']}.\n\n- Javi presentará el presupuesto antes del vencimiento.\n"
             f"- Xabier revisará la factura de {A['nombre']}.\n"
             f"- La Sra. Domínguez pide que se le escriba a {R['correo']}.\n"
             f"- lucía martín sanz (en minúsculas) también está en copia.\n")
    (CASOS / "05_acta.md").write_text(texto, encoding="utf-8")
    caso("05_acta.md", "Notas en Markdown: apodos, nombres de pila, minúsculas", texto,
         extra_ocultar=[("lucía martín sanz", "PERSONA")])

    texto = (f"2026-03-03 10:14:02 INFO login ok user={L['correo']} ip={IPS[0]}\n"
             f"2026-03-03 10:15:40 WARN pago rechazado tarjeta={TARJETAS[0].replace(' ', '')} ip={IPS[1]}\n"
             f"2026-03-03 10:16:05 INFO factura enviada a {A['correo']}\n"
             f"2026-03-03 10:17:12 INFO conexion desde {VARIANTES[-1][0]}\n")
    (CASOS / "06_servidor.log").write_text(texto, encoding="utf-8")
    caso("06_servidor.log", "Registro de servidor con IP v4/v6, correos y tarjeta", texto)

    texto = "Variantes de formato del mismo tipo de dato (todas deben sustituirse):\n\n" + \
        "\n".join(f"- {t}: {v}" for v, t in VARIANTES) + "\n"
    (CASOS / "07_formatos.txt").write_text(texto, encoding="utf-8")
    caso("07_formatos.txt", "NIF, IBAN, teléfonos, tarjetas y correos escritos de muchas formas", texto,
         solo_exacto=True)  # las variantes comparten cifras: se comprueba cada una tal cual

    texto = ("<!doctype html><html lang=\"es\"><body><h1>Ficha de proveedor</h1>"
             f"<p>Contacto: <b>{X['nombre']}</b> &lt;<a href=\"mailto:{X['correo']}\">{X['correo']}</a>&gt;</p>"
             f"<p>Teléfono: <a href=\"tel:{X['movil'].replace(' ', '')}\">{X['movil']}</a></p>"
             f"<table><tr><td>NIF</td><td>{X['doc']}</td></tr><tr><td>IBAN</td><td>{X['iban']}</td></tr></table>"
             "<p>Último pedido: Tornillo M8, total 54,00 €.</p></body></html>\n")
    (CASOS / "08_proveedor.html").write_text(texto, encoding="utf-8")
    caso("08_proveedor.html", "HTML con enlaces mailto: y tel:", texto)

    # ---- Documentos de oficina -------------------------------------------- #
    cuerpo = "".join([
        w_parrafo(("CONTRATO DE PRESTACIÓN DE SERVICIOS", "b")),
        w_parrafo("Reunidos, de una parte ", (M["nombre"].split()[0] + " " + M["nombre"].split()[1], "b"),
                  " " + " ".join(M["nombre"].split()[2:]) + f", con NIF {M['doc']}, y de otra ",
                  (J["nombre"], "b"), f", con NIE {J['doc']}."),
        w_parrafo(f"El pago del presupuesto se hará por transferencia a {agrupar(J['iban'])}."),
        w_parrafo("Responsable del contrato: ", (X["nombre"], "del"), (R["nombre"], "ins"), "."),
        w_parrafo(f"Correo de notificaciones: {M['correo']}; teléfono {M['movil']}."),
        w_tabla([["Parte", "Documento", "Firma"], [M["nombre"], M["doc"], ""], [J["nombre"], J["doc"], ""]]),
        w_parrafo("El vencimiento del contrato será el 31 de diciembre de 2026."),
    ])
    escribir_docx(CASOS / "10_contrato.docx", cuerpo, cabecera=f"Confidencial - {M['nombre']}",
                  autor=X["nombre"])
    fuente_docx = " ".join([M["nombre"], M["doc"], J["nombre"], J["doc"], agrupar(J["iban"]),
                            R["nombre"], M["correo"], M["movil"], "presupuesto", "vencimiento"])
    caso("10_contrato.docx", "Word con negritas que parten un nombre, tabla, cabecera y "
         "control de cambios", fuente_docx,
         notas=f"{X['nombre']} solo está en texto ELIMINADO con control de cambios; si aparece "
               "en la salida y sin sustituir, también es una fuga.", extra_ocultar=[(X["nombre"], "PERSONA")])

    import openpyxl
    libro = openpyxl.Workbook()
    hoja = libro.active
    hoja.title = "Nóminas"
    hoja.merge_cells("A1:F1")
    hoja["A1"] = "Nómina de marzo de 2026"
    hoja.append(["Empleado", "Documento", "N.º Seguridad Social", "IBAN", "Bruto", "Neto"])
    for i, p in enumerate(PERSONAS[:4]):
        hoja.append([p["nombre"], p["doc"], NSS[i % 2], p["iban"], 2100 + 150 * i, None])
        hoja[f"F{i + 3}"] = f"=E{i + 3}*0.78"
    notas = libro.create_sheet("Notas internas")
    notas["A1"] = f"{A['nombre']} pide adelanto; contactar en {A['correo']} o {A['movil']}."
    notas.sheet_state = "hidden"
    libro.save(CASOS / "11_nominas.xlsx")
    fuente_xlsx = " ".join([p["nombre"] + " " + p["doc"] + " " + p["iban"] for p in PERSONAS[:4]]
                           + NSS + [A["nombre"], A["correo"], A["movil"], "Nómina"])
    caso("11_nominas.xlsx", "Excel con celdas combinadas, fórmulas y una hoja oculta", fuente_xlsx)

    escribir_pdf(CASOS / "12_factura.pdf", [pdf_lineas(lineas_factura())])
    caso("12_factura.pdf", "PDF con capa de texto (factura)", "\n".join(lineas_factura()))

    escaneada = pagina(lineas_ficha(), tam=24)
    escribir_pdf(CASOS / "13_expediente_mixto.pdf",
                 [pdf_lineas(lineas_contrato(), tam=10),
                  [("img", jpeg(escaneada.resize((1240, 1754)), 80), 1240, 1754)]])
    caso("13_expediente_mixto.pdf", "PDF mixto: página 1 con texto, página 2 escaneada",
         "\n".join(lineas_contrato() + lineas_ficha()), ocr=True)

    paginas = [pagina(lineas_contrato()[:6]), pagina(lineas_contrato()[6:]), pagina(lineas_ficha())]
    paginas = [escaner_sucio(p).convert("L") for p in paginas]
    paginas[0].save(CASOS / "14_escaneado_3_paginas.pdf", save_all=True,
                    append_images=paginas[1:], resolution=150)
    caso("14_escaneado_3_paginas.pdf", "PDF escaneado de tres páginas, con grano y motas",
         "\n".join(lineas_contrato() + lineas_ficha()), ocr=True)

    # ---- Imagenes ------------------------------------------------------------ #
    base_factura = recortar(pagina(lineas_factura(), tam=26))
    base_contrato = recortar(pagina(lineas_contrato(), tam=25))
    base_ficha = recortar(pagina(lineas_ficha(), tam=26))

    base_ficha.save(CASOS / "20_ficha_limpia.png")
    caso("20_ficha_limpia.png", "Imagen nítida (referencia del OCR)", "\n".join(lineas_ficha()), ocr=True)

    (CASOS / "21_factura_foto_movil.jpg").write_bytes(jpeg(foto_inclinada(base_factura), 62))
    caso("21_factura_foto_movil.jpg", "Foto de móvil: perspectiva, giro, sombra y JPEG",
         "\n".join(lineas_factura()), ocr=True)

    (CASOS / "22_contrato_borroso.jpg").write_bytes(jpeg(borrosa(base_contrato), 75))
    caso("22_contrato_borroso.jpg", "Desenfocada", "\n".join(lineas_contrato()), ocr=True)

    baja_resolucion(base_ficha).save(CASOS / "23_ficha_baja_resolucion.png")
    caso("23_ficha_baja_resolucion.png", "Un tercio de resolución (unos 50 ppp)",
         "\n".join(lineas_ficha()), ocr=True)

    escaner_sucio(base_contrato).save(CASOS / "24_contrato_escaner_sucio.png")
    caso("24_contrato_escaner_sucio.png", "Escáner viejo: fondo gris, grano, motas y giro",
         "\n".join(lineas_contrato()), ocr=True)

    manuscrito = [f"Nota para {R['nombre']}:", f"llamar a {L['nombre']}", f"al {L['movil']}",
                  f"NIF {L['doc']}", "sobre el pago de la fianza"]
    recortar(pagina(manuscrito, tipo=["segoepr.ttf", "comic.ttf"], tam=34, tinta=(20, 40, 120),
                    fondo=(252, 248, 225), temblor=4)).save(CASOS / "25_nota_manuscrita.png")
    caso("25_nota_manuscrita.png", "Letra tipo manuscrita con renglones irregulares",
         "\n".join(manuscrito), ocr=True)

    captura_correo().save(CASOS / "26_captura_correo.png")
    caso("26_captura_correo.png", "Captura de un cliente de correo (simulada)",
         " ".join([J["nombre"], L["nombre"], A["nombre"], L["correo"], R["correo"],
                   agrupar(L["iban"]), L["doc"], L["movil"], "Asunto", "presupuesto"]), ocr=True)

    captura_hoja().save(CASOS / "27_captura_hoja.png")
    caso("27_captura_hoja.png", "Captura de una hoja de cálculo (simulada)",
         " ".join(p[k] for p in PERSONAS for k in ("nombre", "doc", "movil", "correo")) + " Importe",
         ocr=True)

    captura_chat().save(CASOS / "28_captura_chat.png")
    caso("28_captura_chat.png", "Captura de una conversación de mensajería (simulada)",
         " ".join([J["nombre"], J["doc"], agrupar(J["iban"]), J["correo"], J["movil"], "Javi"]), ocr=True)

    base_factura.rotate(90, expand=True).save(CASOS / "29_factura_girada_90.png")
    caso("29_factura_girada_90.png", "Escaneada de lado (girada 90°)", "\n".join(lineas_factura()), ocr=True)

    ficha_tarjeta().save(CASOS / "30_tarjeta_socio.png")
    caso("30_tarjeta_socio.png", "Tarjeta con campos en mayúsculas y en líneas separadas",
         f"{X['doc']} Xabier", ocr=True,
         extra_ocultar=[("ETXEBERRIA GOIKOETXEA", "PERSONA"), ("XABIER", "PERSONA")],
         extra_limite=[("05 06 1990", "FECHA_NACIMIENTO")])

    # ---- Controles ------------------------------------------------------------ #
    texto = ("Informe mensual de almacén\n\nEn marzo se recibieron 14 pedidos. El presupuesto de\n"
             "reposición de Tornillo M8 queda en 1.240,00 euros (Total con IVA: 1.500,40).\n"
             "La reunión de inventario será el jueves en la nave de Córdoba.\n"
             "Referencia del pedido: PED-2026-0098. Factura: 2026-0417. Vencimiento: 30 días.\n"
             "Importe pendiente por transferencia: 0,00. Asunto cerrado.\n")
    (CASOS / "40_sin_datos.txt").write_text(texto, encoding="utf-8")
    caso("40_sin_datos.txt", "Control: sin datos personales; nada importante debería desaparecer", texto)

    import numpy as np
    azar = np.random.default_rng(5)
    fondo = np.zeros((600, 800, 3), np.float32)
    fondo[:] = np.linspace([90, 140, 200], [230, 200, 150], 600)[:, None, :]
    for _ in range(40):
        x, y, r = azar.integers(0, 800), azar.integers(0, 600), azar.integers(10, 60)
        yy, xx = np.ogrid[:600, :800]
        fondo[(xx - x) ** 2 + (yy - y) ** 2 < r * r] = azar.integers(40, 255, 3)
    (CASOS / "41_foto_sin_texto.jpg").write_bytes(
        jpeg(Image.fromarray(fondo.astype(np.uint8)), 85))
    caso("41_foto_sin_texto.jpg", "Control: imagen sin texto; debe rechazarse (no hay nada que leer)",
         "", ocr=True, sin_texto=True)

    # ---- Esperado ---------------------------------------------------------------- #
    for c in casos:
        fuente_texto = c.pop("texto_fuente").casefold()
        ocultar = [(v, t) for v, t, cat in CATALOGO if cat == "ocultar" and v.casefold() in fuente_texto]
        limite = [(v, t) for v, t, cat in CATALOGO if cat == "limite" and v.casefold() in fuente_texto]
        ocultar += c.pop("extra_ocultar", [])
        limite += c.pop("extra_limite", [])
        c["ocultar"] = [{"valor": v, "tipo": t} for v, t in dict(ocultar).items()]
        c["limite"] = [{"valor": v, "tipo": t} for v, t in dict(limite).items()]
        c["deben_quedar"] = [p for p in DEBEN_QUEDAR
                             if re.search(rf"(?<!\w){re.escape(p.casefold())}(?!\w)", fuente_texto)]

    (CASOS / "esperado.json").write_text(json.dumps({
        "aviso": "Todos los datos de estos ficheros son ficticios.",
        "casos": casos}, ensure_ascii=False, indent=1), encoding="utf-8")
    return casos


def main() -> int:
    _relanzar()
    casos = generar()
    total = sum(len(c["ocultar"]) for c in casos)
    print(f"{len(casos)} ficheros generados en {CASOS}")
    print(f"{total} datos que deben sustituirse; detalle en casos/esperado.json")
    print("Siguiente paso:  python pruebas/bateria/lanzar.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
