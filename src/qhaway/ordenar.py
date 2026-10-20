"""Ordena los archivos sueltos de input/_bandeja/ en su curso/clase."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from rich.prompt import Prompt

from qhaway.clases import Clase, Curso, buscar_clase, crear_clase, kebab, listar_cursos, subcarpeta_para
from qhaway.config import Config
from qhaway.logs import console, log
from qhaway.registro import sha256

RE_NUMERO = re.compile(
    r"(?:^|-)(?:clase|class|sesion|session|leccion|lesson|modulo|module|semana|c|s|l)-?0*(\d{1,3})(?=-|$)"
)
IGNORAR = {"desktop.ini", "thumbs.db", ".ds_store"}
PALABRAS_VACIAS = {"clase", "class", "sesion", "curso", "video", "audio", "grabacion", "zoom",
                   "para", "como", "with", "the", "del", "las", "los", "una", "uno"}


@dataclass
class Propuesta:
    archivo: Path
    subcarpeta: str
    curso: Curso | None = None
    clase: Clase | None = None
    numero: int | None = None
    seguro: bool = False
    motivo: str = ""


def _tokens(texto: str) -> set[str]:
    return {t for t in kebab(texto).split("-") if len(t) > 2 and t not in PALABRAS_VACIAS and not t.isdigit()}


def inferir(cfg: Config, archivo: Path, cursos: list[Curso]) -> Propuesta:
    sub = subcarpeta_para(archivo)
    p = Propuesta(archivo, sub or "")
    nombre = kebab(archivo.stem)
    # Las subcarpetas dentro de la bandeja también cuentan como pista (ej. _bandeja/curso-x/clase 3/)
    pistas = "-".join(kebab(x) for x in archivo.relative_to(cfg.dir_bandeja).parts[:-1])
    texto = f"{pistas}-{nombre}".strip("-")
    tokens = _tokens(texto)

    # Curso
    if len(cursos) == 1:
        p.curso = cursos[0]
    else:
        puntajes = []
        for c in cursos:
            claves = _tokens(c.id) | _tokens(c.nombre)
            puntajes.append((len(claves & tokens), c))
        puntajes.sort(key=lambda x: -x[0])
        if puntajes and puntajes[0][0] > 0 and (len(puntajes) == 1 or puntajes[0][0] > puntajes[1][0]):
            p.curso = puntajes[0][1]

    # Clase: número explícito o coincidencia de tema
    m = RE_NUMERO.search(texto)
    if m:
        p.numero = int(m.group(1))
    if p.curso:
        if p.numero is not None:
            p.clase = buscar_clase(cfg, p.curso.id, str(p.numero))
            if p.clase:
                p.motivo = f"número de clase {p.numero:02d}"
        if not p.clase:
            puntajes = []
            for cl in p.curso.clases():
                claves = _tokens(cl.id) | _tokens(cl.titulo)
                puntajes.append((len(claves & tokens), cl))
            puntajes.sort(key=lambda x: -x[0])
            if puntajes and puntajes[0][0] > 0 and (len(puntajes) == 1 or puntajes[0][0] > puntajes[1][0]):
                p.clase = puntajes[0][1]
                p.motivo = "coincidencia con el tema"
    p.seguro = bool(sub and p.curso and p.clase)
    return p


def _elegir(opciones: list[str], pregunta: str, extra: dict[str, str]) -> str:
    for i, o in enumerate(opciones, 1):
        console.print(f"  [cyan]{i}[/cyan]. {o}")
    for k, v in extra.items():
        console.print(f"  [cyan]{k}[/cyan]. {v}")
    validas = [str(i) for i in range(1, len(opciones) + 1)] + list(extra)
    return Prompt.ask(pregunta, choices=validas, show_choices=False)


def preguntar(cfg: Config, p: Propuesta) -> Propuesta | None:
    console.rule(f"[bold]{p.archivo.name}[/bold]  ->  {p.subcarpeta}/")
    cursos = listar_cursos(cfg)
    if p.curso:
        console.print(f"Curso sugerido: [green]{p.curso.id}[/green]")
        if Prompt.ask("¿Usar este curso?", choices=["s", "n"], default="s") == "n":
            p.curso = None
    if not p.curso:
        r = _elegir([c.id for c in cursos], "Curso", {"n": "nuevo curso", "o": "omitir archivo"})
        if r == "o":
            return None
        if r == "n":
            nombre = Prompt.ask("Nombre del curso nuevo")
            from qhaway.clases import crear_curso
            p.curso = crear_curso(cfg, nombre, nombre)
        else:
            p.curso = cursos[int(r) - 1]
        p.clase = None
    if p.clase:
        console.print(f"Clase sugerida: [green]{p.clase.id}[/green] ({p.motivo})")
        if Prompt.ask("¿Usar esta clase?", choices=["s", "n"], default="s") == "n":
            p.clase = None
    if not p.clase:
        clases = p.curso.clases()
        r = _elegir([c.id for c in clases], "Clase", {"n": "nueva clase", "o": "omitir archivo"})
        if r == "o":
            return None
        if r == "n":
            tema = Prompt.ask("Tema de la clase nueva (ej. crear usuarios)")
            num = Prompt.ask("Número", default=str(p.numero or p.curso.siguiente_numero()))
            p.clase, _ = crear_clase(cfg, p.curso.id, tema, numero=int(num))
        else:
            p.clase = clases[int(r) - 1]
    return p


def destino_libre(destino: Path) -> Path:
    if not destino.exists():
        return destino
    i = 2
    while True:
        candidato = destino.with_name(f"{destino.stem}-{i}{destino.suffix}")
        if not candidato.exists():
            return candidato
        i += 1


def mover(cfg: Config, p: Propuesta, dry_run: bool) -> str:
    carpeta = p.clase.ruta / p.subcarpeta
    nombre = f"{kebab(p.archivo.stem) or 'archivo'}{p.archivo.suffix.lower()}"
    destino = carpeta / nombre
    if destino.exists() and destino.stat().st_size == p.archivo.stat().st_size \
            and sha256(destino) == sha256(p.archivo):
        dup = destino_libre(cfg.dir_bandeja / "_duplicados" / p.archivo.name)
        if not dup.parent.exists() and not dry_run:
            dup.parent.mkdir(parents=True)
        if not dry_run:
            shutil.move(str(p.archivo), str(dup))
        return f"duplicado de {destino.relative_to(cfg.dir_input)} -> _bandeja/_duplicados/"
    destino = destino_libre(destino)
    if not dry_run:
        carpeta.mkdir(parents=True, exist_ok=True)
        shutil.move(str(p.archivo), str(destino))
    return str(destino.relative_to(cfg.dir_input))


def archivos_bandeja(cfg: Config) -> list[Path]:
    if not cfg.dir_bandeja.is_dir():
        return []
    return sorted(
        p for p in cfg.dir_bandeja.rglob("*")
        if p.is_file() and "_duplicados" not in p.relative_to(cfg.dir_bandeja).parts
        and p.name.lower() not in IGNORAR and not p.name.startswith(".")
    )


def ordenar(cfg: Config, auto: bool = False, dry_run: bool = False,
            curso: str | None = None, clase: str | None = None) -> dict[str, int]:
    cfg.dir_bandeja.mkdir(parents=True, exist_ok=True)
    conteo = {"movidos": 0, "omitidos": 0, "no_soportados": 0}
    archivos = archivos_bandeja(cfg)
    if not archivos:
        log.info(f"La bandeja está vacía ({cfg.dir_bandeja}).")
        return conteo

    forzada = None
    if curso and clase:
        forzada = buscar_clase(cfg, curso, clase)
        if not forzada:
            raise ValueError(f"No existe la clase {curso}/{clase}")

    for archivo in archivos:
        cursos = listar_cursos(cfg)
        p = inferir(cfg, archivo, cursos)
        if not p.subcarpeta:
            log.warning(f"Tipo no soportado, se deja en la bandeja: {archivo.name}")
            conteo["no_soportados"] += 1
            continue
        if forzada:
            p.curso, p.clase, p.seguro = forzada.curso, forzada, True
        if not p.seguro:
            if auto:
                log.info(f"Sin coincidencia segura, se deja en la bandeja: {archivo.name}")
                conteo["omitidos"] += 1
                continue
            p = preguntar(cfg, p)
            if p is None:
                conteo["omitidos"] += 1
                continue
        resultado = mover(cfg, p, dry_run)
        prefijo = "[simulación] " if dry_run else ""
        log.info(f"{prefijo}{archivo.name} -> {resultado}")
        conteo["movidos"] += 1

    if not dry_run:
        # Limpia subcarpetas vacías de la bandeja
        for d in sorted((d for d in cfg.dir_bandeja.rglob("*") if d.is_dir()), reverse=True):
            if d.name != "_duplicados" and not any(d.iterdir()):
                d.rmdir()
    return conteo
