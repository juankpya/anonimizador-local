# -*- coding: utf-8 -*-
"""Motor de deteccion: Presidio + spaCy, en local.

AVISO: la deteccion es probabilistica. Reduce mucho la exposicion de datos
personales, pero no garantiza que no se escape ninguno.
"""

from __future__ import annotations

import re

from .mapa import LONGITUD_MINIMA, Mapa

LETRAS_NIF = "TRWAGMYFPDXBNJZSQVHLCKE"


def _solo_alfanum(texto: str) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", texto).upper()


def _nif_valido(texto: str) -> bool:
    t = _solo_alfanum(texto)
    if len(t) == 9 and t[0] in "XYZ":
        t = str("XYZ".index(t[0])) + t[1:]
    return len(t) == 9 and t[:8].isdigit() and LETRAS_NIF[int(t[:8]) % 23] == t[8]


def _iban_valido(texto: str) -> bool:
    t = _solo_alfanum(texto)
    if len(t) < 15:
        return False
    numero = "".join(str(int(c, 36)) for c in t[4:] + t[:4])
    return int(numero) % 97 == 1


def _telefono_valido(texto: str) -> bool:
    cifras = re.sub(r"\D", "", texto)
    for prefijo in ("0034", "34"):
        if len(cifras) > 9 and cifras.startswith(prefijo):
            cifras = cifras[len(prefijo):]
    return len(cifras) == 9 and cifras[0] in "6789"


def _reconocedores_es(idioma: str) -> list:
    """Formatos espanoles que los reconocedores de Presidio no cubren:
    - telefonos sin prefijo internacional (Presidio no trae la region ES);
    - IBAN con espacios seguido de una palabra (el patron de Presidio se traga
      las primeras letras como un grupo final y la validacion falla);
    - NIF/NIE con puntos, espacios o en minusculas.
    Todos validan el digito de control o la longitud, para no confundir
    importes, referencias o codigos postales."""
    from presidio_analyzer import Pattern, PatternRecognizer

    class Validado(PatternRecognizer):
        def __init__(self, validar, **kw):
            super().__init__(supported_language=idioma, **kw)
            self._validar = validar

        def validate_result(self, pattern_text: str):
            return self._validar(pattern_text)

    separador = r"[ \t.\-]?"
    return [
        Validado(_telefono_valido, supported_entity="PHONE_NUMBER", name="TelefonoES",
                 # Solo se exige que no haya cifras pegadas: el OCR une a veces el
                 # numero con la palabra vecina ("699487221Correo").
                 patterns=[Pattern("telefono_es_prefijo",
                                   r"(?:\+\s?34|\(\+?34\)|(?<!\d)0034)[ .\-]?"
                                   r"[6789](?:" + separador + r"\d){8}(?!\d)", 0.6),
                           Pattern("telefono_es",
                                   r"(?<![\d+])[6789](?:" + separador + r"\d){8}(?!\d)", 0.6)],
                 context=["telefono", "teléfono", "tel", "movil", "móvil", "llamar", "contacto"]),
        Validado(_iban_valido, supported_entity="IBAN_CODE", name="IbanES",
                 patterns=[Pattern("iban_es", r"(?<!\w)ES\d{2}(?:[ \-]?\d{4}){5}(?!\w)", 0.6)]),
        Validado(_nif_valido, supported_entity="ES_NIF", name="NifES",
                 patterns=[Pattern("nif_es", r"(?<![\w.])(?:\d{1,2}\.\d{3}\.\d{3}|\d{8})"
                                             r"[ \-]?[A-Z](?!\w)", 0.6)]),
        Validado(_nif_valido, supported_entity="ES_NIE", name="NieES",
                 patterns=[Pattern("nie_es", r"(?<!\w)[XYZ][ \-]?\d{7}[ \-]?[A-Z](?!\w)", 0.6)]),
    ]


def crear_analizador(idioma: str, modelo: str):
    """AnalyzerEngine con spaCy local (patron de la documentacion de Presidio)."""
    from presidio_analyzer import AnalyzerEngine
    from presidio_analyzer.nlp_engine import NlpEngineProvider

    motor_nlp = NlpEngineProvider(nlp_configuration={
        "nlp_engine_name": "spacy",
        "models": [{"lang_code": idioma, "model_name": modelo}],
    }).create_engine()
    analizador = AnalyzerEngine(nlp_engine=motor_nlp, supported_languages=[idioma])
    if idioma == "es":
        for r in _reconocedores_es(idioma):
            analizador.registry.add_recognizer(r)
    return analizador


