"""Descarga de links compartidos de Zoom (/rec/share/, /rec/play/) con yt-dlp."""

from __future__ import annotations

import json
from pathlib import Path

import yt_dlp
from yt_dlp.extractor.zoom import ZoomIE

from qhaway.config import Config
from qhaway.logs import log


class QhawayZoomIE(ZoomIE):
    """ZoomIE que además conserva el JSON de play/info (incluye el chat en `xmppList`)."""

    IE_NAME = "qhaway:zoom"

    def _download_json(self, url_or_request, *args, **kwargs):
        datos = super()._download_json(url_or_request, *args, **kwargs)
        url = getattr(url_or_request, "url", url_or_request)
        if "/play/info/" in str(url) and isinstance(datos, dict):
            self.play_info = datos.get("result") or {}
        return datos


def guardar_chat(play_info: dict, destino: Path) -> Path | None:
    mensajes = play_info.get("xmppList") or []
    if not mensajes:
        return None
    lineas = [
        f"[{m.get('timeFromMeetingStart', '')}] {m.get('senderName', '?')}: {(m.get('content') or '').strip()}"
        for m in sorted(mensajes, key=lambda m: m.get("time") or 0)
    ]
    destino.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    log.info(f"Chat guardado: {destino.name} ({len(mensajes)} mensajes)")
    return destino


class _Logger:
    def debug(self, msg: str) -> None:
        if not msg.startswith("[download]"):
            log.debug(msg)

    def info(self, msg: str) -> None:
        log.debug(msg)

    def warning(self, msg: str) -> None:
        log.warning(msg)

    def error(self, msg: str) -> None:
        log.debug(msg)  # el error se reporta una sola vez al capturar la excepción


def _progreso(d: dict) -> None:
    if d.get("status") == "finished":
        log.info(f"Descargado: {Path(d.get('filename', '')).name}")


def descargar(cfg: Config, url: str, passcode: str | None, dir_clase: Path, base: str) -> list[Path]:
    """Descarga video (+ subtítulos/transcripción si existen) y devuelve los archivos creados."""
    dir_video = dir_clase / "video"
    dir_zoom = dir_clase / "zoom"
    dir_video.mkdir(parents=True, exist_ok=True)
    dir_zoom.mkdir(parents=True, exist_ok=True)

    opciones = {
        "outtmpl": {
            "default": str(dir_video / f"{base}.%(ext)s"),
            "subtitle": str(dir_zoom / f"{base}.%(ext)s"),
            "infojson": str(dir_zoom / f"{base}"),
        },
        "format": cfg.zoom.formato_ytdlp,
        "merge_output_format": "mp4",
        "writesubtitles": cfg.zoom.descargar_transcripcion,
        "subtitleslangs": ["all", "-chapter"],  # "chapter" solo marca inicio/fin de pantalla compartida
        "subtitlesformat": "vtt/best",
        "writeinfojson": True,
        "clean_infojson": True,
        "retries": 10,
        "fragment_retries": 10,
        "continuedl": True,
        "noprogress": True,
        "logger": _Logger(),
        "progress_hooks": [_progreso],
        "windowsfilenames": True,
    }
    if passcode:
        opciones["videopassword"] = str(passcode)
    if cfg.zoom.cookies_navegador:
        # Para grabaciones que exigen iniciar sesión en Zoom
        opciones["cookiesfrombrowser"] = (cfg.zoom.cookies_navegador,)

    log.info(f"yt-dlp: descargando {url}")
    ie = QhawayZoomIE()
    ie.play_info = {}
    with yt_dlp.YoutubeDL(opciones) as ydl:
        ydl.add_info_extractor(ie)
        info = ydl.extract_info(url, download=True, ie_key=ie.ie_key())
        info = ydl.sanitize_info(info)
    if ie.play_info.get("totalClips", 1) > 1:
        log.warning(f"La grabación tiene {ie.play_info['totalClips']} partes; solo se bajó la del link. "
                    "Agrega el link de cada parte en zoom_links.yaml.")

    archivos: list[Path] = []
    video = dir_video / f"{base}.mp4"
    if not video.exists():
        candidatos = sorted(dir_video.glob(f"{base}.*"))
        if not candidatos:
            raise RuntimeError("yt-dlp terminó sin generar el archivo de video")
        video = candidatos[0]
    archivos.append(video)
    archivos += [p for p in dir_zoom.glob(f"{base}*") if p.suffix.lower() in (".vtt", ".srt")]
    if cfg.zoom.descargar_chat and (chat := guardar_chat(ie.play_info, dir_zoom / f"{base}.chat.txt")):
        archivos.append(chat)

    meta = dir_zoom / f"{base}.info.json"
    if meta.exists():
        archivos.append(meta)
    else:
        meta.write_text(json.dumps({k: info.get(k) for k in ("title", "duration", "upload_date", "webpage_url")},
                                   ensure_ascii=False, indent=2), encoding="utf-8")
        archivos.append(meta)
    if not any(p.suffix.lower() == ".vtt" for p in archivos) and cfg.zoom.descargar_transcripcion:
        log.info("El link compartido no expone transcripción (normal si no se activó en Zoom).")
    return archivos
