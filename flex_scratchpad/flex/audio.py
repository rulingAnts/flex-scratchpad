"""Cutting a timed segment out of a media file into the notebook's cache.

Order of preference:
  1. WAV → the stdlib `wave` module: an exact sample slice, no dependencies.
  2. anything else → `ffmpeg`: the one shipped beside the Windows build (`<app>/ffmpeg/ffmpeg.exe`),
     else Settings, PATH and the usual install spots (decoded to WAV).
  3. otherwise the UI captures the range itself while it plays once (MediaRecorder → webm/opus)
     and hands the bytes back through `store_clip_bytes`.
"""
from __future__ import annotations

import base64
import shutil
import subprocess
import sys
import wave
from pathlib import Path


def _run(cmd: list[str], timeout: int) -> None:
    """ffmpeg, quietly: on Windows a windowed app that starts a console program flashes a console
    window for every clip unless it asks for none."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    subprocess.run(cmd, check=True, capture_output=True, timeout=timeout, creationflags=flags)


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


def bundled_ffmpeg() -> Path | None:
    """The ffmpeg shipped with the Windows build, beside the program: `<app>/ffmpeg/ffmpeg.exe`
    (Seth, 2026-10-16: a release ships ffmpeg — field laptops are often offline)."""
    if not getattr(sys, "frozen", False):
        return None
    exe = Path(sys.executable).resolve().parent / "ffmpeg" / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    return exe if exe.is_file() else None


def find_ffmpeg(configured: str = "") -> str | None:
    """ffmpeg, if there is one: the path from Settings, the bundled one, PATH, then the usual
    install spots."""
    import os
    bundled = bundled_ffmpeg()
    for cand in ([configured] if configured else []) + [str(bundled) if bundled else ""] + [shutil.which("ffmpeg") or ""] + [os.path.expandvars(c) for c in _FFMPEG_CANDIDATES]:
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
        _run(cmd, 120)
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


EMBED_MIMES = {".ogg": "audio/ogg", ".opus": "audio/ogg", ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".wav": "audio/wav",
               ".flac": "audio/flac", ".webm": "audio/webm"}


def encode_for_embed(src: str | Path, dst_stem: Path, ffmpeg: str | None = None) -> tuple[Path, str] | None:
    """A clip as the smallest file a web page can carry (Seth, 2026-10-18: "base64 embedded
    audio"): Opus in Ogg at 40 kb/s mono through ffmpeg (an hour is ~18 MB), MP3 when the build
    has no Opus encoder; without ffmpeg the clip itself (a WAV or FLAC slice, which Chromium
    plays too — just bigger). Returns (path, mime) or None when nothing could be made."""
    src = Path(src)
    if not src.is_file():
        return None
    exe = ffmpeg or find_ffmpeg()
    if exe:
        for ext, codec in ((".ogg", ["-c:a", "libopus", "-b:a", "40k", "-ar", "48000", "-application", "voip"]), (".mp3", ["-c:a", "libmp3lame", "-q:a", "6"])):
            dst = dst_stem.with_name(dst_stem.name + ext)      # <clip>.export.ogg: never mistaken for the clip itself (find_audio_clip matches stems)
            if dst.is_file() and dst.stat().st_mtime >= src.stat().st_mtime:
                return dst, EMBED_MIMES[ext]
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_name(dst.stem + ".tmp" + ext)
            try:
                _run([exe, "-y", "-v", "error", "-i", str(src), "-vn", "-ac", "1", *codec, str(tmp)], 300)
                tmp.replace(dst)
                return dst, EMBED_MIMES[ext]
            except (subprocess.SubprocessError, OSError):
                try:
                    tmp.unlink()
                except OSError:
                    pass
    mime = EMBED_MIMES.get(src.suffix.lower())
    return (src, mime) if mime else None


OFFICE_MIMES = {".m4a": "audio/mp4", ".mp3": "audio/mpeg", ".wav": "audio/wav"}


def encode_for_office(src: str | Path, dst_stem: Path, ffmpeg: str | None = None) -> tuple[Path, str] | None:
    """A clip PowerPoint plays (Seth, 2026-10-20: "embedded audio as playable media in the slides next
    to the examples"): PowerPoint does not play Opus or FLAC, so AAC in an .m4a at 64 kb/s mono through
    ffmpeg (ffmpeg's own encoder, in every build), MP3 when that fails, else a 16-bit WAV; without
    ffmpeg only a WAV clip can go in (the stdlib cuts WAV). Kept beside the clip as
    `<clip>.office.m4a` so a second export is instant. Returns (path, mime) or None."""
    src = Path(src)
    if not src.is_file():
        return None
    exe = ffmpeg or find_ffmpeg()
    if exe:
        for ext, codec in ((".m4a", ["-c:a", "aac", "-b:a", "64k"]), (".mp3", ["-c:a", "libmp3lame", "-q:a", "6"]), (".wav", ["-c:a", "pcm_s16le"])):
            dst = dst_stem.with_name(dst_stem.name + ext)
            if dst.is_file() and dst.stat().st_mtime >= src.stat().st_mtime:
                return dst, OFFICE_MIMES[ext]
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_name(dst.stem + ".tmp" + ext)
            try:
                _run([exe, "-y", "-v", "error", "-i", str(src), "-vn", "-ac", "1", *codec, str(tmp)], 300)
                tmp.replace(dst)
                return dst, OFFICE_MIMES[ext]
            except (subprocess.SubprocessError, OSError):
                try:
                    tmp.unlink()
                except OSError:
                    pass
    return (src, "audio/wav") if src.suffix.lower() == ".wav" else None


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
        _run(cmd, 300)
        return dst
    except (subprocess.SubprocessError, OSError):
        return None


CLICK_MS = 5            # the join click: 5 ms of a 2 kHz sine fading out (the Visual Stimulus
CLICK_HZ = 2000         # Kit's joiner, rulingAnts/videoannotationtool vat/audio/joiner.py)
CLICK_PAD_MS = 500      # silence either side of it
CLICK_LEVEL = 0.5       # its peak at most (−6 dBFS) …
CLICK_FLOOR = 0.03      # … and at least, beside a silent clip


def click_samples(rate: int, level: float) -> "array.array":
    """The join click as 16-bit mono samples, its peak exactly `level` of full scale."""
    import array
    import math
    n = max(1, int(rate * CLICK_MS / 1000))
    wave_ = [math.sin(2 * math.pi * CLICK_HZ * i / rate) * (1 - i / n) for i in range(n)]
    peak = max(abs(v) for v in wave_) or 1.0
    return array.array("h", (int(v / peak * level * 32767) for v in wave_))


def _samples16(wav: Path) -> tuple["array.array", int]:
    import array
    with wave.open(str(wav), "rb") as r:
        if r.getnchannels() != 1 or r.getsampwidth() != 2:
            raise ValueError(f"{wav.name} is not 16-bit mono")
        rate = r.getframerate()
        out = array.array("h")
        out.frombytes(r.readframes(r.getnframes()))
    if sys.byteorder == "big":
        out.byteswap()
    return out, rate


def concat_clips(clips: list[Path], dst: Path, pad_ms: int = CLICK_PAD_MS, ffmpeg: str | None = None,
                 click: bool = True) -> list[tuple[int, int]]:
    """One small 16-bit mono WAV out of several clips in order (Seth, 2026-10-16: the examples'
    audio, matched in the flextext export). Between two clips: `pad_ms` of silence, a CLICK, `pad_ms`
    of silence (Seth, 2026-10-17: "a generated click inserted at join points", as the Visual
    Stimulus Kit joins its recordings); the click's peak is the quieter neighbour's, between
    CLICK_FLOOR and CLICK_LEVEL, so it marks the join without standing out above the speech.
    Returns each clip's (begin, end) in milliseconds within `dst`. Every clip is taken to the first
    one's sample rate; that needs ffmpeg when the rates differ or a clip is not a WAV (the FLAC
    cache), else ValueError."""
    import array
    import tempfile
    exe = ffmpeg or find_ffmpeg()
    dst.parent.mkdir(parents=True, exist_ok=True)
    spans: list[tuple[int, int]] = []
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        parts: list[array.array] = []
        rate = None
        for i, c in enumerate(clips):
            c = Path(c)
            if c.suffix.lower() != ".wav" and not exe:
                raise ValueError(f"{c.name} is not a WAV and ffmpeg was not found")
            mono = tmpdir / f"clip{i}.wav"
            if not to_mono16(c, mono, exe):
                raise ValueError(f"could not read {c.name}")
            samples, r = _samples16(mono)
            if rate is None:
                rate = r
            elif r != rate:
                if not exe or not _decode_to_wav(c, tmpdir / f"clip{i}r.wav", exe, rate, 1):
                    raise ValueError(f"{c.name} has a different sample rate and ffmpeg was not found")
                samples, _ = _samples16(tmpdir / f"clip{i}r.wav")
            parts.append(samples)
        if rate is None:
            raise ValueError("no clips")
        pad = array.array("h", bytes(2 * int(round(pad_ms / 1000 * rate))))
        tmp = dst.with_suffix(dst.suffix + ".tmp")
        pos = 0
        with wave.open(str(tmp), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)

            def put(a: array.array) -> None:
                nonlocal pos
                if sys.byteorder == "big":
                    a = array.array("h", a)
                    a.byteswap()
                w.writeframes(a.tobytes())
                pos += len(a)

            def peak(a: array.array) -> float:
                return (max(max(a), -min(a)) / 32767) if len(a) else 0.0

            for i, samples in enumerate(parts):
                if i:
                    put(pad)
                    if click:
                        level = max(CLICK_FLOOR, min(CLICK_LEVEL, peak(parts[i - 1]), peak(samples)))
                        put(click_samples(rate, level))
                        put(pad)
                begin = pos
                put(samples)
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
            _run([exe, "-y", "-v", "error", "-i", str(src), "-vn", "-ac", "1", "-acodec", "pcm_s16le", str(tmp)], 300)
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
