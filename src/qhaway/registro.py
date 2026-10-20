"""Registro de lo descargado y procesado (output/.registro.json).

Permite que todos los comandos sean idempotentes: un archivo se reprocesa solo si
cambió su contenido (SHA-256) o la "huella" del procesamiento (modelo, prompt,
resolución...), o si se pide --forzar.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from qhaway.config import Config


def sha256(ruta: Path, bloque: int = 4 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        while chunk := f.read(bloque):
            h.update(chunk)
    return h.hexdigest()


def huella(*partes: object) -> str:
    h = hashlib.sha256()
    for p in partes:
        h.update(str(p).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:16]


class Registro:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.ruta = cfg.archivo_registro
        self.datos: dict = {"descargas": {}, "procesados": {}, "hashes": {}}
        if self.ruta.is_file():
            self.datos.update(json.loads(self.ruta.read_text(encoding="utf-8")))

    # --- utilidades ----------------------------------------------------------
    def rel(self, ruta: Path) -> str:
        try:
            return ruta.resolve().relative_to(self.cfg.raiz.resolve()).as_posix()
        except ValueError:
            return ruta.resolve().as_posix()

    def guardar(self) -> None:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.ruta.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(self.datos, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.ruta)

    def hash_archivo(self, ruta: Path) -> str:
        """SHA-256 con caché por (tamaño, mtime) para no releer videos grandes."""
        st = ruta.stat()
        clave = self.rel(ruta)
        cache = self.datos["hashes"].get(clave)
        if cache and cache["size"] == st.st_size and cache["mtime"] == st.st_mtime:
            return cache["sha256"]
        valor = sha256(ruta)
        self.datos["hashes"][clave] = {"size": st.st_size, "mtime": st.st_mtime, "sha256": valor}
        return valor

    # --- procesados ----------------------------------------------------------
    def procesado(self, ruta: Path, huella_proc: str, sha: str | None = None) -> dict | None:
        """Devuelve la entrada si el archivo ya fue procesado igual y sus salidas existen.

        `sha` permite registrar entradas virtuales (ej. el conjunto de documentos de una clase).
        """
        entrada = self.datos["procesados"].get(self.rel(ruta))
        if not entrada:
            return None
        if entrada.get("sha256") != (sha or self.hash_archivo(ruta)) or entrada.get("huella") != huella_proc:
            return None
        if not all((self.cfg.raiz / s).exists() for s in entrada.get("salidas", [])):
            return None
        return entrada

    def marcar_procesado(self, ruta: Path, huella_proc: str, salidas: list[Path],
                         sha: str | None = None, **extra) -> None:
        self.datos["procesados"][self.rel(ruta)] = {
            "sha256": sha or self.hash_archivo(ruta),
            "huella": huella_proc,
            "salidas": [self.rel(s) for s in salidas],
            "fecha": datetime.now().isoformat(timespec="seconds"),
            **extra,
        }
        self.guardar()

    def entrada_procesado(self, ruta: Path) -> dict | None:
        return self.datos["procesados"].get(self.rel(ruta))

    # --- descargas -----------------------------------------------------------
    def descarga(self, clave: str) -> dict | None:
        entrada = self.datos["descargas"].get(clave)
        if not entrada:
            return None
        if not all((self.cfg.raiz / a).exists() for a in entrada.get("archivos", [])):
            return None
        return entrada

    def marcar_descarga(self, clave: str, archivos: list[Path], **extra) -> None:
        self.datos["descargas"][clave] = {
            "archivos": [self.rel(a) for a in archivos],
            "fecha": datetime.now().isoformat(timespec="seconds"),
            **extra,
        }
        self.guardar()
