"""`python -m flex_scratchpad` / `flex-scratchpad` — start the app.

    flex-scratchpad                       open the configured notebook (default: Documents/FLEx Scratchpad)
    flex-scratchpad --notebook DIR        open a specific notebook folder
    flex-scratchpad --demo                use the built-in demo project instead of FieldWorks
    flex-scratchpad --list-projects       print the FieldWorks projects flexicon can see, then exit
    flex-scratchpad --check               report whether flexicon/pythonnet/pywebview import, then exit
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
    ap.add_argument("--project", help="FieldWorks project name (with --dump)")
    ap.add_argument("--dump", metavar="TEXT", help="print the first segments of a text (title, part of a title, or GUID) as JSON and exit — for diagnosing what flexicon returns")
    args = ap.parse_args(argv)

    if args.check:
        return check()
    if args.dump:
        return dump(args.project, args.dump)
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
    return run(notebook_dir=args.notebook, demo=args.demo, debug=args.debug)


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
        page = be.get_text(guid, 1, 3)
        print(json.dumps(page, ensure_ascii=False, indent=1))
        return 0
    except FlexError as e:
        print(e.message, file=sys.stderr)
        if e.detail:
            print(e.detail, file=sys.stderr)
        return 2
    finally:
        be.close()


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
    print("python  ", sys.version.split()[0], "64-bit" if sys.maxsize > 2**32 else "32-bit (FieldWorks needs 64-bit)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
