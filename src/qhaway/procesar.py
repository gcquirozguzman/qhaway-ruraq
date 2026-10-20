"""Procesamiento de clases: extracción de textos + procedimientos con Gemini."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import date
from importlib import resources
from pathlib import Path

import yaml

from qhaway import costos
from qhaway.clases import Clase, kebab, listar_cursos, buscar_clase
from qhaway.config import Config
from qhaway.extractores import extraer
from qhaway.logs import log
from qhaway.registro import Registro, huella

SEPARADOR = "<!-- PROCEDIMIENTO -->"
VERSION_EXTRACCION = "extraccion-v1"
VERSION_PROMPT = "procedimientos-v1"


def prompt(nombre: str) -> str:
    return resources.files("qhaway.prompts").joinpath(f"{nombre}.md").read_text(encoding="utf-8")


@dataclass
class Resumen:
    extraidos: int = 0
    procesados: int = 0
    omitidos: int = 0
    errores: list[str] = field(default_factory=list)
    costo: float = 0.0


# --------------------------------------------------------------------------
# Selección de objetivos
# --------------------------------------------------------------------------

def clase_de_archivo(cfg: Config, archivo: Path) -> Clase:
    archivo = archivo.resolve()
    try:
        partes = archivo.relative_to(cfg.dir_input.resolve()).parts
    except ValueError:
        raise ValueError(f"{archivo} no está dentro de {cfg.dir_input}") from None
    if len(partes) < 3:
        raise ValueError(f"{archivo} no está dentro de una carpeta de clase")
    clase = buscar_clase(cfg, partes[0], partes[1])
    if not clase:
        raise ValueError(f"No se reconoce la clase de {archivo}")
    return clase


def todas_las_clases(cfg: Config) -> list[Clase]:
    return [cl for c in listar_cursos(cfg) for cl in c.clases()]


# --------------------------------------------------------------------------
# Extracción de texto
# --------------------------------------------------------------------------

def nombre_extraido(ruta: Path) -> str:
    return f"{ruta.parent.name}--{kebab(ruta.stem) or 'archivo'}{ruta.suffix.lower().replace('.', '-')}.md"


def extraer_textos(cfg: Config, reg: Registro, clase: Clase, forzar: bool, resumen: Resumen) -> list[Path]:
    destino = clase.dir_output(cfg) / "extraido"
    salidas: list[Path] = []
    for ruta in clase.textos():
        salida = destino / nombre_extraido(ruta)
        if not forzar and reg.procesado(ruta, VERSION_EXTRACCION):
            salidas.append(salida)
            continue
        try:
            texto = extraer(ruta)
        except Exception as e:
            log.error(f"No se pudo extraer {ruta.name}: {e}")
            resumen.errores.append(f"{clase.ref}/{ruta.name}: {e}")
            continue
        destino.mkdir(parents=True, exist_ok=True)
        salida.write_text(texto, encoding="utf-8")
        reg.marcar_procesado(ruta, VERSION_EXTRACCION, [salida], tipo="extraccion")
        log.info(f"Texto extraído: {ruta.name} -> {salida.name} ({len(texto):,} caracteres)")
        resumen.extraidos += 1
        salidas.append(salida)
    return salidas


# --------------------------------------------------------------------------
# Contexto
# --------------------------------------------------------------------------

def _yaml_bloque(datos: dict, claves: list[str]) -> str:
    sub = {k: datos[k] for k in claves if datos.get(k) not in (None, "", [], {})}
    return yaml.safe_dump(sub, allow_unicode=True, sort_keys=False).strip() if sub else ""


def construir_contexto(cfg: Config, clase: Clase, extraidos: list[Path]) -> str:
    partes = ["## Contexto de la clase"]
    curso_meta = _yaml_bloque(clase.curso.meta, ["nombre", "descripcion", "plataformas", "url_base"])
    if curso_meta:
        partes.append(f"### Curso\n```yaml\n{curso_meta}\n```")
    meta = clase.meta
    clase_meta = _yaml_bloque(meta, ["titulo", "fecha", "plataformas", "url_inicio", "links", "notas"])
    if clase_meta:
        partes.append(f"### Clase\n```yaml\n{clase_meta}\n```")
    tareas = meta.get("tareas_esperadas") or []
    if tareas:
        lista = "\n".join(f"- {t}" for t in tareas)
        partes.append(
            "### Tareas que esta clase debería enseñar\n"
            "Asegúrate de cubrir cada una si aparece en el material (no inventes las que no aparezcan):\n"
            + lista
        )
    if extraidos:
        partes.append(
            "### Material complementario (texto extraído de presentaciones, documentos y Zoom)\n"
            "Úsalo para confirmar nombres exactos, URLs y conceptos. Si contradice lo que se ve en "
            "pantalla, prevalece la pantalla."
        )
        disponible = cfg.gemini.max_chars_contexto
        for ruta in extraidos:
            if not ruta.exists():
                continue
            texto = ruta.read_text(encoding="utf-8")
            if disponible <= 0:
                partes.append(f"_(omitido por longitud: {ruta.name})_")
                continue
            if len(texto) > disponible:
                texto = texto[:disponible] + "\n\n_(texto truncado por longitud)_"
            disponible -= len(texto)
            partes.append(f"#### {ruta.name}\n\n{texto}")
    return "\n\n".join(partes)


def armar_prompt(tipo: str, contexto: str) -> str:
    return prompt(tipo).replace("{{CONTEXTO}}", contexto).replace("{{FORMATO}}", prompt("formato"))


def huella_prompt(cfg: Config, tipo: str) -> str:
    g = cfg.gemini
    extra = (g.procesamiento_video, g.resolucion_video) if tipo == "video" else ()
    return huella(VERSION_PROMPT, g.modelo, *extra, prompt("sistema"), prompt(tipo), prompt("formato"))


# --------------------------------------------------------------------------
# Salida de Gemini -> archivos de procedimiento
# --------------------------------------------------------------------------

RE_TITULO = re.compile(r"^#\s+(.+)$", re.M)
RE_CUANDO = re.compile(r"\*\*Cu[aá]ndo usar:?\*\*:?\s*(.+)", re.I)


def separar_procedimientos(texto: str) -> list[str]:
    texto = texto.strip()
    texto = re.sub(r"^```(?:markdown|md)?\s*\n", "", texto)
    texto = re.sub(r"\n```\s*$", "", texto)
    bloques = [b.strip() for b in texto.split(SEPARADOR)]
    bloques = [b for b in bloques if RE_TITULO.search(b)]
    if not bloques and texto:
        bloques = [texto]
    return bloques


def escribir_procedimientos(cfg: Config, clase: Clase, origen: Path | None, etiqueta: str,
                            texto: str, previas: list[str]) -> list[Path]:
    # Borra las salidas de una ejecución anterior del mismo origen
    for rel in previas:
        p = cfg.raiz / rel
        if p.exists() and p.suffix == ".md" and "procedimientos" in p.parts:
            p.unlink()

    base = clase.dir_output(cfg)
    crudo = base / "crudo" / f"{etiqueta}.md"
    crudo.parent.mkdir(parents=True, exist_ok=True)
    crudo.write_text(texto, encoding="utf-8")

    destino = base / "procedimientos"
    destino.mkdir(parents=True, exist_ok=True)
    salidas = [crudo]
    for i, bloque in enumerate(separar_procedimientos(texto), 1):
        m = RE_TITULO.search(bloque)
        titulo = m.group(1).strip() if m else f"Procedimiento {i}"
        cuando = RE_CUANDO.search(bloque)
        meta = {
            "titulo": titulo,
            "cuando_usar": cuando.group(1).strip() if cuando else "",
            "curso": clase.curso.id,
            "clase": clase.id,
            "fuente": origen.relative_to(clase.ruta).as_posix() if origen else "documentos",
            "modelo": cfg.gemini.modelo,
            "generado": date.today().isoformat(),
        }
        frontmatter = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).strip()
        archivo = destino / f"{etiqueta}--{i:02d}-{kebab(titulo)[:60]}.md"
        archivo.write_text(f"---\n{frontmatter}\n---\n\n{bloque}\n", encoding="utf-8")
        salidas.append(archivo)
    log.info(f"{len(salidas) - 1} procedimiento(s) escritos en {destino}")
    return salidas


# --------------------------------------------------------------------------
# Compresión opcional (desactivada por defecto). Nunca corta el video.
# --------------------------------------------------------------------------

def preparar_video(cfg: Config, clase: Clase, ruta: Path) -> Path:
    v = cfg.video
    if not v.comprimir or ruta.stat().st_size < v.umbral_mb * 1_048_576:
        return ruta
    if not shutil.which("ffmpeg"):
        log.warning("video.comprimir=true pero ffmpeg no está en el PATH; se sube el original.")
        return ruta
    salida = clase.dir_output(cfg) / ".cache" / f"{ruta.stem}.comprimido-crf{v.crf}-w{v.ancho_max}.mp4"
    if salida.exists():
        return salida
    salida.parent.mkdir(parents=True, exist_ok=True)
    tmp = salida.with_suffix(".tmp.mp4")
    log.info(f"Comprimiendo {ruta.name} con ffmpeg (crf {v.crf}, ancho máx. {v.ancho_max})...")
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(ruta),
        "-vf", f"scale='min({v.ancho_max},iw)':-2",
        "-c:v", "libx264", "-preset", v.preset, "-crf", str(v.crf),
        "-c:a", "aac", "-b:a", f"{v.audio_kbps}k", "-ac", "1",
        "-movflags", "+faststart", str(tmp),
    ]
    subprocess.run(cmd, check=True)
    tmp.replace(salida)
    log.info(f"Comprimido: {ruta.stat().st_size / 1_048_576:.0f} MB -> {salida.stat().st_size / 1_048_576:.0f} MB")
    return salida


# --------------------------------------------------------------------------
# Orquestación
# --------------------------------------------------------------------------

def _etiqueta(ruta: Path) -> str:
    return kebab(ruta.stem) or "media"


def procesar_media(cfg: Config, reg: Registro, gem, clase: Clase, ruta: Path,
                   contexto: str, forzar: bool, resumen: Resumen) -> None:
    tipo = "video" if ruta.parent.name == "video" else "audio"
    h = huella_prompt(cfg, tipo)
    if not forzar and reg.procesado(ruta, h):
        log.info(f"Ya procesado, se omite: {clase.ref}/{tipo}/{ruta.name}")
        resumen.omitidos += 1
        return
    previas = (reg.entrada_procesado(ruta) or {}).get("salidas", [])
    a_subir = preparar_video(cfg, clase, ruta) if tipo == "video" else ruta
    archivo = gem.subir(a_subir)
    try:
        partes = [gem.parte_media(archivo, a_subir), {"type": "text", "text": armar_prompt(tipo, contexto)}]
        res = gem.generar(partes, sistema=prompt("sistema"), etiqueta=ruta.name)
    finally:
        gem.borrar(archivo)
    fila = costos.registrar(cfg, curso=clase.curso.id, clase=clase.id, archivo=ruta.name, tipo=tipo,
                            uso=res.uso, segundos=res.segundos, interaction_id=res.interaction_id)
    salidas = escribir_procedimientos(cfg, clase, ruta, _etiqueta(ruta), res.texto, previas)
    reg.marcar_procesado(ruta, h, salidas, tipo=tipo, interaction_id=res.interaction_id,
                         costo_usd=fila["costo_total_usd"])
    resumen.procesados += 1
    resumen.costo += fila["costo_total_usd"]
    log.info(f"Costo estimado {ruta.name}: US$ {fila['costo_total_usd']:.4f} "
             f"({fila['tokens_total']:,} tokens)")


def procesar_documentos(cfg: Config, reg: Registro, gem, clase: Clase, extraidos: list[Path],
                        contexto: str, forzar: bool, resumen: Resumen) -> None:
    virtual = clase.ruta / "__documentos__"
    sha = huella(*(p.read_text(encoding="utf-8") for p in extraidos if p.exists()), clase.meta)
    h = huella_prompt(cfg, "documentos")
    if not forzar and reg.procesado(virtual, h, sha=sha):
        log.info(f"Documentos ya procesados, se omite: {clase.ref}")
        resumen.omitidos += 1
        return
    previas = (reg.entrada_procesado(virtual) or {}).get("salidas", [])
    partes = [{"type": "text", "text": armar_prompt("documentos", contexto)}]
    res = gem.generar(partes, sistema=prompt("sistema"), etiqueta=f"documentos de {clase.ref}")
    fila = costos.registrar(cfg, curso=clase.curso.id, clase=clase.id, archivo="(documentos)",
                            tipo="documentos", uso=res.uso, segundos=res.segundos,
                            interaction_id=res.interaction_id)
    salidas = escribir_procedimientos(cfg, clase, None, "documentos", res.texto, previas)
    reg.marcar_procesado(virtual, h, salidas, sha=sha, tipo="documentos",
                         interaction_id=res.interaction_id, costo_usd=fila["costo_total_usd"])
    resumen.procesados += 1
    resumen.costo += fila["costo_total_usd"]


def procesar(cfg: Config, clases: list[Clase], archivo: Path | None = None,
             forzar: bool = False, solo_extraer: bool = False) -> Resumen:
    reg = Registro(cfg)
    resumen = Resumen()
    gem = None
    for clase in clases:
        log.info(f"== {clase.ref} ==")
        extraidos = extraer_textos(cfg, reg, clase, forzar, resumen)
        if solo_extraer:
            continue
        media = clase.media()
        if archivo is not None:
            media = [m for m in media if m.resolve() == archivo.resolve()]
            if not media:
                continue  # el archivo era un documento: solo se extrae
        if not media and not (cfg.gemini.procesar_documentos_sin_media and extraidos):
            log.info("Sin video/audio ni documentos para procesar.")
            continue
        contexto = construir_contexto(cfg, clase, extraidos)
        if gem is None:
            from qhaway.gemini import Gemini
            try:
                gem = Gemini(cfg)
            except RuntimeError as e:
                log.error(str(e))
                resumen.errores.append(str(e))
                break
        objetivos = media or [None]
        for ruta in objetivos:
            try:
                if ruta is None:
                    procesar_documentos(cfg, reg, gem, clase, extraidos, contexto, forzar, resumen)
                else:
                    procesar_media(cfg, reg, gem, clase, ruta, contexto, forzar, resumen)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                nombre = ruta.name if ruta else "documentos"
                log.exception(f"Error procesando {clase.ref}/{nombre}: {e}")
                resumen.errores.append(f"{clase.ref}/{nombre}: {e}")
    reg.guardar()
    return resumen
