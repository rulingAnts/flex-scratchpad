"""`python -m flex_scratchpad` / `flex-scratchpad` — start the app.

    flex-scratchpad                       open the configured notebook (default: Documents/FLEx Scratchpad)
    flex-scratchpad --notebook DIR        open a specific notebook folder
    flex-scratchpad --demo                use the built-in demo project instead of FieldWorks
    flex-scratchpad --list-projects       print the FieldWorks projects flexicon can see, then exit
    flex-scratchpad --check               report whether flexicon/pythonnet/pywebview import, then exit
    flex-scratchpad --selftest OUT.json   check the installed program (window code, .NET, flexicon, ffmpeg, rclone,
                                          the page) and write the results; what the release build runs
    flex-scratchpad flexscratchpad://note/<id>   open that note (a second instance hands it to the running one)
    flex-scratchpad --register-links      register the flexscratchpad:// scheme for this user (Windows)
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="flex-scratchpad", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--notebook", help="notebook folder (markdown files)")
    ap.add_argument("--demo", action="store_true", help="use the built-in demo project")
    ap.add_argument("--devtools", "--debug", dest="debug", action="store_true", help="turn the browser developer tools on for the page (WebView2 opens them in their own window: press F12 in the app, or right-click → Inspect); off without this flag")
    ap.add_argument("-v", "--verbose", action="store_true", help="log everything to the terminal (the default when run from a pip install in a terminal; the windowed exe only writes the log file)")
    ap.add_argument("-q", "--quiet", action="store_true", help="only warnings and errors on the terminal")
    ap.add_argument("--list-projects", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--selftest", metavar="OUT", help="check the installed program and write a JSON report to OUT, then exit (0 = all good)")
    ap.add_argument("--version", action="store_true", help="print the version and build fingerprint and exit")
    ap.add_argument("--project", help="FieldWorks project name (with --dump)")
    ap.add_argument("--dump", metavar="TEXT", help="print the first segments of a text (title, part of a title, or GUID) as JSON and exit — for diagnosing what flexicon returns")
    ap.add_argument("--seg", metavar="LINE", help="with --dump: the line(s) to print instead of the first three — FLEx's own number (11.1, or 11.1-11.3) or the running count (42, 42-44)")
    ap.add_argument("--locate", metavar="SOURCE", help="explain where pasted FLEx rows land: SOURCE is 'clip' (the clipboard, Windows) or a text file; writes a JSON report (--out) and exits")
    ap.add_argument("--dump-tags", nargs="?", const="", metavar="TEXT", help="write what the project's text markup tags look like raw (the list, and the tags of the first texts that have any, or of TEXT) to a JSON report (--out) and exit")
    ap.add_argument("--dump-charts", nargs="?", const="", metavar="TEXT", help="write what the project's text charts look like raw (every chart, the Chart Markers list, and the rows of one chart as read: the first with rows, or the one whose text title, template or GUID holds every word of TEXT, e.g. \"Siakai SVC\") to a JSON report (--out) and exit")
    ap.add_argument("--out", default=None, help="report file for --locate (flex-scratchpad-locate.json), --dump-tags (flex-scratchpad-tags.json) or --dump-charts (flex-scratchpad-charts.json)")
    ap.add_argument("--backup", action="store_true", help="back the notebook up to the place set in Settings (what closing the app starts), then exit (0 = backed up)")
    ap.add_argument("--register-links", action="store_true", help="register flexscratchpad:// links for this user (Windows) and exit")
    ap.add_argument("url", nargs="?", help="a flexscratchpad://note/<id> link to open (what Windows passes when such a link is clicked)")
    args = ap.parse_args(argv)
    from .log import setup as log_setup
    log_setup(verbose=True if args.verbose else None, quiet=args.quiet)

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
    if args.selftest:
        return selftest(args.selftest)
    if args.backup:
        return backup_once(args.notebook)
    if args.dump:
        return dump(args.project, args.dump, args.seg)
    if args.locate:
        return locate_report(args.project, args.locate, args.out or "flex-scratchpad-locate.json", demo=args.demo)
    if args.dump_tags is not None:
        return tags_report(args.project, args.dump_tags, args.out or "flex-scratchpad-tags.json")
    if args.dump_charts is not None:
        return charts_report(args.project, args.dump_charts, args.out or "flex-scratchpad-charts.json", demo=args.demo)
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

    from .app import exit_now, run
    code = run(notebook_dir=args.notebook, demo=args.demo, debug=args.debug, open_url=args.url)
    exit_now(code)                      # never through Python's shutdown with pythonnet loaded (app.shut_down)
    return code


def dump(project: str | None, which: str, seg: str | None = None) -> int:
    """Open the project read-only and print one text's first three segments (or the lines `seg`
    names: FLEx's own numbers such as 11.1-11.3, or the running count) plus the writing systems,
    so a rendering problem can be diagnosed from the raw data (Seth, 2026-10-19: a Morphemes line
    showing every morph twice — the dump shows the bundles exactly as the project returns them)."""
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
        a, b = dump_range(be, guid, seg)
        page = be.get_text(guid, a, b, diag=True)
        print(json.dumps(page, ensure_ascii=False, indent=1))
        return 0
    except FlexError as e:
        print(e.message, file=sys.stderr)
        if e.detail:
            print(e.detail, file=sys.stderr)
        return 2
    finally:
        be.close()


def tags_report(project: str | None, which: str, out: str) -> int:
    """Write the project's text markup tags as read raw (FlexiconBackend.explain_tags) to a UTF-8
    JSON file — the first thing to ask for when tags come out nameless or on the wrong words."""
    import json
    from pathlib import Path
    from . import __version__, build_id
    from .flex.lcm import FlexError, FlexiconBackend
    be = FlexiconBackend(progress=lambda m: print(m, file=sys.stderr))
    try:
        if not project:
            names = be.list_projects()
            if len(names) != 1:
                print("Several projects; pass --project NAME. Found: " + ", ".join(names), file=sys.stderr)
                return 2
            project = names[0]
        be.open(project)
        report = {"app": f"FLEx Scratchpad {__version__} (build {build_id()})", "project": project}
        report.update(be.explain_tags(which))
        Path(out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{len(report['list'])} tag(s) in the list, {sum(t['tagCount'] for t in report['texts'])} use(s) in {len(report['texts'])} text(s) → {out}")
        return 0
    except FlexError as e:
        print(e.message, file=sys.stderr)
        if e.detail:
            print(e.detail, file=sys.stderr)
        return 2
    finally:
        be.close()


def charts_report(project: str | None, which: str, out: str, demo: bool = False) -> int:
    """Write the project's text charts as read raw (FlexiconBackend.explain_charts) to a UTF-8
    JSON file — the first thing to ask for when a chart comes out wrong (--demo: the fixture)."""
    import json
    from pathlib import Path
    from . import __version__, build_id
    from .flex.lcm import FlexError, FlexiconBackend
    if demo:
        from .flex.demo import DemoBackend
        be = DemoBackend()
        report = {"app": f"FLEx Scratchpad {__version__} (build {build_id()})", "project": be.project_name, "charts": be.list_charts(),
                  "markers": be.list_chart_markers(), "chart": be.get_chart(be.list_charts()[0]["guid"]) if be.list_charts() else None}
        Path(out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{len(report['charts'])} chart(s) → {out}")
        return 0
    be = FlexiconBackend(progress=lambda m: print(m, file=sys.stderr))
    try:
        if not project:
            names = be.list_projects()
            if len(names) != 1:
                print("Several projects; pass --project NAME. Found: " + ", ".join(names), file=sys.stderr)
                return 2
            project = names[0]
        be.open(project)
        report = {"app": f"FLEx Scratchpad {__version__} (build {build_id()})", "project": project}
        report.update(be.explain_charts(which))
        Path(out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        ch = report.get("chart") or {}
        print(f"{len(report['charts'])} chart(s), {len(report['markers'])} marker(s) in the list"
              + (f"; {ch.get('name') or 'chart'} on “{ch.get('title') or '?'}” ({(ch.get('template') or {}).get('name') or 'no template'}): {ch.get('rowCount', 0)} row(s), {len((ch.get('template') or {}).get('columns') or [])} column(s)" if ch else "; no chart matches " + repr(which) if which else "")
              + f" → {out}")
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


def dump_range(be, guid: str, seg: str | None) -> tuple[int, int]:
    """(first, last) running segment numbers for --seg: `42` / `42-44` as they are; a FLEx number
    (`11.1`, `11.1-11.3`) found by walking the text's pages for the segments carrying those labels."""
    from .flex.lcm import FlexError
    if not seg:
        return 1, 3
    parts = [x.strip() for x in str(seg).split("-", 1)]
    if all(x.isdigit() for x in parts):
        a = int(parts[0])
        return a, int(parts[-1])
    want = {x: None for x in parts}
    start, total = 1, None
    while any(v is None for v in want.values()) and (total is None or start <= total):
        page = be.get_text(guid, start, start + 59)
        segs = page.get("segments") or []
        total = page.get("segmentCount") or total or 0
        for sg in segs:
            if sg.get("label") in want and want[sg["label"]] is None:
                want[sg["label"]] = int(sg["n"])
        if not segs:
            break
        start += 60
    missing = [k for k, v in want.items() if v is None]
    if missing:
        raise FlexError("No line numbered " + ", ".join(missing) + " in that text.", "", "no-object")
    ns = [want[x] for x in parts]
    return min(ns), max(ns)


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


