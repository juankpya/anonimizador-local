"""Anonimizador local: pseudonimiza documentos antes de que lleguen a Claude.

Modulos sin dependencias externas (los usan los hooks, deben arrancar rapido):
    config, mapa, sensibles
Modulos pesados (solo se cargan dentro del entorno virtual):
    conversion, motor, tuberia
"""

__version__ = "0.1.0"
