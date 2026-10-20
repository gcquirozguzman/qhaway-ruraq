"""Registro de tokens y costo estimado en output/costos.csv."""

from __future__ import annotations

import csv
from datetime import datetime

from qhaway.config import Config

COLUMNAS = [
    "fecha", "curso", "clase", "archivo", "tipo", "modelo", "procesamiento", "resolucion",
    "tokens_input", "tokens_tool_use", "tokens_cached", "tokens_output", "tokens_thought",
    "tokens_total", "costo_input_usd", "costo_output_usd", "costo_total_usd",
    "segundos", "interaction_id",
]


def calcular(cfg: Config, uso: dict) -> dict:
    """Estimación: input + tool_use se cobran como entrada; output + thought como salida.

    En modo agentic, los frames/audio que el modelo carga bajo demanda se reportan como
    total_tool_use_tokens. No se aplica descuento por caché (estimación conservadora).
    """
    entrada = uso.get("total_input_tokens", 0) + uso.get("total_tool_use_tokens", 0)
    salida = uso.get("total_output_tokens", 0) + uso.get("total_thought_tokens", 0)
    c_in = entrada / 1e6 * cfg.precios.input_por_millon
    c_out = salida / 1e6 * cfg.precios.output_por_millon
    return {"costo_input_usd": round(c_in, 6), "costo_output_usd": round(c_out, 6),
            "costo_total_usd": round(c_in + c_out, 6)}


def registrar(cfg: Config, *, curso: str, clase: str, archivo: str, tipo: str,
              uso: dict, segundos: float, interaction_id: str) -> dict:
    costos = calcular(cfg, uso)
    fila = {
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "curso": curso, "clase": clase, "archivo": archivo, "tipo": tipo,
        "modelo": cfg.gemini.modelo,
        "procesamiento": cfg.gemini.procesamiento_video if tipo == "video" else "",
        "resolucion": cfg.gemini.resolucion_video if tipo == "video" else "",
        "tokens_input": uso.get("total_input_tokens", 0),
        "tokens_tool_use": uso.get("total_tool_use_tokens", 0),
        "tokens_cached": uso.get("total_cached_tokens", 0),
        "tokens_output": uso.get("total_output_tokens", 0),
        "tokens_thought": uso.get("total_thought_tokens", 0),
        "tokens_total": uso.get("total_tokens", 0),
        **costos,
        "segundos": round(segundos, 1),
        "interaction_id": interaction_id,
    }
    ruta = cfg.archivo_costos
    ruta.parent.mkdir(parents=True, exist_ok=True)
    nuevo = not ruta.exists()
    # utf-8-sig para que Excel en Windows muestre bien los acentos
    with ruta.open("a", newline="", encoding="utf-8-sig" if nuevo else "utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS)
        if nuevo:
            w.writeheader()
        w.writerow(fila)
    return fila


def total(cfg: Config) -> tuple[float, int]:
    """(costo total USD, número de llamadas) según output/costos.csv."""
    ruta = cfg.archivo_costos
    if not ruta.exists():
        return 0.0, 0
    with ruta.open(encoding="utf-8-sig") as f:
        filas = list(csv.DictReader(f))
    return sum(float(r.get("costo_total_usd") or 0) for r in filas), len(filas)
