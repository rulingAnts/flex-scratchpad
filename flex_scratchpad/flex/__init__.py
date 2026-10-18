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
from ..log import LOG
from .audio import cut_clip, store_clip_bytes
from .cache import SnapshotCache
from .lcm import FlexError

EMBED_RE = re.compile(r"\{\{\s*flex:(entry|sense|text|wordform|chart)\s+([0-9a-fA-F-]{36})", re.I)
# the whole embed, for refresh-all: kind, guid and the rest of the spec (seg= / at= are read out of it)
EMBED_FULL_RE = re.compile(r"\{\{\s*flex:(entry|sense|text|wordform|chart)\s+([0-9a-fA-F-]{36})([^}]*)\}\}", re.I)
LINK_RE = re.compile(r"\(flex:(entry|sense|text|wordform|chart)/([0-9a-fA-F-]{36})", re.I)


import unicodedata as _ud


def _depunct(s: str) -> str:
    return " ".join("".join(c for c in s if not _ud.category(c).startswith("P")).split())


def _joined(s: str) -> str:
    """Letters, digits and marks only: morpheme forms ('ka- nuwa =mo') against a baseline word
    ('ka-nuwa=mo' / 'kanuwamo'), with every break character, space and clitic marker gone."""
    return "".join(c for c in s if c.isalnum() or _ud.category(c).startswith("M"))


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


LOCATE_GAP = 3   # segments of the text a pasted range may skip between two of its own


def _pinned(rows: list, i0: int, i1: int) -> dict:
    """What pins a located range to its segments, whatever the numbering: FLEx's own numbers
    (for the dialog) and the first and last segment's GUID anchors (for the embed's `at=`,
    which wins over `seg=` when the example is drawn — Seth, 2026-10-16: the dialog showed the
    right line but the example came out two lines above)."""
    out: dict = {}
    a, b = rows[i0], rows[i1]
    if len(a) > 5 and len(b) > 5 and a[5] and b[5]:
        out["label"], out["labelTo"] = str(a[5]), str(b[5])
    if len(a) > 6 and len(b) > 6 and a[6] and b[6]:
        out["at"] = [model.anchor_of(a[6]), model.anchor_of(b[6])]
    return out


def _label_key(label: str) -> str:
    """FLEx's segment number as a key: "13" (a paragraph of one segment) is "13.1"."""
    s = str(label or "").strip().rstrip(".")
    return s if "." in s else s + ".1"


