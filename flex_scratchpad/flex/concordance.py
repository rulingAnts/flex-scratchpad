"""A FieldWorks concordance export as example lines (Seth, 2026-10-20: "the ability to paste the
results of a FLEx concordance (or complex concordance) search and get an example collection …
you can't actually 'paste' concordance search results, but you could open the CSV results").

FLEx's File › Export Concordance Results… writes a CSV with two columns:

    Ref,Occurrence
    Boa Cons 1.20,korokoi a bu i bi dirou aha dai§ dai kaduako …
    aː boɥo 3.1,ohu bia kakoɾide

`Ref` is the TEXT (its abbreviation — FLEx's own, or the title cut to eight letters when none was
set — or its title; it may hold spaces) followed by FLEx's paragraph.segment number; `Occurrence`
is the whole PARAGRAPH's baseline with `§` between its segments (a row per match, so a segment
matched twice appears twice). The reader here is pure: `parse()` reads the file, `match()` places
each row in the project's index (the same per-session index the paste locator uses) — the text
by its abbreviation or title, the line by FLEx's number, the baseline checked against the
occurrence — and returns rows shaped like `rule_matches` rows, so `match_embed` writes them.
"""
from __future__ import annotations

import csv
import io
import re
import unicodedata as _ud

from . import model

SEG_SEP = "§"      # § between a paragraph's segments in the Occurrence column
_REF_RE = re.compile(r"^(?P<name>.*?)\s*(?P<label>\d+(?:\.\d+)?)\s*$")


def parse(text: str) -> list[dict]:
    """The CSV's rows: [{ref, name, label, occurrence, line}] (line = 1-based line in the file).
    A header row naming Ref / Occurrence picks the columns; without one the first two are taken.
    A row whose Ref carries no number is skipped."""
    text = (text or "").lstrip("﻿")
    rows: list[dict] = []
    reader = csv.reader(io.StringIO(text))
    ref_i, occ_i = 0, 1
    for i, rec in enumerate(reader):
        if not rec or not any(c.strip() for c in rec):
            continue
        if i == 0 and any(c.strip().casefold() == "ref" for c in rec):
            heads = [c.strip().casefold() for c in rec]
            ref_i = heads.index("ref")
            occ_i = heads.index("occurrence") if "occurrence" in heads else (1 if len(rec) > 1 else 0)
            continue
        ref = rec[ref_i].strip() if len(rec) > ref_i else ""
        m = _REF_RE.match(ref)
        if not m:
            continue
        rows.append({"ref": ref, "name": m.group("name").strip(), "label": m.group("label"),
                     "occurrence": (rec[occ_i] if len(rec) > occ_i else "").strip(), "line": i + 1})
    return rows


def label_key(label: str) -> str:
    """FLEx's number as a key: "13" (a paragraph of one segment) is "13.1"."""
    s = str(label or "").strip().rstrip(".")
    return s if "." in s else s + ".1"


def norm(s: str) -> str:
    """Casefolded, marks and punctuation dropped, spaces collapsed: a baseline against the
    occurrence's pieces, whatever the export did to diacritics and spacing."""
    out = []
    for ch in _ud.normalize("NFKD", s or ""):
        cat = _ud.category(ch)
        if cat.startswith("M") or cat.startswith("P") or cat.startswith("S"):
            continue
        out.append(ch.casefold())
    return " ".join("".join(out).split())


def pieces(occurrence: str) -> list[str]:
    """The occurrence's segments, normalised (empty ones dropped)."""
    return [p for p in (norm(x) for x in (occurrence or "").split(SEG_SEP)) if p]


def text_names(t: dict) -> tuple[list[str], list[str]]:
    """(abbreviations, titles) a text goes by — in every writing system the backend knows
    (`names`), since FLEx's export names a text in the system its concordance showed, often the
    vernacular (Seth, 2026-10-20: "texts that have a title in the vernacular writing system …
    it's not finding")."""
    abbrevs = [t.get("abbrev") or ""]
    titles = [t.get("title") or ""] + [x for x in (t.get("names") or []) if x]
    return [a for a in abbrevs if a], [x for x in dict.fromkeys(titles) if x]


