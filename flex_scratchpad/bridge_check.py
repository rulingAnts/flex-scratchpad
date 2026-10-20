"""What pywebview will expose of the Api, checked the way pywebview does it.

pywebview (5.x, `webview/util.py` `inject_pywebview`) builds the page's `window.pywebview.api`
by walking `dir(js_api)`: every public bound method becomes a function (its parameters from
`inspect.getfullargspec`), and every public attribute that is a class or a non-callable object
is walked in turn. One attribute that raises on access, or one method whose signature cannot be
read, aborts the whole walk — pywebview logs the exception and the page's api stays EMPTY, and
the page then waits forever for an `init` that never comes (Seth, 2026-10-19: the newest wheel
started on the page's in-browser demo instead of his notebook, which looked like lost data).

`exposed(obj)` repeats that walk and returns the function names it would produce and every
problem it met, so a test can fail on a new attribute before a user does and the app can say in
its log exactly what pywebview would have choked on."""
from __future__ import annotations

import inspect
import json


def exposed(obj) -> tuple[list[str], list[str]]:
    """(the dotted names pywebview would expose, the problems it would hit) — never raises."""
    names: list[str] = []
    problems: list[str] = []
    seen: list = []

    def walk(o, base: str) -> None:
        if any(o is s for s in seen):
            return
        seen.append(o)
        try:
            attrs = dir(o)
        except Exception as e:  # noqa: BLE001
            problems.append(f"dir({base or 'api'}) raised {type(e).__name__}: {e}")
            return
        for name in attrs:
            if name.startswith("_"):
                continue
            full = f"{base}.{name}" if base else name
            try:
                attr = getattr(o, name)
            except Exception as e:  # noqa: BLE001
                problems.append(f"{full}: reading it raised {type(e).__name__}: {e}")
                continue
            if inspect.ismethod(attr):
                try:
                    params = list(inspect.getfullargspec(attr).args)[1:]
                    json.dumps({"func": full, "params": params})
                    names.append(full)
                except Exception as e:  # noqa: BLE001
                    problems.append(f"{full}: its signature cannot be read ({type(e).__name__}: {e})")
            elif inspect.isclass(attr) or (not callable(attr) and hasattr(attr, "__module__")):
                walk(attr, full)

    walk(obj, "")
    return names, problems


def report(obj) -> str:
    """One line for the log: how many functions, whether `init` is among them, the problems."""
    names, problems = exposed(obj)
    head = f"{len(names)} functions" + ("" if "init" in names else ", init MISSING")
    return head + (("; problems: " + " | ".join(problems)) if problems else "")