def _query_score(q: dict, baseline: str, free: str, morphs: str = "", glosses: str = "") -> int:
    """A segment query {bases, morphs, glosses, free} against a segment: the best baseline
    match over the Word rows; without a Word row the Morphemes rows against the segment's own
    morpheme line, then the Lex. Gloss rows against its gloss line; a translation-only query
    matches the free translation. Agreeing glosses / free translation add a bonus each."""
    bases, morphs_q, gloss_q = q.get("bases") or [], q.get("morphs") or [], q.get("glosses") or []
    base = max((_text_score(b, baseline) for b in bases), default=0)
    if not bases and morphs_q:
        # the segment's own Morphemes line (the forms need not spell the baseline word: an
        # underlying form, another writing system); the baseline only when the index has none
        hay = morphs or _joined(baseline)
        base = max((_text_score(m, hay) for m in morphs_q), default=0)
        if not base and morphs:
            base = max((_text_score(m, _joined(baseline)) for m in morphs_q), default=0)
    gl = max((_text_score(g, glosses) for g in gloss_q), default=0) if gloss_q and glosses else 0
    fr = _text_score(q.get("free", ""), free) if q.get("free") else 0
    if bases or morphs_q:
        return base + (1 if fr else 0) + (1 if gl else 0) if base else 0
    if gloss_q:
        return gl + (1 if fr else 0) if gl else 0
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
        self._chart_rows: list[dict] | None = None     # the chart search index (chart_rows)

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
            self._chart_rows = None
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
                LOG.warning("FLEx source not opened (%s): %s%s", e.code, e.message, (" — " + e.detail[:300]) if e.detail else "")
            except Exception as e:  # noqa: BLE001
                self.last_error = f"Could not open the FLEx source: {e}"
                self.last_error_code = "lcm"
                self.backend = None
                LOG.exception("FLEx source not opened")
            st = self.status()
            LOG.info("FLEx source: %s project=%r open=%s", st.get("source"), st.get("project"), st.get("open"))
            return st

    def close(self) -> None:
        with self.lock:
            if self.backend is not None:
                try:
                    self.backend.close()
                except Exception:  # noqa: BLE001
                    pass
                self.backend = None

    def refresh(self, indexes: bool = True) -> dict:
        with self.lock:
            if indexes:
                self._chart_rows = None          # the chart search index is rebuilt at the next search
            if self.backend is not None and hasattr(self.backend, "refresh"):
                try:
                    self.backend.refresh() if indexes else self.backend.refresh(indexes=False)
                except FlexError as e:
                    self.last_error = e.message
            return self.status()

    def _live(self):
        if self.backend is None:
            raise FlexError(self.last_error or "No FLEx source is open.", "", "closed")
        return self.backend

    # -- objects ----------------------------------------------------------------

    def get_object(self, kind: str, guid: str, seg_from: int | None = None, seg_to: int | None = None,
                   prefer_cache: bool = False, ws: dict | None = None, at: list | None = None, alts: bool = False) -> dict:
        """Live object (snapshotted on the way through) or the snapshot when live fails.
        `ws` pins a writing system per interlinear line ({"txt": "fau-fonipa", "gls": "id"});
        such a selection is snapshotted under its own variant key."""
        kind = "entry" if kind == "sense" else kind
        guid = (guid or "").lower()
        ws = {k: v for k, v in (ws or {}).items() if v} or None
        variant = guid if not ws else guid + "~" + "-".join(k + "_" + v for k, v in sorted(ws.items())).lower()
        if alts:
            variant += "~alts"          # every writing system: its own snapshot, never the lean one
        with self.lock:
            live_err = None

            def keep(write):
                # the snapshot is a convenience: a write that fails (a locked file, a full disk)
                # must never turn a good live read into "showing the snapshot" (Seth, 2026-10-19)
                try:
                    write()
                except Exception as e:  # noqa: BLE001
                    LOG.warning("%s %s: snapshot not written: %s", kind, guid[:8], e)

            if not prefer_cache:
                try:
                    be = self._live()
                    if kind == "entry":
                        obj = be.get_entry(guid)
                        keep(lambda: self.cache.put(self.project_name, "entry", guid, obj))
                    elif kind == "text":
                        obj = self._tracked_text(be, guid, seg_from, seg_to, ws, at, alts)
                        if not obj.get("lost"):
                            keep(lambda: self.cache.merge_text(self.project_name, variant, obj))
                    elif kind == "wordform":
                        obj = be.get_wordform(guid)
                        keep(lambda: self.cache.put(self.project_name, "wordform", guid, obj))
                    elif kind == "chart":
                        # the whole chart is read and snapshotted (charts are small); the embed's rows are sliced here
                        whole = be.get_chart(guid)
                        keep(lambda: self.cache.put(self.project_name, "chart", guid, whole))
                        obj = model.slice_chart(whole, seg_from, seg_to, at)
                    else:
                        raise FlexError(f"Unknown object kind: {kind}", "", "kind")
                    obj = dict(obj)
                    obj["cached"] = False
                    if kind == "text":
                        obj["chartSpans"] = self._chart_spans(guid)
                    return obj
                except FlexError as e:
                    live_err = e
                except Exception as e:  # noqa: BLE001
                    LOG.exception("%s %s: the live fetch failed", kind, guid[:8])
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
                elif kind == "chart":
                    snap = model.slice_chart(snap, seg_from, seg_to, at)
                snap["cached"] = True
                if kind == "text":
                    snap["chartSpans"] = self._chart_spans(guid)
                snap["liveError"] = live_err.message if live_err else ""
                LOG.info("%s %s: showing the snapshot (%s)", kind, guid[:8], live_err.message if live_err else "cache preferred")
                return snap
            if live_err:
                raise live_err
            raise FlexError("Not in the FLEx project and not cached.", "", "missing")

    def _tracked_text(self, be, guid: str, seg_from, seg_to, ws, at, alts: bool) -> dict:
        """The text range an embed asks for, kept on ITS lines when FLEx has changed the text
        (flex/tracking.py): the backend first follows the `at=` anchors; the ledger then
        widens / narrows / re-finds the range for split, merged, deleted or rebuilt segments
        and says how each of the embed's old segments maps now (`track`), so the page can move
        the embed's highlights with them. Lines that cannot be found come back as the saved
        copy, marked `lost`, never as whatever now has their numbers."""
        from . import tracking

        def get(a, b, anchors):
            return be.get_text(guid, a, b, ws=ws, at=anchors, alts=alts) if alts else be.get_text(guid, a, b, ws=ws, at=anchors)

        obj = get(seg_from, seg_to, at)
        ledger = tracking.Ledger(self.cache.ledger_path(self.project_name, guid))
        tr = None
        if seg_from and ledger.orders:
            texts = (lambda: be.text_baselines(guid)) if hasattr(be, "text_baselines") else (lambda: {})
            try:
                seen = {model.anchor_of(x.get("guid", "")): x.get("baseline", "") for x in obj.get("segments") or []}
                tr = tracking.track(ledger, obj.get("index") or [], texts, seg_from, seg_to, at, seen)
            except Exception:  # noqa: BLE001 — tracking must never stop a text from showing
                tr = None
        if tr:
            if tr["change"] == "lost":
                saved = [x for x in tr.get("saved") or [] if x]
                obj = dict(obj)
                obj["segments"] = saved
                obj["range"] = [int(seg_from), int(seg_to or seg_from)]
                obj["anchors"] = list(at or [])
                obj["lost"] = True
                obj["rangeMoved"] = False
            elif tr["change"] in ("reshaped", "found") and [tr["from"], tr["to"]] != list(obj.get("range") or []):
                obj = get(tr["from"], tr["to"], None)
            if tr["change"] in ("moved", "reshaped", "found"):
                obj["rangeMoved"] = [int(seg_from), int(seg_to or seg_from)] != list(obj.get("range") or [])
            obj["track"] = {k: tr[k] for k in ("change", "how", "map", "oldWords")}
        if not obj.get("lost"):
            try:
                ledger.record(obj.get("index") or [], obj.get("segments") or [])
                ledger.save()
            except OSError:
                pass
        return obj

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
        """Where in the project do these pasted interlinear lines come from? Matched against
        every segment's baseline, Morphemes line, Lex. Gloss line and free translation.
        FLEx's labelled rows (Word / Morphemes / Free …) all describe ONE segment: the Word row
        is its baseline, the Free row its translation; unlabelled lines are taken as one
        segment each, in order. Matching is normalised and diacritics-insensitive, with
        punctuation ignored. Returns candidates [{guid, title, seg, segTo, score, matched, of}]."""
        queries, norm = self._paste_queries(pasted)
        if not queries:
            return []
        with self.lock:
            be = self._live()
            index = be.all_baselines()
        hits = []
        by_label: set = set()
        for guid, t in index.items():
            segs = [(row[0], norm(row[1]), norm(row[2]), _joined(norm(row[3] if len(row) > 3 else "")), _joined(norm(row[4] if len(row) > 4 else "")))
                    for row in t["segments"]]
            # FLEx's numbers on the pasted rows say exactly which segments were copied (Seth,
            # 2026-10-16: content matching "grabbing the wrong line … two lines above"); they
            # decide the range whenever the text has them and its content there agrees
            labels = {_label_key(row[5]): i for i, row in enumerate(t["segments"]) if len(row) > 5 and row[5]}
            if queries[0].get("label") and labels:
                placed = self._place_by_labels(queries, segs, labels)
                if placed:
                    score, i0, i1, k = placed
                    hits.append(dict({"guid": guid, "title": t["title"], "seg": segs[i0][0], "segTo": segs[i1][0], "score": score, "matched": k, "of": len(queries), "byLabel": True},
                                     **_pinned(t["segments"], i0, i1)))
                    by_label.add(guid)
                    continue
            for i, (n, nb, nf, nm, ng) in enumerate(segs):
                sc = _query_score(queries[0], nb, nf, nm, ng)
                if sc <= 0:
                    continue
                score, last, k, j, skipped, li = sc, n, 1, i + 1, 0, i
                while k < len(queries) and j < len(segs):
                    # FLEx's copy can leave segments out (Seth, 2026-10-16: a paste of 12.1, 12.3,
                    # 13, 14 — no 12.2 — found only 12.1), so the next pasted segment may skip a
                    # few of the text's; the example's range still runs first to last
                    s2, step = 0, 0
                    for step in range(LOCATE_GAP + 1):
                        if j + step >= len(segs):
                            break
                        s2 = _query_score(queries[k], segs[j + step][1], segs[j + step][2], segs[j + step][3], segs[j + step][4])
                        if s2 > 0:
                            break
                    if s2 <= 0:
                        break
                    score += s2
                    skipped += step
                    last, li = segs[j + step][0], j + step
                    k += 1
                    j += step + 1
                hits.append(dict({"guid": guid, "title": t["title"], "seg": n, "segTo": last, "score": score, "matched": k, "of": len(queries), "skipped": skipped},
                                 **_pinned(t["segments"], i, li)))
        # numbered rows placed by their numbers first; then the best content match, and on a tie
        # the placement that skips the fewest of the text's segments
        hits.sort(key=lambda h: (not h.get("byLabel"), -h["score"], -h["matched"], h.get("skipped", 0), h["title"]))
        return hits[:limit]

    def explain_locate(self, pasted: str) -> dict:
        """Why a paste lands where it does (or nowhere): the rows as read, the hits, the best few
        segments for EACH pasted segment, and what every text holding the pasted FLEx numbers has
        at those numbers — raw and as normalised for matching. For `flex-scratchpad --locate`."""
        queries, norm = self._paste_queries(pasted)
        out: dict = {"queries": queries, "hits": self.locate(pasted, limit=5) if queries else []}
        if not queries:
            return out
        with self.lock:
            index = self._live().all_baselines()
        prepared = {g: [(row, (row[0], norm(row[1]), norm(row[2]), _joined(norm(row[3] if len(row) > 3 else "")),
                               _joined(norm(row[4] if len(row) > 4 else "")))) for row in t["segments"]]
                    for g, t in index.items()}
        best = []
        for k, q in enumerate(queries):
            scored = [(_query_score(q, *sg[1:]), index[g]["title"], row[5] if len(row) > 5 else "", row[0])
                      for g, rows in prepared.items() for row, sg in rows]
            scored = sorted((x for x in scored if x[0] > 0), key=lambda x: -x[0])[:5]
            best.append({"segment": k + 1, "label": q.get("label", ""),
                         "candidates": [{"score": a, "text": b, "label": c, "n": d} for a, b, c, d in scored]})
        out["bestPerSegment"] = best
        labels = [q["label"] for q in queries if q.get("label")]
        if labels:
            want = {_label_key(x) for x in labels}
            found = []
            for g, rows in prepared.items():
                sel = [(row, sg) for row, sg in rows if len(row) > 5 and _label_key(row[5]) in want]
                if not sel:
                    continue
                first = next((x for x in sel if _label_key(x[0][5]) == _label_key(labels[0])), None)
                found.append((_query_score(queries[0], *first[1][1:]) if first else 0, g, sel))
            found.sort(key=lambda x: -x[0])
            out["textsWithThoseNumbers"] = [
                {"text": index[g]["title"], "guid": g, "firstSegmentScore": s0,
                 "segments": [{"label": row[5], "n": row[0], "baseline": row[1], "baselineNorm": sg[1],
                               "morphsNorm": sg[3], "glossesNorm": sg[4], "free": row[2]} for row, sg in sel]}
                for s0, g, sel in found[:3]]
        return out

    def _paste_queries(self, pasted: str):
        """The pasted FLEx rows as segment queries [{bases, morphs, glosses, free, label}], and the
        normaliser they were made with (see locate)."""
        from ..notebook import normalize
        strip = bool(self.nb.config.get("settings", {}).get("diacriticsInsensitive", True))
        norm = lambda t: _depunct(normalize(" ".join((t or "").split()), strip))  # noqa: E731
        queries: list[dict] = []
        cur: dict | None = None
        prev_free = False            # the previous row was a Free row (a "Ind …" line continues it)

        def block() -> dict:
            nonlocal cur
            cur = {"bases": [], "morphs": [], "glosses": [], "free": ""}
            queries.append(cur)
            return cur

        # bidi format marks (U+200E/F and friends) ride along in FLEx's clipboard text
        pasted = "".join(c for c in (pasted or "") if _ud.category(c) != "Cf")
        ws_codes = self._paste_ws_codes(pasted)
        for raw in pasted.replace("\r\n", "\n").split("\n"):
            line = raw.strip()
            if not line:
                continue
            cells = [c.strip() for c in line.split("\t")]
            while cells and not cells[0]:          # a row whose number cell is empty
                cells = cells[1:]
            # FLEx's Gloss / Print views lead each block with the segment number ("4.1") — as
            # its own cell or glued to the label ("4.1 Word") — and end the Word row with the
            # paragraph mark "§"; neither is text to match (Seth, 2026-10-13: a pasted range
            # only found its first segment)
            numbered, row_label = False, ""
            if cells and re.fullmatch(r"\d+(\.\d+)?", cells[0]) and len(cells) > 1:
                row_label, cells, numbered = cells[0], cells[1:], True
            elif cells:
                m = re.match(r"^(\d+(?:\.\d+)?)\s+(\S.*)$", cells[0])
                if m and len(cells) > 1:
                    row_label, cells[0], numbered = m.group(1), m.group(2), True
            # a label followed by a space instead of a tab ("Free she caught it.")
            if len(cells) == 1:
                labels = sorted(self._ROW_KEEP + self._ROW_DROP, key=len, reverse=True)   # "word gloss" before "word"
                if cells[0].rstrip(":").casefold() in labels:
                    continue                                                                 # an empty labelled row
                m = re.match(r"^(" + "|".join(re.escape(k) for k in labels) + r")\s+(\S.*)$", cells[0], re.I)
                if m and re.fullmatch(r"[A-Za-z]{2,3}(-[\w-]+)*", m.group(2)):
                    prev_free = m.group(1).casefold() == "free"                              # "Free Eng" with nothing after it
                    continue                                                                 # "Word fau-ose" with every cell empty
                if m:
                    cells = [m.group(1), m.group(2)]
                elif prev_free:
                    # the Print view's second analysis language: "Ind <translation>" under "Free Eng …"
                    m2 = re.match(r"^([A-Za-z]{2,3})(?:\s+(\S.*))?$", cells[0])
                    if m2:
                        if m2.group(2) and cur is not None and not cur["free"]:
                            cur["free"] = norm(m2.group(2))
                        continue
            cells = [c for c in cells if c not in ("§", "¶")]
            if not cells:
                continue
            label = cells[0].rstrip(":").casefold() if len(cells) > 1 else ""
            # the Gloss / Analyze tabs suffix a label with the writing system when more than
            # one shows ("Word base", "Word fau-ose", "Morphemes fau-ose", "Word Gloss Eng"):
            # the same row in another writing system is an ALTERNATIVE of the segment, never
            # a new segment (Seth, 2026-10-13)
            key = next((k for k in sorted(self._ROW_KEEP + self._ROW_DROP, key=len, reverse=True) if label == k or label.startswith(k + " ") or label.startswith(k + ".")), "") if label else ""
            suffix = label[len(key):].lstrip(".").strip() if key else ""
            is_morph = key == "morphemes"
            is_gloss = key in ("lex. gloss", "lex gloss")
            if key and not is_morph and not is_gloss and key in self._ROW_DROP:
                continue
            is_free = key == "free"
            labelled = bool(key)
            words = [c for c in (cells[1:] if labelled else cells) if c]
            prev_free = is_free
            if not words:
                continue
            # "Free Eng So concerning…": Eng names the writing system — in a cell of its own
            # always, glued to the text when the paste names it elsewhere ("Word Gloss Eng")
            if is_free and len(words) > 1 and re.fullmatch(r"[A-Za-z]{2,3}(-[\w-]+)*", words[0]):
                words = words[1:]
            elif is_free and len(words) == 1 and " " in words[0] and words[0].split(" ", 1)[0].casefold() in ws_codes:
                words = words[0].split(" ", 1)[1:]
            text = " ".join(words)
            if len(text) > 400:
                return [], norm
            if is_free:
                if cur is not None and not cur["free"] and not numbered:
                    cur["free"] = norm(text)
                else:
                    block()["free"] = norm(text)
            elif is_morph:
                # no Word row copied: the morpheme forms match the segment's own Morphemes line
                if cur is None or numbered or cur["free"] or (cur["morphs"] and not suffix):
                    block()
                cur["morphs"].append(_joined(norm(text)))
            elif is_gloss:
                if cur is None or numbered or cur["free"] or (cur["glosses"] and not suffix):
                    block()
                g = _joined(norm(" ".join(w for w in words if w.strip("*"))))   # *** = no gloss
                if g:
                    cur["glosses"].append(g)
            else:
                if cur is None or numbered or cur["free"] or not labelled or not (suffix and cur["bases"]):
                    block()
                cur["bases"].append(norm(text))
            if numbered and cur is not None and not cur.get("label"):
                cur["label"] = row_label          # FLEx's own number for this segment ("12.3", "13")
        queries = [q for q in queries if q["bases"] or q["morphs"] or q["glosses"] or q["free"]]
        return queries, norm

    def _paste_ws_codes(self, pasted: str) -> set:
        """The writing-system codes the pasted rows name ("Word Gloss Eng", a lone "Ind" under a
        Free row), casefolded, so "Free Eng <translation>" can drop its "Eng" while a translation
        that merely starts with a short word ("She caught it") keeps it."""
        keys = sorted(self._ROW_KEEP + self._ROW_DROP, key=len, reverse=True)
        codes: set = set()
        for raw in pasted.replace("\r\n", "\n").split("\n"):
            cells = [c.strip() for c in raw.split("\t") if c.strip()]
            if not cells:
                continue
            if re.fullmatch(r"\d+(\.\d+)?", cells[0]) and len(cells) > 1:
                cells = cells[1:]
            head = re.sub(r"^\d+(\.\d+)?\s+", "", cells[0]).casefold()
            if len(cells) == 1 and re.fullmatch(r"[a-z]{2,3}", head):
                codes.add(head)
                continue
            for k in keys if len(cells) > 1 else ():     # the label in a cell of its own
                if k == "free":
                    continue
                if head.startswith(k + " "):
                    rest = head[len(k):].split()
                    if rest and re.fullmatch(r"[a-z]{2,3}(-[\w-]+)*", rest[0]):
                        codes.add(rest[0])
                    break
        return codes

    @staticmethod
    def _place_by_labels(queries: list, segs: list, labels: dict):
        """The pasted segments put where their FLEx numbers say: (score, first index, last index,
        matched) when the first one's content agrees with the segment of that number, else None.
        A query without a number follows the one before it."""
        idx, first, last, score, matched = None, None, None, 0, 0
        for k, q in enumerate(queries):
            idx = labels.get(_label_key(q["label"])) if q.get("label") else (idx + 1 if idx is not None else None)
            if idx is None or idx >= len(segs) or (last is not None and idx <= last):
                break
            s = _query_score(q, segs[idx][1], segs[idx][2], segs[idx][3], segs[idx][4])
            if k == 0:
                if s <= 0:
                    return None
                first = idx
            if s > 0:
                score += s
                matched += 1
            last = idx
        return (score, first, last, matched) if first is not None else None

    def example_text(self, guid: str, seg: list | None, at: list | None) -> dict:
        """A text carrying exactly an example's segments with every writing system — the whole
        text when the embed has no range (fetched in pages; the backends cap a slice)."""
        if seg or at:
            obj = self.get_object("text", guid, seg[0] if seg else None, seg[1] if seg else None, False, None, at, alts=True)
            return obj
        page = 60
        a = 1
        obj = None
        while True:
            part = self.get_object("text", guid, a, a + page - 1, False, None, None, alts=True)
            if obj is None:
                obj = dict(part)
                obj["segments"] = []
            obj["segments"].extend(part.get("segments") or [])
            total = part.get("segmentCount") or 0
            a += page
            if not part.get("segments") or a > total:
                break
        obj["range"] = [obj["segments"][0]["n"], obj["segments"][-1]["n"]] if obj["segments"] else [0, 0]
        return obj

    def clip_audio(self, examples: list[dict], folder: Path, stem: str, linked_root: Path | None = None) -> dict:
        """One small 16-bit mono WAV per timed segment of these examples, in `folder`, named
        `<stem>-<paragraph>.<segment>.wav` by the NEW text's numbering (Seth, 2026-10-16:
        flextext attaches clips to individual lines; small 16-bit mono WAVs into Linked Files).
        Each segment then points at its own clip from 0 to its length. When the folder sits
        inside a FieldWorks LinkedFiles folder the locations are written relative to it
        (`AudioVisual/x.wav`), which is how FLEx itself stores media; else absolute paths.
        Returns {folder, files, matched, missing}."""
        from .audio import find_ffmpeg, to_mono16
        import uuid as _uuid
        exe = find_ffmpeg(self.nb.config.get("settings", {}).get("ffmpegPath", ""))
        folder = Path(folder)
        files: list[str] = []
        matched = missing = 0
        for pi, ex in enumerate(examples, 1):
            text = ex["text"]
            media = []
            for k, seg in enumerate(text.get("segments") or [], 1):
                if seg.get("begin") is None or seg.get("end") is None or seg["end"] <= seg["begin"]:
                    seg["begin"] = seg["end"] = None
                    continue
                info = self.ensure_clip(text["guid"], seg.get("media"), seg["begin"], seg["end"])
                clip = info.get("clipPath")
                dst = folder / f"{stem}-{pi}.{k}.wav"
                length = to_mono16(clip, dst, exe) if clip else None
                if not length:
                    missing += 1
                    seg["begin"] = seg["end"] = None
                    continue
                guid = str(_uuid.uuid4())
                loc = str(dst.resolve())
                if linked_root is not None:
                    try:
                        loc = dst.resolve().relative_to(Path(linked_root).resolve()).as_posix()
                    except ValueError:
                        pass
                media.append({"guid": guid, "uri": loc, "path": loc, "found": True})
                seg["begin"], seg["end"], seg["media"] = 0, int(length), guid
                files.append(str(dst))
                matched += 1
            text["media"] = media
        return {"folder": str(folder) if files else "", "files": files, "matched": matched, "missing": missing}

    def bundle_audio(self, examples: list[dict], dst: Path, linked_root: Path | None = None) -> dict:
        """One recording of these examples, in order, as the text's ONE media file (Seth,
        2026-10-17: "concatenate the audio as a single audio file stored in the text media file
        … with a generated click inserted at join points"). The unit is the EXAMPLE, not the line
        ("an example that's multiple lines long … treated as a unit. So per flex object"): each
        example's audio is cut once, from its first timed line's begin to its last one's end
        (a run of lines on another recording is its own piece), so its lines keep their own
        timing inside it; the click (`audio.concat_clips`) goes only between examples. Offsets and
        media are rewritten to the new file. Inside a FieldWorks LinkedFiles folder the location
        is relative to it, as for clips. Returns {path, matched, missing}; no file when nothing
        was timed."""
        from .audio import concat_clips, find_ffmpeg
        import uuid as _uuid
        clips: list[Path] = []
        runs: list[tuple[int, list[dict]]] = []          # (begin in the source, its segments)
        missing = 0
        for ex in examples:
            text = ex["text"]
            timed = [seg for seg in text.get("segments") or []
                     if seg.get("begin") is not None and seg.get("end") is not None and seg["end"] > seg["begin"]]
            pieces: list[list[dict]] = []
            for seg in timed:                            # consecutive lines on one recording
                if pieces and pieces[-1][-1].get("media") == seg.get("media"):
                    pieces[-1].append(seg)
                else:
                    pieces.append([seg])
            for piece in pieces:
                begin, end = min(x["begin"] for x in piece), max(x["end"] for x in piece)
                info = self.ensure_clip(text["guid"], piece[0].get("media"), begin, end)
                if info.get("clipPath"):
                    clips.append(Path(info["clipPath"]))
                    runs.append((begin, piece))
                else:
                    missing += len(piece)
        kept = {id(seg) for _, piece in runs for seg in piece}
        for ex in examples:
            for seg in ex["text"].get("segments") or []:
                if id(seg) not in kept:
                    seg["begin"] = seg["end"] = None      # no recording to point at
        if not clips:
            return {"path": "", "matched": 0, "missing": missing}
        spans = concat_clips(clips, Path(dst), ffmpeg=find_ffmpeg(self.nb.config.get("settings", {}).get("ffmpegPath", "")))
        bundle_guid = str(_uuid.uuid4())
        loc = str(Path(dst).resolve())
        if linked_root is not None:
            try:
                loc = Path(dst).resolve().relative_to(Path(linked_root).resolve()).as_posix()
            except ValueError:
                pass
        for ex in examples:
            ex["text"]["media"] = [{"guid": bundle_guid, "uri": loc, "path": loc, "found": True}]
        for (src_begin, piece), (a, z) in zip(runs, spans):
            for seg in piece:
                b0 = min(z, a + seg["begin"] - src_begin)
                seg["begin"], seg["end"], seg["media"] = b0, max(b0 + 1, min(z, a + seg["end"] - src_begin)), bundle_guid
        return {"path": str(dst), "matched": len(kept), "missing": missing}

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

    # -- which texts a note draws on (Seth, 2026-10-16) ----------------------------------

    def texts_used(self, sources: list[tuple[str, str, str]]) -> list[dict]:
        """The FLEx TEXTS that the examples in `sources` [(note id, note title, markdown)] come from —
        not the examples themselves (three from one text and two from another: two rows). Each row
        {guid, title, examples, links, notes: [{id, title}], url}: `examples` counts the rendered
        examples ({{flex:text …}}, blocks and inline), `links` the plain links to the text, `url`
        is its FLEx hyperlink. Titles come from the snapshot cache, else the open project, else
        "(a text not in this project)"; sorted by title."""
        rows: dict[str, dict] = {}
        for note_id, note_title, body in sources:
            for rx, key in ((EMBED_RE, "examples"), (LINK_RE, "links")):
                for m in rx.finditer(body or ""):
                    kind = m.group(1).lower()
                    g = m.group(2).lower()
                    if kind == "chart":                      # a chart counts for the text it charts
                        snap = self.cache.get(self.project_name, "chart", g) or self.cache.find("chart", g)
                        g = (snap or {}).get("text") or ""
                        if not g:
                            continue
                        key = "charts"
                    elif kind != "text":
                        continue
                    r = rows.setdefault(g, {"guid": g, "examples": 0, "links": 0, "charts": 0, "notes": []})
                    r[key] += 1
                    if not any(n["id"] == note_id for n in r["notes"]):
                        r["notes"].append({"id": note_id, "title": note_title})
        if not rows:
            return []
        live: dict[str, str] | None = None
        for g, r in rows.items():
            snap = self.cache.get(self.project_name, "text", g) or self.cache.find("text", g)
            title = (snap or {}).get("title") or ""
            if not title:
                if live is None:
                    try:
                        live = {t["guid"].lower(): t.get("title", "") for t in self.list_texts()}
                    except Exception:  # noqa: BLE001 — no project open: the cache is all there is
                        live = {}
                title = live.get(g, "")
            r["title"] = title or "(a text not in this project)"
            r["url"] = (snap or {}).get("url") or model.goto_url(self.project_name, "text", g)
        return sorted(rows.values(), key=lambda r: (r["title"].casefold(), r["guid"]))

    # -- text markup tags (Seth, 2026-10-17) ----------------------------------------

    def text_tags(self) -> list[dict]:
        """The project's TextMarkupTags list; the last one seen is kept in the snapshot folder so
        the style editors and the picker list the tags without FLEx."""
        with self.lock:
            try:
                tags = self._live().list_text_tags()
                self.cache.put(self.project_name, "list", "texttags", {"tags": tags})
                return tags
            except Exception:  # noqa: BLE001 — closed, or a backend without tags
                snap = self.cache.get(self.project_name, "list", "texttags") if self.project_name else None
                return list((snap or {}).get("tags") or [])

    # -- text charts (Seth, 2026-10-18) -------------------------------------------------

    def charts(self, text_guid: str | None = None) -> list[dict]:
        """The project's constituent charts (optionally those of one text): live, else what the
        snapshot folder holds, so a note's chart is still listed without FLEx."""
        g = (text_guid or "").lower()
        with self.lock:
            try:
                return self._live().list_charts(g or None)
            except Exception:  # noqa: BLE001 — closed, or a backend without charts
                out = []
                d = self.cache.project_dir(self.project_name) if self.project_name else None
                for f in sorted(d.glob("chart-*.json")) if d and d.is_dir() else []:
                    snap = self.cache.get(self.project_name, "chart", f.stem[6:])
                    if snap and (not g or snap.get("text") == g):
                        out.append({"guid": snap["guid"], "name": snap.get("name", ""), "text": snap.get("text", ""), "title": snap.get("title", ""),
                                    "rows": snap.get("rowCount", 0), "template": (snap.get("template") or {}).get("name", ""),
                                    "columns": len((snap.get("template") or {}).get("columns") or []), "cached": True})
                return out

    def chart_markers(self) -> list[dict]:
        """The project's Chart Markers list (kept in the snapshot folder like the text tags)."""
        with self.lock:
            try:
                items = self._live().list_chart_markers()
                self.cache.put(self.project_name, "list", "chartmarkers", {"markers": items})
                return items
            except Exception:  # noqa: BLE001
                snap = self.cache.get(self.project_name, "list", "chartmarkers") if self.project_name else None
                return list((snap or {}).get("markers") or [])

    def tag_occurrences(self, tag_guid: str, q: str = "") -> list[dict]:
        with self.lock:
            rows = self._live().tag_occurrences(tag_guid)
        ql = (q or "").strip().casefold()
        if ql:
            rows = [r for r in rows if ql in (r.get("title", "") + " " + r.get("words", "") + " " + r.get("label", "")).casefold()]
        return rows

    def rule_matches(self, rule: dict) -> list[dict]:
        """Every LINE (segment range) carrying any tag a rule names (Seth, 2026-10-18: "a
        collection with ALL lines that match a specific rule"). A selector is a tag's GUID,
        name or abbreviation, `group:<name>` (every tag under that group, at any depth) or `*`;
        `texts` limits the search to those texts. One row per distinct range, in text order,
        each with the names of the tags that put it there. A rule with `charts` (a chart search
        query) matches CHART ROWS instead (chart_search): one row per chart row."""
        rule = rule or {}
        if (rule.get("charts") or "").strip():
            return self.chart_search(rule["charts"])
        sels = [str(t).strip() for t in rule.get("tags") or [] if str(t).strip()]
        if not sels:
            return []
        tags = self.text_tags()
        want: dict[str, None] = {}
        norm = lambda x: str(x or "").strip().casefold().replace("_", " ")  # noqa: E731
        for sel in sels:
            if sel == "*":
                for t in tags:
                    want[t["guid"]] = None
            elif sel.lower().startswith("group:"):
                g = norm(sel[6:])
                for t in tags:
                    if any(norm(p) == g for p in (t.get("path") or [t.get("group")])):
                        want[t["guid"]] = None
            else:
                for t in tags:
                    if sel.lower() == t["guid"] or norm(sel) in (norm(t.get("name")), norm(t.get("abbr"))):
                        want[t["guid"]] = None
        names = {t["guid"]: t.get("name") or t.get("abbr") or "?" for t in tags}
        only = {str(x).lower() for x in rule.get("texts") or []}
        rows: dict[tuple, dict] = {}
        for guid in want:
            for r in self.tag_occurrences(guid):
                if only and str(r.get("text", "")).lower() not in only:
                    continue
                key = (r.get("text"), r.get("seg"), r.get("segTo"))
                if key in rows:
                    if names.get(guid) not in rows[key]["tags"]:
                        rows[key]["tags"].append(names.get(guid))
                else:
                    rows[key] = dict(r, tags=[names.get(guid)])
        out = list(rows.values())
        out.sort(key=lambda r: (str(r.get("title", "")).casefold(), r.get("seg") or 0, r.get("segTo") or 0))
        return out

    # -- text chart search (Seth, 2026-10-18: "FLEx does not give us great ways to search text
    # charts … returning cells or rows with a certain text chart markers or which column a
    # certain lexical item is found in") -------------------------------------------------------

    def _chart_spans(self, text_guid: str) -> list[dict]:
        """Every word group of the text's charts, as spans an interlinear example can show as
        synthetic tags (Seth, 2026-10-18: "style spans of non-chart interlinear text objects that
        are mapped to text chart columns"): [{chart, chartName, template, row (label), column:
        {guid, name, abbr, path}, from: {seg, w}, to: {seg, w}}]. From the charts already
        snapshotted (the live list when open); never a fetch of its own beyond the charts."""
        out: list[dict] = []
        try:
            summaries = self.charts(text_guid)
        except Exception:  # noqa: BLE001
            return out
        for summ in summaries:
            snap = self.cache.get(self.project_name, "chart", summ["guid"]) or self.cache.find("chart", summ["guid"])
            if snap is None and self.backend is not None:
                try:
                    snap = self.get_object("chart", summ["guid"])
                except Exception:  # noqa: BLE001
                    snap = None
            if not snap:
                continue
            cols = {c["n"]: c for c in (snap.get("template") or {}).get("columns") or []}
            for r in snap.get("rows") or []:
                for c in r.get("cells") or []:
                    if c.get("kind") != "words" or not c.get("seg"):
                        continue
                    col = cols.get(c.get("colN")) or {}
                    out.append({"chart": snap.get("guid", ""), "chartName": snap.get("name", ""), "template": (snap.get("template") or {}).get("name", ""),
                                "row": r.get("label", ""), "column": {"guid": col.get("guid", ""), "name": col.get("name", ""), "abbr": col.get("abbr", ""), "path": list(col.get("path") or [])},
                                "from": dict(c.get("from") or {"seg": c.get("seg"), "w": 0}), "to": dict(c.get("to") or {"seg": c.get("segTo"), "w": 0})})
        return out

    def chart_rows(self, refresh: bool = False) -> list[dict]:
        """One record per CHART ROW across every chart of the project (live, each chart
        snapshotted on the way; the snapshots when FLEx is closed), kept for the session:
        {chart, chartName, text, title, template, row, label, guid, at, clause, endSent, endPara,
        markers (names + their groups), moved, clauseref, notes, cells: [{colN, col, abbr, path,
        words, glosses, forms, cfs, mgls, pos, seg, segTo}]}."""
        with self.lock:
            if self._chart_rows is not None and not refresh:
                return self._chart_rows
            rows: list[dict] = []
            # only the charts that have rows are read (Seth's project, 2026-10-18: 80 charts, most of
            # them the empty chart FLEx makes when a template's tab is opened); each one is snapshotted
            # on the way, so the second build is quick
            todo = [s for s in self.charts() if s.get("rows")]
            for i, summ in enumerate(todo, 1):
                self.progress(f"Reading chart {i} of {len(todo)}: {summ.get('title') or ''}…")
                try:
                    chart = self.get_object("chart", summ["guid"])
                except FlexError as e:
                    LOG.warning("chart %s not read for the index: %s", summ["guid"][:8], e.message)
                    continue
                rows.extend(_chart_index_rows(chart))
            self.progress("")
            LOG.info("chart index: %d rows from %d charts", len(rows), len(todo))
            self._chart_rows = rows
            return rows

    def chart_search(self, q: str) -> list[dict]:
        """The chart rows a query matches, in chart order. The query: words (matched against the
        words, glosses, morpheme forms and notes), `col:Subject` (a column by name, Group/Name,
        abbreviation or c3 — content terms then apply to THAT column's cells), `marker:Topic`
        (a chart marker on the row, or its group; `*` = any), `lex:kabir` (a word, morpheme form
        or lexeme form), `gloss:dog`, `word:kabir`, `pos:n`, `clause:dependent|speech|song|normal`,
        `moved[:preposed|postposed]`, `clauseref`, `endsent`, `endpara`, `chart:name`,
        `text:title`, `template:name`, `row:2a`, `note:text`, `-term` to exclude. Each hit carries
        `hits` (the column numbers that matched) and `embed` / keys for a collection."""
        terms = _parse_chart_query(q)
        out = []
        for r in self.chart_rows():
            hit = _row_matches(r, terms)
            if hit is None:
                continue
            row = dict(r)
            row["hits"] = hit
            out.append(row)
        return out

    def chart_profile(self, term: str) -> dict:
        """Where a lexical item sits in the charts (Seth: "which column a certain lexical item is
        found in"): the cells whose words, morpheme forms, lexeme forms or glosses contain `term`,
        counted per template and column, each count with its rows."""
        from ..notebook import normalize
        t = normalize(term or "", True)
        out: dict = {"term": term, "total": 0, "templates": []}
        if not t:
            return out
        tmpl: dict[str, dict] = {}
        for r in self.chart_rows():
            for c in r["cells"]:
                hay = c["words"] + c["forms"] + c["cfs"] + c["glosses"] + c["mgls"]
                if not any(t in normalize(x, True) for x in hay):
                    continue
                tp = tmpl.setdefault(r["template"] or "", {"name": r["template"] or "", "columns": {}, "total": 0})
                col = tp["columns"].setdefault(c["path"], {"name": c["col"], "path": c["path"], "colN": c["colN"], "count": 0, "rows": []})
                col["count"] += 1
                tp["total"] += 1
                out["total"] += 1
                col["rows"].append({"chart": r["chart"], "chartName": r["chartName"], "title": r["title"], "row": r["row"], "label": r["label"], "at": r["at"],
                                    "words": " ".join(c["words"]), "glosses": " ".join(c["glosses"])})
        for tp in tmpl.values():
            cols = sorted(tp["columns"].values(), key=lambda c: c["colN"])
            out["templates"].append({"name": tp["name"], "total": tp["total"], "columns": cols})
        out["templates"].sort(key=lambda x: -x["total"])
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

    def export_clips(self, items: list[dict]) -> list[dict]:
        """The recordings an HTML export embeds (Seth, 2026-10-18: "audio players and base64
        embedded audio where audio files and segmentation data are available and match"): per
        item {id, text, media?, begin, end} — ONE clip per example or chart, its first timed line's
        begin to its last one's end, so the page seeks inside it per line — the clip is cut as for
        playback (the cache, else the live file) and compressed for the page
        (`audio.encode_for_embed`), returned as {id, mime, base64, bytes, begin, end}; an item
        whose audio cannot be had says `error` instead and the page shows that example without
        a player. The compressed copies live beside the clips (`<text>_<b>-<e>.export.ogg`) so a
        second export is instant."""
        import base64
        from .audio import encode_for_embed, find_ffmpeg
        exe = find_ffmpeg(self.nb.config.get("settings", {}).get("ffmpegPath", ""))
        out = []
        for it in items or []:
            rid = it.get("id")
            try:
                begin, end = int(it.get("begin", 0)), int(it.get("end", 0))
                if end <= begin or not it.get("text"):
                    out.append({"id": rid, "error": "no timing"})
                    continue
                info = self.ensure_clip(it["text"], it.get("media"), begin, end)
                src = info.get("clipPath")
                if not src:
                    out.append({"id": rid, "error": "The recording is not available on this computer." if not info.get("found") else "This recording cannot be cut here (a non-WAV file needs ffmpeg)."})
                    continue
                stem = self.cache.audio_clip_path(self.project_name, it["text"], begin, end, ".export")
                enc = encode_for_embed(src, stem, exe)
                if not enc:
                    out.append({"id": rid, "error": "The clip could not be encoded."})
                    continue
                data = Path(enc[0]).read_bytes()
                out.append({"id": rid, "mime": enc[1], "base64": base64.b64encode(data).decode("ascii"), "bytes": len(data), "begin": begin, "end": end})
            except FlexError as e:
                out.append({"id": rid, "error": e.message})
            except Exception as e:  # noqa: BLE001
                LOG.warning("export_clips: %s", e)
                out.append({"id": rid, "error": str(e)})
        return out

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


