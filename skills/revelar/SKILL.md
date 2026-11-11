---
name: revelar
description: Restaura los datos reales en un fichero de texto que contiene identificadores (PERSONA_1, NIF_1...). Crea una copia <nombre>.revelado.<ext>.
argument-hint: <fichero> [más ficheros]
disable-model-invocation: true
---

El usuario quiere una copia con los datos reales de: $ARGUMENTS

1. Ejecuta, sin encadenar ninguna otra orden:

   ```
   python "${CLAUDE_PLUGIN_ROOT}/anonimizar.py" --revelar $ARGUMENTS
   ```

   Pon cada ruta entre comillas si contiene espacios.
2. La orden solo imprime cuántos identificadores ha restaurado y el nombre del
   fichero creado (`<nombre>.revelado.<ext>`, junto al original). Comunícaselo
   al usuario.
3. No leas ni abras el fichero `.revelado.`: contiene los datos reales y el
   plugin te lo impedirá.