def _texts_named(name: str, texts: list[dict]) -> list[dict]:
    """The texts a Ref's name can mean, best first: an abbreviation, then a title (in any writing
    system), then a title that starts with the name (FLEx shows eight letters of the title when no
    abbreviation is set)."""
    n = norm(name)
    if not n:
        return []
    exact, title, head = [], [], []
    for t in texts:
        abbrevs, titles = text_names(t)
        if any(norm(a) == n for a in abbrevs):
            exact.append(t)
        elif any(norm(x) == n for x in titles):
            title.append(t)
        elif len(n) >= 3 and any(norm(x).startswith(n) for x in titles):
            head.append(t)
    return exact + title + head


def match(rows: list[dict], texts: list[dict], index: dict) -> dict:
    """Place every parsed row. `texts` = list_texts() ({guid, title, abbrev}); `index` =
    all_baselines() ({guid: {title, segments: [(n, baseline, free, …, label, segGuid), …]}}).
    Returns {rows: [...], matched, unmatched, texts: [titles]}: a row per DISTINCT line found
    (`hits` counts the export's rows that led to it, in file order of first appearance), each
    {text, title, seg, segTo, label, labelTo, at, ref, hits, how}, and the misses as
    {ref, found: False, why}. `how` is "number" (FLEx's number, baseline agreeing), "number?"
    (the number alone: the text has no baseline there to check, or the export's differs) or
    "text" (found by its baseline where the number was not in the text)."""
    out: list[dict] = []
    misses: list[dict] = []
    seen: dict[str, dict] = {}
    for r in rows:
        cands = _texts_named(r["name"], texts)
        if not cands:
            misses.append({"ref": r["ref"], "found": False, "why": "no text named “%s”" % r["name"], "line": r["line"]})
            continue
        want = label_key(r["label"])
        occ = pieces(r["occurrence"])
        placed = None
        # FLEx's number in a text of that name: the occurrence is the whole PARAGRAPH, so its k-th
        # piece should be segment p.k's baseline (an edited baseline still counts as "number?";
        # the number wins whenever a text of that name has it — the other pieces are the
        # paragraph's OTHER lines, never a better place for this one)
        try:
            k = int(want.split(".")[1]) - 1
        except ValueError:
            k = -1
        for t in cands:
            segs = (index.get(t["guid"]) or {}).get("segments") or []
            for i, row in enumerate(segs):
                if len(row) > 5 and label_key(row[5]) == want:
                    base = norm(row[1])
                    if not occ or not base:
                        how = "number?"
                    elif 0 <= k < len(occ) and (occ[k] == base or base in occ[k] or occ[k] in base):
                        how = "number"
                    elif base in occ:
                        how = "number"
                    else:
                        how = "number?"
                    if placed is None or (how == "number" and placed[3] != "number"):
                        placed = (t, i, row, how)
                    break
            if placed and placed[3] == "number":
                break
        # no text of that name has the number: the baseline itself, in those texts
        if placed is None and occ:
            for t in cands:
                segs = (index.get(t["guid"]) or {}).get("segments") or []
                found = [(i, row) for i, row in enumerate(segs) if norm(row[1]) and norm(row[1]) in occ]
                if len(found) == 1:
                    placed = (t, found[0][0], found[0][1], "text")
                    break
        if placed is None:
            misses.append({"ref": r["ref"], "found": False, "line": r["line"],
                           "why": "“%s” has no line %s" % (cands[0].get("title") or r["name"], r["label"])})
            continue
        t, i, row, how = placed
        key = f"{t['guid']}#{row[0]}"
        if key in seen:
            seen[key]["hits"] += 1
            continue
        d = {"text": t["guid"], "title": t.get("title") or "", "seg": row[0], "segTo": row[0],
             "label": str(row[5]) if len(row) > 5 and row[5] else str(row[0]), "ref": r["ref"], "hits": 1, "how": how, "found": True}
        d["labelTo"] = d["label"]
        if len(row) > 6 and row[6]:
            a = model.anchor_of(row[6])
            d["at"] = [a, a]
        seen[key] = d
        out.append(d)
    return {"rows": out, "misses": misses, "matched": len(out), "unmatched": len(misses),
            "texts": list(dict.fromkeys(d["title"] for d in out))}
