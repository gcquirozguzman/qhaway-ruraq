"""Genera la Skill de Claude en output/skill/ y su .zip."""

from __future__ import annotations

import re
import shutil
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from qhaway.clases import Clase, kebab, listar_cursos
from qhaway.config import Config
from qhaway.logs import log

INSTRUCCIONES = """\
## Cómo usar esta skill

1. Busca en el **Índice** el procedimiento cuyo "Cuándo usar" coincide con lo que pide el usuario.
   Si hay varios candidatos, elige el más específico o pregunta.
2. Lee el archivo del procedimiento completo antes de empezar.
3. Ejecuta los pasos en orden en el navegador (Claude in Chrome), partiendo de la
   **URL de inicio**. Antes de cada clic, confirma que el elemento con el texto indicado está
   en pantalla. Si la interfaz cambió, busca el equivalente por su función y avísale al usuario.
4. Los valores entre `<ángulos>` los proporciona el usuario: pídelos si faltan. No inventes datos.
5. Pide confirmación explícita antes de acciones irreversibles o sensibles (eliminar, enviar,
   publicar, compartir, cambiar permisos, pagar).
6. Revisa la sección "Errores comunes y advertencias" antes de ejecutar y verifica el
   "Resultado esperado" al final.
7. Los timestamps `[mm:ss]` remiten a la grabación original; no son necesarios para ejecutar.
8. Para conceptos o datos de contexto, consulta los archivos de `referencias/`.
"""


@dataclass
class Proc:
    archivo: Path
    titulo: str
    cuando: str


def leer_frontmatter(ruta: Path) -> tuple[dict, str]:
    texto = ruta.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", texto, re.S)
    if not m:
        return {}, texto
    return yaml.safe_load(m.group(1)) or {}, texto[m.end():]


def procedimientos_de(cfg: Config, clase: Clase) -> list[Proc]:
    carpeta = clase.dir_output(cfg) / "procedimientos"
    if not carpeta.is_dir():
        return []
    procs = []
    for ruta in sorted(carpeta.glob("*.md")):
        meta, _ = leer_frontmatter(ruta)
        procs.append(Proc(ruta, meta.get("titulo") or ruta.stem, meta.get("cuando_usar") or ""))
    return procs


def _recortar(texto: str, max_kb: int) -> str:
    limite = max_kb * 1024
    datos = texto.encode("utf-8")
    if len(datos) <= limite:
        return texto
    return datos[:limite].decode("utf-8", errors="ignore") + "\n\n_(recortado por tamaño)_\n"


def generar(cfg: Config) -> tuple[Path, Path, int]:
    s = cfg.skill
    nombre = kebab(s.nombre)[:64] or "qhaway-ruraq"
    raiz = cfg.dir_skill / nombre
    if raiz.exists():
        shutil.rmtree(raiz)
    (raiz / "procedimientos").mkdir(parents=True)
    (raiz / "referencias").mkdir(parents=True)

    indice: list[str] = []
    cursos_txt: list[str] = []
    plataformas: set[str] = set()
    total = 0

    for curso in listar_cursos(cfg):
        meta_c = curso.meta
        bloques_clase: list[str] = []
        for clase in curso.clases():
            procs = procedimientos_de(cfg, clase)
            plataformas.update(clase.meta.get("plataformas") or [])
            if s.incluir_referencias:
                extraido = clase.dir_output(cfg) / "extraido"
                for ref in sorted(extraido.glob("*.md")) if extraido.is_dir() else []:
                    if "chat" in ref.name:
                        continue
                    dest = raiz / "referencias" / curso.id / clase.id / ref.name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_text(_recortar(ref.read_text(encoding="utf-8"), s.max_kb_por_referencia),
                                    encoding="utf-8")
            if not procs:
                continue
            lineas = [f"#### Clase {clase.numero:02d} — {clase.titulo}"]
            for p in procs:
                rel = Path("procedimientos") / curso.id / clase.id / p.archivo.name
                dest = raiz / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p.archivo, dest)
                cuando = f" — *Cuándo usar:* {p.cuando}" if p.cuando else ""
                lineas.append(f"- [{p.titulo}]({rel.as_posix()}){cuando}")
                total += 1
            bloques_clase.append("\n".join(lineas))
        if not bloques_clase:
            continue
        plats = meta_c.get("plataformas") or []
        plataformas.update(plats)
        cabecera = [f"### {curso.nombre} (`{curso.id}`)"]
        if meta_c.get("descripcion"):
            cabecera.append(str(meta_c["descripcion"]).strip())
        detalles = []
        if plats:
            detalles.append("Plataformas: " + ", ".join(plats))
        if meta_c.get("url_base"):
            detalles.append(f"URL base: {meta_c['url_base']}")
        if detalles:
            cabecera.append(" · ".join(detalles))
        indice.append("\n\n".join(cabecera) + "\n\n" + "\n\n".join(bloques_clase))
        cursos_txt.append(curso.nombre)

    descripcion = " ".join(s.descripcion.split())
    if cursos_txt:
        descripcion += " Cursos: " + "; ".join(cursos_txt) + "."
    if plataformas:
        descripcion += " Plataformas: " + ", ".join(sorted(plataformas)) + "."
    descripcion = descripcion[:1024]

    frontmatter = yaml.safe_dump({"name": nombre, "description": descripcion},
                                 allow_unicode=True, sort_keys=False, width=10_000).strip()
    cuerpo = [
        f"---\n{frontmatter}\n---",
        f"# {nombre}",
        f"Procedimientos generados el {date.today().isoformat()} a partir de material de capacitación "
        f"({total} procedimientos).",
        INSTRUCCIONES,
        "## Índice\n\n" + ("\n\n".join(indice) if indice else "_(Aún no hay procedimientos generados.)_"),
    ]
    (raiz / "SKILL.md").write_text("\n\n".join(cuerpo) + "\n", encoding="utf-8")

    # Elimina carpetas vacías y empaqueta
    for d in sorted((d for d in raiz.rglob("*") if d.is_dir()), reverse=True):
        if not any(d.iterdir()):
            d.rmdir()
    zip_path = cfg.dir_skill / f"{nombre}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(raiz.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(cfg.dir_skill).as_posix())
    log.info(f"Skill generada: {raiz} ({total} procedimientos)")
    log.info(f"Zip listo para subir a Claude: {zip_path}")
    return raiz, zip_path, total
