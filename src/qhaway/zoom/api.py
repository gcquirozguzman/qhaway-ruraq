"""Descarga de grabaciones en la nube de TU cuenta con la API de Zoom (Server-to-Server OAuth).

Docs: https://developers.zoom.us/docs/internal-apps/s2s-oauth/
      https://developers.zoom.us/docs/api/meetings/#tag/cloud-recording
"""

from __future__ import annotations

import time
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote

import requests
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential_jitter

from qhaway.config import Config, env
from qhaway.logs import log

API = "https://api.zoom.us/v2"
EXT = {"MP4": "mp4", "M4A": "m4a", "TRANSCRIPT": "vtt", "CC": "vtt", "CHAT": "txt",
       "TIMELINE": "json", "SUMMARY": "json"}


def _reintentable(exc: BaseException) -> bool:
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        return exc.response.status_code in (429, 500, 502, 503, 504)
    return isinstance(exc, (requests.ConnectionError, requests.Timeout))


_retry = retry(retry=retry_if_exception(_reintentable), stop=stop_after_attempt(5),
               wait=wait_exponential_jitter(initial=3, max=60), reraise=True)


def credenciales_disponibles() -> bool:
    return all(env(k) for k in ("ZOOM_ACCOUNT_ID", "ZOOM_CLIENT_ID", "ZOOM_CLIENT_SECRET"))


class ZoomAPI:
    def __init__(self) -> None:
        self.account_id = env("ZOOM_ACCOUNT_ID", requerido=True)
        self.client_id = env("ZOOM_CLIENT_ID", requerido=True)
        self.client_secret = env("ZOOM_CLIENT_SECRET", requerido=True)
        self._token: str | None = None
        self._expira = 0.0
        self.s = requests.Session()

    @_retry
    def token(self) -> str:
        if self._token and time.time() < self._expira - 60:
            return self._token
        r = self.s.post(
            "https://zoom.us/oauth/token",
            params={"grant_type": "account_credentials", "account_id": self.account_id},
            auth=(self.client_id, self.client_secret),
            timeout=30,
        )
        r.raise_for_status()
        datos = r.json()
        self._token = datos["access_token"]
        self._expira = time.time() + int(datos.get("expires_in", 3600))
        return self._token

    @_retry
    def get(self, ruta: str, **params) -> dict:
        r = self.s.get(f"{API}{ruta}", params=params,
                       headers={"Authorization": f"Bearer {self.token()}"}, timeout=60)
        if r.status_code == 404:
            raise FileNotFoundError(f"Zoom: no existe {ruta} ({r.json().get('message', '')})")
        r.raise_for_status()
        return r.json()

    # --- consultas -----------------------------------------------------------
    def grabacion(self, meeting_id: str) -> dict:
        mid = str(meeting_id).replace(" ", "")
        # Los UUID que empiezan con "/" o contienen "//" deben codificarse dos veces
        if mid.startswith("/") or "//" in mid:
            mid = quote(quote(mid, safe=""), safe="")
        return self.get(f"/meetings/{mid}/recordings")

    def listar(self, desde: date, hasta: date | None = None) -> list[dict]:
        """Lista grabaciones del usuario en tramos de 30 días (límite de la API)."""
        usuario = env("ZOOM_USER_ID") or "me"
        hasta = hasta or date.today()
        reuniones: list[dict] = []
        inicio = desde
        while inicio <= hasta:
            fin = min(inicio + timedelta(days=30), hasta)
            token_pag = ""
            while True:
                datos = self.get(f"/users/{usuario}/recordings", **{
                    "from": inicio.isoformat(), "to": fin.isoformat(), "page_size": 300,
                    "next_page_token": token_pag,
                })
                reuniones += datos.get("meetings", [])
                token_pag = datos.get("next_page_token") or ""
                if not token_pag:
                    break
            inicio = fin + timedelta(days=1)
        return reuniones

    # --- descarga ------------------------------------------------------------
    @_retry
    def bajar_archivo(self, url: str, destino: Path, tam_esperado: int | None = None) -> Path:
        if destino.exists() and (not tam_esperado or destino.stat().st_size == tam_esperado):
            log.info(f"Ya existe: {destino.name}")
            return destino
        destino.parent.mkdir(parents=True, exist_ok=True)
        tmp = destino.with_suffix(destino.suffix + ".part")
        with self.s.get(url, headers={"Authorization": f"Bearer {self.token()}"},
                        stream=True, timeout=120, allow_redirects=True) as r:
            r.raise_for_status()
            with tmp.open("wb") as f:
                for chunk in r.iter_content(chunk_size=4 * 1024 * 1024):
                    f.write(chunk)
        tmp.replace(destino)
        log.info(f"Descargado: {destino.name} ({destino.stat().st_size / 1_048_576:.1f} MB)")
        return destino


def elegir_archivos(cfg: Config, archivos: list[dict]) -> list[dict]:
    listos = [a for a in archivos if a.get("status", "completed") == "completed" and a.get("download_url")]
    pendientes = [a for a in archivos if a not in listos]
    if pendientes:
        log.warning(f"{len(pendientes)} archivo(s) aún en procesamiento en Zoom o sin download_url; "
                    "vuelve a ejecutar más tarde.")
    mp4 = [a for a in listos if a.get("file_type") == "MP4"]
    elegidos: list[dict] = []
    if cfg.zoom.descargar_todas_las_vistas:
        elegidos += mp4
    elif mp4:
        orden = {v: i for i, v in enumerate(cfg.zoom.vistas_preferidas)}
        elegidos.append(min(mp4, key=lambda a: orden.get(a.get("recording_type", ""), 99)))
    else:
        elegidos += [a for a in listos if a.get("file_type") == "M4A"][:1]
    if cfg.zoom.descargar_transcripcion:
        elegidos += [a for a in listos if a.get("file_type") in ("TRANSCRIPT", "CC")]
    if cfg.zoom.descargar_chat:
        elegidos += [a for a in listos if a.get("file_type") == "CHAT"]
    return elegidos


def descargar(cfg: Config, meeting_id: str, dir_clase: Path, base: str) -> list[Path]:
    api = ZoomAPI()
    datos = api.grabacion(meeting_id)
    log.info(f"Zoom API: '{datos.get('topic', '')}' ({datos.get('start_time', '')}), "
             f"{len(datos.get('recording_files', []))} archivo(s)")
    salidas: list[Path] = []
    for a in elegir_archivos(cfg, datos.get("recording_files", [])):
        tipo = a["file_type"]
        ext = (a.get("file_extension") or EXT.get(tipo, "bin")).lower()
        if tipo == "MP4":
            sufijo = f"-{a.get('recording_type', '')}" if cfg.zoom.descargar_todas_las_vistas else ""
            destino = dir_clase / "video" / f"{base}{sufijo}.{ext}"
        elif tipo == "M4A":
            destino = dir_clase / "audio" / f"{base}.{ext}"
        elif tipo == "CHAT":
            destino = dir_clase / "zoom" / f"{base}.chat.{ext}"
        else:
            destino = dir_clase / "zoom" / f"{base}.{tipo.lower()}.{ext}"
        salidas.append(api.bajar_archivo(a["download_url"], destino, a.get("file_size")))
    return salidas
