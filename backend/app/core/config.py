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
    google_maps_api_key: str = ""         # optional: Google Places for business competitors
    tile_provider: str = "mapbox_static"   # mapbox_static | mapbox | esri

    # Analysis defaults (all overridable per request)
    tile_zoom: int = 18
    audit_box_m: int = 2100          # side of square analysed around the pin
    riparian_buffer_m: float = 30.0  # EMCA (Water Quality) Regs 2006: 6-30 m; 30 m enforced on Nairobi Rivers
    utm_epsg: int = 32737            # UTM 37S, metric CRS for Nairobi

    # Access control and limits (see core/security.py). Empty API_KEY = checks off (local development).
    api_key: str = ""
    staff_key: str = ""
    ask_per_minute: int = 10          # questions per IP / device
    ask_per_day: int = 100
    reports_per_minute: int = 5       # voice reports per IP / device
    reports_per_day: int = 50
    google_calls_per_day: int = 300   # Google Places calls for the whole server (Enterprise SKU: 1,000 free/month)
    max_audio_mb: float = 10
    max_photo_mb: float = 5

    data_dir: Path = ROOT / "data"
    cache_dir: Path = ROOT / "data" / "cache"
    db_path: Path = ROOT / "data" / "terrasat.db"


settings = Settings()