# Marcas de Markdown que el reconocedor de nombres arrastra dentro de la entidad.
_BORDES = " \t*_|#>`[]()\"'“”«».,;:"

# Tipos que salen del reconocedor estadistico (los demas son patrones exactos).
_TIPOS_NER = {"PERSON", "LOCATION", "NRP"}

# Separadores que una entidad de nombre no debe cruzar: celdas de CSV o de
# tabla, tabuladores, y el doble espacio con el que el OCR une columnas.
_CORTES = re.compile(r"[;|\t]|\s{2,}")

# Un apellido mas pegado al nombre detectado: "Maria Jose Ibanez" + " Pena".
_APELLIDO_MAS = re.compile(
    r"^((?:\s+(?:de|del|la|las|los|y))*\s+[A-ZÁÉÍÓÚÑÜ][a-záéíóúñü]+(?:-[A-ZÁÉÍÓÚÑÜ][a-záéíóúñü]+)?)"
    r"(?![\w:])")

# Formularios y documentos de identidad: una linea-etiqueta y, debajo, el valor
# en mayusculas ("APELLIDOS" / "GARCIA LOPEZ"). El reconocedor de nombres
# apenas reconoce texto todo en mayusculas.
_ETIQUETA_NOMBRE = re.compile(r"(?i)(apellido|nombre|surname|name|cognome|nome\b|titular)")
_VALOR_MAYUSCULAS = re.compile(r"^[A-ZÁÉÍÓÚÑÜÇ][A-ZÁÉÍÓÚÑÜÇ'\- ]{1,48}$")
_OTRAS_ETIQUETAS = {
    "NACIONALIDAD", "NATIONALITY", "SEXO", "SEX", "FECHA", "DATE", "LUGAR", "PLACE", "DOMICILIO",
    "DIRECCION", "DIRECCIÓN", "DNI", "NIF", "NIE", "DOCUMENTO", "DOCUMENT", "NACIMIENTO", "BIRTH",
    "FIRMA", "SIGNATURE", "CONDICION", "CONDICIÓN", "CIUDADANA", "CIUDADANO", "HOMBRE", "MUJER",
    "VALIDEZ", "EXPEDICION", "EXPEDICIÓN", "CADUCIDAD", "SCADENZA", "EXPIRY", "EMISSIONE", "ISSUING",
    "CITTADINANZA", "SESSO", "STATURA", "HEIGHT", "COMUNE", "MUNICIPALITY", "NUMERO", "NÚMERO",
    "SOCIO", "EQUIPO", "NACIMENTO", "LUOGO", "DATA",
}

# Zona de lectura mecanica (MRZ) de pasaportes y documentos de identidad.
_MRZ = re.compile(r"^[A-Z0-9<]{28,44}$")