# --------------------------------------------------------------------------- chart search helpers

def _chart_index_rows(chart: dict) -> list[dict]:
    cols = {c["n"]: c for c in (chart.get("template") or {}).get("columns") or []}
    out = []
    for r in chart.get("rows") or []:
        cells, markers, moved = [], [], []
        clauseref = False
        for c in r.get("cells") or []:
            k = c.get("kind")
            if k == "words":
                col = cols.get(c.get("colN")) or {}
                words = [w for w in c.get("words") or [] if not w.get("punct")]
                morphs = [m for w in words for m in w.get("morphs") or []]
                cells.append({"colN": c.get("colN") or 0, "col": col.get("name", ""), "abbr": col.get("abbr", ""),
                              "path": "/".join((col.get("path") or []) + [col.get("name", "")]),
                              "words": [w.get("txt", "") for w in words], "glosses": [w.get("gls", "") for w in words],
                              "forms": [m.get("form", "") for m in morphs], "cfs": [m.get("cf", "") for m in morphs if m.get("cf")],
                              "mgls": [m.get("gls", "") for m in morphs], "pos": [w.get("pos", "") for w in words if w.get("pos")],
                              "seg": c.get("seg"), "segTo": c.get("segTo")})
            elif k == "tag" and c.get("tag"):
                t = c["tag"]
                markers.append(t.get("name") or t.get("abbr") or "")
                if t.get("abbr"):
                    markers.append(t["abbr"])
                markers.extend(t.get("path") or [])
            elif k == "moved":
                moved.append("preposed" if c.get("preposed") else "postposed")
            elif k == "clause":
                clauseref = True
        out.append({"chart": chart.get("guid", ""), "chartName": chart.get("name", ""), "text": chart.get("text", ""), "title": chart.get("title", ""),
                    "template": (chart.get("template") or {}).get("name", ""), "row": r.get("n"), "label": r.get("label", ""), "guid": r.get("guid", ""),
                    "at": model.anchor_of(r.get("guid", "")), "clause": r.get("clause", "normal"), "endSent": bool(r.get("endSent")), "endPara": bool(r.get("endPara")),
                    "markers": [m for m in markers if m], "moved": moved, "clauseref": clauseref, "notes": r.get("notes", ""), "cells": cells})
    return out


