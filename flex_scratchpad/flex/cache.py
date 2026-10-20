"""Snapshot cache: every FLEx object the notebook has rendered, saved as JSON under
`<notebook>/.scratchpad/flex-cache/<project>/`, so a note still displays when the project is
not open (another machine, FLEx closed, flexicon missing). The UI shows such objects with a
"cached" badge and a refresh button. Audio clips cut for timed segments live beside them.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path

from ..fsutil import replace_file

_SAFE = re.compile(r"[^\w.\-~]+", re.UNICODE)


def _safe(s: str) -> str:
    return _SAFE.sub("_", s or "project").strip("_") or "project"


class SnapshotCache:
    def __init__(self, root: str | Path):
        self._lock = threading.RLock()
        self.root = Path(root)

    def project_dir(self, project: str) -> Path:
        return self.root / _safe(project)

    def _path(self, project: str, kind: str, guid: str) -> Path:
        return self.project_dir(project) / f"{kind}-{_SAFE.sub('_', (guid or '').lower())}.json"

    def put(self, project: str, kind: str, guid: str, obj: dict) -> None:
        """Write a snapshot atomically. ONE writer at a time (pywebview calls the Api on many
        threads at once: a note with twelve examples of one text wrote the same file from twelve
        threads, and on Windows the second `os.replace` failed with "Access is denied" while the
        first still had the file open — Seth, 2026-10-19); the replace is retried a few times for
        a reader that has the file open at that moment."""
        p = self._path(project, kind, guid)
        payload = dict(obj)
        payload["cachedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        with self._lock:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_name(p.name + f".{threading.get_ident()}.tmp")
            with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                json.dump(payload, f, ensure_ascii=False)
            replace_file(tmp, p)

    def get(self, project: str, kind: str, guid: str) -> dict | None:
        p = self._path(project, kind, guid)
        try:
            with open(p, "r", encoding="utf-8") as f:
                obj = json.load(f)
        except (OSError, ValueError):
            return None
        obj["cached"] = True
        return obj

    def find(self, kind: str, guid: str) -> dict | None:
        """Any project's snapshot of this guid (guids are globally unique; useful when no
        project is open at all)."""
        if not self.root.is_dir():
            return None
        for d in sorted(self.root.iterdir()):
            if d.is_dir():
                obj = self.get(d.name, kind, guid)
                if obj:
                    return obj
        return None

    def ledger_path(self, project: str, text_guid: str) -> Path:
        return self.project_dir(project) / f"ledger-{_SAFE.sub('_', (text_guid or '').lower())}.json"

    def merge_text(self, project: str, guid: str, page: dict) -> dict:
        """Texts are fetched a segment range at a time; the snapshot accumulates every range
        seen so far (keyed by segment number) so a note with several embeds stays whole."""
        with self._lock:                      # read-modify-write as one step
            return self._merge_text(project, guid, page)

    def _merge_text(self, project: str, guid: str, page: dict) -> dict:
        existing = self.get(project, "text", guid) or {}
        segs = {s["n"]: s for s in existing.get("segments", [])}
        # after FLEx renumbered the text, an old snapshot's segment 5 is not the new segment 5:
        # keep only those the new index still has at that number (Seth, 2026-10-17)
        now = {e.get("n"): (e.get("guid") or "").lower() for e in page.get("index") or []}
        if now:
            segs = {n: s for n, s in segs.items() if now.get(n) == (s.get("guid") or "").lower()}
        for s in page.get("segments", []):
            segs[s["n"]] = s
        merged = dict(page)
        merged.pop("cached", None)
        merged.pop("range", None)
        merged["segments"] = [segs[k] for k in sorted(segs)]
        self.put(project, "text", guid, merged)
        return merged

    def audio_dir(self, project: str) -> Path:
        return self.project_dir(project) / "audio"

    def audio_clip_path(self, project: str, text_guid: str, begin: int, end: int, ext: str) -> Path:
        return self.audio_dir(project) / f"{(text_guid or '').lower()}_{int(begin)}-{int(end)}{ext}"

    def find_audio_clip(self, project: str, text_guid: str, begin: int, end: int) -> Path | None:
        d = self.audio_dir(project)
        if not d.is_dir():
            return None
        stem = f"{(text_guid or '').lower()}_{int(begin)}-{int(end)}"
        for p in d.iterdir():
            if p.stem == stem and p.is_file():
                return p
        return None
