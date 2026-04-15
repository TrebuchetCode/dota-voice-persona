"""Stateless helpers used across UI modules."""
from __future__ import annotations

import struct
import subprocess
import sys
import wave
from pathlib import Path

try:
    import soundfile as _sf  # libsndfile — handles every WAV variant
except Exception:
    _sf = None


def _wav_duration_from_header(path: Path) -> int:
    """Manual RIFF/WAVE parser. Works for any WAV regardless of format code
    (PCM, float, extensible, etc.) because we compute duration from
    byte_rate × data_chunk_size, not from sample interpretation."""
    try:
        with open(path, "rb") as f:
            riff = f.read(12)
            if len(riff) < 12 or riff[:4] != b"RIFF" or riff[8:12] != b"WAVE":
                return 0
            byte_rate = None
            data_size = None
            while True:
                header = f.read(8)
                if len(header) < 8:
                    break
                chunk_id, chunk_size = struct.unpack("<4sI", header)
                if chunk_id == b"fmt " and chunk_size >= 16:
                    fmt = f.read(chunk_size)
                    # fmt layout: format_code, channels, sample_rate,
                    #             byte_rate, block_align, bits_per_sample, ...
                    byte_rate = struct.unpack("<I", fmt[8:12])[0]
                elif chunk_id == b"data":
                    data_size = chunk_size
                    break
                else:
                    f.seek(chunk_size, 1)  # skip unrecognised chunk
            if byte_rate and data_size and byte_rate > 0:
                return int(data_size / byte_rate * 1000)
    except Exception:
        pass
    return 0


def fmt_time(ms: int) -> str:
    """Format milliseconds as `M:SS`."""
    s = max(0, int(ms)) // 1000
    return f"{s // 60}:{s % 60:02d}"


def to_ms(x) -> int:
    """Coerce a flet_audio position/duration into int milliseconds.

    flet_audio's event payloads are an int in some versions and a `TimeDelta`
    in others — normalise here so callers don't care.
    """
    if x is None:
        return 0
    if hasattr(x, "milliseconds"):
        return int(x.milliseconds)
    try:
        return int(x)
    except (TypeError, ValueError):
        return 0


def wav_duration_ms(path: Path) -> int:
    """Return a WAV file's duration in ms. 0 on failure.

    flet_audio reports duration unreliably for HTTP-streamed sources, so we
    compute it locally from the file on disk as ground truth.

    Tries three strategies in order of robustness:
        1. Manual WAV header parse — format-agnostic, handles any WAV.
        2. soundfile (libsndfile)  — handles pretty much everything.
        3. stdlib `wave`            — PCM only; last resort.
    """
    ms = _wav_duration_from_header(path)
    if ms > 0:
        return ms
    if _sf is not None:
        try:
            info = _sf.info(str(path))
            if info.samplerate > 0:
                return int(info.frames / info.samplerate * 1000)
        except Exception:
            pass
    try:
        with wave.open(str(path), "rb") as wf:
            rate = wf.getframerate()
            if rate > 0:
                return int(wf.getnframes() / rate * 1000)
    except Exception:
        pass
    return 0


def reveal_in_finder(path: Path) -> None:
    """Open the given file's enclosing folder in the native file browser."""
    if not path.exists():
        return
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
    elif sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path.parent)])
