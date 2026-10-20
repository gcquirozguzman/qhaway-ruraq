"""Modelo de cursos y clases dentro de input/."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml
from slugify import slugify

from qhaway.config import Config

# Subcarpeta de cada clase -> extensiones que contiene
TIPOS: dict[str, tuple[str, ...]] = {
    "video": (".mp4", ".mov", ".mkv", ".webm", ".m4v"),
    "audio": (".mp3", ".m4a", ".wav", ".aac", ".ogg", ".flac"),
    "presentaciones": (".pptx", ".pdf"),
    "documentos": (".docx", ".txt", ".md"),
    "zoom": (".vtt", ".srt", ".json"),
}
SUBCARPETAS = ("video", "audio", "presentaciones", "documentos", "zoom")
MEDIA = ("video", "audio")
RE_CLASE = re.compile(r"^clase-(\d{2,3})(?:-(.+))?$")


def kebab(texto: str) -> str:
    return slugify(texto, separator="-", lowercase=True)


def subcarpeta_para(archivo: Path) -> str | None:
    ext = archivo.suffix.lower()
    for sub, exts in TIPOS.items():
        if sub == "zoom":
            continue
        if ext in exts:
            return sub
    return None


def leer_yaml(ruta: Path) -> dict:
    if not ruta.is_file():
        return {}
    return yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}


@dataclass
class Clase:
    curso: "Curso"
    ruta: Path

    @property
    def id(self) -> str:
        return self.ruta.name

    @property
    def ref(self) -> str:
        return f"{self.curso.id}/{self.id}"

    @property
    def numero(self) -> int:
        m = RE_CLASE.match(self.id)
        return int(m.group(1)) if m else 0

    @property
    def meta(self) -> dict:
        return leer_yaml(self.ruta / "clase.yaml")

    @property
    def titulo(self) -> str:
        return self.meta.get("titulo") or self.id

    def archivos(self, sub: str) -> list[Path]:
        carpeta = self.ruta / sub
        if not carpeta.is_dir():
            return []
        exts = TIPOS[sub]
        return sorted(p for p in carpeta.iterdir() if p.is_file() and p.suffix.lower() in exts)

    def media(self) -> list[Path]:
        return self.archivos("video") + self.archivos("audio")

    def textos(self) -> list[Path]:
        zoom = [p for p in self.archivos("zoom") if p.suffix.lower() in (".vtt", ".srt")]
        chat = sorted((self.ruta / "zoom").glob("*chat*.txt")) if (self.ruta / "zoom").is_dir() else []
        return self.archivos("presentaciones") + self.archivos("documentos") + zoom + chat

    def dir_output(self, cfg: Config) -> Path:
        return cfg.dir_output / self.curso.id / self.id


@dataclass
class Curso:
    ruta: Path
    _clases: list[Clase] | None = field(default=None, repr=False)

    @property
    def id(self) -> str:
        return self.ruta.name

    @property
    def meta(self) -> dict:
        return leer_yaml(self.ruta / "curso.yaml")

    @property
    def nombre(self) -> str:
        return self.meta.get("nombre") or self.id

    def clases(self) -> list[Clase]:
        if self._clases is None:
            self._clases = sorted(
                (Clase(self, p) for p in self.ruta.iterdir() if p.is_dir() and RE_CLASE.match(p.name)),
                key=lambda c: (c.numero, c.id),
            )
        return self._clases

    def siguiente_numero(self) -> int:
        return max((c.numero for c in self.clases()), default=0) + 1


def listar_cursos(cfg: Config) -> list[Curso]:
    if not cfg.dir_input.is_dir():
        return []
    return sorted(
        (Curso(p) for p in cfg.dir_input.iterdir() if p.is_dir() and not p.name.startswith(("_", "."))),
        key=lambda c: c.id,
    )


def buscar_curso(cfg: Config, curso: str) -> Curso | None:
    ruta = cfg.dir_input / kebab(curso)
    return Curso(ruta) if ruta.is_dir() else None


def buscar_clase(cfg: Config, curso: str, clase: str) -> Clase | None:
    """Acepta 'clase-01-tema', 'clase-01', '01' o '1'."""
    c = buscar_curso(cfg, curso)
    if not c:
        return None
    clase = str(clase).strip()
    for cl in c.clases():
        if cl.id == clase:
            return cl
    num = re.sub(r"^clase-?", "", clase).split("-")[0]
    if num.isdigit():
        for cl in c.clases():
            if cl.numero == int(num):
                return cl
    return None


def resolver_ref(cfg: Config, ref: str) -> Clase:
    """'curso/clase' -> Clase. Lanza ValueError si no existe."""
    if "/" not in ref:
        raise ValueError(f"Usa el formato curso/clase (ej. google-workspace/01). Recibido: {ref}")
    curso, clase = ref.split("/", 1)
    cl = buscar_clase(cfg, curso, clase)
    if not cl:
        raise ValueError(f"No existe la clase {ref} en {cfg.dir_input}")
    return cl


# --------------------------------------------------------------------------
# Plantillas
# --------------------------------------------------------------------------

PLANTILLA_CURSO = """\
# Datos del curso. Se usan como contexto para Gemini y para el índice de la Skill.
nombre: {nombre}
descripcion: ""
# Plataformas web que enseña el curso (ej. Google Workspace Admin, Google Drive, Looker Studio)
plataformas: []
# URL principal donde se trabaja (ej. https://admin.google.com)
url_base: ""
idioma: es
"""

PLANTILLA_CLASE = """\
titulo: {titulo}
fecha: {fecha}  # AAAA-MM-DD
fuente: {fuente}  # local | zoom
zoom:  # opcional: también puede ir en zoom_links.yaml
  url: {zoom_url}
  passcode: {passcode}
  meeting_id:
