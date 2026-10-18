"""Logging for troubleshooting (Seth, 2026-10-18: "make our cli, interpreted python very verbose
so that it's easy to troubleshoot if something goes wrong … What I install and test via pip
install, I'd like to see verbose debugging output to tty that I can copy and send to you").

What goes where:

* **The terminal** (stderr): everything at DEBUG when the program runs from a pip install with a
  terminal attached — every Api call with its arguments and how long it took, every LCM call on
  the worker, every FLEx fetch and snapshot fallback, every note saved. The frozen, windowed exe
  has no terminal; it logs nothing there. `-v` / `--verbose` forces DEBUG, `-q` / `--quiet` keeps
  only warnings, and `FLEX_SCRATCHPAD_LOG=debug|info|warning|error` sets it without a flag.
* **A log file** always (also for the frozen exe, so a problem on a field laptop leaves a trace):
  `<local data folder>/log/flex-scratchpad.log`, INFO and up, rotated at 1 MB × 3.
  `FLEX_SCRATCHPAD_LOGFILE=<path>` moves it, `FLEX_SCRATCHPAD_LOGFILE=` (empty) turns it off.

Nothing secret is ever logged: `redact()` drops the arguments that carry a key, a password or a
file's bytes (`secrets`, `data_base64`, anything named *password* / *secret* / *key*), and long
strings are cut. `tests/test_log.py` checks both.
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import threading
import time
from pathlib import Path

LOG = logging.getLogger("flexscratchpad")
_setup_done = False
SECRET_ARGS = ("secrets", "secret", "password", "data_base64", "key", "token")
MAX_STR = 160


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _level_from(name: str | None, default: int) -> int:
    if not name:
        return default
    return getattr(logging, name.strip().upper(), None) if isinstance(getattr(logging, name.strip().upper(), None), int) else default


def default_log_file() -> Path | None:
    env = os.environ.get("FLEX_SCRATCHPAD_LOGFILE")
    if env is not None:
        return Path(env) if env.strip() else None
    try:
        from .config import local_data_dir
        return local_data_dir() / "log" / "flex-scratchpad.log"
    except Exception:  # noqa: BLE001
        return None


class _Fmt(logging.Formatter):
    def formatTime(self, record, datefmt=None):  # noqa: N802 — logging's name
        t = time.strftime("%H:%M:%S", time.localtime(record.created))
        return f"{t}.{int(record.msecs):03d}"


def setup(verbose: bool | None = None, quiet: bool = False, to_file: bool = True) -> None:
    """Install the handlers once. `verbose=None` means "decide": DEBUG on a terminal of an
    unfrozen program, nothing on the console otherwise."""
    global _setup_done
    if _setup_done:
        if verbose:
            LOG.setLevel(logging.DEBUG)
            for h in LOG.handlers:
                if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
                    h.setLevel(logging.DEBUG)
        return
    _setup_done = True
    LOG.setLevel(logging.DEBUG)
    LOG.propagate = False
    env_level = os.environ.get("FLEX_SCRATCHPAD_LOG")
    fmt = _Fmt("%(asctime)s %(levelname)-7s [%(threadName)s] %(message)s")
    console_level: int | None
    if quiet:
        console_level = logging.WARNING
    elif verbose:
        console_level = logging.DEBUG
    elif env_level:
        console_level = _level_from(env_level, logging.INFO)
    elif not is_frozen() and sys.stderr is not None and getattr(sys.stderr, "isatty", lambda: False)():
        console_level = logging.DEBUG
    else:
        console_level = None
    if console_level is not None and sys.stderr is not None:
        h = logging.StreamHandler(sys.stderr)
        h.setLevel(console_level)
        h.setFormatter(fmt)
        LOG.addHandler(h)
    if to_file:
        path = default_log_file()
        if path is not None:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                fh = logging.handlers.RotatingFileHandler(str(path), maxBytes=1_000_000, backupCount=3, encoding="utf-8")
                fh.setLevel(logging.DEBUG if verbose else logging.INFO)
                fh.setFormatter(_Fmt("%(asctime)s %(levelname)-7s [%(threadName)s] %(message)s"))
                LOG.addHandler(fh)
            except Exception:  # noqa: BLE001 — a read-only folder must not stop the program
                pass
    if not LOG.handlers:
        LOG.addHandler(logging.NullHandler())


def banner(argv: list | None = None) -> None:
    """What every troubleshooting transcript should start with."""
    import platform
    from . import __version__, build_id
    LOG.info("FLEx Scratchpad %s (build %s) python %s %s frozen=%s", __version__, build_id(), sys.version.split()[0],
             platform.platform(), is_frozen())
    LOG.info("argv: %s", " ".join(argv if argv is not None else sys.argv[1:]))
    p = default_log_file()
    if p is not None:
        LOG.debug("log file: %s", p)


def short(v, limit: int = MAX_STR):
    """A loggable rendering of a value: cut long strings, summarise big containers."""
    if isinstance(v, str):
        if v == "<redacted>":
            return v
        s = v.replace("\n", "\\n")
        return "'" + (s if len(s) <= limit else s[:limit] + f"…(+{len(s) - limit})") + "'"
    if isinstance(v, (bytes, bytearray)):
        return f"<{len(v)} bytes>"
    if isinstance(v, dict):
        if len(v) > 12:
            return f"<dict {len(v)} keys: {', '.join(str(k) for k in list(v)[:12])}…>"
        return "{" + ", ".join(f"{k}: {short(x, 60)}" for k, x in redact(v).items()) + "}"
    if isinstance(v, (list, tuple, set)):
        if len(v) > 8:
            return f"<{type(v).__name__} {len(v)}: {short(list(v)[:3], 60)}…>"
        return "[" + ", ".join(short(x, 60) for x in v) + "]"
    return repr(v) if not isinstance(v, (int, float, bool, type(None))) else str(v)


def redact(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        kl = str(k).lower()
        if any(s in kl for s in SECRET_ARGS):
            out[k] = "<redacted>" if v not in (None, "", {}, []) else v
        elif isinstance(v, dict):
            out[k] = redact(v)
        else:
            out[k] = v
    return out


def call_line(name: str, args: tuple, kwargs: dict, names: list[str] | None = None) -> str:
    parts = []
    for i, a in enumerate(args):
        n = names[i] if names and i < len(names) else None
        if n and any(s in n.lower() for s in SECRET_ARGS):
            parts.append(f"{n}=<redacted>")
        else:
            parts.append((n + "=" if n else "") + short(a))
    for k, v in redact(kwargs).items():
        parts.append(f"{k}={short(v)}")
    return f"{name}({', '.join(parts)})"


def logged(fn, prefix: str = "api"):
    """Wrap a method: one DEBUG line per call with its arguments and duration, a WARNING for an
    error the page will show (a RuntimeError / ValueError we raise on purpose), an ERROR with
    the traceback for anything else."""
    import functools
    import inspect
    try:
        names = [p for p in inspect.signature(fn).parameters if p != "self"]
    except (TypeError, ValueError):
        names = None

    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        t0 = time.perf_counter()
        line = call_line(f"{prefix}.{fn.__name__}", args, kwargs, names) if LOG.isEnabledFor(logging.DEBUG) else f"{prefix}.{fn.__name__}"
        try:
            out = fn(self, *args, **kwargs)
        except (RuntimeError, ValueError, KeyError, FileNotFoundError) as e:
            LOG.warning("%s → %s: %s (%.0f ms)", line, type(e).__name__, e, (time.perf_counter() - t0) * 1000)
            raise
        except Exception:
            LOG.exception("%s failed (%.0f ms)", line, (time.perf_counter() - t0) * 1000)
            raise
        ms = (time.perf_counter() - t0) * 1000
        if LOG.isEnabledFor(logging.DEBUG):
            LOG.debug("%s → %s (%.0f ms)", line, short(out, 100), ms)
        elif ms > 2000:
            LOG.info("%s took %.1f s", line, ms / 1000)
        return out
    return wrapper


def timed(label: str):
    """`with timed("…"):` — a DEBUG line with the duration (and the error, if any)."""
    class _T:
        def __enter__(self):
            self.t0 = time.perf_counter()
            return self

        def __exit__(self, et, ev, tb):
            ms = (time.perf_counter() - self.t0) * 1000
            if et is None:
                LOG.debug("%s (%.0f ms)", label, ms)
            else:
                LOG.debug("%s failed after %.0f ms: %s: %s", label, ms, et.__name__, ev)
            return False
    return _T()


def thread_name() -> str:
    return threading.current_thread().name
