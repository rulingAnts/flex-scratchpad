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


def _decode_to_wav(src: Path, dst: Path, exe: str, rate: int | None = None, channels: int | None = None) -> Path | None:
    cmd = [exe, "-y", "-v", "error", "-i", str(src), "-vn", "-acodec", "pcm_s16le"]
    if rate:
        cmd += ["-ar", str(rate)]
    if channels:
        cmd += ["-ac", str(channels)]
    cmd.append(str(dst))
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=300)
        return dst
    except (subprocess.SubprocessError, OSError):
        return None


def concat_clips(clips: list[Path], dst: Path, gap_ms: int = 600, ffmpeg: str | None = None) -> list[tuple[int, int]]:
    """One WAV out of several clips in order, `gap_ms` of silence between them (Seth,
    2026-10-16: the examples' audio, matched in the flextext export). Returns each clip's
    (begin, end) in milliseconds within `dst`. Non-WAV clips (the FLAC cache) and WAVs whose
    sample format differs from the first one are decoded with ffmpeg; without ffmpeg every
    clip must be a WAV with the same rate / channels / width, else ValueError."""
    import tempfile
    exe = ffmpeg or find_ffmpeg()
    dst.parent.mkdir(parents=True, exist_ok=True)
    spans: list[tuple[int, int]] = []
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        params = None            # (channels, width, rate) of the output
        readers = []
        for i, c in enumerate(clips):
            c = Path(c)
            wav = c
            if c.suffix.lower() != ".wav":
                if not exe:
                    raise ValueError(f"{c.name} is not a WAV and ffmpeg was not found")
                wav = _decode_to_wav(c, tmpdir / f"clip{i}.wav", exe, params[2] if params else None, params[0] if params else None)
                if not wav:
                    raise ValueError(f"ffmpeg could not decode {c.name}")
            with wave.open(str(wav), "rb") as r:
                these = (r.getnchannels(), r.getsampwidth(), r.getframerate())
            if params is None:
                params = these
            elif these != params:
                if not exe:
                    raise ValueError(f"{c.name} has a different sample format and ffmpeg was not found")
                wav = _decode_to_wav(c, tmpdir / f"clip{i}.wav", exe, params[2], params[0])
                if not wav:
                    raise ValueError(f"ffmpeg could not convert {c.name}")
                with wave.open(str(wav), "rb") as r:
                    these = (r.getnchannels(), r.getsampwidth(), r.getframerate())
                if these[2] != params[2] or these[0] != params[0]:
                    raise ValueError(f"{c.name} could not be matched to the first clip's format")
                params = (params[0], these[1], params[2]) if these[1] != params[1] and i == 0 else params
            readers.append(wav)
        if params is None:
            raise ValueError("no clips")
        nch, width, rate = params
        gap = b"\x00" * int(round(gap_ms / 1000 * rate)) * nch * width
        tmp = dst.with_suffix(dst.suffix + ".tmp")
        pos = 0
        with wave.open(str(tmp), "wb") as w:
            w.setnchannels(nch)
            w.setsampwidth(width)
            w.setframerate(rate)
            for i, wav in enumerate(readers):
                if i:
                    w.writeframes(gap)
                    pos += len(gap) // (nch * width)
                with wave.open(str(wav), "rb") as r:
                    n = r.getnframes()
                    begin = pos
                    while n > 0:
                        chunk = r.readframes(min(n, 65536))
                        if not chunk:
                            break
                        w.writeframes(chunk)
                        n -= len(chunk) // (nch * width)
                    pos += r.getnframes()
                spans.append((int(round(begin * 1000 / rate)), int(round(pos * 1000 / rate))))
        tmp.replace(dst)
    return spans


def _wav_to_mono16(src: Path, dst: Path) -> int:
    """A WAV as 16-bit mono (channels averaged, any PCM width), by hand: Python 3.13 has no
    audioop. Returns the length in milliseconds."""
    import array
    with wave.open(str(src), "rb") as r:
        nch, width, rate = r.getnchannels(), r.getsampwidth(), r.getframerate()
        n = r.getnframes()
        raw = r.readframes(n)
    out = array.array("h")
    if width == 2 and nch == 1:
        out.frombytes(raw)
        if __import__("sys").byteorder == "big":
            out.byteswap()
    else:
        frame = nch * width
        for i in range(0, len(raw) - frame + 1, frame):
            acc = 0
            for c in range(nch):
                b = raw[i + c * width:i + (c + 1) * width]
                if width == 1:
                    v = (b[0] - 128) << 8
                else:
                    v = int.from_bytes(b, "little", signed=True) >> (8 * (width - 2))
                acc += v
            v = acc // nch
            out.append(max(-32768, min(32767, v)))
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(out.tobytes())
    tmp.replace(dst)
    return int(round(n * 1000 / rate))


def to_mono16(src: str | Path, dst: Path, ffmpeg: str | None = None) -> int | None:
    """Any clip (the FLAC cache, a WAV) as a small 16-bit mono WAV at `dst` (Seth, 2026-10-16:
    "as long as they use small file size (16-bit wav, mono)"). ffmpeg when there is one, the
    stdlib for WAVs otherwise. Returns the length in ms, or None when it could not be done."""
    src = Path(src)
    exe = ffmpeg or find_ffmpeg()
    if exe:
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_suffix(".tmp.wav")
        try:
            subprocess.run([exe, "-y", "-v", "error", "-i", str(src), "-vn", "-ac", "1", "-acodec", "pcm_s16le", str(tmp)], check=True, capture_output=True, timeout=300)
            tmp.replace(dst)
            with wave.open(str(dst), "rb") as r:
                return int(round(r.getnframes() * 1000 / r.getframerate()))
        except (subprocess.SubprocessError, OSError, wave.Error):
            try:
                tmp.unlink()
            except OSError:
                pass
    if src.suffix.lower() == ".wav":
        try:
            return _wav_to_mono16(src, dst)
        except (wave.Error, EOFError, OSError):
            return None
    return None
