"""Check that each Meta model works with your key. Run from the project root:

    python scripts/smoke_test_meta.py sam            # 1 SAM call on a Mathare window (~$0.0025)
    python scripts/smoke_test_meta.py spark          # 1 Muse Spark call with web search
    python scripts/smoke_test_meta.py voice --wav path/to/clip.wav
    python scripts/smoke_test_meta.py all --wav path/to/clip.wav

SAM needs MAPBOX_TOKEN too (or pass --image some_aerial.jpg).
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402
from PIL import Image  # noqa: E402

from backend.app.core.config import settings  # noqa: E402

BASE = (settings.meta_api_base_url or "https://api.meta.ai/v1").rstrip("/")
HEADERS = {"Authorization": f"Bearer {settings.meta_api_key}"}
OUT = ROOT / "data" / "outputs" / "smoke"


def check_key():
    if not settings.meta_api_key:
        sys.exit("META_API_KEY missing - copy .env.example to .env and fill it in.")


def test_sam(image_path, prompt):
    from backend.app.services.sam_service import MetaSAMBackend, parse_sam_output
    if image_path:
        img = Image.open(image_path).convert("RGB")
    else:
        from backend.app.services.tiles import build_mosaic
        m = build_mosaic(36.8580, -1.2615, side_m=650, zoom=18)  # Mathare, ~1 window
        img = m.image.crop((0, 0, min(1024, m.image.width), min(1024, m.image.height)))
    OUT.mkdir(parents=True, exist_ok=True)
    img.save(OUT / "sam_input.jpg")
    be = MetaSAMBackend()
    t = time.time()
    raw = be.call(img, prompt)
    dt = time.time() - t
    (OUT / "sam_raw_output.txt").write_text(raw)
    masks = parse_sam_output(raw, prompt)
    print(f"[SAM] prompt={prompt!r} image={img.size} time={dt:.1f}s instances={len(masks)}")
    print(f"[SAM] raw output starts: {raw[:200]!r}")
    from PIL import ImageDraw
    over = img.convert("RGBA")
    layer = Image.new("RGBA", over.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for mk in masks:
        d.polygon(mk.polygon, fill=(0, 229, 255, 110), outline=(0, 229, 255, 255))
    Image.alpha_composite(over, layer).convert("RGB").save(OUT / "sam_overlay.jpg")
    print(f"[SAM] saved {OUT / 'sam_overlay.jpg'} and the raw text for inspection")


def test_spark():
    body = {
        "model": "muse-spark-1.3",
        "input": "What is the Kenya Meteorological Department's latest forecast for the "
                 "October-December 2026 short rains in Nairobi? Two sentences, cite sources.",
        "tools": [{"type": "web_search", "user_location": {"type": "approximate", "country": "KE",
                                                            "city": "Nairobi"}}],
    }
    t = time.time()
    r = httpx.post(f"{BASE}/responses", json=body, headers=HEADERS, timeout=120)
    print(f"[Spark] HTTP {r.status_code} in {time.time() - t:.1f}s")
    r.raise_for_status()
    data = r.json()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "spark_response.json").write_text(json.dumps(data, indent=2))
    searches, text, cites = 0, [], []
    for item in data.get("output", []):
        if item.get("type") == "web_search_call":
            searches += 1
        if item.get("type") == "message":
            for c in item.get("content", []):
                if c.get("type") == "output_text":
                    text.append(c.get("text", ""))
                    cites += [a.get("url") for a in c.get("annotations", []) if a.get("type") == "url_citation"]
    print(f"[Spark] web searches: {searches}")
    print("[Spark] answer:", " ".join(text)[:800])
    print("[Spark] citations:", cites[:5])
    print("[Spark] usage:", data.get("usage"))


def test_voice(wav):
    if not wav:
        print("[Voice] skipped - pass --wav path/to/clip.wav (WAV only)")
        return
    req = {"model": "muse-voice-transcribe-1.0", "audioEncoding": "WAV", "mode": "PUSH_TO_TALK"}
    with open(wav, "rb") as f:
        files = {"request": (None, json.dumps(req), "application/json"),
                 "audio": (Path(wav).name, f, "audio/wav")}
        t = time.time()
        r = httpx.post(f"{BASE}/asr/transcribe", files=files,
                       headers={**HEADERS, "Accept": "application/json"}, timeout=180)
    print(f"[Voice] HTTP {r.status_code} in {time.time() - t:.1f}s")
    print("[Voice] response:", r.text[:1000])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("which", choices=["sam", "spark", "voice", "all"])
    ap.add_argument("--image")
    ap.add_argument("--prompt", default="rooftop")
    ap.add_argument("--wav")
    a = ap.parse_args()
    check_key()
    if a.which in ("sam", "all"):
        test_sam(a.image, a.prompt)
    if a.which in ("spark", "all"):
        test_spark()
    if a.which in ("voice", "all"):
        test_voice(a.wav)


if __name__ == "__main__":
    main()
