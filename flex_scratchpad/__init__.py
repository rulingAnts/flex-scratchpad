"""FLEx Scratchpad — a notebook that shows live FieldWorks objects inside notes.

Python owns the FieldWorks project (through flexicon / LCM) and the notebook on disk; the
notebook UI is HTML and JavaScript shown in a native pywebview window and talks to Python only
through pywebview's exposed ``js_api`` (no HTTP server of any kind).
"""

__version__ = "0.1.0"
APP_NAME = "FLEx Scratchpad"


_BUILD: str | None = None


def build_id() -> str:
    """A short fingerprint of the installed code (every .py and UI file), shown in Settings and by
    `--version`. The version number stays 0.1.0 while the app is installed from a branch, so this
    is what tells two installs apart: when a fix "did not work", compare it with the build the
    fix was pushed in. Computed once, from the files themselves (no git needed)."""
    global _BUILD
    if _BUILD is None:
        import hashlib
        from pathlib import Path
        root = Path(__file__).resolve().parent
        # a packaged build has no .py files to hash: the spec wrote the source's fingerprint
        stamp = root / "BUILD_ID"
        if stamp.is_file():
            _BUILD = stamp.read_text(encoding="utf-8").strip()[:7]
            return _BUILD
        h = hashlib.sha1()
        for f in sorted(root.rglob("*")):
            if f.is_file() and f.suffix in (".py", ".js", ".css", ".html") and "__pycache__" not in f.parts:
                h.update(f.relative_to(root).as_posix().encode("utf-8"))
                h.update(f.read_bytes().replace(b"\r\n", b"\n"))
        _BUILD = h.hexdigest()[:7]
    return _BUILD