def selftest(out: str) -> int:
    """What a packaged build must have, checked from inside it and written to `out` as JSON:
    the page and icon, pywebview, pythonnet's .NET runtime, flexicon (packaged; FieldWorks itself
    need not be installed — an error that names FieldWorks is the expected answer on a machine
    without it), and ffmpeg (found, runs, and cuts a clip). The release workflow runs it on the
    built folder and on the installed copy; a user can run it to report what their copy lacks.
    Writes only `out` and a temporary folder."""
    import json
    import platform
    import tempfile
    from pathlib import Path
    from . import __version__, build_id
    res: dict = {"app": __version__, "build": build_id(), "frozen": bool(getattr(sys, "frozen", False)),
                 "executable": sys.executable, "python": sys.version.split()[0], "platform": platform.platform(), "checks": {}}

    def rec(name, fn):
        try:
            res["checks"][name] = {"ok": True, "detail": fn()}
        except Exception as e:  # noqa: BLE001
            res["checks"][name] = {"ok": False, "detail": f"{type(e).__name__}: {e}"}

    def page():
        from .app import ICON, UI_DIR, ui_url
        for p in (UI_DIR / "index.html", UI_DIR / "js" / "app.js", UI_DIR / "css" / "app.css", ICON):
            if not p.is_file():
                raise FileNotFoundError(str(p))
        return ui_url()
    rec("page", page)

    def window():
        import webview
        return getattr(webview, "__version__", "") or "imported"
    rec("pywebview", window)

    def dotnet():
        import clr  # noqa: F401
        import System
        return "CLR " + str(System.Environment.Version)
    if sys.platform == "win32":
        rec("pythonnet", dotnet)

    def flex():
        try:
            import flexicon  # noqa: F401
            return "imported (FieldWorks found)"
        except ModuleNotFoundError as e:
            if (e.name or "").split(".")[0] in ("flexicon", "flexlibs2", "clr", "pythonnet", "clr_loader"):
                raise                                     # not packaged: a real failure
            return f"packaged; FieldWorks not available here ({type(e).__name__}: {e})"
        except Exception as e:  # noqa: BLE001 — no FieldWorks on this machine: expected on a build runner
            return f"packaged; FieldWorks not available here ({type(e).__name__}: {e})"
    if sys.platform == "win32":
        rec("flexicon", flex)

    def ffmpeg():
        import subprocess
        import wave
        from .flex.audio import bundled_ffmpeg, cut_ffmpeg, find_ffmpeg
        exe = find_ffmpeg()
        if not exe:
            raise FileNotFoundError("no ffmpeg")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        ver = subprocess.run([exe, "-version"], capture_output=True, text=True, timeout=60, creationflags=flags).stdout.splitlines()[0]
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "tone.wav"
            with wave.open(str(src), "wb") as w:                  # one second of silence, 16 kHz mono
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(b"\0\0" * 16000)
            clip = cut_ffmpeg(src, Path(d) / "clip.flac", 250, 750, exe)
            if not clip or not clip.is_file() or clip.stat().st_size == 0:
                raise RuntimeError("ffmpeg ran but cut no clip")
        bundled = bundled_ffmpeg()
        if res["frozen"] and not (bundled and Path(exe).resolve() == bundled.resolve()):
            raise RuntimeError(f"the bundled ffmpeg was not used (found {exe})")
        return f"{ver} — {exe}"
    rec("ffmpeg", ffmpeg)

    def rclone():
        # the backup's engine: present, runs, and takes a password on stdin (how the encryption
        # password reaches it, never on a command line)
        import subprocess
        from .backup import bundled_rclone, find_rclone
        exe = find_rclone()
        if not exe:
            raise FileNotFoundError("no rclone")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        ver = subprocess.run([exe, "version"], capture_output=True, text=True, timeout=60, creationflags=flags).stdout.splitlines()[0]
        ob = subprocess.run([exe, "obscure", "-"], input="selftest", capture_output=True, text=True, timeout=60, creationflags=flags)
        if ob.returncode != 0 or not ob.stdout.strip():
            raise RuntimeError("rclone obscure failed: " + ob.stderr[-200:])
        bundled = bundled_rclone()
        if res["frozen"] and not (bundled and Path(exe).resolve() == bundled.resolve()):
            raise RuntimeError(f"the bundled rclone was not used (found {exe})")
        return f"{ver} — {exe}"
    rec("rclone", rclone)

    if sys.platform == "win32":
        def secrets():
            # the Windows Credential Manager, through advapi32: write, read back, remove
            from .secrets_store import WindowsCredentialStore
            st = WindowsCredentialStore()
            st.set("selftest", "ŋ-selftest")
            try:
                if st.get("selftest") != "ŋ-selftest":
                    raise RuntimeError("the credential read back differs")
            finally:
                st.delete("selftest")
            if st.get("selftest") is not None:
                raise RuntimeError("the credential was not removed")
            return "Windows Credential Manager: write, read, remove"
        rec("secrets", secrets)

    res["ok"] = all(c["ok"] for c in res["checks"].values())
    Path(out).write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0 if res["ok"] else 1


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


def backup_once(notebook: str | None) -> int:
    """One backup without a window (closing the app starts this); the result is recorded in the
    per-user config, where Settings shows it."""
    from .backup import Backup, BackupError
    from .config import AppConfig
    from .secrets_store import default_store
    import time
    cfg = AppConfig()
    root = Path(notebook) if notebook else cfg.notebook_dir
    try:
        b = Backup(cfg, default_store(), lambda: root)
        t0 = time.monotonic()
        while True:
            r = b.run("close")
            # the window that started this process may still be letting go of its own cancelled
            # run (its lock): wait for it, up to two minutes, rather than give up at once
            if not r.get("busy") or time.monotonic() - t0 > 120:
                break
            time.sleep(2)
    except BackupError as e:
        print(e)
        return 2
    print(r.get("message", ""))
    return 0 if r.get("ok") else 1
