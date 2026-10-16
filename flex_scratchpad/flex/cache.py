"""Snapshot cache: every FLEx object the notebook has rendered, saved as JSON under
`<notebook>/.scratchpad/flex-cache/<project>/`, so a note still displays when the project is
not open (another machine, FLEx closed, flexicon missing). The UI shows such objects with a
"cached" badge and a refresh button. Audio clips cut for timed segments live beside them.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

_SAFE = re.compile(r"[^\w.\-~]+", re.UNICODE)


def _safe(s: str) -> str:
    return _SAFE.sub("_", s or "project").strip("_") or "project"


class SnapshotCache:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def project_dir(self, project: str) -> Path:
        return self.root / _safe(project)

    def _path(self, project: str, kind: str, guid: str) -> Path:
        return self.project_dir(project) / f"{kind}-{_SAFE.sub('_', (guid or '').lower())}.json"

    def put(self, project: str, kind: str, guid: str, obj: dict) -> None:
        p = self._path(project, kind, guid)
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(obj)
        payload["cachedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        tmp = p.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, p)

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

    def merge_text(self, project: str, guid: str, page: dict) -> dict:
        """Texts are fetched a segment range at a time; the snapshot accumulates every range
        seen so far (keyed by segment number) so a note with several embeds stays whole."""
        existing = self.get(project, "text", guid) or {}
        segs = {s["n"]: s for s in existing.get("segments", [])}
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
