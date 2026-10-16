"""`python -m flex_scratchpad` / `flex-scratchpad` — start the app.

    flex-scratchpad                       open the configured notebook (default: Documents/FLEx Scratchpad)
    flex-scratchpad --notebook DIR        open a specific notebook folder
    flex-scratchpad --demo                use the built-in demo project instead of FieldWorks
    flex-scratchpad --list-projects       print the FieldWorks projects flexicon can see, then exit
    flex-scratchpad --check               report whether flexicon/pythonnet/pywebview import, then exit
    flex-scratchpad flexscratchpad://note/<id>   open that note (a second instance hands it to the running one)
    flex-scratchpad --register-links      register the flexscratchpad:// scheme for this user (Windows)
"""
from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="flex-scratchpad", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--notebook", help="notebook folder (markdown files)")
    ap.add_argument("--demo", action="store_true", help="use the built-in demo project")
    ap.add_argument("--debug", action="store_true", help="open WebView2 devtools")
    ap.add_argument("--list-projects", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--version", action="store_true", help="print the version and build fingerprint and exit")
    ap.add_argument("--project", help="FieldWorks project name (with --dump)")
    ap.add_argument("--dump", metavar="TEXT", help="print the first segments of a text (title, part of a title, or GUID) as JSON and exit — for diagnosing what flexicon returns")
    ap.add_argument("--locate", metavar="SOURCE", help="explain where pasted FLEx rows land: SOURCE is 'clip' (the clipboard, Windows) or a text file; writes a JSON report (--out) and exits")
    ap.add_argument("--out", default="flex-scratchpad-locate.json", help="report file for --locate")
    ap.add_argument("--register-links", action="store_true", help="register flexscratchpad:// links for this user (Windows) and exit")
    ap.add_argument("url", nargs="?", help="a flexscratchpad://note/<id> link to open (what Windows passes when such a link is clicked)")
    args = ap.parse_args(argv)

    if args.register_links:
        from .links import register_scheme
        ok = register_scheme()
        print("registered flexscratchpad:// for this user" if ok else "could not register (not Windows, or the registry refused)")
        return 0 if ok else 1

    if args.version:
        from . import __version__, build_id
        print(f"FLEx Scratchpad {__version__} (build {build_id()})")
        return 0
    if args.check:
        return check()
    if args.dump:
        return dump(args.project, args.dump)
    if args.locate:
        return locate_report(args.project, args.locate, args.out, demo=args.demo)
    if args.list_projects:
        from .flex.lcm import FlexError, FlexiconBackend
        be = FlexiconBackend()
        try:
            for name in be.list_projects():
                print(name)
            return 0
        except FlexError as e:
            print(e.message, file=sys.stderr)
            return 2
        finally:
            be.close()

    from .app import run
    return run(notebook_dir=args.notebook, demo=args.demo, debug=args.debug, open_url=args.url)


def dump(project: str | None, which: str) -> int:
    """Open the project read-only and print one text's first three segments plus the writing
    systems, so a rendering problem can be diagnosed from the raw data."""
    import json
    from .flex.lcm import FlexError, FlexiconBackend
    from .flex.model import is_guid
    be = FlexiconBackend(progress=lambda m: print(m, file=sys.stderr))
    try:
        if not project:
            names = be.list_projects()
            if len(names) != 1:
                print("Several projects; pass --project NAME. Found: " + ", ".join(names), file=sys.stderr)
                return 2
            project = names[0]
        st = be.open(project)
        print(json.dumps({"status": st}, ensure_ascii=False, indent=1))
        guid = which if is_guid(which) else None
        if not guid:
            hits = [t for t in be.list_texts() if which.casefold() in t["title"].casefold()]
            if not hits:
                print("No text title contains " + repr(which) + ". Texts: " + ", ".join(t["title"] for t in be.list_texts()[:30]), file=sys.stderr)
                return 2
            guid = hits[0]["guid"]
        page = be.get_text(guid, 1, 3, diag=True)
        print(json.dumps(page, ensure_ascii=False, indent=1))
        return 0
    except FlexError as e:
        print(e.message, file=sys.stderr)
        if e.detail:
            print(e.detail, file=sys.stderr)
        return 2
    finally:
        be.close()


def _clipboard_text() -> str:
    """The Windows clipboard's Unicode text (no third-party packages)."""
    import ctypes
    from ctypes import wintypes
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    user32.GetClipboardData.restype = wintypes.HANDLE
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    if not user32.OpenClipboard(None):
        raise RuntimeError("could not open the clipboard")
    try:
        h = user32.GetClipboardData(13)              # CF_UNICODETEXT
        if not h:
            return ""
        ptr = kernel32.GlobalLock(h)
        try:
            return ctypes.wstring_at(ptr)
        finally:
            kernel32.GlobalUnlock(h)
    finally:
        user32.CloseClipboard()


def locate_report(project: str | None, source: str, out: str, demo: bool = False) -> int:
    """Run the paste locator on rows copied from FLEx against the real project and write what it
    saw to a UTF-8 JSON file (the Windows console cannot be trusted with IPA)."""
    import json
    import tempfile
    from pathlib import Path
    from . import __version__, build_id
    from .flex import FlexService
    from .flex.lcm import FlexError
    from .notebook import Notebook
    if source == "clip":
        if sys.platform != "win32":
            print("--locate clip reads the Windows clipboard; pass a file instead", file=sys.stderr)
            return 2
        text = _clipboard_text()
    else:
        text = Path(source).read_text(encoding="utf-8-sig")
    if not text.strip():
        print("Nothing to locate (the clipboard or file is empty).", file=sys.stderr)
        return 2
    fs = FlexService(Notebook(tempfile.mkdtemp(prefix="fs-locate-")))
    try:
        if demo:
            from .flex.demo import DemoBackend
            fs.backend = DemoBackend()
        else:
            from .flex.lcm import FlexiconBackend
            be = FlexiconBackend(progress=lambda m: print(m, file=sys.stderr))
            if not project:
                names = be.list_projects()
                if len(names) != 1:
                    print("Several projects; pass --project NAME. Found: " + ", ".join(names), file=sys.stderr)
                    return 2
                project = names[0]
            be.open(project)
            fs.backend = be
        report = {"app": f"FLEx Scratchpad {__version__} (build {build_id()})", "project": project or "demo", "pasted": text}
        report.update(fs.explain_locate(text))
        Path(out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        hits = report.get("hits") or []
        print(f"{len(report.get('queries') or [])} pasted segment(s); {len(hits)} candidate(s)"
              + (f"; best: segments {hits[0].get('label', hits[0]['seg'])}-{hits[0].get('labelTo', hits[0]['segTo'])}, {hits[0]['matched']} of {hits[0]['of']} matched" if hits else ""))
        print("Report written to " + str(Path(out).resolve()))
        return 0
    except FlexError as e:
        print(e.message, file=sys.stderr)
        return 2
    finally:
        if fs.backend is not None and hasattr(fs.backend, "close"):
            fs.backend.close()


def check() -> int:
    ok = True
    for mod, why in (("webview", "pywebview — the native window"),
                     ("clr", "pythonnet — needed by flexicon"),
                     ("flexicon", "flexicon — reads the FieldWorks project (Windows + FieldWorks only)")):
        try:
            __import__(mod)
            print(f"ok       {mod:10s} {why}")
        except Exception as e:  # noqa: BLE001
            ok = False
            print(f"MISSING  {mod:10s} {why}: {type(e).__name__}: {e}")
    from . import __version__, build_id
    print("app     ", __version__, "build", build_id())
    print("python  ", sys.version.split()[0], "64-bit" if sys.maxsize > 2**32 else "32-bit (FieldWorks needs 64-bit)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
