"""Keeping a text example on ITS lines while the text changes in FLEx (Seth, 2026-10-17: "lines
deleted, merged, or split in baseline … We'd really like our flex objects to be more reliable,
stable, and intelligent than that").

What FieldWorks does to segments when the baseline is edited (liblcm DomainImpl/AnalysisAdjuster.cs):
a segment whose text is untouched keeps its object, so its GUID (only its number changes); a
SPLIT segment keeps its object in the FIRST piece and the later pieces are new segments; two
MERGED segments keep the FIRST one's object and the second is deleted (its translation is
appended); a segment entirely inside deleted text is deleted. Re-importing a text, or replacing a
paragraph wholesale, gives every segment a new GUID.

So an embed's `at=` anchors (the first and last segment's GUID tails) already survive
renumbering, and the LEDGER below makes the rest work. Per text, in the snapshot folder, it keeps
the last few ORDERS of the text's segments (anchors only) and, per segment, its last texts, its
word forms and the segment as last drawn. `track()` then:

  1. finds the embed's own old range: the stored order in which its anchors sit exactly at its
     `seg=` numbers (the numbering it was last written with), else the newest that has them;
  2. maps every old segment to where it is now (a deleted one to nothing);
  3. takes the span of the survivors, and widens it over the pieces of a SPLIT last segment (the
     following segments whose text was part of that segment's earlier text) and over the
     segment a deleted FIRST segment was MERGED into (the one before, whose text now holds it);
  4. when nothing survives, looks for the old lines by their TEXT (the closest run of segments,
     nearest the old place), and otherwise reports them LOST (the caller shows the saved copy).

It returns the new range, a per-old-segment map (for the embed's highlights), the old words of
changed segments (so a word-level highlight follows its word) and what kind of change it was.
Pure functions + a small JSON file; every backend (FLEx, .flextext, demo) goes through it.
"""
from __future__ import annotations

import difflib
import json
import os
import time
import unicodedata
from pathlib import Path

from . import model

MAX_ORDERS = 6          # orders of the text kept (only when the order changed)
MAX_TEXTS = 4           # texts kept per segment (newest first)
FIND_MIN = 0.6          # how alike the old and new lines must be to be "found by their text"


def norm(s: str) -> str:
    """Letters, marks and digits only, NFC, case-folded: punctuation and spacing are what a split
    or a merge changes, so they never decide whether two texts are the same words."""
    s = unicodedata.normalize("NFC", s or "").casefold()
    return "".join(c for c in s if unicodedata.category(c)[0] in "LMN")


def words_of(seg: dict) -> list[str]:
    return [w.get("txt", "") for w in (seg.get("words") or []) if not w.get("punct")]


class Ledger:
    """<cache>/<project>/ledger-<text guid>.json — see the module docstring."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.data = {"orders": [], "segs": {}}
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                self.data.update(d)
        except (OSError, ValueError):
            pass

    @property
    def orders(self) -> list[dict]:
        return self.data["orders"]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    def record(self, index: list[dict], segments: list[dict], texts: dict | None = None) -> None:
        """After a live fetch: the text's current order, and what the drawn segments say."""
        order = [model.anchor_of(e.get("guid", "")) for e in index or []]
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        if order and (not self.orders or self.orders[0]["order"] != order):
            self.orders.insert(0, {"at": now, "order": order})
            del self.orders[MAX_ORDERS:]
        elif self.orders:
            self.orders[0]["at"] = now
        segs = self.data["segs"]

        def note_text(a: str, text: str) -> dict:
            e = segs.setdefault(a, {"texts": []})
            if text is not None and (not e["texts"] or e["texts"][0] != text):
                e["texts"] = ([text] + [t for t in e["texts"] if t != text])[:MAX_TEXTS]
            e["seen"] = now
            return e

        for s in segments or []:
            a = model.anchor_of(s.get("guid", ""))
            if not a:
                continue
            e = note_text(a, s.get("baseline", ""))
            e["words"] = words_of(s)
            e["seg"] = s
        for a, text in (texts or {}).items():
            note_text(a, text)
        # forget segments no stored order mentions any more
        keep = {a for o in self.orders for a in o["order"]}
        for a in [a for a in segs if a not in keep]:
            del segs[a]


def _old_range(ledger: Ledger, seg_from: int | None, seg_to: int | None, at: list | None) -> list[str] | None:
    """The embed's segments as it last knew them (anchors, in order)."""
    if not ledger.orders:
        return None
    a = int(seg_from or 1)
    b = int(seg_to or a)
    want = [str(x or "").lower() for x in (at or [])[:2]]
    if len(want) == 1:
        want.append(want[0])

    def pos(order: list[str], w: str) -> int | None:
        hits = [i for i, x in enumerate(order) if w and x.endswith(w)]
        return hits[0] if hits else None

    best = None
    for o in ledger.orders:
        order = o["order"]
        if want and want[0]:
            i, j = pos(order, want[0]), pos(order, want[1] or want[0])
            if i is None or j is None:
                continue
            i, j = min(i, j), max(i, j)
            if i + 1 == a and j + 1 == b:
                return order[i:j + 1]             # exactly the numbering the embed was written with
            if best is None:
                best = order[i:j + 1]
        else:                                     # an older embed without anchors: its numbers, in the order it saw
            if 1 <= a <= b <= len(order):
                return order[a - 1:b]
    return best


