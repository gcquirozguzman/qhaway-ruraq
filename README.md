# qhaway-ruraq

*"El que mira y hace"* en quechua. Convierte capacitaciones (video, audio, pptx, pdf, docx, txt, md, Zoom) en procedimientos paso a paso y los empaqueta como una Skill de Claude.

## Instalación (Windows)

Requiere Python 3.11+ y `ffmpeg` (`winget install Gyan.FFmpeg`).

```powershell
python -m venv .venv            # o: uv venv
.venv\Scripts\activate
pip install -r requirements.txt # o: uv pip install -r requirements.txt
pip install -e .
copy .env.example .env          # completar GEMINI_API_KEY (y Zoom si aplica)
```

## Estructura de clases

```
input/
├── _bandeja/                     # archivos sueltos -> qhaway ordenar
└── <curso>/
    ├── curso.yaml                # nombre, descripción, plataformas, url_base
    └── clase-01-<tema>/
        ├── clase.yaml            # título, fecha, zoom, url_inicio, notas, tareas_esperadas
        ├── video/  audio/  presentaciones/  documentos/
        └── zoom/                 # transcripción y chat
```

Las clases se referencian como `curso/01`. El texto de presentaciones, documentos y Zoom se envía a Gemini como contexto del video.

## Zoom

Agrega cada grabación en `zoom_links.yaml` (o en el campo `zoom:` de `clase.yaml`):

```yaml
grabaciones:
  - curso: google-workspace-admin
    clase: "01"
    url: https://xxx.zoom.us/rec/share/...
    passcode: "a1b2c3"        # opcional
```

- **Links compartidos:** se bajan con yt-dlp. Descarga el video (pantalla + cámara), el chat y la transcripción si existe.
- **Grabaciones de tu cuenta:** usa `meeting_id:` en lugar de `url:` y pon las credenciales Server-to-Server OAuth en `.env`.
- **Grabaciones que piden iniciar sesión:** pon `zoom.cookies_navegador: chrome` en `config.yaml`.

## Comandos

| Comando | Qué hace |
|---|---|
| `qhaway nueva-clase <curso> "<tema>"` | Crea la clase con sus carpetas y plantillas |
| `qhaway ordenar [--auto] [--dry-run]` | Mueve los archivos de `_bandeja/` a su clase |
| `qhaway zoom [--clase c/01] [--listar]` | Descarga las grabaciones pendientes |
| `qhaway procesar [--clase c/01] [--file F] [--solo-extraer] [--forzar]` | Extrae texto y genera los procedimientos con Gemini |
| `qhaway skill` | Genera `output/skill/` y el `.zip` para subir a Claude |
| `qhaway estado` | Muestra qué está descargado, procesado o pendiente |

Ningún comando repite trabajo: lo ya descargado o procesado se omite (registro en `output/.registro.json`).

## Configuración (`config.yaml`)

- `gemini.modelo`: por defecto `gemini-3.8-flash`, con `procesamiento_video: agentic`.
- `gemini.resolucion_video`: `low`, `medium` (por defecto) o `high`. A mayor resolución, más tokens.
- `video.comprimir`: compresión con ffmpeg antes de subir. Desactivada por defecto; los videos nunca se cortan.
- `precios`: tarifas usadas para el costo estimado que se registra en `output/costos.csv`.

Los prompts están en `src/qhaway/prompts/`. Si cambias un prompt, el modelo o la resolución, los archivos afectados se reprocesan en la siguiente ejecución.
