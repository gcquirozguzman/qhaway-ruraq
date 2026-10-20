"""Cliente Gemini: Files API + Interactions API, con reintentos y polling.

Referencias (verificadas con google-genai 2.31):
- https://ai.google.dev/gemini-api/docs/video-understanding
- https://ai.google.dev/gemini-api/docs/media-resolution
- https://ai.google.dev/gemini-api/docs/interactions/tokens
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from google import genai
from slugify import slugify
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from qhaway.config import Config, env
from qhaway.logs import log

MIME = {
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".mov": "video/mov",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
    ".mp3": "audio/mp3",
    ".m4a": "audio/m4a",
    ".wav": "audio/wav",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
}
REINTENTABLES = {408, 409, 429, 500, 502, 503, 504}
EN_CURSO = {"in_progress", "queued"}


def _es_reintentable(exc: BaseException) -> bool:
    codigo = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if isinstance(codigo, int):
        return codigo in REINTENTABLES
    return isinstance(exc, (httpx.TransportError, ConnectionError, TimeoutError))


@dataclass
class Resultado:
    texto: str
    uso: dict = field(default_factory=dict)
    interaction_id: str = ""
    segundos: float = 0.0


class Gemini:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.g = cfg.gemini
        self.client = genai.Client(api_key=env("GEMINI_API_KEY", requerido=True))
        self._retry = retry(
            retry=retry_if_exception(_es_reintentable),
            stop=stop_after_attempt(self.g.max_reintentos),
            wait=wait_exponential_jitter(initial=5, max=120),
            before_sleep=before_sleep_log(log, 30),  # WARNING
            reraise=True,
        )

    # --- Files API -----------------------------------------------------------
    def subir(self, ruta: Path):
        mime = MIME.get(ruta.suffix.lower())
        tam_mb = ruta.stat().st_size / 1_048_576
        log.info(f"Subiendo {ruta.name} ({tam_mb:.0f} MB) a la Files API...")
        archivo = self._retry(self.client.files.upload)(
            file=str(ruta),
            config={"mime_type": mime, "display_name": slugify(ruta.stem)[:100] or "archivo"},
        )
        inicio = time.monotonic()
        while archivo.state and archivo.state.name == "PROCESSING":
            if time.monotonic() - inicio > self.g.timeout_min * 60:
                raise TimeoutError(f"La Files API no terminó de procesar {ruta.name}")
            time.sleep(self.g.intervalo_polling_s)
            archivo = self._retry(self.client.files.get)(name=archivo.name)
        if archivo.state and archivo.state.name == "FAILED":
            raise RuntimeError(f"La Files API no pudo procesar {ruta.name}: {archivo.error}")
        log.info(f"Archivo listo: {archivo.name}")
        return archivo

    def borrar(self, archivo) -> None:
        if not self.g.borrar_archivo_remoto:
            return
        try:
            self.client.files.delete(name=archivo.name)
        except Exception as e:  # no es crítico
            log.debug(f"No se pudo borrar {archivo.name}: {e}")

    # --- Interactions API ----------------------------------------------------
    def parte_media(self, archivo, ruta: Path) -> dict:
        mime = archivo.mime_type or MIME.get(ruta.suffix.lower())
        if mime.startswith("video/"):
            parte = {"type": "video", "uri": archivo.uri, "mime_type": mime}
            parte["processing"] = self.g.procesamiento_video
            if self.g.resolucion_video != "unspecified":
                parte["resolution"] = self.g.resolucion_video
            return parte
        return {"type": "audio", "uri": archivo.uri, "mime_type": mime}

    def generar(self, partes: list[dict], sistema: str | None = None, etiqueta: str = "") -> Resultado:
        """Crea una interacción en segundo plano y espera el resultado."""
        cuerpo = {"model": self.g.modelo, "input": partes, "background": True}
        if sistema:
            cuerpo["system_instruction"] = sistema
        inicio = time.monotonic()
        inter = self._retry(self.client.interactions.create)(**cuerpo)
        log.info(f"Gemini trabajando en {etiqueta or 'la solicitud'} (id {inter.id})...")
        ultimo_aviso = inicio
        while inter.status in EN_CURSO:
            if time.monotonic() - inicio > self.g.timeout_min * 60:
                try:
                    self.client.interactions.cancel(inter.id)
                except Exception:
                    pass
                raise TimeoutError(f"Gemini excedió {self.g.timeout_min} min en {etiqueta}")
            time.sleep(self.g.intervalo_polling_s)
            inter = self._retry(self.client.interactions.get)(inter.id)
            if time.monotonic() - ultimo_aviso > 120:
                log.info(f"  ...sigue en curso ({(time.monotonic() - inicio) / 60:.0f} min)")
                ultimo_aviso = time.monotonic()
        if inter.status != "completed":
            raise RuntimeError(f"Gemini terminó con estado '{inter.status}': {getattr(inter, 'error', '')}")
        texto = inter.output_text or ""
        if not texto.strip():
            raise RuntimeError("Gemini devolvió una respuesta vacía")
        uso = inter.usage.model_dump(exclude_none=True) if inter.usage else {}
        return Resultado(texto=texto, uso=uso, interaction_id=inter.id or "", segundos=time.monotonic() - inicio)
