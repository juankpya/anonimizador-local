# -*- coding: utf-8 -*-
"""Motor de deteccion: Presidio + spaCy, en local.

AVISO: la deteccion es probabilistica. Reduce mucho la exposicion de datos
personales, pero no garantiza que no se escape ninguno.
"""

from __future__ import annotations

import re

from .mapa import LONGITUD_MINIMA, Mapa


def crear_analizador(idioma: str, modelo: str):
    """AnalyzerEngine con spaCy local (patron de la documentacion de Presidio)."""
    from presidio_analyzer import AnalyzerEngine
    from presidio_analyzer.nlp_engine import NlpEngineProvider

    motor_nlp = NlpEngineProvider(nlp_configuration={
        "nlp_engine_name": "spacy",
        "models": [{"lang_code": idioma, "model_name": modelo}],
    }).create_engine()
    return AnalyzerEngine(nlp_engine=motor_nlp, supported_languages=[idioma])


# Marcas de Markdown que el reconocedor de nombres arrastra dentro de la entidad.
_BORDES = " \t*_|#>`[]()\"'“”«».,;:"

# Tipos que salen del reconocedor estadistico (los demas son patrones exactos).
_TIPOS_NER = {"PERSON", "LOCATION", "NRP"}


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
        for linea in texto.splitlines():
            if not linea.strip():
                continue
            for r in self.analizador.analyze(text=linea, language=self.idioma,
                                             entities=self.entidades,
                                             score_threshold=self.umbral):
                literal = linea[r.start:r.end]
                # "Arrendataria: Maria Lopez": el reconocedor de nombres toma a
                # menudo la etiqueta (una palabra con mayuscula seguida de dos
                # puntos) por una persona o un lugar. Una etiqueta no es un dato.
                if (r.entity_type in _TIPOS_NER and len(literal.split()) == 1
                        and linea[r.end:].lstrip(" *_").startswith(":")):
                    continue
                # En una tabla Markdown el reconocedor puede abarcar dos celdas
                # ("Titular | Maria Lopez"): cada celda es un dato distinto.
                # La primera, si es una sola palabra, suele ser la etiqueta.
                celdas = literal.split("|")
                for i, celda in enumerate(celdas):
                    if (len(celdas) > 1 and i == 0 and r.entity_type in _TIPOS_NER
                            and len(celda.split()) == 1):
                        continue
                    self._registrar(celda, r.entity_type, r.score, procedencia)
            for patron in self.terminos:
                for m in patron.finditer(linea):
                    self._registrar(m.group(0), "TERMINO_PROPIO", 1.0, procedencia)

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
