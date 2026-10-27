"""TerraSat API. All business logic lives in app/services and the audit
profiles in app/profiles, so the Streamlit debug UI and the React demo UI call
the same endpoints."""
from fastapi import FastAPI

from backend.app.core.config import settings
from backend.app.profiles.loader import list_profiles

app = FastAPI(title="TerraSat", version="0.1.0",
              description="Geospatial auditing engine: satellite imagery + SAM 3.1 + "
                          "spatial rules + grounded Muse Spark memos, configured by audit profiles.")


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "meta_key_set": bool(settings.meta_api_key),
        "mapbox_token_set": bool(settings.mapbox_token),
    }


@app.get("/profiles")
def profiles() -> list[dict]:
    """Available audit profiles (use cases) and what each one looks for."""
    return [{"id": p.id, "name": p.name, "tagline": p.tagline, "status": p.status,
             "audience": p.audience, "classes": {k: v.prompts for k, v in p.classes.items()},
             "layers": p.layers} for p in list_profiles()]
