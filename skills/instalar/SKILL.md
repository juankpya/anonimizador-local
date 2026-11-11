---
name: instalar
description: Instala las dependencias locales del anonimizador (Presidio, spaCy y MarkItDown). Se ejecuta una sola vez tras instalar el plugin.
disable-model-invocation: true
---

Instala el entorno local del plugin anonimizador.

1. Avisa al usuario de que este paso descarga alrededor de 1 GB (paquetes de
   Python y el modelo de lenguaje en español) y de que es el único momento en
   que el plugin usa la red.
2. Ejecuta, sin encadenar ninguna otra orden:

   ```
   python "${CLAUDE_PLUGIN_ROOT}/instalar.py" $ARGUMENTS
   ```

   Puede tardar varios minutos. Si `python` no existe, prueba con `python3` o,
   en Windows, con `py`.
3. Si termina bien, dile al usuario que ya puede pedir que se lean documentos.
   Si falla, muéstrale el error tal cual: lo más habitual es que falte un
   Python entre 3.10 y 3.13.
