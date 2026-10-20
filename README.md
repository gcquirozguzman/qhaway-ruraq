# qhaway-ruraq

*"El que mira y hace"* en quechua.

Pipeline en Python que toma material de capacitación (videos, audios, presentaciones,
documentos y grabaciones de Zoom) y lo convierte en **procedimientos paso a paso**. Luego
los empaqueta como una **Skill de Claude**, para que Claude in Chrome pueda ejecutar esas
tareas en plataformas web (principalmente de Google).

```
input/<curso>/<clase>/  ->  qhaway procesar  ->  output/<curso>/<clase>/procedimientos/*.md
                                                         |
                                       qhaway skill  ->  output/skill/qhaway-ruraq.zip
```

---

## 1. Instalación (Windows)

Requisitos:
- Python 3.11 o superior.
- `ffmpeg` en el PATH. yt-dlp lo usa para unir video y audio, y también sirve para la compresión opcional:
  `winget install Gyan.FFmpeg`.

### Opción A: con `uv` (más rápido, si lo tienes instalado)

```powershell
uv venv
.venv\Scripts\activate
uv pip install -r requirements.txt
uv pip install -e .
```

### Opción B: con `venv` + `pip`

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
```

`pip install -e .` instala el comando `qhaway`. También puedes usar `python -m qhaway`.

### Activar el entorno en cada sesión

```powershell
.venv\Scripts\activate          # PowerShell o CMD
```

Si PowerShell bloquea el script, ejecuta una sola vez:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.
Para salir del entorno: `deactivate`.

### Credenciales

```powershell
copy .env.example .env
```

Edita `.env` y completa los valores:
- `GEMINI_API_KEY`: obligatoria para `procesar`. Se obtiene en https://aistudio.google.com/apikey.
- `ZOOM_ACCOUNT_ID`, `ZOOM_CLIENT_ID` y `ZOOM_CLIENT_SECRET`: opcionales. Solo hacen falta para bajar grabaciones de tu propia cuenta con la API de Zoom (ver sección 4).

---

## 2. Estructura del proyecto

```
.
├── .venv/
├── input/                     # material organizado por curso/clase
│   └── _bandeja/              # archivos sueltos por ordenar (qhaway ordenar)
├── output/
│   ├── <curso>/<clase>/
│   │   ├── extraido/          # texto extraído de pptx/pdf/docx/txt/md/transcripciones
│   │   ├── procedimientos/    # un .md por tarea (con frontmatter)
│   │   └── crudo/             # respuesta completa de Gemini, por archivo
│   ├── skill/                 # Skill final + .zip para subir a Claude
│   ├── costos.csv             # tokens y costo estimado por llamada
│   ├── logs/                  # logs diarios
│   └── .registro.json         # qué se descargó/procesó (idempotencia)
├── src/qhaway/                # código
├── zoom_links.yaml            # grabaciones de Zoom a descargar
├── config.yaml                # modelo, resolución de video, rutas, precios...
├── .env.example
├── requirements.txt
└── pyproject.toml
```

---

## 3. Organización de las clases

```
input/
└── google-workspace-admin/            # curso (kebab-case)
    ├── curso.yaml                     # nombre, descripción, plataformas, url_base
    └── clase-01-crear-usuarios/       # clase-NN-tema (dos dígitos)
        ├── clase.yaml                 # título, fecha, fuente, zoom, links, notas, tareas_esperadas
        ├── video/                     # mp4, mov, mkv, webm
        ├── audio/                     # mp3, m4a, wav
        ├── presentaciones/            # pptx, pdf
        ├── documentos/                # docx, txt, md
        └── zoom/                      # transcripción (.vtt) y chat (.txt) de Zoom, metadata