# `-key:value` excludes; a bare `-mo` is the text "-mo" (a suffix), never a negation
_QTOKEN = re.compile(r'(-(?=[A-Za-z]+:))?(?:([A-Za-z]+):)?("([^"]*)"|\S+)')
ROW_KEYS = ("marker", "clause", "chart", "text", "template", "row", "label", "note", "notes", "moved", "clauseref", "endsent", "endpara")
CELL_KEYS = ("col", "column", "lex", "gloss", "word", "words", "pos", "form", "morph")


def _parse_chart_query(q: str) -> list[dict]:
    """[{neg, key, val}] — key '' for a bare word; a quoted value keeps its spaces."""
    from ..notebook import normalize
    out = []
    for m in _QTOKEN.finditer(q or ""):
        neg, key, raw, quoted = m.group(1), (m.group(2) or "").lower(), m.group(3), m.group(4)
        val = quoted if quoted is not None else raw
        if key and key not in ROW_KEYS + CELL_KEYS:        # not a key we know: the whole token is a word
            val, key, neg = m.group(0), "", None
        if not key and val.lower() in ("moved", "clauseref", "endsent", "endpara"):   # bare row flags
            key, val = val.lower(), ""
        out.append({"neg": bool(neg), "key": key, "val": normalize(val, True), "raw": val})
    return out


