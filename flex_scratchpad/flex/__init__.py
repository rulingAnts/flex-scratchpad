"""FlexService: the one object the Api talks to for anything FieldWorks.

It owns the current backend (flexicon LCM, a .flextext file, or the demo), the snapshot cache in
the notebook, the audio clip cache, media-file mappings, and FLEx hyperlink resolution. Every
successful fetch is snapshotted; every failed one falls back to the snapshot (marked `cached`).
"""
from __future__ import annotations

import re
import threading
from pathlib import Path

from . import model
from .audio import cut_clip, store_clip_bytes
from .cache import SnapshotCache
from .lcm import FlexError

EMBED_RE = re.compile(r"\{\{\s*flex:(entry|sense|text|wordform)\s+([0-9a-fA-F-]{36})", re.I)
# the whole embed, for refresh-all: kind, guid and the rest of the spec (seg= / at= are read out of it)
EMBED_FULL_RE = re.compile(r"\{\{\s*flex:(entry|sense|text|wordform)\s+([0-9a-fA-F-]{36})([^}]*)\}\}", re.I)
LINK_RE = re.compile(r"\(flex:(entry|sense|text|wordform)/([0-9a-fA-F-]{36})", re.I)


import unicodedata as _ud


def _depunct(s: str) -> str:
    return " ".join("".join(c for c in s if not _ud.category(c).startswith("P")).split())


def _text_score(q: str, hay: str) -> int:
    """3 = equal, 2 = one contains the other (and the query is substantial), else 0."""
    if not q or not hay:
        return 0
    if q == hay:
        return 3
    substantial = len(q) >= 6 or " " in q
    if substantial and (q in hay or (hay in q and len(hay) >= 6)):
        return 2
    return 0


def _query_score(q: dict, baseline: str, free: str) -> int:
    """A segment query {base, free} against a segment: the baseline match (or, for a
    translation-only query, the free match) plus a bonus when the free translation agrees."""
    base = _text_score(q.get("base", ""), baseline) if q.get("base") else 0
    fr = _text_score(q.get("free", ""), free) if q.get("free") else 0
    if q.get("base"):
        return base + (1 if fr else 0) if base else 0
    return 1 if fr else 0


