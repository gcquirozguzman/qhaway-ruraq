"""CLI de qhaway-ruraq."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import typer

from qhaway.config import cargar_config
from qhaway.logs import configurar_logs, console, log

app = typer.Typer(
    help="qhaway-ruraq: convierte capacitaciones en procedimientos y en una Skill de Claude.",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode="rich",
)


@app.callback()
def _inicio(verbose: bool = typer.Option(False, "--verbose", "-v", help="Muestra logs de depuración.")):
    configurar_logs(verbose)


def _salir_con_errores(errores: list[str]) -> None:
    if errores:
        console.print(f"\n[red]{len(errores)} error(es):[/red]")
        for e in errores:
            console.print(f"  - {e}", markup=False)
        raise typer.Exit(1)


@app.command("nueva-clase")
def nueva_clase(
    curso: str = typer.Argument(..., help="Curso (se crea si no existe). Ej: google-workspace-admin"),
    tema: str = typer.Argument(..., help="Tema de la clase. Ej: 'crear usuarios'"),
    numero: Optional[int] = typer.Option(None, "--numero", "-n", help="Número de clase (por defecto, el siguiente)."),
    titulo: Optional[str] = typer.Option(None, help="Título legible (por defecto, el tema)."),
    fecha: Optional[str] = typer.Option(None, help="Fecha AAAA-MM-DD (por defecto, hoy)."),
    zoom: Optional[str] = typer.Option(None, "--zoom", help="Link de la grabación de Zoom."),
    passcode: Optional[str] = typer.Option(None, help="Passcode de la grabación de Zoom."),
):
    """Crea un curso/clase con sus carpetas y plantillas curso.yaml / clase.yaml."""
    from qhaway.clases import crear_clase

    cfg = cargar_config()
    clase, creada = crear_clase(cfg, curso, tema, numero, titulo, fecha, zoom, passcode)
    if creada:
        console.print(f"[green]Clase creada:[/green] {clase.ruta.relative_to(cfg.raiz)}")
    else:
        console.print(f"[yellow]La clase ya existía:[/yellow] {clase.ruta.relative_to(cfg.raiz)}")
    console.print("Completa clase.yaml y copia el material en video/, audio/, presentaciones/ y documentos/.")


@app.command()
def ordenar(
    auto: bool = typer.Option(False, "--auto", help="No preguntar: mueve solo lo que se infiere con seguridad."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Muestra qué haría sin mover nada."),
    curso: Optional[str] = typer.Option(None, help="Forzar todo al curso indicado (junto con --clase)."),
    clase: Optional[str] = typer.Option(None, help="Forzar todo a esta clase (ej. 03)."),
):
    """Ordena los archivos sueltos de input/_bandeja/ en su curso/clase."""
    from qhaway.ordenar import ordenar as _ordenar

    cfg = cargar_config()
    r = _ordenar(cfg, auto=auto, dry_run=dry_run, curso=curso, clase=clase)
    console.print(f"Movidos: {r['movidos']} · Omitidos: {r['omitidos']} · No soportados: {r['no_soportados']}")


@app.command()
def zoom(
    clase: Optional[str] = typer.Option(None, "--clase", "-c", help="Solo esta clase (curso/clase)."),
    forzar: bool = typer.Option(False, "--forzar", help="Vuelve a descargar aunque ya exista."),
    listar: bool = typer.Option(False, "--listar", help="Lista las grabaciones de tu cuenta (API) y sale."),
    desde: Optional[str] = typer.Option(None, help="Con --listar: fecha inicial AAAA-MM-DD (por defecto, hace 30 días)."),
):
    """Descarga las grabaciones de zoom_links.yaml (y de los clase.yaml) a su clase."""
    cfg = cargar_config()
    if listar:
        from rich.table import Table

        from qhaway.zoom.api import ZoomAPI

        inicio = date.fromisoformat(desde) if desde else date.today() - timedelta(days=30)
        reuniones = ZoomAPI().listar(inicio)
        t = Table(title=f"Grabaciones desde {inicio}")
        for col in ("Fecha", "Tema", "meeting_id", "Archivos"):
            t.add_column(col)
        for m in reuniones:
            tipos = ", ".join(sorted({f.get("file_type", "?") for f in m.get("recording_files", [])}))
            t.add_row(m.get("start_time", "")[:16], m.get("topic", ""), str(m.get("id", "")), tipos)
        console.print(t)
        return
    from qhaway.zoom import descargar_todo

    r = descargar_todo(cfg, solo_clase=clase, forzar=forzar)
    console.print(f"Descargadas: {r.descargadas} · Ya existentes: {r.omitidas}")
    _salir_con_errores(r.errores)


@app.command()
def procesar(
    clase: Optional[str] = typer.Option(None, "--clase", "-c", help="Solo esta clase (curso/clase, ej. google-workspace/01)."),
    curso: Optional[str] = typer.Option(None, "--curso", help="Solo las clases de este curso."),
    file: Optional[Path] = typer.Option(None, "--file", "-f", help="Solo este archivo (dentro de input/)."),
    forzar: bool = typer.Option(False, "--forzar", help="Reprocesa aunque no haya cambios."),
    solo_extraer: bool = typer.Option(False, "--solo-extraer", help="Solo extrae texto de documentos (sin Gemini)."),
):
    """Extrae texto y genera procedimientos con Gemini (todo, una clase o un archivo)."""
    from qhaway.clases import buscar_curso, resolver_ref
    from qhaway.procesar import clase_de_archivo, procesar as _procesar, todas_las_clases

    cfg = cargar_config()
    try:
        if file:
            clases = [clase_de_archivo(cfg, file)]
        elif clase:
            clases = [resolver_ref(cfg, clase)]
        elif curso:
            c = buscar_curso(cfg, curso)
            if not c:
                raise ValueError(f"No existe el curso {curso}")
            clases = c.clases()
        else:
            clases = todas_las_clases(cfg)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(2)
    if not clases:
        console.print("No hay clases en input/. Crea una con: qhaway nueva-clase <curso> <tema>")
        return
    r = _procesar(cfg, clases, archivo=file, forzar=forzar, solo_extraer=solo_extraer)
    console.print(
        f"\nTextos extraídos: {r.extraidos} · Procesados con Gemini: {r.procesados} · "
        f"Omitidos (sin cambios): {r.omitidos} · Costo de esta ejecución: US$ {r.costo:.4f}"
    )
    _salir_con_errores(r.errores)


@app.command()
def skill():
    """Genera output/skill/ (SKILL.md, procedimientos/, referencias/) y el .zip para Claude."""
    from qhaway.skill import generar

    cfg = cargar_config()
    raiz, zip_path, total = generar(cfg)
    if total == 0:
        console.print("[yellow]No hay procedimientos todavía. Ejecuta primero: qhaway procesar[/yellow]")
    console.print(f"[green]Listo:[/green] {zip_path.relative_to(cfg.raiz)}")


@app.command()
def estado(
    verificar: bool = typer.Option(False, "--verificar", help="Recalcula hashes para detectar archivos modificados."),
):
    """Muestra qué está descargado, procesado o pendiente."""
    from qhaway.estado import mostrar

    mostrar(cargar_config(), verificar_hash=verificar)


def main() -> None:  # pragma: no cover
    try:
        app()
    except KeyboardInterrupt:
        log.warning("Interrumpido por el usuario.")
        raise SystemExit(130)
