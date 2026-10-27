"""Central settings, loaded from .env."""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    meta_api_key: str = ""
    meta_api_base_url: str = ""
    mapbox_token: str = ""
    africastalking_username: str = "sandbox"
    africastalking_api_key: str = ""

    # Analysis defaults (all overridable per request)
    tile_zoom: int = 18
    tile_size_px: int = 1024
    audit_box_m: int = 2100          # side of square analysed around the pin
    tile_overlap: float = 0.10
    riparian_buffer_m: float = 30.0  # configurable; verify legal source (6-30 m range)
    utm_epsg: int = 32737            # UTM 37S, metric CRS for Nairobi

    data_dir: Path = ROOT / "data"
    cache_dir: Path = ROOT / "data" / "cache"


settings = Settings()
