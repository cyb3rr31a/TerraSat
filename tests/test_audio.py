import io
import subprocess
import wave

import numpy as np
import pytest

from backend.app.services.audio import ffmpeg_exe, to_wav


def test_phone_m4a_becomes_16k_mono_wav(tmp_path):
    rate = 44100
    t = np.linspace(0, 1.0, rate, endpoint=False)
    pcm = (0.3 * np.sin(2 * np.pi * 440 * t) * 32767).astype("<i2")
    src = tmp_path / "tone.wav"
    with wave.open(str(src), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(pcm.tobytes())
    m4a = tmp_path / "tone.m4a"  # like an Android voice note
    subprocess.run([ffmpeg_exe(), "-loglevel", "error", "-y", "-i", str(src), "-c:a", "aac", str(m4a)], check=True)
    with wave.open(io.BytesIO(to_wav(m4a.read_bytes(), ".m4a"))) as w:
        assert (w.getnchannels(), w.getframerate(), w.getsampwidth()) == (1, 16000, 2)
        assert abs(w.getnframes() / 16000 - 1.0) < 0.1


def test_garbage_input_raises():
    with pytest.raises(ValueError):
        to_wav(b"not audio at all", ".m4a")
