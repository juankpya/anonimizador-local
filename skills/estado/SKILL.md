---
name: estado
description: Muestra el estado del anonimizador en este proyecto (instalación, carpetas protegidas, número de datos en el mapa).
disable-model-invocation: true
---

Ejecuta, sin encadenar ninguna otra orden:

```
python "${CLAUDE_PLUGIN_ROOT}/anonimizar.py" --estado
```

Muestra al usuario el resultado. Solo contiene recuentos y rutas, ningún dato
personal.
