"""Cutting a timed segment out of a media file into the notebook's cache.

Order of preference:
  1. WAV → the stdlib `wave` module: an exact sample slice, no dependencies.
  2. anything else → `ffmpeg` if it is on PATH (decoded to WAV).
  3. otherwise the UI captures the range itself while it plays once (MediaRecorder → webm/opus)
     and hands the bytes back through `store_clip_bytes`.
"""
from __future__ import annotations

import base64
import shutil
import subprocess
import wave
from pathlib import Path


def cut_wav(src: Path, dst: Path, begin_ms: int, end_ms: int) -> Path:
    with wave.open(str(src), "rb") as r:
        rate = r.getframerate()
        nch, width = r.getnchannels(), r.getsampwidth()
        total = r.getnframes()
        a = max(0, min(total, int(round(begin_ms / 1000 * rate))))
        b = max(a, min(total, int(round(end_ms / 1000 * rate))))
        r.setpos(a)
        frames = r.readframes(b - a)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(nch)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(frames)
    tmp.replace(dst)
    return dst


def cut_ffmpeg(src: Path, dst: Path, begin_ms: int, end_ms: int) -> Path | None:
    exe = shutil.which("ffmpeg")
    if not exe:
        return None
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(".tmp.wav")
    cmd = [exe, "-y", "-v", "error", "-ss", f"{begin_ms / 1000:.3f}", "-to", f"{end_ms / 1000:.3f}",
           "-i", str(src), "-vn", "-acodec", "pcm_s16le", str(tmp)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=120)
    except (subprocess.SubprocessError, OSError):
        try:
            tmp.unlink()
        except OSError:
            pass
        return None
    tmp.replace(dst)
    return dst


def cut_clip(src: str | Path, dst_wav: Path, begin_ms: int, end_ms: int) -> Path | None:
    """Try the two Python-side cutters. None means "let the UI capture it"."""
    src = Path(src)
    if not src.is_file() or end_ms <= begin_ms:
        return None
    if src.suffix.lower() == ".wav":
        try:
            return cut_wav(src, dst_wav, begin_ms, end_ms)
        except (wave.Error, EOFError, OSError):
            pass  # a WAV the stdlib cannot read (e.g. WAVE_FORMAT_EXTENSIBLE float) → ffmpeg
    return cut_ffmpeg(src, dst_wav, begin_ms, end_ms)


def store_clip_bytes(dst: Path, data_base64: str) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    raw = base64.b64decode(data_base64.split(",", 1)[-1])
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    with open(tmp, "wb") as f:
        f.write(raw)
    tmp.replace(dst)
    return dst
