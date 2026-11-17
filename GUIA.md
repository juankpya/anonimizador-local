# Guía de uso

Esta guía explica, paso a paso, cómo instalar y usar el Anonimizador local
para trabajar con Claude sobre documentos de clientes sin que los datos
personales salgan de tu equipo. Los detalles técnicos están en el
[README](README.md).

## En qué consiste

Antes de que Claude lea un documento, el anonimizador lo procesa **en tu
equipo** y cambia los datos personales por identificadores:

| En tu documento | Lo que recibe Claude |
|---|---|
| María Fernández López | `PERSONA_1` |
| 12345678Z | `NIF_1` |
| maria.fernandez@ejemplo.es | `CORREO_1` |
| ES91 2100 0418 4502 0005 1332 | `IBAN_1` |
| 699 487 221 | `TELEFONO_1` |

Claude trabaja con esos identificadores y tú recuperas los datos reales al
final. La tabla que une cada identificador con su dato real se guarda solo en
tu equipo (`~/.anonimizador`).

> **Importante.** Reduce mucho el riesgo, pero no es infalible: algún dato
> puede escaparse, sobre todo nombres poco comunes, direcciones y fechas de
> nacimiento. Lee [Lo que no debes hacer](#lo-que-no-debes-hacer) antes de
> usarlo con datos reales.

## ¿Claude Code o Claude Desktop?

Funciona en los dos, pero de forma distinta:

| | Claude Code | Claude Desktop |
|---|---|---|
| Cómo se instala | Como plugin, con tres órdenes | Como servidor MCP, editando un fichero de configuración |
| Qué ves en las respuestas | **Los datos reales** | Los identificadores (`PERSONA_1`) |
| Si adjuntas o pegas un documento | Te avisa y detiene el mensaje | No se entera |
| Resultado con datos reales | `/anonimizador:revelar fichero` | Pides a Claude que lo guarde y abres el `.revelado.md` |

Si puedes elegir, **Claude Code protege más**. El chat web de claude.ai no es
compatible.

## Requisitos

- **Python 3.10, 3.11, 3.12 o 3.13** instalado ([python.org](https://www.python.org/downloads/)).
  En Windows, marca «Add python.exe to PATH» durante la instalación.
- Unos **2 GB libres** en disco. La instalación descarga cerca de 1 GB una sola
  vez; después todo funciona sin conexión.

## Instalación en Claude Code

1. Abre Claude Code y escribe, una por una:

   ```
   /plugin marketplace add juankpya/anonimizador-local
   /plugin install anonimizador@anonimizador-local
   ```

2. Cierra y vuelve a abrir Claude Code.
3. Instala el motor (tarda unos minutos):

   ```
   /anonimizador:instalar
   ```

4. Comprueba que todo está bien:

   ```
   /anonimizador:estado
   ```

**Para actualizar** a una versión nueva: `/plugin marketplace update
anonimizador-local` y vuelve a abrir Claude Code.

## Instalación en Claude Desktop

1. Descarga el proyecto en una carpeta que no vayas a mover. Con git:

   ```bash
   git clone https://github.com/juankpya/anonimizador-local.git
   ```

   O desde GitHub: botón **Code → Download ZIP** y descomprímelo.
2. Abre una terminal en esa carpeta e instala el motor:

   ```bash
   python instalar.py
   ```

3. Genera la configuración:

   ```bash
   python anonimizar.py --config-escritorio
   ```

   Imprime un bloque de texto que empieza por `"mcpServers"`.
4. En Claude Desktop ve a **Ajustes → Desarrollador → Editar configuración**.
   Se abre la carpeta de `claude_desktop_config.json`. Ábrelo con el Bloc de
   notas y copia dentro el bloque. Si el fichero ya tiene contenido, el bloque
   va dentro de las llaves principales, separado por una coma.
5. **Cierra Claude Desktop del todo** (también desde la bandeja del sistema),
   guarda el fichero y vuelve a abrir la app.
6. Comprueba que en el chat aparecen las herramientas del anonimizador
   (icono de herramientas, «anonimizador»).

**Para actualizar**: `git pull` en la carpeta (o descarga de nuevo el ZIP en
el mismo sitio) y reinicia Claude Desktop.

## Uso diario

### Pide los documentos por su ruta

No adjuntes el documento: dile a Claude dónde está.

```
Resume C:\Clientes\Fernandez\contrato.docx y dime qué plazos tiene
```

```
Compara las facturas de C:\Clientes\Fernandez\facturas y dime cuáles están pendientes
```

Se pueden leer Word, PDF (también escaneados), Excel, ficheros de texto
(`.txt`, `.csv`, `.json`, `.xml`, `.md`, `.eml`…) e imágenes (`.png`, `.jpg`…).
De las imágenes y de los PDF escaneados se extrae el texto en tu equipo; Claude
recibe ese texto, nunca la imagen.

### Confía en la carpeta (solo Claude Desktop)

La primera vez que Claude pida algo de una carpeta, **tu sistema abrirá una
ventana** preguntando si confías en ella. Pulsa **Sí** si es una carpeta de
trabajo. No se vuelve a preguntar por esa carpeta ni por sus subcarpetas. Si
pulsas **No**, o no contestas en dos minutos, Claude no accede.

### Obtén el resultado con los datos reales

**En Claude Code** las respuestas ya se muestran con los datos reales. Si
Claude escribe un fichero (un informe, una carta), contendrá identificadores;
para una copia con los datos reales:

```
/anonimizador:revelar informe.md
```

Se crea `informe.revelado.md` junto al original.

**En Claude Desktop** las respuestas muestran identificadores. Pide el
resultado como fichero:

```
Escribe una carta de reclamación para el cliente y guárdala como C:\Clientes\Fernandez\carta.md
```

Claude la guarda con los datos reales como `carta.revelado.md`. Ábrelo desde
tu explorador de archivos.

### Mantén la coherencia entre documentos

La misma persona tiene el mismo identificador en todos los documentos de un
proyecto: si en el contrato es `PERSONA_1`, en las facturas también. Puedes
pedir a Claude que cruce información entre ellos.

## Mejora la detección

Crea un fichero `.anonimizador.json` en la carpeta del proyecto:

```json
{
  "terminos": ["Construcciones Ejemplo S.L.", "EXP-2024-0042"],
  "permitidos": ["Mi Empresa S.L.", "soporte@miempresa.com"]
}
```

- **`terminos`**: lo que debe ocultarse siempre aunque no parezca un dato
  personal (nombres de clientes, empresas, proyectos, códigos de expediente).
  Es lo que más fugas evita.
- **`permitidos`**: lo que no debe ocultarse nunca (tu empresa, tus propios
  datos de contacto).

Más opciones en el [README](README.md#configuración).

## Lo que no debes hacer

- **No arrastres ni adjuntes documentos o capturas al chat**, ni pegues su
  contenido: llegan a Claude sin anonimizar.
- **No escribas datos personales en tus mensajes.** Usa los identificadores:
  «redacta un correo para PERSONA_1», no «para María Fernández». Claude Code
  te avisa si detecta un NIF, IBAN, correo o teléfono en el mensaje; Claude
  Desktop no.
- **No pongas datos personales en los nombres de fichero.** Claude ve el
  nombre tal cual: mejor `cliente_042.pdf` que `Contrato Juan Pérez.pdf`.
- **No des confianza a carpetas enteras como «Documentos» o el disco C:.**
  El anonimizador ya rechaza las más amplias; elige carpetas de trabajo
  concretas.
- **No uses a la vez otro conector con acceso a los mismos ficheros** (por
  ejemplo, un servidor de sistema de archivos en Claude Desktop): Claude
  podría leer el original por ahí.

## Revisa lo que se ha ocultado

Cada lectura deja un informe de detección en
`~/.anonimizador/proyectos/<id>/detecciones/`. Ábrelo de vez en cuando para ver
qué se ha sustituido y qué no; si algo importante se escapa, añádelo a
`terminos`.

Ten en cuenta también:

- **Exceso de celo:** alguna palabra normal puede sustituirse («Correo» como
  persona, una fecha como teléfono). Cualquier número de nueve cifras que
  empiece por 6, 7, 8 o 9 se trata como teléfono.
- **Erratas del OCR:** en fotos borrosas, torcidas o manuscritas, el OCR puede
  leer mal un dato; si lo deforma, quizá no se reconozca.

## Problemas frecuentes

| Problema | Solución |
|---|---|
| `/anonimizador:instalar` dice que no encuentra Python | Instala Python 3.10–3.13 y marca «Add to PATH»; vuelve a abrir Claude Code |
| Claude dice que no puede leer el documento | Es intencionado si el anonimizado falla: el original nunca se envía. Ejecuta `/anonimizador:estado` y revisa la instalación |
| En Claude Code aparece una orden `anonimizar.py --preparar` | Es el paso normal para Word y Excel: prepara la copia anonimizada antes de que Claude la lea |
| En Claude Desktop no aparece el anonimizador | Comprueba que el bloque sigue en `claude_desktop_config.json`: la app puede reescribirlo si se editó con ella abierta. Ciérrala del todo, edítalo y vuelve a abrirla |
| No salió la ventana de confianza | Puede estar detrás de otras ventanas; pasados dos minutos se toma como «No». Pide a Claude que lo intente de nuevo |
| Quiero retirar la confianza a una carpeta | Borra su línea en `~/.anonimizador/confianza.json` |
| Quiero borrar todos los datos guardados | Borra la carpeta `~/.anonimizador/proyectos` (perderás la posibilidad de revelar los textos ya generados) |

`~` es tu carpeta personal: en Windows, `C:\Users\<tu usuario>`.

## Privacidad

- Todo el proceso es local: la red solo se usa al instalar.
- La tabla de identificadores **no está cifrada**. Quien tenga acceso a tu
  carpeta personal puede deshacer el anonimizado. En términos del RGPD esto es
  **seudonimización**, no anonimización.
- Claude tiene bloqueado el acceso a esa tabla y a los ficheros `.revelado`.