class Detector:
    """Analiza texto y registra lo que encuentra en el mapa del proyecto."""

    def __init__(self, analizador, mapa: Mapa, cfg: dict):
        self.analizador = analizador
        self.mapa = mapa
        self.idioma = cfg["idioma"]
        self.entidades = cfg["entidades"]
        self.umbral = float(cfg["umbral"])
        self.permitidos = {p.casefold() for p in cfg.get("permitidos", [])}
        self.terminos = [
            re.compile(r"(?i)(?<!\w)" + re.escape(t.strip()) + r"(?!\w)")
            for t in cfg.get("terminos", []) if t.strip()
        ]
        self.detecciones: list[dict] = []

    def observar(self, texto: str, procedencia: str = "cuerpo") -> None:
        """Se analiza LINEA A LINEA a proposito: con el bloque entero el
        reconocedor produce entidades que cruzan el salto de linea ("Maria
        Lopez\\nNIF" como una sola persona) y se traga la etiqueta siguiente.
        El contexto que usan los reconocedores ("NIF:", "Cuenta:") vive en la
        misma linea, asi que no se pierde nada relevante."""
        lineas = texto.splitlines()
        for linea in lineas:
            if not linea.strip():
                continue
            for r in self.analizador.analyze(text=linea, language=self.idioma,
                                             entities=self.entidades,
                                             score_threshold=self.umbral):
                if r.entity_type in _TIPOS_NER:
                    self._nombre(linea, r, procedencia)
                else:
                    self._registrar(linea[r.start:r.end], r.entity_type, r.score, procedencia)
            for patron in self.terminos:
                for m in patron.finditer(linea):
                    self._registrar(m.group(0), "TERMINO_PROPIO", 1.0, procedencia)
        self._formularios(lineas, procedencia)
        self._mrz(lineas, procedencia)

    # -- nombres -------------------------------------------------------------- #

    def _nombre(self, linea: str, r, procedencia: str) -> None:
        literal = linea[r.start:r.end]
        # "Arrendataria: Maria Lopez": el reconocedor de nombres toma a menudo
        # la etiqueta (una palabra con mayuscula seguida de dos puntos) por una
        # persona o un lugar. Una etiqueta no es un dato.
        if len(literal.split()) == 1 and linea[r.end:].lstrip(" *_").startswith(":"):
            return
        if r.entity_type == "PERSON":
            # El reconocedor a veces se deja el ultimo apellido.
            extra = _APELLIDO_MAS.match(linea[r.end:])
            if extra and not _CORTES.search(extra.group(1)):
                literal += extra.group(1)
        piezas = _CORTES.split(literal)
        for i, pieza in enumerate(piezas):
            # Dentro de cada pieza, nada a partir de la primera palabra con
            # cifras o arroba: eso es otro dato (un NIF, un correo...).
            palabras = []
            for palabra in pieza.split():
                if re.search(r"[\d@]", palabra):
                    break
                palabras.append(palabra)
            pieza = " ".join(palabras)
            # En una tabla, la primera celda de una sola palabra suele ser la
            # etiqueta ("Titular | Maria Lopez").
            if len(piezas) > 1 and i == 0 and len(pieza.split()) == 1:
                continue
            # Y la ultima, si es una sola palabra seguida de ":", otra etiqueta
            # que el OCR ha pegado ("Juan Perez  Asunto: ...").
            if (len(piezas) > 1 and i == len(piezas) - 1 and len(pieza.split()) == 1
                    and linea[r.end:].lstrip(" *_").startswith(":")):
                continue
            if pieza:
                self._registrar(pieza, r.entity_type, r.score, procedencia)

    def _formularios(self, lineas: list[str], procedencia: str) -> None:
        limpias = [l.strip().strip(_BORDES) for l in lineas]
        for i, etiqueta in enumerate(limpias):
            if not etiqueta or len(etiqueta) > 32 or not _ETIQUETA_NOMBRE.search(etiqueta):
                continue
            # El valor, en la misma linea tras ":" o en las lineas siguientes
            # (los apellidos ocupan a veces dos).
            candidatos = []
            if ":" in lineas[i]:
                candidatos.append(lineas[i].split(":", 1)[1].strip().strip(_BORDES))
            candidatos += [l for l in limpias[i + 1:i + 3] if l]
            for n, valor in enumerate(candidatos):
                palabras = valor.split()
                if (not _VALOR_MAYUSCULAS.match(valor) or not 1 <= len(palabras) <= 4
                        or any(p.strip("'-") in _OTRAS_ETIQUETAS for p in palabras)
                        or _ETIQUETA_NOMBRE.search(valor)):
                    break
                self._registrar(valor, "PERSON", 0.6, procedencia)
                if not re.search(r"(?i)apellido|surname|cognome", etiqueta) or n >= 1:
                    break

    def _mrz(self, lineas: list[str], procedencia: str) -> None:
        for linea in lineas:
            compacta = linea.replace(" ", "")
            if not _MRZ.match(compacta) or compacta.count("<") < 4:
                continue
            nombres = re.search(r"([A-Z]+(?:<[A-Z]+)*<<[A-Z]+(?:<[A-Z]+)*)", compacta)
            if nombres and not re.search(r"\d", compacta):
                self._registrar(nombres.group(1), "PERSON", 0.9, procedencia)
            else:
                # Lineas con numero de documento, fechas y nacionalidad.
                self._registrar(compacta.rstrip("<"), "MRZ", 0.9, procedencia)

    # -- registro ------------------------------------------------------------- #

    def _registrar(self, literal: str, tipo: str, confianza: float, procedencia: str) -> None:
        literal = literal.strip(_BORDES)
        if len(literal) < LONGITUD_MINIMA or literal.casefold() in self.permitidos:
            return
        pseudo = self.mapa.registrar(literal, tipo)
        if pseudo:
            self.detecciones.append({
                "pseudonimo": pseudo, "tipo": tipo,
                "confianza": round(float(confianza), 3),
                "original": literal, "procedencia": procedencia,
            })
