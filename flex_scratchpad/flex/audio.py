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


_FFMPEG_CANDIDATES = (
    r"%LOCALAPPDATA%\\Microsoft\\WinGet\\Links\\ffmpeg.exe",
    r"C:\\ffmpeg\\bin\\ffmpeg.exe",
    r"%ProgramFiles%\\ffmpeg\\bin\\ffmpeg.exe",
    r"%LOCALAPPDATA%\\Programs\\ffmpeg\\bin\\ffmpeg.exe",
    "/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg",
)


def find_ffmpeg(configured: str = "") -> str | None:
    """ffmpeg, if there is one: the path from Settings, PATH, then the usual install spots."""
    import os
    for cand in ([configured] if configured else []) + [shutil.which("ffmpeg") or ""] + [os.path.expandvars(c) for c in _FFMPEG_CANDIDATES]:
        if cand and Path(cand).is_file():
            return str(cand)
    return None


def cut_ffmpeg(src: Path, dst: Path, begin_ms: int, end_ms: int, exe: str | None = None) -> Path | None:
    """Slice with ffmpeg. A .flac destination gets lossless FLAC (small, exact, plays in
    WebView2); anything else 16-bit WAV. Seth, 2026-10-13: "I'm thinking FLAC for caching"."""
    exe = exe or find_ffmpeg()
    if not exe:
        return None
    dst.parent.mkdir(parents=True, exist_ok=True)
    flac = dst.suffix.lower() == ".flac"
    tmp = dst.with_name(dst.stem + ".tmp" + (".flac" if flac else ".wav"))
    # -ss before -i seeks the input; the length is then a DURATION (-t), never -to, whose
    # meaning after an input seek differs between ffmpeg versions
    cmd = [exe, "-y", "-v", "error", "-ss", f"{begin_ms / 1000:.3f}", "-t", f"{(end_ms - begin_ms) / 1000:.3f}",
           "-i", str(src), "-vn", "-acodec", "flac" if flac else "pcm_s16le", str(tmp)]
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


def cut_clip(src: str | Path, dst_wav: Path, begin_ms: int, end_ms: int, ffmpeg: str | None = None) -> Path | None:
    """Try the Python-side cutters: ffmpeg → a FLAC slice of any format; else the stdlib → a
    WAV slice of a WAV. None means "let the UI capture it"."""
    src = Path(src)
    if not src.is_file() or end_ms <= begin_ms:
        return None
    exe = ffmpeg or find_ffmpeg()
    if exe:
        out = cut_ffmpeg(src, dst_wav.with_suffix(".flac"), begin_ms, end_ms, exe)
        if out:
            return out
    if src.suffix.lower() == ".wav":
        try:
            return cut_wav(src, dst_wav.with_suffix(".wav"), begin_ms, end_ms)
        except (wave.Error, EOFError, OSError):
            pass  # a WAV the stdlib cannot read (e.g. WAVE_FORMAT_EXTENSIBLE float)
    return None


def store_clip_bytes(dst: Path, data_base64: str) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    raw = base64.b64decode(data_base64.split(",", 1)[-1])
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    with open(tmp, "wb") as f:
        f.write(raw)
    tmp.replace(dst)
    return dst
