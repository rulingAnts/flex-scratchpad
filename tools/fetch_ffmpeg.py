"""Fetch the ffmpeg that ships with the Windows build (build time only; the app never downloads).

Seth, 2026-10-16: a release must ship ffmpeg or install it on first use. It is shipped: field
laptops are often offline when the app first needs to cut a clip, and an installed program that
fetches and runs another executable is what anti-malware software watches for (the same reason
the app runs no HTTP server).

The build is BtbN/FFmpeg-Builds' LGPL Windows x64 static build of the newest release branch
(`ffmpeg-n<X.Y>-latest-win64-lgpl-<X.Y>.zip` in its `latest` release) — LGPL, so it can sit beside
the program as a separate executable with its licence and a pointer to its source. The download is
checked against the release's own `checksums.sha256`; anything that does not match is refused.

    python tools/fetch_ffmpeg.py --out build/ffmpeg        (GITHUB_TOKEN, if set, is sent to the API)

writes ffmpeg.exe, LICENSE.txt and FFMPEG-NOTICE.txt into --out. Network errors are retried with
back-off; a partial download is resumed with an HTTP Range request.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

API = "https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/tags/latest"
ASSET = re.compile(r"^ffmpeg-n(\d+)\.(\d+)(?:\.\d+)?-latest-win64-lgpl-\d+\.\d+\.zip$")
FALLBACK = "ffmpeg-master-latest-win64-lgpl.zip"
TRIES = 6


def _req(url: str, accept: str = "") -> urllib.request.Request:
    r = urllib.request.Request(url, headers={"User-Agent": "flex-scratchpad-build"})
    if accept:
        r.add_header("Accept", accept)
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok and url.startswith("https://api.github.com/"):
        r.add_header("Authorization", "Bearer " + tok)
    return r


def _retry(what: str, fn):
    delay = 2
    for k in range(1, TRIES + 1):
        try:
            return fn()
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            if isinstance(e, urllib.error.HTTPError) and e.code in (401, 403, 404):
                raise
            if k == TRIES:
                raise
            print(f"{what}: {e} — retrying in {delay}s ({k}/{TRIES})", file=sys.stderr)
            time.sleep(delay)
            delay = min(delay * 2, 60)


def _json(url: str):
    return _retry(url, lambda: json.loads(urllib.request.urlopen(_req(url, "application/vnd.github+json"), timeout=60).read()))


def download(url: str, dst: Path) -> Path:
    """`url` to `dst`, resuming a partial `dst.part` after a dropped connection."""
    part = dst.with_name(dst.name + ".part")

    def once():
        have = part.stat().st_size if part.exists() else 0
        r = _req(url)
        if have:
            r.add_header("Range", f"bytes={have}-")
        with urllib.request.urlopen(r, timeout=120) as resp:
            mode = "ab" if have and resp.status == 206 else "wb"
            with open(part, mode) as f:
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
            total = resp.headers.get("Content-Range", "").rsplit("/", 1)[-1] if resp.status == 206 else resp.headers.get("Content-Length")
        if total and total.isdigit() and part.stat().st_size != int(total):
            raise ConnectionError(f"short download: {part.stat().st_size} of {total} bytes")
    _retry(url, once)
    part.replace(dst)
    return dst


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pick(assets: list[dict]) -> dict:
    """The newest release branch's LGPL win64 zip; master's only when there is none."""
    best, key = None, None
    for a in assets:
        m = ASSET.match(a.get("name", ""))
        if m and (key is None or (int(m.group(1)), int(m.group(2))) > key):
            best, key = a, (int(m.group(1)), int(m.group(2)))
    if best:
        return best
    for a in assets:
        if a.get("name") == FALLBACK:
            return a
    raise SystemExit("no LGPL win64 ffmpeg build in BtbN's latest release: " + ", ".join(a.get("name", "") for a in assets))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rel = _json(API)
    assets = rel.get("assets") or []
    asset = pick(assets)
    sums = next((a for a in assets if a.get("name") == "checksums.sha256"), None)
    if not sums:
        raise SystemExit("BtbN's release has no checksums.sha256; refusing an unverified ffmpeg")
    work = out / ".download"
    work.mkdir(exist_ok=True)
    zpath = download(asset["browser_download_url"], work / asset["name"])
    spath = download(sums["browser_download_url"], work / "checksums.sha256")
    want = next((ln.split()[0] for ln in spath.read_text(encoding="utf-8").splitlines() if ln.strip().endswith(asset["name"])), "")
    got = sha256(zpath)
    if not want or want.lower() != got:
        raise SystemExit(f"checksum mismatch for {asset['name']}: release says {want or 'nothing'}, file is {got}")
    with zipfile.ZipFile(zpath) as z:
        names = z.namelist()
        exe = next(n for n in names if n.endswith("/bin/ffmpeg.exe"))
        lic = next((n for n in names if n.endswith("/LICENSE.txt")), None)
        (out / "ffmpeg.exe").write_bytes(z.read(exe))
        if lic:
            (out / "LICENSE.txt").write_bytes(z.read(lic))
    ver = asset["name"]
    (out / "FFMPEG-NOTICE.txt").write_text(
        "FLEx Scratchpad uses FFmpeg (https://ffmpeg.org), run as a separate program, to cut audio clips.\n"
        "FFmpeg is licensed under the GNU Lesser General Public License (LGPL) version 2.1 or later;\n"
        "the licence is in LICENSE.txt beside this file.\n\n"
        f"This copy: {ver}\n"
        f"  built by BtbN/FFmpeg-Builds: https://github.com/BtbN/FFmpeg-Builds (release 'latest', {rel.get('published_at', '')})\n"
        f"  SHA-256 of the archive: {got}\n"
        "  source code: https://ffmpeg.org/download.html#get-sources, and the build scripts at the link above.\n"
        "Replacing ffmpeg.exe with another build of FFmpeg is fine: FLEx Scratchpad only runs it.\n",
        encoding="utf-8")
    for p in work.iterdir():
        p.unlink()
    work.rmdir()
    print(f"ffmpeg: {ver} ({got[:12]}…) → {out / 'ffmpeg.exe'} ({(out / 'ffmpeg.exe').stat().st_size // 1_000_000} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
