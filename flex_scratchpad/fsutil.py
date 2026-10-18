"""Small file helpers shared by every module that writes a file atomically.

`replace_file` is `os.replace` with patience for Windows: a target another thread or process
has open for READING cannot be replaced there (the handle is opened without sharing deletes),
and the call fails with "Access is denied" — Seth hit it twice on 2026-10-19, on a FLEx snapshot
two examples wrote at the same moment and on config.json while the backup on close recorded
its result. A few short retries ride out a reader; a writer is kept out by each module's lock.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

TRIES = 8


def replace_file(tmp: str | Path, dst: str | Path, tries: int = TRIES) -> None:
    """Move `tmp` over `dst` atomically, retrying a PermissionError (Windows: the target is open
    elsewhere) with a short, growing pause; the temporary file is removed when every try fails."""
    for attempt in range(tries):
        try:
            os.replace(tmp, dst)
            return
        except PermissionError:
            if attempt == tries - 1:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
            time.sleep(0.03 * (attempt + 1))