# Plataformas y URL de inicio de esta clase (si difieren de curso.yaml)
plataformas: []
url_inicio: ""
# Links útiles mencionados en la clase
links: []
# Tareas que la clase debería enseñar (opcional). Ayuda a Gemini a no omitir ninguna.
tareas_esperadas: []
# Notas libres: contexto, nombres de cuentas de prueba, aclaraciones, etc.
notas: |

"""


def _yaml_str(valor: str | None) -> str:
    return "" if not valor else yaml.safe_dump(valor, allow_unicode=True).strip().removesuffix("...").strip()


def crear_curso(cfg: Config, curso: str, nombre: str | None = None) -> Curso:
    ruta = cfg.dir_input / kebab(curso)
    ruta.mkdir(parents=True, exist_ok=True)
    archivo = ruta / "curso.yaml"
    if not archivo.exists():
        archivo.write_text(PLANTILLA_CURSO.format(nombre=_yaml_str(nombre or curso)), encoding="utf-8")
    return Curso(ruta)


def crear_clase(
    cfg: Config,
    curso: str,
    tema: str,
    numero: int | None = None,
    titulo: str | None = None,
    fecha: str | None = None,
    zoom_url: str | None = None,
    passcode: str | None = None,
) -> tuple[Clase, bool]:
    """Crea la clase con sus subcarpetas y clase.yaml. Devuelve (clase, creada)."""
    c = buscar_curso(cfg, curso) or crear_curso(cfg, curso)
    if numero is not None:
        existente = buscar_clase(cfg, c.id, str(numero))
        if existente:
            return existente, False
    numero = numero or c.siguiente_numero()
    tema_slug = kebab(tema)
    nombre = f"clase-{numero:02d}" + (f"-{tema_slug}" if tema_slug else "")
    ruta = c.ruta / nombre
    creada = not ruta.exists()
    for sub in SUBCARPETAS:
        (ruta / sub).mkdir(parents=True, exist_ok=True)
    archivo = ruta / "clase.yaml"
    if not archivo.exists():
        archivo.write_text(
            PLANTILLA_CLASE.format(
                titulo=_yaml_str(titulo or tema.strip().capitalize() or nombre),
                fecha=fecha or date.today().isoformat(),
                fuente="zoom" if zoom_url else "local",
                zoom_url=_yaml_str(zoom_url),
                passcode=_yaml_str(passcode),
            ),
            encoding="utf-8",
        )
    c._clases = None
    return Clase(c, ruta), creada
