"""TerraSat API on Modal: one always-on container serving FastAPI, with the map data on a Volume.

    modal deploy modal_app.py

One-time setup (README, "Public demo"): create the `terrasat` secret from .env and upload data/ to the
`terrasat-data` volume. One container on purpose: SQLite and the in-memory rate limits assume a single process.
"""
import modal

data = modal.Volume.from_name("terrasat-data", create_if_missing=True)
image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install_from_requirements("requirements.txt")
    .add_local_dir("backend", "/app/backend", ignore=["**/__pycache__"])
)
app = modal.App("terrasat", image=image)


@app.function(volumes={"/app/data": data}, secrets=[modal.Secret.from_name("terrasat")],
              cpu=2, memory=4096, timeout=600, min_containers=1, max_containers=1)
@modal.concurrent(max_inputs=20)
@modal.asgi_app()
def api():
    import sys
    sys.path.insert(0, "/app")
    from backend.app.main import app as fastapi_app
    return fastapi_app
