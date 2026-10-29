"""Live checks against the real services (needs keys in .env). Each SAM call
costs $0.0025 and is cached, so repeating a check is free.

    python scripts/check.py mapbox                       # token + one satellite image
    python scripts/check.py sam                          # 1 SAM call on Mathare
    python scripts/check.py spark                        # 1 Muse Spark call with web search
    python scripts/check.py voice --audio data/voice/english.m4a
    python scripts/check.py prompts --classes building,garbage [--zoom 19]

Results go to data/outputs/checks/.
"""
import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageStat  # noqa: E402

from backend.app.core.config import settings  # noqa: E402
from backend.app.services import geo  # noqa: E402
from backend.app.services.audit import PRESETS  # noqa: E402
from backend.app.services.sam_service import MetaSAMBackend, parse_sam_output  # noqa: E402
from backend.app.services.tiles import build_mosaic  # noqa: E402

BASE = (settings.meta_api_base_url or "https://api.meta.ai/v1").rstrip("/")
HEADERS = {"Authorization": f"Bearer {settings.meta_api_key}"}
OUT = ROOT / "data" / "outputs" / "checks"

# Prompt candidates, with results of the Oct 28 tests on Mathare in comments
CANDIDATES = {
    "building": ["building", "house", "roof", "rooftop", "shack"],  # "building" best; none finds informal roofs
    "garbage": ["garbage", "rubbish", "garbage pile", "dump site"],  # nothing found from above
    "solar_panel": ["solar panel", "photovoltaic panel"],
    "water_tank": ["water tank", "plastic water tank"],
}


def draw_masks(img, masks, color=(0, 229, 255)):
    over = img.convert("RGBA")
    layer = Image.new("RGBA", over.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for m in masks:
        d.polygon(m.polygon, fill=color + (110,), outline=color + (255,))
    return Image.alpha_composite(over, layer).convert("RGB")


def check_mapbox():
    tok = settings.mapbox_token
    if not tok:
        sys.exit("MAPBOX_TOKEN missing in .env")
    with httpx.Client(timeout=30) as c:
        r = c.get("https://api.mapbox.com/tokens/v2", params={"access_token": tok})
        print(f"Token check: HTTP {r.status_code} {r.text[:150]}")
        r = c.get("https://api.mapbox.com/styles/v1/mapbox/satellite-v9/static/36.858,-1.2615,16/300x300",
                  params={"access_token": tok})
        print(f"Static Images API (used by TerraSat): HTTP {r.status_code}")


def check_sam(prompt="building"):
    m = build_mosaic(*PRESETS["mathare"], side_m=650, zoom=18)
    img = m.image.crop((0, 0, min(1024, m.image.width), min(1024, m.image.height)))
    t = time.time()
    raw = MetaSAMBackend().call(img, prompt)
    masks = parse_sam_output(raw, prompt)
    OUT.mkdir(parents=True, exist_ok=True)
    draw_masks(img, masks).save(OUT / "sam.jpg")
    print(f"SAM: {len(masks)} x '{prompt}' in {time.time() - t:.1f}s -> data/outputs/checks/sam.jpg")


def check_spark():
    body = {"model": "muse-spark-1.3",
            "input": "What is the Kenya Meteorological Department's latest forecast for the "
                     "October-December 2026 short rains in Nairobi? Two sentences, cite sources.",
            "tools": [{"type": "web_search", "user_location": {"type": "approximate", "country": "KE", "city": "Nairobi"}}]}
    r = httpx.post(f"{BASE}/responses", json=body, headers=HEADERS, timeout=120)
    r.raise_for_status()
    data = r.json()
    texts = [c for i in data.get("output", []) if i.get("type") == "message" for c in i.get("content", [])
             if c.get("type") == "output_text"]
    cites = [a["url"] for c in texts for a in c.get("annotations", []) if a.get("type") == "url_citation"]
    searches = sum(i.get("type") == "web_search_call" for i in data.get("output", []))
    print(f"Spark: {searches} web searches, {len(cites)} citations\n{' '.join(c['text'] for c in texts)[:600]}")


def check_voice(audio):
    """Any recording works (m4a, mp3, wav...): it's converted to 16 kHz mono WAV first."""
    from backend.app.services.audio import file_to_wav
    req = {"model": "muse-voice-transcribe-1.0", "audioEncoding": "WAV", "mode": "PUSH_TO_TALK"}
    files = {"request": (None, json.dumps(req), "application/json"),
             "audio": ("clip.wav", file_to_wav(audio), "audio/wav")}
    r = httpx.post(f"{BASE}/asr/transcribe", files=files,
                   headers={**HEADERS, "Accept": "application/json"}, timeout=180)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"voice_{Path(audio).stem}.txt").write_text(f"HTTP {r.status_code}\n{r.text}", encoding="utf-8")
    print(f"Voice ({Path(audio).name}): HTTP {r.status_code}\n{r.text[:1000]}")


