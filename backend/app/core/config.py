"""Central settings, loaded from .env."""
from pathlib import Path

import truststore
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]

# Use the operating system's certificate store for HTTPS. Without this, Python
# rejects connections when antivirus or a network proxy inspects HTTPS traffic
# ("self-signed certificate in certificate chain").
truststore.inject_into_ssl()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    meta_api_key: str = ""
    meta_api_base_url: str = ""
    mapbox_token: str = ""
    tile_provider: str = "mapbox_static"   # mapbox_static | mapbox | esri

    # Analysis defaults (all overridable per request)
    tile_zoom: int = 18
    audit_box_m: int = 2100          # side of square analysed around the pin
    riparian_buffer_m: float = 30.0  # configurable; verify legal source (6-30 m range)
    utm_epsg: int = 32737            # UTM 37S, metric CRS for Nairobi

    data_dir: Path = ROOT / "data"
    cache_dir: Path = ROOT / "data" / "cache"


settings = Settings()
