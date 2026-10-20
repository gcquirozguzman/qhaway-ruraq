"""Logs en consola (rich) y en output/logs/."""

from __future__ import annotations

import logging
from datetime import datetime

from rich.console import Console
from rich.logging import RichHandler

from qhaway.config import cargar_config

console = Console()
log = logging.getLogger("qhaway")


def configurar_logs(verbose: bool = False) -> None:
    if log.handlers:
        return
    log.setLevel(logging.DEBUG)

    consola = RichHandler(console=console, show_path=False, markup=False, rich_tracebacks=True)
    consola.setLevel(logging.DEBUG if verbose else logging.INFO)
    log.addHandler(consola)

    cfg = cargar_config()
    cfg.dir_logs.mkdir(parents=True, exist_ok=True)
    archivo = cfg.dir_logs / f"qhaway-{datetime.now():%Y%m%d}.log"
    fh = logging.FileHandler(archivo, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s"))
    log.addHandler(fh)

    # Silenciar librerías ruidosas
    for nombre in ("httpx", "google_genai", "urllib3"):
        logging.getLogger(nombre).setLevel(logging.WARNING)