def check_prompts(classes, site="mathare", zoom=18, n_windows=3):
    """Run each candidate prompt on a few windows; save one contact sheet per class."""
    lon, lat = PRESETS[site]
    m = build_mosaic(lon, lat, 2100, zoom)
    wins = list(m.windows())
    edges = lambda w: ImageStat.Stat(w[2].convert("L").resize((256, 256)).filter(ImageFilter.FIND_EDGES)).mean[0]
    wins = sorted(wins, key=edges, reverse=True)[:n_windows]  # the busiest windows
    backend = MetaSAMBackend()
    jobs = [(c, p, i) for c in classes for p in CANDIDATES[c] for i in range(len(wins))]
    with ThreadPoolExecutor(max_workers=8) as ex:
        found = dict(zip(jobs, ex.map(lambda j: parse_sam_output(backend.call(wins[j[2]][2], j[1]), j[1]), jobs)))
    OUT.mkdir(parents=True, exist_ok=True)
    cell = 380
    try:
        font = ImageFont.load_default(size=16)
    except TypeError:
        font = ImageFont.load_default()
    for c in classes:
        sheet = Image.new("RGB", (180 + cell * len(wins), cell * len(CANDIDATES[c])), (20, 28, 33))
        d = ImageDraw.Draw(sheet)
        for row, p in enumerate(CANDIDATES[c]):
            counts = [len(found[(c, p, i)]) for i in range(len(wins))]
            d.text((10, row * cell + 10), f"{p}\ntotal {sum(counts)}", fill=(255, 255, 255), font=font)
            for i, (_, _, crop) in enumerate(wins):
                sheet.paste(draw_masks(crop, found[(c, p, i)]).resize((cell - 6, cell - 6)), (180 + i * cell + 3, row * cell + 3))
            print(f"{c:12} {p:20} per window {counts}")
        sheet.save(OUT / f"prompts_{c}_z{zoom}.jpg", quality=88)
    print(f"{len(jobs)} SAM calls (~${len(jobs) * 0.0025:.2f}). Sheets in data/outputs/checks/")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("check", choices=["mapbox", "sam", "spark", "voice", "prompts"])
    ap.add_argument("--audio", help="voice note for the voice check (m4a, mp3, wav...)")
    ap.add_argument("--prompt", default="building")
    ap.add_argument("--classes", default="building")
    ap.add_argument("--site", choices=PRESETS, default="mathare")
    ap.add_argument("--zoom", type=int, default=18, help="18 = ~0.6 m/px, 19 = ~0.3 m/px")
    a = ap.parse_args()
    if a.check != "mapbox" and not settings.meta_api_key:
        sys.exit("META_API_KEY missing in .env")
    if a.check == "mapbox":
        check_mapbox()
    elif a.check == "sam":
        check_sam(a.prompt)
    elif a.check == "spark":
        check_spark()
    elif a.check == "voice":
        if not a.audio:
            sys.exit("Pass the recording: --audio data/voice/english.m4a")
        check_voice(a.audio)
    else:
        classes = [c.strip() for c in a.classes.split(",")]
        bad = [c for c in classes if c not in CANDIDATES]
        if bad:
            sys.exit(f"Unknown class {bad}; choose from {list(CANDIDATES)}")
        check_prompts(classes, a.site, a.zoom)


if __name__ == "__main__":
    main()