```

- **Nombres:** las carpetas van en kebab-case y la clase se numera con dos dígitos (`clase-01-...`). Para referirte a una clase en los comandos basta el número: `google-workspace-admin/01`.
- **`curso.yaml`:** describe el curso. Las plataformas que declares aparecen en la descripción de la Skill y ayudan a Claude a saber cuándo usarla.
- **`clase.yaml`:** todo su contenido se manda a Gemini como contexto. Conviene completar:
  - `url_inicio` y `plataformas`.
  - `tareas_esperadas`: lista de las tareas que la clase enseña. Gemini se asegura de no omitirlas.
  - `notas`: aclaraciones útiles, por ejemplo "la cuenta de prueba es admin@empresa.com".
- **Contexto para Gemini:** el texto de `presentaciones/`, `documentos/` y la transcripción de Zoom se envía junto al video. Así Gemini acierta mejor los nombres exactos de botones y las URLs.
- **Clases sin video ni audio:** si una clase solo tiene documentos, igual se generan procedimientos a partir de ellos. Se desactiva con `gemini.procesar_documentos_sin_media`.

### Crear una clase

```powershell
qhaway nueva-clase google-workspace-admin "crear usuarios"
qhaway nueva-clase google-workspace-admin "grupos" --numero 2 --fecha 2026-10-20
qhaway nueva-clase google-workspace-admin "drive compartido" --zoom "https://...zoom.us/rec/share/..." --passcode "a1b2c3"
```

Si el curso no existe, se crea con su `curso.yaml`. Si no indicas `--numero`, se usa el siguiente disponible.

### Ordenar archivos sueltos

Deja los archivos en `input/_bandeja/`. Puedes usar subcarpetas: sus nombres también sirven como pista para ubicar el archivo. Luego ejecuta:

```powershell
qhaway ordenar --dry-run      # muestra qué haría, sin mover nada
qhaway ordenar                # pregunta cuando no está seguro
qhaway ordenar --auto         # mueve solo lo seguro y deja el resto en la bandeja
qhaway ordenar --curso google-workspace-admin --clase 03   # todo a esa clase
```

Cómo decide:
- **Tipo:** por la extensión del archivo.
- **Curso:** por coincidencia de palabras con el nombre del curso. Si solo existe un curso, usa ese.
- **Clase:** por número (`clase 3`, `c03`, `sesion-3`, `modulo 3`) o por coincidencia con el tema.

Qué hace con el archivo:
- Lo renombra a kebab-case.
- Si encuentra una copia idéntica ya ordenada, lo mueve a `_bandeja/_duplicados/`.
- Si es un tipo no soportado, lo deja en la bandeja.

---

## 4. Grabaciones de Zoom

### Método elegido

| Método | Cuándo usarlo | Qué descarga |
|---|---|---|
| **yt-dlp** (principal) | Links compartidos `.../rec/share/...` o `.../rec/play/...`, incluidas grabaciones de otras personas. No requiere crear nada en Zoom. | Video "pantalla compartida + cámara" (el mismo mp4 que se baja desde el navegador), **chat** (si hubo) y, si el link la expone, la transcripción (`.vtt`) |
| **API de Zoom** (Server-to-Server OAuth) | Grabaciones en la nube de **tu** cuenta | Video (vista preferida), transcripción y **chat** |

Con `metodo: auto` (el valor por defecto), se usa la API si la entrada tiene `meeting_id` y hay credenciales en `.env`. En cualquier otro caso se usa yt-dlp.

### Agregar links

En `zoom_links.yaml`:

```yaml
grabaciones:
  - curso: google-workspace-admin
    clase: "01"                 # o clase-01-crear-usuarios
    tema: crear usuarios        # opcional: crea la clase si no existe
    url: https://us02web.zoom.us/rec/share/XXXXXXXX
    passcode: "a1b2c3"          # entre comillas (respeta ceros iniciales)

  - curso: google-workspace-admin
    clase: "02"
    meeting_id: "85212345678"   # grabación de tu cuenta -> API
