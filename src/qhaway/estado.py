"""Resumen de lo descargado, procesado y pendiente."""

from __future__ import annotations

from rich.table import Table

from qhaway import costos
from qhaway.clases import listar_cursos
from qhaway.config import Config
from qhaway.logs import console
from qhaway.ordenar import archivos_bandeja
from qhaway.procesar import huella_prompt, VERSION_EXTRACCION
from qhaway.registro import Registro


def mostrar(cfg: Config, verificar_hash: bool = False) -> None:
    reg = Registro(cfg)
    tabla = Table(title="Estado de qhaway-ruraq", show_lines=False)
    for col in ("Curso/clase", "Video", "Audio", "Pres.", "Docs", "Zoom", "Media procesada", "Textos", "Proced."):
        if col == "Curso/clase":
            tabla.add_column(col, overflow="fold", min_width=24)
        else:
            tabla.add_column(col, justify="center")

    huellas = {"video": huella_prompt(cfg, "video"), "audio": huella_prompt(cfg, "audio")}
    pendientes: list[str] = []
    for curso in listar_cursos(cfg):
        for clase in curso.clases():
            media = clase.media()
            hechos = 0
            for m in media:
                tipo = m.parent.name
                entrada = reg.entrada_procesado(m)
                if verificar_hash:
                    ok = reg.procesado(m, huellas[tipo]) is not None
                else:
                    ok = bool(entrada and entrada.get("huella") == huellas[tipo])
                hechos += ok
                if not ok:
                    pendientes.append(f"{clase.ref}/{tipo}/{m.name}")
            textos = clase.textos()
            extraidos = sum(
                1 for t in textos
                if (reg.entrada_procesado(t) or {}).get("huella") == VERSION_EXTRACCION
            )
            dir_proc = clase.dir_output(cfg) / "procedimientos"
            n_proc = len(list(dir_proc.glob("*.md"))) if dir_proc.is_dir() else 0
            zoom = len([p for p in clase.archivos("zoom") if p.suffix.lower() in (".vtt", ".srt")])
            estilo = "green" if media and hechos == len(media) else ("yellow" if hechos else "")
            tabla.add_row(
                clase.ref,
                str(len(clase.archivos("video"))), str(len(clase.archivos("audio"))),
                str(len(clase.archivos("presentaciones"))), str(len(clase.archivos("documentos"))),
                str(zoom),
                f"[{estilo}]{hechos}/{len(media)}[/{estilo}]" if estilo else f"{hechos}/{len(media)}",
                f"{extraidos}/{len(textos)}", str(n_proc),
            )
    console.print(tabla)

    # Zoom pendiente
    from qhaway.zoom import cargar_grabaciones
    grabaciones = cargar_grabaciones(cfg)
    sin_bajar = [g for g in grabaciones if not reg.descarga(g.clave)]
    console.print(f"\n[bold]Zoom:[/bold] {len(grabaciones) - len(sin_bajar)}/{len(grabaciones)} grabaciones descargadas")
    for g in sin_bajar:
        console.print(f"  - pendiente: {g.curso}/{g.clase}  ({g.url or 'meeting ' + str(g.meeting_id)})")

    if pendientes:
        console.print(f"\n[bold]Media sin procesar ({len(pendientes)}):[/bold]")
        for p in pendientes:
            console.print(f"  - {p}")

    bandeja = archivos_bandeja(cfg)
    if bandeja:
        console.print(f"\n[bold]Bandeja:[/bold] {len(bandeja)} archivo(s) por ordenar -> qhaway ordenar")

    skill_zip = cfg.dir_skill / f"{cfg.skill.nombre}.zip"
    if skill_zip.exists():
        from datetime import datetime
        fecha = datetime.fromtimestamp(skill_zip.stat().st_mtime)
        console.print(f"\n[bold]Skill:[/bold] {skill_zip.relative_to(cfg.raiz)} (generada {fecha:%Y-%m-%d %H:%M})")
    else:
        console.print("\n[bold]Skill:[/bold] aún no generada -> qhaway skill")

    gasto, llamadas = costos.total(cfg)
    console.print(f"[bold]Costo acumulado:[/bold] US$ {gasto:.4f} en {llamadas} llamada(s) a Gemini")
