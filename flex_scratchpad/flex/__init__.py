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

    def refresh(self, indexes: bool = True) -> dict:
        with self.lock:
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
            if not prefer_cache:
                try:
                    be = self._live()
                    if kind == "entry":
                        obj = be.get_entry(guid)
                        self.cache.put(self.project_name, "entry", guid, obj)
                    elif kind == "text":
                        obj = be.get_text(guid, seg_from, seg_to, ws=ws, at=at, alts=alts) if alts else be.get_text(guid, seg_from, seg_to, ws=ws, at=at)
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

    def bundle_audio(self, examples: list[dict], dst: Path, gap_ms: int = 600) -> dict:
        """One recording of every timed segment of these examples, in order (the clips the
        cache already cuts, concatenated with a gap); the segments' offsets and media are
        rewritten to it. Returns {path, matched, missing}; no file when nothing was timed."""
        from .audio import concat_clips, find_ffmpeg
        import uuid as _uuid
        clips, slots = [], []
        missing = 0
        for ex in examples:
            text = ex["text"]
            for seg in text.get("segments") or []:
                if seg.get("begin") is None or seg.get("end") is None or seg["end"] <= seg["begin"]:
                    continue
                info = self.ensure_clip(text["guid"], seg.get("media"), seg["begin"], seg["end"])
                if info.get("clipPath"):
                    clips.append(Path(info["clipPath"]))
                    slots.append(seg)
                else:
                    missing += 1
        if not clips:
            for ex in examples:
                for seg in ex["text"].get("segments") or []:
                    seg["begin"] = seg["end"] = None      # no recording to point at
            return {"path": "", "matched": 0, "missing": missing}
        spans = concat_clips(clips, Path(dst), gap_ms, find_ffmpeg(self.nb.config.get("settings", {}).get("ffmpegPath", "")))
        bundle_guid = str(_uuid.uuid4())
        matched = {id(seg) for seg in slots}
        for ex in examples:
            ex["text"]["media"] = [{"guid": bundle_guid, "uri": Path(dst).name, "path": str(Path(dst).resolve()), "found": True}]
            for seg in ex["text"].get("segments") or []:
                if id(seg) not in matched:
                    seg["begin"] = seg["end"] = None
        for seg, (a, b) in zip(slots, spans):
            seg["begin"], seg["end"], seg["media"] = a, b, bundle_guid
        return {"path": str(dst), "matched": len(slots), "missing": missing}

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
                    if m.group(1).lower() != "text":
                        continue
                    g = m.group(2).lower()
                    r = rows.setdefault(g, {"guid": g, "examples": 0, "links": 0, "notes": []})
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
