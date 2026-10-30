"""Meta Model API calls other than SAM (which lives in sam_service.py):
speech-to-text and Muse Spark (optionally grounded with web search)."""
from __future__ import annotations

import json
import re

import httpx

from backend.app.core.config import settings


def _base() -> str:
    return (settings.meta_api_base_url or "https://api.meta.ai/v1").rstrip("/")


def _headers() -> dict:
    if not settings.meta_api_key:
        raise RuntimeError("META_API_KEY is not set (see .env.example)")
    return {"Authorization": f"Bearer {settings.meta_api_key}"}


def transcribe(wav: bytes) -> str:
    """Transcribe 16 kHz mono WAV (see audio.to_wav) with muse-voice-transcribe-1.0."""
    req = {"model": "muse-voice-transcribe-1.0", "audioEncoding": "WAV", "mode": "PUSH_TO_TALK"}
    files = {"request": (None, json.dumps(req), "application/json"),
             "audio": ("clip.wav", wav, "audio/wav")}
    r = httpx.post(f"{_base()}/asr/transcribe", files=files,
                   headers={**_headers(), "Accept": "application/json"}, timeout=180)
    r.raise_for_status()
    return r.json().get("transcript", "").strip()


def spark(prompt: str, web_search: bool = False, model: str = "muse-spark-1.3") -> dict:
    """One Muse Spark call (Standard mode: our data isn't used for training).
    Returns the answer text, URL citations and how many web searches ran."""
    body = {"model": model, "input": prompt}
    if web_search:
        body["tools"] = [{"type": "web_search",
                          "user_location": {"type": "approximate", "country": "KE", "city": "Nairobi"}}]
    r = httpx.post(f"{_base()}/responses", json=body, headers=_headers(), timeout=180)
    r.raise_for_status()
    out = r.json().get("output", [])
    parts = [c for item in out if item.get("type") == "message" for c in item.get("content", [])
             if c.get("type") == "output_text"]
    return {
        "text": "".join(p.get("text", "") for p in parts).strip(),
        "citations": [{"url": a.get("url"), "title": a.get("title")} for p in parts
                      for a in p.get("annotations", []) if a.get("type") == "url_citation"],
        "web_searches": sum(item.get("type") == "web_search_call" for item in out),
    }


JSON_ONLY = "\n\nReply with only a JSON object."


def parse_json(text: str) -> dict:
    """The JSON object in a Muse Spark answer (tolerates text or code fences around it)."""
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError(f"Muse Spark did not return JSON: {text[:200]}")
    return json.loads(match.group(0))


def spark_json(prompt: str, **kw) -> dict:
    """Ask Muse Spark for a JSON object and parse it."""
    return parse_json(spark(prompt + JSON_ONLY, **kw)["text"])