```

También puedes ponerlo en el campo `zoom:` del `clase.yaml` de cada clase (`url`, `passcode`, `meeting_id`).

### Descargar

```powershell
qhaway zoom                                   # todo lo pendiente
qhaway zoom --clase google-workspace-admin/01 # solo una clase
qhaway zoom --forzar                          # volver a descargar
qhaway zoom --listar --desde 2026-09-01       # (API) lista tus grabaciones y sus meeting_id
```

- **Nombres de los archivos:** `video/clase-01-crear-usuarios__zoom.mp4`, `zoom/clase-01-crear-usuarios__zoom.transcript.vtt` y `zoom/...__zoom.chat.txt`. Si una clase tiene varias grabaciones, se numeran: `__zoom-02`, `__zoom-03`...
- **Lo ya descargado no se vuelve a bajar:** se controla con `output/.registro.json` y verificando que los archivos existan.
- **Grabaciones que piden iniciar sesión en Zoom:** en `config.yaml`, pon `zoom.cookies_navegador: chrome` (o `edge` / `firefox`). yt-dlp usará tu sesión del navegador.

### Configurar la API de Zoom (opcional)

1. Entra a https://marketplace.zoom.us/ y ve a **Develop → Build App → Server-to-Server OAuth**.
2. Agrega los scopes de grabaciones en la nube: listar las grabaciones del usuario y leer los archivos de grabación (`cloud_recording:read:...`).
3. Activa la app.
4. Copia `Account ID`, `Client ID` y `Client Secret` en `.env`.

Si un archivo aparece sin `download_url`, normalmente es porque Zoom aún lo está procesando. Vuelve a ejecutar el comando más tarde.

---

## 5. Procesamiento con IA

```powershell
qhaway procesar                                   # todo lo pendiente
qhaway procesar --curso google-workspace-admin
qhaway procesar --clase google-workspace-admin/01
qhaway procesar --file "input/google-workspace-admin/clase-01-crear-usuarios/video/clase-01-crear-usuarios__zoom.mp4"
qhaway procesar --solo-extraer                    # solo extrae texto (sin Gemini, sin costo)
qhaway procesar --clase google-workspace-admin/01 --forzar
```

### Por tipo de archivo

| Tipo | Herramienta |
|---|---|
| mp4 / mov / webm | Gemini (`gemini-3.8-flash`) vía Files API + Interactions API, `processing: agentic` |
| mp3 / m4a / wav | Gemini vía Files API |
| pptx | python-pptx (texto de diapositivas, tablas y notas del orador) |
| pdf | PyMuPDF |
| docx | python-docx (títulos, listas y tablas) |
| txt / md | lectura directa |
| vtt / srt (Zoom) | se compacta a `[hh:mm:ss] texto` |

### Videos

- **Tamaño:** se suben completos a la Files API (hasta 20 GB en el plan pago). **Los videos no se cortan.**
- **Modo `agentic`:** el modelo ajusta los fps y la resolución según lo que necesita, y consulta la transcripción cuando le sirve.
- **Resolución (`config.yaml` → `gemini.resolucion_video`):** puede ser `low`, `medium`, `high` o `ultra_high`.
  - `low`/`medium` usan unos 70 tokens por frame; `high`, unos 280.
  - Con `high` los textos pequeños de los botones se leen mejor, pero cuesta más tokens y admite menos duración (alrededor de 1 h, contra unas 3 h en baja).
  - Por defecto: `medium`.
- **Compresión opcional (desactivada):** con `video.comprimir: true`, los videos que superen `umbral_mb` se recomprimen con ffmpeg antes de subirlos (reescala a `ancho_max`, `crf`). El original no se modifica.

### Qué devuelve Gemini por cada tarea

1. Título y objetivo.
2. Plataforma y URL de inicio.
3. Requisitos previos.
4. Pasos numerados. Cada uno incluye la acción, el nombre **exacto** del elemento en pantalla, lo que debería verse después y el timestamp `[mm:ss]`.
5. Errores comunes y advertencias.
6. Resultado esperado.

Si un video enseña varias tareas, cada una sale en un archivo separado:
`output/<curso>/<clase>/procedimientos/<video>--01-<tarea>.md`.

Los prompts están en `src/qhaway/prompts/` y se pueden editar. Si cambias un prompt, el modelo o la resolución, los archivos afectados se reprocesan en la siguiente ejecución.

### Idempotencia, costos y errores

- **Idempotencia:** cada archivo se identifica por su SHA-256 más una "huella" del procesamiento (modelo, prompt y resolución). Si nada cambió, no se vuelve a procesar. Para reprocesar igual, usa `--forzar`.
- **Costos:** cada llamada queda registrada en `output/costos.csv` con los tokens de entrada, tool use (frames cargados en modo agentic), salida y pensamiento, y el costo estimado en USD.
  - Tarifas: US$0.75 por millón de tokens de entrada y US$3.75 por millón de salida. Se cambian en `config.yaml` → `precios`.
  - El pensamiento se cobra como salida y el tool use como entrada.
- **Errores:** ante 429, 5xx o fallas de red, se reintenta con backoff exponencial (`gemini.max_reintentos`). Si un archivo falla, los demás siguen procesándose. El detalle queda en `output/logs/`.

---

## 6. Generar la Skill

```powershell
qhaway skill
```

Genera:

```
output/skill/
├── qhaway-ruraq/
│   ├── SKILL.md            # frontmatter (name, description) + instrucciones + índice
│   ├── procedimientos/<curso>/<clase>/*.md
│   └── referencias/<curso>/<clase>/*.md    # texto extraído (sin chats)
└── qhaway-ruraq.zip        # listo para subir a Claude
```

El índice de `SKILL.md` lista cada procedimiento por curso y clase, con su línea **"Cuándo usar"**. El nombre y la descripción de la Skill se configuran en `config.yaml` → `skill`.

**Para subirla:** en Claude, ve a *Settings → Capabilities → Skills → Upload skill* y elige el `.zip`.

---

## 7. Estado

```powershell
qhaway estado              # por clase: archivos, media procesada, textos, procedimientos
qhaway estado --verificar  # además recalcula hashes para detectar archivos modificados
```

También muestra:
- las grabaciones de Zoom pendientes,
- los archivos en la bandeja,
- la fecha de la última Skill generada,
- el costo acumulado.

---

## Flujo típico

```powershell
.venv\Scripts\activate
qhaway nueva-clase google-workspace-admin "crear usuarios"
# copiar material a input/... o a input/_bandeja/ y luego:
qhaway ordenar
# agregar links en zoom_links.yaml y luego:
qhaway zoom
qhaway procesar --clase google-workspace-admin/01
# revisar output/google-workspace-admin/clase-01-crear-usuarios/procedimientos/
qhaway skill
qhaway estado
```

Usa `qhaway --verbose <comando>` para ver logs de depuración.