def track(ledger: Ledger, new_index: list[dict], current_texts, seg_from: int | None, seg_to: int | None,
          at: list | None, seen_now: dict | None = None) -> dict | None:
    """Where the embed's lines are now. `seen_now` = {anchor: baseline} of the segments already
    fetched; `current_texts()` → the same for the whole text as it is, read only when a text is
    needed that was not fetched (a possible split, merge or rebuild — never on a plain redraw).
    None when the ledger knows nothing of this embed."""
    old = _old_range(ledger, seg_from, seg_to, at)
    if not old:
        return None
    new_order = [model.anchor_of(e.get("guid", "")) for e in new_index]
    where = {a: i for i, a in enumerate(new_order)}
    segs = ledger.data["segs"]
    known = {a for o in ledger.orders for a in o["order"]}       # every segment this text has had
    texts_now: dict | None = None

    def now_text(a: str) -> str:
        nonlocal texts_now
        if seen_now and a in seen_now:
            return seen_now[a]
        if texts_now is None:
            texts_now = current_texts() or {}
        return texts_now.get(a, "")

    def old_texts(a: str) -> list[str]:
        return (segs.get(a) or {}).get("texts") or []

    surv = [where[a] for a in old if a in where]
    how = []
    if surv:
        i, j = min(surv), max(surv)
        # the first segment is gone: merged into the one before? (FLEx keeps the first of two)
        if old[0] not in where and i > 0:
            first_old = next((norm(t) for t in old_texts(old[0]) if norm(t)), "")
            if first_old and first_old in norm(now_text(new_order[i - 1])):
                i -= 1
                how.append("merged")
        # the last segment was split: its later pieces are the new segments after it whose text
        # was part of its earlier text (FLEx keeps the first piece)
        last = old[-1]
        if last in where and where[last] == j:
            earlier = [norm(t) for t in old_texts(last)]
            cur = norm(now_text(last)) if earlier else ""
            k = j + 1
            while earlier and k < len(new_order) and new_order[k] not in known:   # a split's pieces are NEW segments
                piece = norm(now_text(new_order[k]))
                if piece and any(piece in t and piece not in cur for t in earlier):
                    k += 1
                    how.append("split")
                    continue
                break
            j = k - 1
        if any(a not in where for a in old):
            how.append("deleted" if "merged" not in how else "merged")
        if (j - i + 1) != len(old) and not how:
            how.append("inserted")
        change = "reshaped" if how else ("moved" if i + 1 != int(seg_from or 1) else "none")
        return {"from": i + 1, "to": j + 1, "change": change, "how": sorted(set(how)),
                "map": [where[a] + 1 if a in where else None for a in old],
                "oldWords": [(segs.get(a) or {}).get("words") if a in where and _changed(segs.get(a), now_text, a) else None for a in old]
                if surv and (how or change != "none") else [None] * len(old),
                "old": old}
    # nothing survives: find the lines by their text, nearest the old place
    target = norm(" ".join((old_texts(a) or [""])[0] for a in old))
    if target and new_order:
        n = len(old)
        hint = int(seg_from or 1) - 1
        best = None
        for size in sorted({max(1, n - 1), n, n + 1}):
            for s in range(0, max(0, len(new_order) - size) + 1):
                cand = norm(" ".join(now_text(a) for a in new_order[s:s + size]))
                if not cand:
                    continue
                r = difflib.SequenceMatcher(None, target, cand, autojunk=False).ratio()
                key = (round(r, 3), -abs(s - hint))
                if best is None or key > best[0]:
                    best = (key, s, size)
        if best and best[0][0] >= FIND_MIN:
            _, s, size = best
            return {"from": s + 1, "to": s + size, "change": "found", "how": ["found by text"],
                    "map": [s + 1 + k if k < size else None for k in range(n)],
                    "oldWords": [(segs.get(a) or {}).get("words") for a in old], "old": old}
    return {"from": None, "to": None, "change": "lost", "how": ["lost"], "map": [None] * len(old), "oldWords": [None] * len(old),
            "old": old, "saved": [(segs.get(a) or {}).get("seg") for a in old]}


def _changed(entry: dict | None, now_text, a: str) -> bool:
    texts = (entry or {}).get("texts") or []
    return bool(texts) and norm(texts[0]) != norm(now_text(a))