def _cell_matches(c: dict, t: dict) -> bool:
    from ..notebook import normalize
    v = t["val"]
    k = t["key"]
    has = lambda xs: any(v and v in normalize(x, True) for x in xs)  # noqa: E731
    if k in ("col", "column"):
        if not v:
            return False
        if re.fullmatch(r"c\d+", v):
            return str(c["colN"]) == v[1:]
        return normalize(c["col"], True) == v or normalize(c["abbr"], True) == v or normalize(c["path"], True) == v \
            or normalize(c["path"], True).endswith("/" + v) or any(normalize(p, True) == v for p in c["path"].split("/")[:-1])
    if k == "lex":
        return has(c["words"]) or has(c["forms"]) or has(c["cfs"])
    if k == "gloss":
        return has(c["glosses"]) or has(c["mgls"])
    if k in ("word", "words"):
        return has(c["words"])
    if k in ("form", "morph"):
        return has(c["forms"]) or has(c["cfs"])
    if k == "pos":
        return any(normalize(x, True) == v for x in c["pos"])
    return has(c["words"]) or has(c["glosses"]) or has(c["forms"]) or has(c["cfs"]) or has(c["mgls"])   # a bare word


def _row_term(r: dict, t: dict) -> bool:
    from ..notebook import normalize
    v, k = t["val"], t["key"]
    if k == "marker":
        return bool(r["markers"]) if v == "*" else any(normalize(m, True) == v for m in r["markers"])
    if k == "clause":
        return r["clause"] == v
    if k == "chart":
        return v in normalize(r["chartName"], True)
    if k == "text":
        return v in normalize(r["title"], True)
    if k == "template":
        return v in normalize(r["template"], True)
    if k in ("row", "label"):
        return normalize(r["label"], True) == v or str(r["row"]) == v
    if k in ("note", "notes"):
        return bool(v) and v in normalize(r["notes"], True)
    if k == "moved":
        return (v in r["moved"]) if v and v not in ("moved", "yes", "true") else bool(r["moved"])
    if k == "clauseref":
        return r["clauseref"]
    if k == "endsent":
        return r["endSent"]
    if k == "endpara":
        return r["endPara"]
    return False


