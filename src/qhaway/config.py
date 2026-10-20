"""Carga de config.yaml y .env."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field


class Rutas(BaseModel):
    input: str = "input"
    output: str = "output"
    bandeja: str = "input/_bandeja"
    zoom_links: str = "zoom_links.yaml"


class GeminiCfg(BaseModel):
    modelo: str = "gemini-3.8-flash"
    procesamiento_video: Literal["agentic", "static"] = "agentic"
    resolucion_video: Literal["unspecified", "low", "medium", "high", "ultra_high"] = "medium"
    intervalo_polling_s: int = 10
    timeout_min: int = 90
    max_reintentos: int = 5
    max_chars_contexto: int = 150_000
    borrar_archivo_remoto: bool = True
    procesar_documentos_sin_media: bool = True


class Precios(BaseModel):
    input_por_millon: float = 0.75
    output_por_millon: float = 3.75


class VideoCfg(BaseModel):
    comprimir: bool = False
    umbral_mb: int = 1500
    ancho_max: int = 1280
    crf: int = 28
    preset: str = "veryfast"
    audio_kbps: int = 64


class ZoomCfg(BaseModel):
    metodo_por_defecto: Literal["auto", "ytdlp", "api"] = "auto"
    formato_ytdlp: str = "bv*+ba/b"
    cookies_navegador: str = ""
    descargar_transcripcion: bool = True
    descargar_chat: bool = True
    vistas_preferidas: list[str] = Field(
        default_factory=lambda: [
            "shared_screen_with_speaker_view",
            "shared_screen_with_gallery_view",
            "shared_screen",
            "active_speaker",
            "gallery_view",
        ]
    )
    descargar_todas_las_vistas: bool = False


class SkillCfg(BaseModel):
    nombre: str = "qhaway-ruraq"
    descripcion: str = "Procedimientos paso a paso extraídos de capacitaciones."
    incluir_referencias: bool = True
    max_kb_por_referencia: int = 300


class Config(BaseModel):
    rutas: Rutas = Field(default_factory=Rutas)
    gemini: GeminiCfg = Field(default_factory=GeminiCfg)
    precios: Precios = Field(default_factory=Precios)
    video: VideoCfg = Field(default_factory=VideoCfg)
    zoom: ZoomCfg = Field(default_factory=ZoomCfg)
    skill: SkillCfg = Field(default_factory=SkillCfg)

    raiz: Path = Path(".")

    # --- rutas absolutas -------------------------------------------------
    @property
    def dir_input(self) -> Path:
        return self.raiz / self.rutas.input

    @property
    def dir_output(self) -> Path:
        return self.raiz / self.rutas.output

    @property
    def dir_bandeja(self) -> Path:
        return self.raiz / self.rutas.bandeja

    @property
    def archivo_zoom_links(self) -> Path:
        return self.raiz / self.rutas.zoom_links

    @property
    def dir_skill(self) -> Path:
        return self.dir_output / "skill"

    @property
    def archivo_registro(self) -> Path:
        return self.dir_output / ".registro.json"

    @property
    def archivo_costos(self) -> Path:
        return self.dir_output / "costos.csv"

    @property
    def dir_logs(self) -> Path:
        return self.dir_output / "logs"


def encontrar_raiz() -> Path:
    """Busca hacia arriba la carpeta que contiene config.yaml."""
    if env := os.environ.get("QHAWAY_ROOT"):
        return Path(env).resolve()
    actual = Path.cwd().resolve()
    for carpeta in (actual, *actual.parents):
        if (carpeta / "config.yaml").is_file():
            return carpeta
    return actual


@lru_cache(maxsize=1)
def cargar_config() -> Config:
    raiz = encontrar_raiz()
    load_dotenv(raiz / ".env")
    archivo = raiz / "config.yaml"
    datos = {}
    if archivo.is_file():
        datos = yaml.safe_load(archivo.read_text(encoding="utf-8")) or {}
    cfg = Config(**datos)
    cfg.raiz = raiz
    return cfg


def env(nombre: str, requerido: bool = False) -> str | None:
    valor = os.environ.get(nombre) or None
    if requerido and not valor:
        raise RuntimeError(
            f"Falta la variable {nombre}. Cópiala en el archivo .env (ver .env.example)."
        )
    return valor