class FlexService:
    def __init__(self, notebook, progress=None):
        self.nb = notebook
        self.cache = SnapshotCache(notebook.cache_dir)
        self.backend = None
        self.lock = threading.RLock()
        self.progress = progress or (lambda msg: None)
        self.last_error: str = ""
        self.last_error_code: str = ""

    # -- configuration -----------------------------------------------------------

    @property
    def flex_config(self) -> dict:
        return self.nb.config.setdefault("flex", {"source": "lcm", "project": "", "flextextPath": ""})

    @property
    def media_config(self) -> dict:
        return self.nb.config.setdefault("media", {"byGuid": {}, "folders": []})

    @property
    def project_name(self) -> str:
        if self.backend is not None and getattr(self.backend, "project_name", ""):
            return self.backend.project_name
        return self.flex_config.get("project", "") or "project"

    def status(self) -> dict:
        with self.lock:
            cfg = dict(self.flex_config)
            st = {"source": cfg.get("source", "lcm"), "project": cfg.get("project", ""),
                  "flextextPath": cfg.get("flextextPath", ""), "open": False, "error": self.last_error,
                  "errorCode": self.last_error_code, "backend": None,
                  "configured": bool(cfg.get("project") or cfg.get("flextextPath") or cfg.get("source") == "demo")}
            if self.backend is not None:
                try:
                    st.update(self.backend.status())
                    st["backend"] = self.backend.kind
                except Exception as e:  # noqa: BLE001
                    st["error"] = str(e)
            return st

    def configure(self, source: str | None = None, project: str | None = None,
                  flextext_path: str | None = None) -> dict:
        with self.lock:
            cfg = self.flex_config
            if source is not None:
                cfg["source"] = source
            if project is not None:
                cfg["project"] = project
            if flextext_path is not None:
                cfg["flextextPath"] = flextext_path
            self.nb.save_config()
            return self.status()

    def list_projects(self) -> list[str]:
        with self.lock:
            src = self.flex_config.get("source", "lcm")
            if src == "demo":
                from .demo import DemoBackend
                return DemoBackend().list_projects()
            from .lcm import FlexiconBackend
            be = self.backend if isinstance(self.backend, FlexiconBackend) else FlexiconBackend(progress=self.progress)
            try:
                return be.list_projects()
            finally:
                if be is not self.backend:
                    be.close()

    # -- opening ----------------------------------------------------------------

    def open(self) -> dict:
        """(Re)open the configured source. Errors become plain messages in status().error."""
        with self.lock:
            self.close()
            cfg = self.flex_config
            src = cfg.get("source", "lcm")
            self.last_error = ""
            self.last_error_code = ""
            try:
                if src == "demo":
                    from .demo import DemoBackend
                    self.backend = DemoBackend(media_dir=self.nb.private_dir / "demo-media",
                                               media_map=self.media_config.get("byGuid", {}))
                elif src == "flextext":
                    from .flextext import FlextextBackend
                    path = cfg.get("flextextPath", "")
                    if not path:
                        raise FlexError("Choose a .flextext file in Settings first.", "", "no-file")
                    self.backend = FlextextBackend(path, media_folders=self.media_config.get("folders", []))
                    self.backend.project_name = cfg.get("project") or self.backend.project_name
                else:
                    from .lcm import FlexiconBackend
                    name = cfg.get("project", "")
                    if not name:
                        raise FlexError("Choose a FieldWorks project in Settings first.", "", "no-project")
                    be = FlexiconBackend(media_map=self.media_config.get("byGuid", {}),
                                         media_folders=self.media_config.get("folders", []),
                                         progress=self.progress)
                    be.open(name)
                    self.backend = be
            except FlexError as e:
                self.last_error = e.message
                self.last_error_code = e.code
                self.backend = None
            except Exception as e:  # noqa: BLE001
                self.last_error = f"Could not open the FLEx source: {e}"
                self.last_error_code = "lcm"
                self.backend = None
            return self.status()

    def close(self) -> None:
        with self.lock:
            if self.backend is not None:
                try:
                    self.backend.close()
                except Exception:  # noqa: BLE001
                    pass
                self.backend = None

    def refresh(self) -> dict:
        with self.lock:
            if self.backend is not None and hasattr(self.backend, "refresh"):
                try:
                    self.backend.refresh()
                except FlexError as e:
                    self.last_error = e.message
            return self.status()

    def _live(self):
        if self.backend is None:
            raise FlexError(self.last_error or "No FLEx source is open.", "", "closed")
        return self.backend

    # -- objects ----------------------------------------------------------------

    def get_object(self, kind: str, guid: str, seg_from: int | None = None, seg_to: int | None = None,
                   prefer_cache: bool = False, ws: dict | None = None, at: list | None = None) -> dict:
        """Live object (snapshotted on the way through) or the snapshot when live fails.
        `ws` pins a writing system per interlinear line ({"txt": "fau-fonipa", "gls": "id"});
        such a selection is snapshotted under its own variant key."""
        kind = "entry" if kind == "sense" else kind
        guid = (guid or "").lower()
        ws = {k: v for k, v in (ws or {}).items() if v} or None
        variant = guid if not ws else guid + "~" + "-".join(k + "_" + v for k, v in sorted(ws.items())).lower()
        with self.lock:
            live_err = None
            if not prefer_cache:
                try:
                    be = self._live()
                    if kind == "entry":
                        obj = be.get_entry(guid)
                        self.cache.put(self.project_name, "entry", guid, obj)
                    elif kind == "text":
                        obj = be.get_text(guid, seg_from, seg_to, ws=ws, at=at)
                        self.cache.merge_text(self.project_name, variant, obj)
                    elif kind == "wordform":
                        obj = be.get_wordform(guid)
                        self.cache.put(self.project_name, "wordform", guid, obj)
                    else:
                        raise FlexError(f"Unknown object kind: {kind}", "", "kind")
                    obj = dict(obj)
                    obj["cached"] = False
                    return obj
                except FlexError as e:
                    live_err = e
                except Exception as e:  # noqa: BLE001
                    live_err = FlexError(str(e), "", "lcm")
            snap = self.cache.get(self.project_name, kind, variant) or self.cache.find(kind, variant) \
                or (self.cache.get(self.project_name, kind, guid) or self.cache.find(kind, guid) if ws else None)
            if snap:
                if kind == "text":
                    segs = snap.get("segments", [])
                    # the snapshot keeps the text's segment index, so anchors resolve offline too
                    r = model.resolve_range(snap.get("index") or model.index_of_segments(segs), seg_from, seg_to, at)
                    sf, st = (r["from"], r["to"]) if (seg_to or at) else (seg_from, seg_to)
                    want = [s for s in segs if (sf is None or s["n"] >= sf) and (st is None or s["n"] <= st)]
                    out = dict(snap)
                    out["segments"] = want[:60]
                    out["range"] = [want[0]["n"], want[-1]["n"]] if want else [0, 0]
                    out["partial"] = len(want) != ((st or (segs[-1]["n"] if segs else 0)) - (sf or 1) + 1)
                    out["anchors"] = model.anchors_for(out["segments"])
                    out["rangeMoved"] = bool(r["moved"])
                    out["anchorsLost"] = bool(r["lost"])
                    snap = out
                snap["cached"] = True
                snap["liveError"] = live_err.message if live_err else ""
                return snap
            if live_err:
                raise live_err
            raise FlexError("Not in the FLEx project and not cached.", "", "missing")

    def refresh_all(self, bodies: list[str]) -> dict:
        """Re-fetch every FLEx object embedded anywhere in the notebook from the live project
        (Seth, 2026-10-13: "a refresh all that goes through ALL examples everywhere"), so the
        snapshots are current. Returns {objects, refreshed, failed: [{kind, guid, error}]}."""
        wanted: dict = {}
        for body in bodies:
            for m in EMBED_FULL_RE.finditer(body or ""):
                kind, guid, rest = m.group(1).lower(), m.group(2).lower(), m.group(3) or ""
                kind = "entry" if kind == "sense" else kind
                seg = re.search(r"\bseg=(\d+)(?:-(\d+))?", rest)
                at = re.search(r"\bat=([0-9a-fA-F]+)(?:-([0-9a-fA-F]+))?", rest)
                ws = re.search(r"\bws=(\S+)", rest)
                a = int(seg.group(1)) if seg else None
                b = int(seg.group(2) or seg.group(1)) if seg else None
                wsd = None
                if ws:
                    wsd = {}
                    for item in ws.group(1).split(","):
                        if ":" in item:
                            k, v = item.split(":", 1)
                            wsd[k.strip().lower()] = v.strip()
                key = (kind, guid, a, b, tuple(sorted((wsd or {}).items())))
                wanted[key] = (kind, guid, a, b, wsd or None, [at.group(1), at.group(2) or at.group(1)] if at else None)
        out = {"objects": len(wanted), "refreshed": 0, "failed": []}
        for kind, guid, a, b, wsd, at in wanted.values():
            try:
                self.get_object(kind, guid, a, b, prefer_cache=False, ws=wsd, at=at)
                out["refreshed"] += 1
            except FlexError as e:
                out["failed"].append({"kind": kind, "guid": guid, "error": e.message})
            except Exception as e:  # noqa: BLE001
                out["failed"].append({"kind": kind, "guid": guid, "error": str(e)})
        return out

    def search_entries(self, q: str, limit: int = 30) -> list[dict]:
        with self.lock:
            return self._live().search_entries(q, limit)

    def list_texts(self) -> list[dict]:
        with self.lock:
            return self._live().list_texts()

    def search_texts(self, q: str) -> list[dict]:
        with self.lock:
            return self._live().search_texts(q)

    def find_in_text(self, guid: str, phrase: str) -> list[int]:
        """Segment numbers whose baseline or free translation contains the phrase (normalised)."""
        from ..notebook import normalize
        strip = bool(self.nb.config.get("settings", {}).get("diacriticsInsensitive", True))
        needle = normalize(phrase or "", strip)
        if not needle:
            return []
        with self.lock:
            page = self._live().get_text(guid, 1, None, max_segments=100000)
        return [s["n"] for s in page["segments"]
                if needle in normalize(s["baseline"], strip) or needle in normalize(s.get("free", ""), strip)]

    # Row labels FLEx writes when interlinear lines are copied; lines so labelled are either
    # vernacular (kept for matching) or something else (dropped).
    _ROW_KEEP = ("word", "free", "baseline", "words")
    _ROW_DROP = ("morphemes", "lex. entries", "lex entries", "lex. gloss", "lex gloss", "lex. gram. info",
                 "word gloss", "word cat.", "word cat", "literal", "note", "notes", "gloss", "category")

    def locate(self, pasted: str, limit: int = 5) -> list[dict]:
        """Where in the project do these pasted interlinear lines come from?
        FLEx's labelled rows (Word / Morphemes / Free …) all describe ONE segment: the Word row
        is its baseline, the Free row its translation; unlabelled lines are taken as one
        segment each, in order. Matching is normalised and diacritics-insensitive, with
        punctuation ignored. Returns candidates [{guid, title, seg, segTo, score, matched, of}]."""
        from ..notebook import normalize
        strip = bool(self.nb.config.get("settings", {}).get("diacriticsInsensitive", True))
        norm = lambda t: _depunct(normalize(" ".join((t or "").split()), strip))  # noqa: E731
        queries: list[dict] = []
        for raw in (pasted or "").replace("\r\n", "\n").split("\n"):
            line = raw.strip()
            if not line:
                continue
            cells = [c.strip() for c in line.split("\t")]
            # FLEx's Gloss / Print views lead each block with the segment number ("4.1") — as
            # its own cell or glued to the label ("4.1 Word") — and end the Word row with the
            # paragraph mark "§"; neither is text to match (Seth, 2026-10-13: a pasted range
            # only found its first segment)
            if cells and re.fullmatch(r"\d+(\.\d+)?", cells[0]) and len(cells) > 1:
                cells = cells[1:]
            elif cells:
                m = re.match(r"^\d+(?:\.\d+)?\s+(\S.*)$", cells[0])
                if m and len(cells) > 1:
                    cells[0] = m.group(1)
            cells = [c for c in cells if c not in ("§", "¶")]
            if not cells:
                continue
            label = cells[0].rstrip(":").casefold() if len(cells) > 1 else ""
            if label and (label in self._ROW_DROP or any(label.startswith(d) for d in self._ROW_DROP)):
                continue
            is_free = label.startswith("free")
            labelled = bool(label) and (is_free or label in self._ROW_KEEP or any(label.startswith(k + " ") for k in self._ROW_KEEP))
            words = [c for c in (cells[1:] if labelled else cells) if c]
            if not words:
                continue
            text = " ".join(words)
            if len(text) > 400:
                return []
            if is_free:
                if queries and not queries[-1].get("free"):
                    queries[-1]["free"] = norm(text)
                else:
                    queries.append({"base": "", "free": norm(text)})
            else:
                queries.append({"base": norm(text), "free": ""})
        queries = [q for q in queries if q["base"] or q["free"]]
        if not queries:
            return []
        with self.lock:
            be = self._live()
            index = be.all_baselines()
        hits = []
        for guid, t in index.items():
            segs = [(n, norm(b), norm(f)) for n, b, f in t["segments"]]
            for i, (n, nb, nf) in enumerate(segs):
                sc = _query_score(queries[0], nb, nf)
                if sc <= 0:
                    continue
                score, last, k, j = sc, n, 1, i + 1
                while k < len(queries) and j < len(segs):
                    s2 = _query_score(queries[k], segs[j][1], segs[j][2])
                    if s2 <= 0:
                        break
                    score += s2
                    last = segs[j][0]
                    k += 1
                    j += 1
                hits.append({"guid": guid, "title": t["title"], "seg": n, "segTo": last, "score": score, "matched": k, "of": len(queries)})
        hits.sort(key=lambda h: (-h["score"], -h["matched"], h["title"]))
        return hits[:limit]

    def resolve_link(self, text: str) -> dict | None:
        """A pasted FLEx hyperlink or bare GUID → {kind, guid, title, seg?, sense?, database?}."""
        s = (text or "").strip()
        info = model.parse_silfw(s)
        guid = info["guid"] if info else (s.lower() if model.is_guid(s) else None)
        if not guid:
            return None
        with self.lock:
            out = None
            if self.backend is not None:
                try:
                    out = self.backend.resolve_guid(guid)
                except Exception:  # noqa: BLE001
                    out = None
            if out is None:
                for kind in ("entry", "text", "wordform"):
                    snap = self.cache.find(kind, guid)
                    if snap:
                        out = {"kind": kind, "guid": guid, "title": snap.get("headword") or snap.get("title") or snap.get("form", ""), "cached": True}
                        break
            if out is None and info:
                tool = info.get("tool", "")
                kind = "text" if tool == "interlinearEdit" else "wordform" if tool == "Analyses" else "entry"
                out = {"kind": kind, "guid": guid, "title": "", "unresolved": True}
            if out is not None and info:
                out["database"] = info.get("database", "")
                out["url"] = s
            return out

    # -- search index support -----------------------------------------------------

    def searchable_text_for_body(self, body: str) -> str:
        parts = []
        seen = set()
        for m in list(EMBED_RE.finditer(body or "")) + list(LINK_RE.finditer(body or "")):
            kind, guid = m.group(1).lower(), m.group(2).lower()
            kind = "entry" if kind == "sense" else kind
            if (kind, guid) in seen:
                continue
            seen.add((kind, guid))
            snap = self.cache.find(kind, guid)
            if snap:
                parts.append(model.searchable_text(snap))
        return " ".join(parts)

    # -- media / audio --------------------------------------------------------------

    def _media_for(self, text_guid: str, media_guid: str | None) -> dict | None:
        """The media record of a text, live or cached."""
        try:
            obj = self.get_object("text", text_guid, 1, 1)
        except FlexError:
            return None
        media = obj.get("media", [])
        if media_guid:
            for m in media:
                if m.get("guid") == media_guid:
                    return m
        return media[0] if media else None

    def ensure_clip(self, text_guid: str, media_guid: str | None, begin: int, end: int) -> dict:
        """Where the UI can play this range from: the live media file, and/or a cached clip
        (cut now if the Python cutters can do it; else the UI records it and stores it)."""
        begin, end = int(begin), int(end)
        with self.lock:
            m = self._media_for(text_guid, media_guid) or {}
            found = bool(m.get("found")) and Path(m.get("path", "")).is_file()
            clip = self.cache.find_audio_clip(self.project_name, text_guid, begin, end)
            if not clip and found:
                from .audio import find_ffmpeg
                dst = self.cache.audio_clip_path(self.project_name, text_guid, begin, end, ".wav")
                clip = cut_clip(m["path"], dst, begin, end, find_ffmpeg(self.nb.config.get("settings", {}).get("ffmpegPath", "")))
            return {
                "found": found,
                "fileUrl": Path(m["path"]).resolve().as_uri() if found else "",
                "path": m.get("path", "") if found else "",
                "uri": m.get("uri", ""),
                "mediaGuid": m.get("guid", media_guid or ""),
                "clipUrl": clip.resolve().as_uri() if clip else "",
                "clipPath": str(clip) if clip else "",
                "needsCapture": bool(found and not clip),
            }

    def store_captured_clip(self, text_guid: str, begin: int, end: int, data_base64: str, mime: str = "audio/webm") -> dict:
        ext = ".webm" if "webm" in mime else ".ogg" if "ogg" in mime else ".wav" if "wav" in mime else ".bin"
        with self.lock:
            dst = self.cache.audio_clip_path(self.project_name, text_guid, int(begin), int(end), ext)
            store_clip_bytes(dst, data_base64)
            return {"clipUrl": dst.resolve().as_uri(), "clipPath": str(dst)}

    def set_media_path(self, media_guid: str, path: str) -> dict:
        """The user browsed for the real media file: remember it (and its folder for siblings)."""
        with self.lock:
            mc = self.media_config
            mc.setdefault("byGuid", {})[media_guid] = path
            folder = str(Path(path).parent)
            if folder not in mc.setdefault("folders", []):
                mc["folders"].append(folder)
            self.nb.save_config()
            if self.backend is not None and hasattr(self.backend, "set_media_map"):
                self.backend.set_media_map(mc["byGuid"])
                if hasattr(self.backend, "media_folders"):
                    self.backend.media_folders = list(mc["folders"])
            return mc