def _row_matches(r: dict, terms: list[dict]) -> list[int] | None:
    """The column numbers that matched (every column when no cell term narrows it), or None."""
    from ..notebook import normalize
    col_terms = [t for t in terms if t["key"] in ("col", "column") and not t["neg"]]
    content = [t for t in terms if (t["key"] in CELL_KEYS and t["key"] not in ("col", "column")) or t["key"] == ""]
    for t in terms:
        if t["key"] in ROW_KEYS:
            if _row_term(r, t) == t["neg"]:
                return None
        elif t["neg"] and t["key"] in ("col", "column"):
            if any(_cell_matches(c, dict(t, neg=False)) for c in r["cells"]):
                return None
    cells = r["cells"]
    if col_terms:
        cells = [c for c in cells if any(_cell_matches(c, t) for t in col_terms)]
        if not cells:
            return None
    if content:
        pos = [t for t in content if not t["neg"]]
        neg = [t for t in content if t["neg"]]
        for t in neg:
            if any(_cell_matches(c, t) for c in r["cells"]) or (t["key"] == "" and t["val"] in normalize(r["notes"], True)):
                return None
        if pos:
            good = [c for c in cells if all(_cell_matches(c, t) for t in pos)]
            if not good:
                # a bare word may also be in the row's notes
                if col_terms or not all(t["key"] == "" and t["val"] in normalize(r["notes"], True) for t in pos):
                    return None
                return []
            return [c["colN"] for c in good]
    return [c["colN"] for c in cells] if (col_terms or content) else []
