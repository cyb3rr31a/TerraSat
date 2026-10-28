import io
import subprocess
import wave

import numpy as np

from backend.app.services.audio import ffmpeg_exe, to_wav


def tone_wav(seconds=1.0, rate=44100):
    t = np.linspace(0, seconds, int(rate * seconds), endpoint=False)
    pcm = (0.3 * np.sin(2 * np.pi * 440 * t) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(np.repeat(pcm, 2).tobytes())
    return buf.getvalue()


def test_phone_m4a_becomes_16k_mono_wav(tmp_path):
    # make an AAC/m4a clip like an Android phone records
    src = tmp_path / "tone.wav"; src.write_bytes(tone_wav())
    m4a = tmp_path / "tone.m4a"
    subprocess.run([ffmpeg_exe(), "-loglevel", "error", "-y", "-i", str(src), "-c:a", "aac", str(m4a)], check=True)
    out = to_wav(m4a.read_bytes(), ".m4a")
    with wave.open(io.BytesIO(out)) as w:
        assert w.getnchannels() == 1 and w.getframerate() == 16000 and w.getsampwidth() == 2
        assert abs(w.getnframes() / 16000 - 1.0) < 0.1


def test_garbage_input_raises():
    import pytest
    with pytest.raises(ValueError):
        to_wav(b"not audio at all", ".m4a")
