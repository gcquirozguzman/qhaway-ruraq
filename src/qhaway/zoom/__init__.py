"""Orquestación de descargas de Zoom a partir de zoom_links.yaml y de cada clase.yaml."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from qhaway.clases import buscar_clase, crear_clase, leer_yaml, listar_cursos
from qhaway.config import Config
from qhaway.logs import log
from qhaway.registro import Registro


@dataclass
class Grabacion:
    curso: str
    clase: str
    url: str | None = None
    passcode: str | None = None
    meeting_id: str | None = None
    metodo: str = "auto"
    nombre: str | None = None
    tema: str | None = None
    origen: str = "zoom_links.yaml"

    @property
    def clave(self) -> str:
        fuente = self.meeting_id or self.url or ""
        return "zoom:" + hashlib.sha256(fuente.strip().encode()).hexdigest()[:16]


@dataclass
class ResumenZoom:
    descargadas: int = 0
    omitidas: int = 0
    errores: list[str] = field(default_factory=list)


def cargar_grabaciones(cfg: Config) -> list[Grabacion]:
    grabaciones: list[Grabacion] = []
    for item in leer_yaml(cfg.archivo_zoom_links).get("grabaciones") or []:
        if not item or not (item.get("url") or item.get("meeting_id")):
            continue
        grabaciones.append(Grabacion(
            curso=str(item["curso"]), clase=str(item.get("clase", "")),
            url=item.get("url"), passcode=_s(item.get("passcode")),
            meeting_id=_s(item.get("meeting_id")),
            metodo=item.get("metodo") or cfg.zoom.metodo_por_defecto,
            nombre=item.get("nombre"), tema=item.get("tema"),
        ))
    # Campo "zoom" dentro de cada clase.yaml
    vistas = {g.clave for g in grabaciones}
    for curso in listar_cursos(cfg):
        for clase in curso.clases():
            z = clase.meta.get("zoom") or {}
            if not (z.get("url") or z.get("meeting_id")):
                continue
            g = Grabacion(curso=curso.id, clase=clase.id, url=z.get("url"),
                          passcode=_s(z.get("passcode")), meeting_id=_s(z.get("meeting_id")),
                          metodo=z.get("metodo") or cfg.zoom.metodo_por_defecto,
                          origen=f"{clase.ref}/clase.yaml")
            if g.clave not in vistas:
                grabaciones.append(g)
                vistas.add(g.clave)
    return grabaciones


def _s(valor) -> str | None:
    return None if valor in (None, "") else str(valor)


def _metodo(g: Grabacion) -> str:
    from qhaway.zoom.api import credenciales_disponibles

    if g.metodo == "api" or (g.metodo == "auto" and g.meeting_id and credenciales_disponibles()):
        if not g.meeting_id:
            raise ValueError("metodo=api requiere meeting_id")
        return "api"
    if not g.url:
        raise ValueError("Falta url (o configura credenciales de Zoom en .env para usar meeting_id)")
    return "ytdlp"


def nombres_base(grabaciones: list[Grabacion], cfg: Config) -> dict[str, str]:
    """clase-01-tema__zoom, clase-01-tema__zoom-02, ... según el orden de aparición."""
    contador: dict[str, int] = {}
    nombres: dict[str, str] = {}
    for g in grabaciones:
        clase = buscar_clase(cfg, g.curso, g.clase)
        id_clase = clase.id if clase else g.clase
        n = contador[id_clase] = contador.get(id_clase, 0) + 1
        sufijo = g.nombre or ("zoom" if n == 1 else f"zoom-{n:02d}")
        nombres[g.clave] = f"{id_clase}__{sufijo}"
    return nombres


def descargar_todo(cfg: Config, solo_clase: str | None = None, forzar: bool = False) -> ResumenZoom:
    reg = Registro(cfg)
    res = ResumenZoom()
    grabaciones = cargar_grabaciones(cfg)
    if not grabaciones:
        log.warning(f"No hay grabaciones en {cfg.archivo_zoom_links.name} ni en los clase.yaml.")
        return res

    for g in grabaciones:
        etiqueta = f"{g.curso}/{g.clase}"
        try:
            clase = buscar_clase(cfg, g.curso, g.clase)
            if solo_clase and (not clase or clase.ref != solo_clase):
                continue
            if not clase:
                if not g.tema:
                    raise ValueError(f"No existe la clase {etiqueta}. Créala con 'qhaway nueva-clase' "
                                     "o agrega 'tema:' en zoom_links.yaml para crearla automáticamente.")
                num = int(g.clase) if g.clase.isdigit() else None
                clase, _ = crear_clase(cfg, g.curso, g.tema, numero=num, zoom_url=g.url, passcode=g.passcode)
                log.info(f"Clase creada: {clase.ref}")
            base = nombres_base(grabaciones, cfg)[g.clave]
            if not forzar and reg.descarga(g.clave):
                log.info(f"Ya descargado, se omite: {clase.ref} ({base})")
                res.omitidas += 1
                continue
            metodo = _metodo(g)
            log.info(f"Descargando {clase.ref} con {metodo} -> {base}")
            if metodo == "api":
                from qhaway.zoom import api
                archivos = api.descargar(cfg, g.meeting_id, clase.ruta, base)
            else:
                from qhaway.zoom import ytdlp
                archivos = ytdlp.descargar(cfg, g.url, g.passcode, clase.ruta, base)
            if not archivos:
                raise RuntimeError("No se descargó ningún archivo")
            reg.marcar_descarga(g.clave, archivos, metodo=metodo, clase=clase.ref,
                                url=g.url, meeting_id=g.meeting_id)
            res.descargadas += 1
        except KeyboardInterrupt:
            raise
        except Exception as e:
            log.error(f"Error con la grabación de {etiqueta} ({g.origen}): {e}")
            res.errores.append(f"{etiqueta}: {e}")
    return res
