"""Convert any phone recording (m4a/aac, 3gp, mp3, ogg/opus, webm, wav…) into
the 16 kHz mono WAV that muse-voice-transcribe-1.0 requires.

Uses the ffmpeg binary bundled by the `imageio-ffmpeg` package, so nothing has
to be installed system-wide (works on Windows, macOS and Linux).
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

MAX_SECONDS = 600  # API limit: 10 minutes


def ffmpeg_exe() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def to_wav(data: bytes, suffix: str = "", sample_rate: int = 16000) -> bytes:
    """Return WAV bytes (PCM s16le, mono, `sample_rate` Hz) for any audio input."""
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / f"in{suffix or '.bin'}"
        dst = Path(td) / "out.wav"  # a real file, so ffmpeg writes correct WAV sizes
        src.write_bytes(data)
        cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
               "-t", str(MAX_SECONDS), "-ac", "1", "-ar", str(sample_rate),
               "-c:a", "pcm_s16le", str(dst)]
        r = subprocess.run(cmd, capture_output=True)
        if r.returncode != 0 or not dst.exists() or dst.stat().st_size < 100:
            raise ValueError(f"Could not read audio: {r.stderr.decode(errors='ignore')[:300]}")
        return dst.read_bytes()


def file_to_wav(path: str | Path) -> bytes:
    p = Path(path)
    return to_wav(p.read_bytes(), p.suffix.lower())
