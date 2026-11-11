# Anonimizador local

Plugin de [Claude Code](https://code.claude.com) para trabajar con documentos
de clientes sin enviar sus datos personales.

Cuando Claude va a leer un documento, el plugin lo **convierte a Markdown y lo
anonimiza en tu equipo**: los nombres, NIF, correos, teléfonos, IBAN… se
sustituyen por identificadores (`PERSONA_1`, `NIF_1`, `IBAN_1`). Claude solo
recibe esa copia. Cuando responde, el plugin **vuelve a poner los datos reales
en tu pantalla**, de modo que tú lees «María Fernández» y Claude solo ha visto
`PERSONA_1`.

> **Estado: versión 0.2, alfa.** La detección es probabilística: reduce mucho
> la exposición de datos personales, pero **no garantiza** que no se escape
> ninguno. Lee el apartado [Límites](#límites) antes de usarlo con datos reales.

## Qué hace

| Situación | Qué ocurre |
|---|---|
| Claude lee un Word, PDF o Excel (`.docx` `.pdf` `.xlsx`), en cualquier carpeta | Se convierte a Markdown, se anonimiza y Claude recibe la copia |
| Claude lee un fichero de texto (`.txt` `.md` `.json` `.xml` `.csv`…) de una carpeta protegida | Se anonimiza tal cual, sin convertir |
| Claude responde | Ves los datos reales; la conversación guardada conserva los identificadores |
| Escribes un NIF, IBAN, tarjeta, correo, teléfono o un nombre ya conocido en el mensaje | El mensaje se detiene y **tú decides**: modificarlo o reenviarlo tal cual |
| Citas un documento con `@` | Igual: se detiene y tú decides |
| Adjuntas una imagen al mensaje | **No siempre se detecta**: ver [Límites](#límites) |
| Claude lee una imagen (`.png` `.jpg` `.webp` `.bmp` `.tif`) o un PDF escaneado | Se extrae el texto por OCR en local, se anonimiza y Claude recibe ese texto, **no la imagen** |
| La imagen no tiene texto (una foto, un logotipo) | Se te pregunta antes de que Claude la vea |
| Claude intenta abrir un original por otro camino (`cat`, `grep`, editar…) | Se deniega o se te pide confirmación |

Todo el proceso es local. La única vez que el plugin usa la red es durante la
instalación, para descargar las dependencias.

## Instalación

Requisitos: Claude Code, un `python` en el PATH (los hooks funcionan con
cualquier versión reciente) y un Python 3.10 – 3.13 instalado para el motor de
detección (el instalador lo busca solo).

Dentro de Claude Code:

```
/plugin marketplace add juankpya/anonimizador-local
/plugin install anonimizador@anonimizador-local
/anonimizador:instalar
```

El último paso crea un entorno en `~/.anonimizador/venv` y descarga alrededor
de 1 GB (Presidio, spaCy con el modelo de español, MarkItDown y RapidOCR). Solo se hace
una vez.

## Uso

Trabaja con normalidad y pide los documentos **por su ruta**:

```
Resume contrato.docx y dime qué plazos tiene
```

- No arrastres el documento al chat ni lo cites con `@`: así se adjunta sin
  pasar por el anonimizado (el plugin te avisará).
- Para proteger también ficheros de texto, déjalos en una carpeta protegida:
  por defecto `originales/`, `privado/` o `confidencial/`.
- Los ficheros que escriba Claude contendrán identificadores. Para obtener una
  copia con los datos reales:

  ```
  /anonimizador:revelar informe.md
  ```

  Crea `informe.revelado.md`, que Claude no puede leer.
- `/anonimizador:estado` muestra la configuración y cuántos datos hay en el mapa.

### Cuando el plugin detiene un mensaje

```
🔒 Anonimizador: mensaje NO enviado.
Contiene datos que no se pueden anonimizar porque van en el propio mensaje:
  • NIF: 12…8Z
Tú decides:
  1. Modificarlo…
  2. Enviarlo igualmente: reenvía exactamente el mismo mensaje…
```

Claude Code no permite que un plugin reescriba lo que escribes, así que no hay
forma de anonimizarlo: solo de avisarte. Si reenvías el mismo texto en los
siguientes 10 minutos, pasa sin cambios.

## Configuración

Opcional. Crea `.anonimizador.json` en la raíz del proyecto (o
`~/.anonimizador/config.json` para todos):

```json
{
  "carpetas_protegidas": ["originales", "clientes"],
  "documentos_en_todas_partes": true,
  "imagenes": "ocr",
  "avisar_prompt": true,
  "revelar_en_pantalla": true,
  "permitidos": ["Acme S.L.", "soporte@miempresa.com"],
  "terminos": ["Proyecto Halcón", "EXP-2024-0042"],
  "modelo": "es_core_news_lg",
  "umbral": 0.35
}
```

| Clave | Para qué |
|---|---|
| `carpetas_protegidas` | Carpetas donde se anonimiza todo, también el texto plano |
| `documentos_en_todas_partes` | Si es `false`, Word/PDF/Excel solo se anonimizan en carpetas protegidas |
| `imagenes` | Fuera de carpetas protegidas: `ocr` (por defecto: Claude recibe el texto anonimizado), `preguntar`, `permitir` (Claude ve la imagen original; útil si trabajas con capturas de interfaz) o `bloquear`. Dentro de una carpeta protegida siempre es `ocr` |
| `avisar_prompt` | Detener los mensajes con datos sensibles o adjuntos |
| `revelar_en_pantalla` | Mostrar los datos reales en las respuestas |
| `permitidos` | Textos que nunca deben anonimizarse ni provocar avisos |
| `terminos` | Textos que deben anonimizarse siempre (clientes, proyectos, códigos) |
| `modelo`, `umbral`, `idioma`, `entidades` | Ajustes del motor de detección |

`terminos` es lo que más fugas evita: el detector no puede saber que el nombre
de tu cliente o un código de expediente son confidenciales.

## Uso sin Claude Code

El mismo motor funciona desde la terminal:

```
python instalar.py
python anonimizar.py contrato.docx          # -> anonimizados/contrato.docx.md
python anonimizar.py carpeta_de_documentos
python anonimizar.py --revelar respuesta.md # -> respuesta.revelado.md
python anonimizar.py --estado
```

## Dónde se guardan los datos

| Qué | Dónde | ¿Sensible? |
|---|---|---|
| Mapa identificador ↔ dato real | `~/.anonimizador/proyectos/<id>/mapa.json` | **Sí**, sin cifrar |
| Informes de detección | `~/.anonimizador/proyectos/<id>/detecciones/` | **Sí** |
| Copias anonimizadas | `~/.anonimizador/proyectos/<id>/cache/` | No |

Nada de esto se guarda en tu proyecto ni en el plugin, y Claude tiene
bloqueado el acceso a todo salvo a las copias anonimizadas. El mapa es por
proyecto: la misma persona recibe el mismo identificador en todos los
documentos. Quien tenga el mapa puede deshacer el anonimizado: técnicamente
esto es **seudonimización**, no anonimización en el sentido del RGPD.

## Límites

Léelos: un plugin de Claude Code no puede cerrar todas las vías.

- **La detección falla a veces.** Se le escapan datos (sobre todo nombres poco
  comunes, fechas de nacimiento, direcciones y códigos internos) y a veces
  sustituye palabras normales. Revisa los informes de detección y usa
  `terminos` y `permitidos`.
- **Lo que escribes o pegas en el mensaje no se anonimiza**, solo se avisa. Y el
  aviso solo reconoce NIF/NIE, IBAN, tarjetas, correos, teléfonos y nombres
  completos que ya hayan aparecido en un documento. Un nombre nuevo escrito a
  mano no se detecta.
- **Los adjuntos no se anonimizan, y las imágenes adjuntas pueden no
  detectarse.** Las menciones con `@` sí se detienen (comprobado). Pero Claude
  Code solo entrega al plugin el texto del mensaje: una imagen adjunta por la
  API o el SDK llega a Claude sin que el plugin la vea (comprobado en la
  versión 2.1.284). El plugin busca el marcador `[Image #N]` que deja la
  terminal al pegar una imagen, sin garantía de que aparezca. **No adjuntes
  capturas ni fotos de documentos con datos personales.**
- **Los nombres de fichero no se anonimizan.** Si un fichero se llama
  `Contrato Juan Pérez.docx`, Claude ve ese nombre.
- **El OCR comete erratas, y una errata es una fuga posible.** Si lee
  `1234567BZ` donde ponía `12345678Z`, el detector ya no lo reconoce como NIF y
  pasa sin anonimizar. Ocurre sobre todo con fotos torcidas, borrosas, de baja
  resolución o manuscritas. El OCR tampoco conserva tablas ni maquetación, y
  Claude no ve gráficos, firmas ni sellos. Las imágenes incrustadas dentro de
  un Word o de un PDF con texto no se leen.
- **Con `imagenes: "ocr"` Claude nunca ve la imagen**, solo su texto. Si
  necesitas que vea capturas de pantalla o diseños, usa `permitir` o
  `preguntar` en ese proyecto.
- **Órdenes de terminal**: la guardia sobre Bash/PowerShell es de mejor esfuerzo.
  Una orden rebuscada puede leer un original sin que el plugin lo note.
- **Word con control de cambios, comentarios o cuadros de texto**: puede que la
  conversión no los incluya, o que incluya texto que creías eliminado.
- **Solo Claude Code.** No funciona en el chat de claude.ai ni en la app de
  escritorio fuera de la pestaña de código. El revelado en pantalla depende del
  evento `MessageDisplay`, que requiere una versión reciente de Claude Code;
  donde no esté disponible verás los identificadores.
- **Fallo cerrado**: si el plugin no puede anonimizar un fichero, Claude no lo
  lee. Si Python no está disponible, las lecturas quedan bloqueadas.
- La telemetría y los registros locales de Claude Code quedan fuera del
  control del plugin.

## Cómo funciona

| Evento de Claude Code | Fichero | Función |
|---|---|---|
| `PreToolUse` | [hooks/guardia.py](hooks/guardia.py) | Anonimiza y redirige la lectura (`updatedInput`); deniega los atajos |
| `UserPromptSubmit` | [hooks/prompt.py](hooks/prompt.py) | Detiene mensajes con datos sensibles o adjuntos |
| `MessageDisplay` | [hooks/pantalla.py](hooks/pantalla.py) | Muestra los datos reales (`displayContent`) |
| `SessionStart` | [hooks/sesion.py](hooks/sesion.py) | Explica las reglas a Claude |

Word y Excel dan un paso más que el PDF: la herramienta de lectura de Claude
Code los rechaza como «binarios» antes de consultar a ningún hook, así que no
se pueden redirigir. Para ellos Claude ejecuta
`anonimizar.py --preparar <documento>` (el plugin autoriza esa orden sin
preguntarte), que deja la copia anonimizada en la caché, y después lee esa
copia. Verás esa orden en la sesión; es el comportamiento previsto.

Los hooks solo usan la biblioteca estándar de Python y responden en
milisegundos; la conversión y la detección corren en un proceso aparte dentro
del entorno virtual. Detección:
[Microsoft Presidio](https://github.com/microsoft/presidio) con
[spaCy](https://spacy.io). Conversión:
[MarkItDown](https://github.com/microsoft/markitdown). OCR:
[RapidOCR](https://github.com/RapidAI/RapidOCR) sobre ONNX Runtime, en CPU
(unos 3-5 segundos por página), con
[pypdfium2](https://github.com/pypdfium2-team/pypdfium2) para convertir en
imagen las páginas escaneadas de un PDF.

## Pruebas

```
python pruebas/test_plugin.py
```

Ejecuta cada hook como lo hace Claude Code, con los documentos de `ejemplos/`
(datos ficticios) y una carpeta temporal en lugar de `~/.anonimizador`.

## Hoja de ruta

- **0.3** — Servidor MCP para usarlo desde Claude Desktop.
- Anonimizar nombres de fichero, cifrar el mapa, revelar ficheros `.docx`.

## Licencia

MIT. Las dependencias se instalan aparte y conservan sus propias licencias.
