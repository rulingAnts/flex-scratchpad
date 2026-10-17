"""Fetch the rclone that ships with the Windows build (build time only; the app never downloads).

Seth, 2026-10-17: backups to S3-compatible storage go through rclone, bundled like ffmpeg (field
laptops are often offline, and an installed program that fetches and runs another executable is
what anti-malware software watches for).

The build is rclone's own release for Windows x64 (`rclone-v<X>-windows-amd64.zip` in the latest
GitHub release of rclone/rclone; MIT licence). The download is checked against the release's own
`SHA256SUMS`; anything that does not match is refused.

    python tools/fetch_rclone.py --out build/rclone        (GITHUB_TOKEN, if set, is sent to the API)

writes rclone.exe, LICENSE.txt and RCLONE-NOTICE.txt into --out. Network errors are retried with
back-off; a partial download is resumed (the helpers are fetch_ffmpeg.py's).
"""
from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_ffmpeg import _json, download, sha256  # noqa: E402

API = "https://api.github.com/repos/rclone/rclone/releases/latest"
ASSET = re.compile(r"^rclone-v\d+\.\d+\.\d+-windows-amd64\.zip$")


def pick(assets: list[dict]) -> dict:
    for a in assets:
        if ASSET.match(a.get("name", "")):
            return a
    raise SystemExit("no windows-amd64 zip in rclone's latest release: " + ", ".join(a.get("name", "") for a in assets))


def expected_sum(sums_text: str, name: str) -> str:
    """The hash for `name` in a SHA256SUMS file (rclone's is PGP clear-signed: the lines sit
    between the signature headers, `<hash>  <file>`)."""
    for ln in sums_text.splitlines():
        parts = ln.split()
        if len(parts) == 2 and parts[1].lstrip("*") == name and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            return parts[0].lower()
    return ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rel = _json(API)
    assets = rel.get("assets") or []
    asset = pick(assets)
    sums = next((a for a in assets if a.get("name") == "SHA256SUMS"), None)
    if not sums:
        raise SystemExit("rclone's release has no SHA256SUMS; refusing an unverified rclone")
    work = out / ".download"
    work.mkdir(exist_ok=True)
    zpath = download(asset["browser_download_url"], work / asset["name"])
    spath = download(sums["browser_download_url"], work / "SHA256SUMS")
    want = expected_sum(spath.read_text(encoding="utf-8", errors="replace"), asset["name"])
    got = sha256(zpath)
    if not want or want != got:
        raise SystemExit(f"checksum mismatch for {asset['name']}: release says {want or 'nothing'}, file is {got}")
    with zipfile.ZipFile(zpath) as z:
        names = z.namelist()
        exe = next(n for n in names if n.endswith("/rclone.exe"))
        lic = next((n for n in names if n.rsplit("/", 1)[-1] in ("LICENSE", "COPYING", "LICENSE.txt")), None)
        (out / "rclone.exe").write_bytes(z.read(exe))
        if lic:
            (out / "LICENSE.txt").write_bytes(z.read(lic))
    (out / "RCLONE-NOTICE.txt").write_text(
        "FLEx Scratchpad uses rclone (https://rclone.org), run as a separate program, to back notebooks up\n"
        "to S3-compatible storage. rclone is licensed under the MIT licence:\n"
        "  https://github.com/rclone/rclone/blob/master/COPYING\n\n"
        f"This copy: {asset['name']} ({rel.get('tag_name', '')})\n"
        f"  from https://github.com/rclone/rclone/releases\n"
        f"  SHA-256 of the archive: {got}\n",
        encoding="utf-8")
    for p in work.iterdir():
        p.unlink()
    work.rmdir()
    # ASCII only: a Windows runner's console is cp1252
    print(f"rclone: {asset['name']} (sha256 {got[:12]}) -> {out / 'rclone.exe'} ({(out / 'rclone.exe').stat().st_size // 1_000_000} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
