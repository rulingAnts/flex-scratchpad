"""The FLEx object model the UI renders — plain dicts, built by every backend alike.

    entry: {kind:'entry', guid, headword, lexemeForm, citationForm, morphType, homograph, pos,
            ws:{vern, anal}, senses:[{guid, number, gloss, definition, pos,
                                      examples:[{guid, text, translation}]}], url}
    text:  {kind:'text', guid, title, abbrev, url, segmentCount, ws:{vern, anal},
            media:[{guid, uri, path, fileUrl, found}],
            segments:[{guid, n, para, baseline, free, lit, notes:[], begin, end, media,
                       words:[{txt, punct, gls, pos, morphs:[{form, gls, msa}], guid}]}]}
    ws:    {tag, name, font, rtl}

Also here: FieldWorks hyperlinks (the `silfw://` scheme FLEx registers on Windows) in both
directions, and the plain-text form of an object for the notebook's search index.
"""
from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, quote, unquote, urlparse

GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

# FLEx tool names, as FwAppArgs writes them (flexicon's BuildGotoURL uses the same table).
TOOL_FOR_KIND = {
    "entry": "lexiconEdit",
    "sense": "lexiconEdit",
    "text": "interlinearEdit",
    "wordform": "Analyses",
    "reversal": "reversalToolEditComplete",
}


def is_guid(s: str) -> bool:
    return bool(s) and bool(GUID_RE.match(s.strip()))


def goto_url(project: str, kind: str, guid: str) -> str:
    """`silfw://localhost/link?app=flex&server=&database=<project>&tool=<tool>&guid=<guid>` —
    what FLEx's *Copy Location as Hyperlink* produces and what `os.startfile` hands to FLEx."""
    tool = TOOL_FOR_KIND.get(kind, "lexiconEdit")
    return (f"silfw://localhost/link?app=flex&server=&database={quote(project or '', safe='')}"
            f"&tool={tool}&guid={guid}")


def parse_silfw(url: str) -> dict | None:
    """Pull database / tool / guid out of a FLEx hyperlink. Returns None for anything else."""
    s = (url or "").strip()
    if not s.lower().startswith("silfw:"):
        return None
    try:
        u = urlparse(s)
        query = u.query
        # FLEx's own "Copy Location as Hyperlink" percent-encodes the whole query
        # (`database%3dfau-iya-flex%26tool%3dinterlinearEdit%26guid%3d…`), so decode until stable
        for _ in range(3):
            dec = unquote(query)
            if dec == query:
                break
            query = dec
        qs = parse_qs(query)
    except ValueError:
        return None
    guid = (qs.get("guid") or [""])[0]
    if not is_guid(guid):
        return None
    return {
        "database": (qs.get("database") or [""])[0],
        "tool": (qs.get("tool") or [""])[0],
        "guid": guid.lower(),
        "tag": (qs.get("tag") or [""])[0],
    }


def make_ws(tag: str = "", name: str = "", font: str = "", rtl: bool = False) -> dict:
    return {"tag": tag or "", "name": name or tag or "", "font": font or "", "rtl": bool(rtl)}


def empty_text(guid: str, title: str = "", ws_vern: dict | None = None, ws_anal: dict | None = None) -> dict:
    return {
        "kind": "text", "guid": guid, "title": title, "abbrev": "", "url": "",
        "segmentCount": 0, "ws": {"vern": ws_vern or make_ws(), "anal": ws_anal or make_ws()},
        "media": [], "segments": [], "tags": [],
    }


# FLEx TEXT MARKUP TAGS (Seth, 2026-10-17): what the Text Tagging view draws under a span of
# words — an ITextTag on the text (begin / end segment, begin / end analysis index, a tag item
# from the project's TextMarkupTags list). `w` counts the segment's analyses (our `words`, with
# punctuation) from 0, as FLEx does. Tags ride on the text as `tags`, all of them whatever
# range was fetched, so a note's snapshot always holds the full list.
def tag_item(guid: str, name: str, abbr: str = "", group: str = "", fore: str = "", back: str = "", path: list | None = None) -> dict:
    # A list item nobody coloured has 0 in all three colour fields (the model's default int; only
    # an XML import writes kclrTransparent), which reads as black on black — not a look anyone
    # chose (Seth's project, 2026-10-18: every tag a black bar). A black background with another
    # text colour is kept.
    if back == "#000000" and fore in ("", "#000000"):
        fore = back = ""
    # `path` = the names of the item's ancestors in FLEx's list, top first (the list has at least
    # two levels; Seth, 2026-10-18: show "that collapsible hierarchy in the UI"); `group` stays the
    # nearest one for older callers
    path = [str(x) for x in (path if path is not None else ([group] if group else [])) if x]
    return {"guid": (guid or "").lower(), "name": name or abbr or "?", "abbr": abbr or name or "?",
            "group": (path[-1] if path else group) or "", "path": path, "fore": fore or "", "back": back or ""}


def make_tag(guid: str, tag: dict, seg_from: int, w_from: int, seg_to: int, w_to: int) -> dict:
    return {"guid": (guid or "").lower(), "tag": tag, "from": {"seg": int(seg_from), "w": int(w_from)},
            "to": {"seg": int(seg_to), "w": int(w_to)}}


def fw_color(v) -> str:
    """A FieldWorks colour (an int holding BGR) as '#rrggbb'; '' when it is transparent / unset
    (kclrTransparent and anything else outside 24 bits — liblcm's XmlImportData gives new items
    kclrTransparent for all three colours)."""
    try:
        v = int(v)
    except (TypeError, ValueError):
        return ""
    if v < 0 or v > 0xFFFFFF:
        return ""
    return "#%02x%02x%02x" % (v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF)


def tag_names(obj: dict) -> list[str]:
    """Every distinct tag name and abbreviation on a text, in first-seen order."""
    out: list[str] = []
    for t in obj.get("tags") or []:
        for k in ("name", "abbr"):
            v = (t.get("tag") or {}).get(k) or ""
            if v and v not in out:
                out.append(v)
    return out


def make_segment(guid: str, n: int, para: int, baseline: str, words: list[dict], free: str = "",
                 lit: str = "", notes: list[str] | None = None, begin: int | None = None,
                 end: int | None = None, media: str | None = None, k: int | None = None) -> dict:
    """`n` counts segments through the whole text (what `seg=` in an embed means); `k` counts
    them within their paragraph, and `label` is FLEx's own number for the segment — the
    `4.1` of its Gloss / Analyze / Print views (paragraph 4, segment 1). Seth, 2026-10-13:
    "we need to actually capture FLEx's numbering"."""
    return {
        "guid": guid, "n": n, "para": para, "k": k, "label": (f"{para}.{k}" if k else str(n)),
        "baseline": baseline, "words": words,
        "free": free, "lit": lit, "notes": list(notes or []),
        "begin": begin, "end": end, "media": media,
    }


def make_word(txt: str, punct: bool = False, gls: str = "", pos: str = "",
              morphs: list[dict] | None = None, guid: str = "") -> dict:
    return {"txt": txt, "punct": bool(punct), "gls": gls, "pos": pos,
            "morphs": list(morphs or []), "guid": guid}


# Morpheme break characters, as FLEx's morph types write them around a form: `-mo` (suffix),
# `ka-` (prefix), `=lo` / `lo=` (clitics), `<in>` (infix), `~` (reduplication). FLEx shows them
# on the Morphemes and Lex. Entries lines; the glosses must carry the same marks so that
# `ka- nuwa -mo` reads `3SG- sleep -PST` (Seth, 2026-10-13: "glosses need to match them").
_LEAD = re.compile(r"^([-=~<]+)")
_TRAIL = re.compile(r"([-=~>]+)$")


def morph_markers(form: str) -> tuple[str, str]:
    """(prefix, postfix) break characters already on a morph form, '' when none."""
    f = form or ""
    lead = _LEAD.match(f)
    trail = _TRAIL.search(f)
    if lead and lead.end() == len(f):
        return f, ""
    return (lead.group(1) if lead else ""), (trail.group(1) if trail else "")


def with_markers(text: str, prefix: str, postfix: str) -> str:
    """`text` wearing the break characters, never doubled (a gloss FLEx already hyphenated)."""
    t = text or ""
    if not t:
        return t
    if prefix and not t.startswith(prefix):
        t = prefix + t
    if postfix and not t.endswith(postfix):
        t = t + postfix
    return t


def make_morph(form: str, gls: str = "", msa: str = "", cf: str = "", prefix: str | None = None,
               postfix: str | None = None) -> dict:
    """A morph with its break characters on form, citation form AND gloss. The markers come
    from the morph type when the backend knows it; otherwise from whichever of form / cf
    already carries them."""
    if prefix is None and postfix is None:
        prefix, postfix = morph_markers(form)
        if not prefix and not postfix:
            prefix, postfix = morph_markers(cf)
    prefix, postfix = prefix or "", postfix or ""
    return {"form": with_markers(form, prefix, postfix), "gls": with_markers(gls, prefix, postfix),
            "msa": msa, "cf": with_markers(cf, prefix, postfix)}


def strip_markers(text: str, form: str) -> str:
    """`text` without the break characters `form` wears (a gloss `-PST` → `PST`), for formats
    that keep glosses bare (flextext)."""
    pre, post = morph_markers(form or "")
    t = text or ""
    if pre and t.startswith(pre) and len(t) > len(pre):
        t = t[len(pre):]
    if post and t.endswith(post) and len(t) > len(post):
        t = t[:-len(post)]
    return t


def morph_type_of(form: str) -> str:
    """FLEx's morph type name from the break characters on a form: `ka-` prefix, `-mo` suffix,
    `=lo` enclitic, `lo=` proclitic, `<in>` infix, `~` reduplication, else stem."""
    pre, post = morph_markers(form or "")
    if pre.startswith("<") or post.endswith(">"):
        return "infix"
    if pre.startswith("=") and post.endswith("="):
        return "clitic"
    if pre.startswith("="):
        return "enclitic"
    if post.endswith("="):
        return "proclitic"
    if pre.startswith("-") and post.endswith("-"):
        return "infix"
    if pre.startswith("-"):
        return "suffix"
    if post.endswith("-"):
        return "prefix"
    if "~" in pre or "~" in post:
        return "stem"
    return "stem"


ALT_KEYS = ("titleAlts", "abbrevAlts", "sourceAlts", "commentAlts", "freeAlts", "litAlts", "notesAlts",
            "txtAlts", "glsAlts", "posAlts", "formAlts", "msaAlts", "cfAlts")


def fill_alts(text: dict) -> dict:
    """Give every string of a text its writing-system alternatives ({tag: text}) where a
    backend has none: the one value under the text's own vernacular / analysis tag. The
    flextext writer walks these to put a `lang` on each item. Existing alts are kept."""
    vt = ((text.get("ws") or {}).get("vern") or {}).get("tag") or "und"
    at = ((text.get("ws") or {}).get("anal") or {}).get("tag") or "en"
    one = lambda v, tag: ({tag: v} if v else {})  # noqa: E731
    text.setdefault("titleAlts", dict(text.get("titleAlternatives") or {}) or one(text.get("title", ""), at))
    text.setdefault("abbrevAlts", one(text.get("abbrev", ""), at))
    text.setdefault("sourceAlts", one(text.get("source", ""), at))
    text.setdefault("commentAlts", one(text.get("comment", ""), at))
    for seg in text.get("segments") or []:
        seg.setdefault("freeAlts", one(seg.get("free", ""), at))
        seg.setdefault("litAlts", one(seg.get("lit", ""), at))
        seg.setdefault("notesAlts", [one(n, at) for n in (seg.get("notes") or [])])
        for w in seg.get("words") or []:
            w.setdefault("txtAlts", one(w.get("txt", ""), vt))
            if not w.get("punct"):
                w.setdefault("glsAlts", one(w.get("gls", ""), at))
                w.setdefault("posAlts", one(w.get("pos", ""), at))
            for m in w.get("morphs") or []:
                m.setdefault("formAlts", one(m.get("form", ""), vt))
                m.setdefault("glsAlts", one(strip_markers(m.get("gls", ""), m.get("form", "")), at))
                m.setdefault("msaAlts", one(m.get("msa", ""), at))
                m.setdefault("cfAlts", one(m.get("cf", ""), vt))
    return text


def strip_alts(text: dict) -> dict:
    """The same text without the alternatives (what ordinary rendering and snapshots carry)."""
    for k in ALT_KEYS:
        text.pop(k, None)
    for seg in text.get("segments") or []:
        for k in ALT_KEYS:
            seg.pop(k, None)
        for w in seg.get("words") or []:
            for k in ALT_KEYS:
                w.pop(k, None)
            for m in w.get("morphs") or []:
                for k in ALT_KEYS:
                    m.pop(k, None)
    return text


def empty_entry(guid: str, headword: str = "") -> dict:
    return {
        "kind": "entry", "guid": guid, "headword": headword, "lexemeForm": "", "citationForm": "",
        "morphType": "", "homograph": 0, "pos": "", "note": "", "ws": {"vern": make_ws(), "anal": make_ws()},
        "senses": [], "url": "",
    }


def make_sense(guid: str, number: str, gloss: str = "", definition: str = "", pos: str = "",
               examples: list[dict] | None = None, note: str = "", domains: list[str] | None = None) -> dict:
    """One sense. `senses` on an entry is FLAT and in FLEx order; a sub-sense is the sense whose
    number has a dot (`2.1`), `level` = depth, `parent` = the number it hangs under."""
    number = number or ""
    return {"guid": guid, "number": number, "gloss": gloss, "definition": definition,
            "pos": pos, "examples": list(examples or []), "note": note or "",
            "domains": list(domains or []),
            "level": number.count("."), "parent": number.rsplit(".", 1)[0] if "." in number else ""}


# --------------------------------------------------------------------------- tokenising
# Borrowed from flextext-editor/docs/js/flextext.js (tokenize + PUNCT_LEADS): a word is letters,
# marks, digits and the orthographic word-internal marks; runs of other characters are punctuation.

_WORD_CHAR = re.compile(r"[\w'’ʼ‘\-=ʔ]", re.UNICODE)
PUNCT_LEADS = re.compile(r"^[(\[{«“‘'\"¿¡]")


def tokenize(text: str) -> list[dict]:
    tokens: list[dict] = []
    cur = ""
    cur_p = ""
    for ch in text or "":
        if ch.isspace():
            if cur:
                tokens.append({"txt": cur, "punct": False}); cur = ""
            if cur_p:
                tokens.append({"txt": cur_p, "punct": True}); cur_p = ""
        elif _WORD_CHAR.match(ch):
            if cur_p:
                tokens.append({"txt": cur_p, "punct": True}); cur_p = ""
            cur += ch
        else:
            if cur:
                tokens.append({"txt": cur, "punct": False}); cur = ""
            cur_p += ch
    if cur:
        tokens.append({"txt": cur, "punct": False})
    if cur_p:
        tokens.append({"txt": cur_p, "punct": True})
    return tokens


def fill_punctuation(words: list[dict], baseline: str) -> list[dict]:
    """Punctuation tokens whose text could not be read take theirs from the segment's baseline
    (the n-th punctuation run of the baseline for the n-th punctuation token, when the counts
    agree); any still empty is dropped, never shown as a placeholder or written to an export
    (Seth, 2026-10-16: "A PunctuationForm" in an example; a <word/> FLEx refused)."""
    if not any(w.get("punct") and not w.get("txt") for w in words):
        return words
    marks = [t["txt"] for t in tokenize(baseline or "") if t["punct"] and t["txt"].strip()]
    puncts = [w for w in words if w.get("punct")]
    if len(marks) == len(puncts):
        for w, m in zip(puncts, marks):
            if not w.get("txt"):
                w["txt"] = m
    return [w for w in words if not (w.get("punct") and not w.get("txt"))]

def baseline_from_words(words: list[dict]) -> str:
    """Opening punctuation leads the next word; everything else trails the previous one."""
    out = ""
    prev_leads = False
    for w in words:
        t = w.get("txt", "")
        if not out:
            out = t
        elif (w.get("punct") and not PUNCT_LEADS.match(t)) or prev_leads:
            out += t
        else:
            out += " " + t
        prev_leads = bool(w.get("punct")) and bool(PUNCT_LEADS.match(t))
    return out


# --------------------------------------------------------------------------- blank lines

_INVISIBLE = re.compile(r"[\s\u200b-\u200d\u2060\ufeff]+")


def is_blank_segment(seg: dict) -> bool:
    """A line with no word and no text — only spaces, the line break FLEx's Shift+Enter leaves
    (U+2028) or other invisible characters — and no translation or note. FLEx shows no such line
    (though it numbers it); the page and every export leave it out (ui/js/interlinear.js blankSeg)."""
    vis = lambda t: _INVISIBLE.sub("", t or "")  # noqa: E731
    if vis(seg.get("baseline")) or any(vis(w.get("txt")) for w in seg.get("words") or []):
        return False
    if vis(seg.get("free")) or vis(seg.get("lit")):
        return False
    return not any(vis(n) for n in seg.get("notes") or [])


# --------------------------------------------------------------------------- segment index + anchors
# An embed addresses segments by running count (`seg=6-11`), which FLEx renumbers the moment a
# line is added or removed above them. So the embed also carries the GUIDs of the first and last
# segment (`at=4ad2c1f0-9f0c33ab`, 8 hex each), and every text comes with a compact index
# [{n, label, guid}] of ALL its segments: the anchors are resolved against it, the range is
# moved to follow them, and the note's `seg=` is rewritten (Seth, 2026-10-13: "GUIDs mean
# those numbers will adjust automatically").

ANCHOR_LEN = 12


def anchor_of(guid: str) -> str:
    """The LAST 12 hex digits of a GUID: the random tail, unlike the head, which the demo's
    hand-made GUIDs (and some generators) share."""
    return (guid or "").lower().replace("-", "")[-ANCHOR_LEN:]


def _find_anchor(index: list[dict], want: str, near: int) -> int | None:
    """n of the segment whose anchor ends with `want` (shorter anchors from older notes still
    match); with several, the one nearest the numeric hint."""
    w = (want or "").lower().replace("-", "")
    if not w:
        return None
    hits = [int(e["n"]) for e in index if anchor_of(e.get("guid", "")).endswith(w)]
    if not hits:
        return None
    return min(hits, key=lambda n: (abs(n - near), n))


def resolve_range(index: list[dict], seg_from: int | None, seg_to: int | None,
                  at: list | None) -> dict:
    """Where does the embed's range sit now? {from, to, moved, lost}. `at` = [first, last]
    anchors (either may be missing); a found anchor wins over the number, a lost anchor keeps
    the number (or the range's length from the other anchor)."""
    total = len(index)
    a = max(1, int(seg_from or 1))
    b = int(seg_to) if seg_to else (total or a)
    if not at or not index:
        return {"from": a, "to": b, "moved": False, "lost": False}
    want = [str(x or "") for x in list(at)[:2]]
    while len(want) < 2:
        want.append("")
    fa = _find_anchor(index, want[0], a)
    fb = _find_anchor(index, want[1], b)
    length = b - a
    na, nb = a, b
    if fa is not None and fb is not None:
        na, nb = min(fa, fb), max(fa, fb)
    elif fa is not None:
        na, nb = fa, fa + length
    elif fb is not None:
        na, nb = max(1, fb - length), fb
    nb = max(na, nb)
    return {"from": na, "to": nb, "moved": (na, nb) != (a, b), "lost": (fa is None and bool(want[0])) or (fb is None and bool(want[1]))}


def index_of_segments(segments: list[dict]) -> list[dict]:
    return [{"n": int(s["n"]), "label": s.get("label") or str(s["n"]), "guid": s.get("guid", "")} for s in segments]


def index_lines(seg: dict) -> tuple[str, str]:
    """A segment's Morphemes and Lex. Gloss lines as FLEx copies them, for locating pasted
    rows that have no Word line (the morpheme forms need not spell the baseline word)."""
    forms, glosses = [], []
    for w in seg.get("words") or []:
        for m in w.get("morphs") or []:
            forms.append(m.get("form", "") or "")
            glosses.append(m.get("gls", "") or "")
    return " ".join(x for x in forms if x), " ".join(x for x in glosses if x)


def anchors_for(segments: list[dict]) -> list[str]:
    """[first, last] anchors of the segments actually returned ('' when none)."""
    if not segments:
        return ["", ""]
    return [anchor_of(segments[0].get("guid", "")), anchor_of(segments[-1].get("guid", ""))]


# --------------------------------------------------------------------------- search text

def searchable_text(obj: dict) -> str:
    """What the notebook index should see for an embedded object: headword, glosses,
    baselines, free translations — so a search for a vernacular word finds the note."""
    if not obj:
        return ""
    parts: list[str] = []
    if obj.get("kind") == "entry":
        parts += [obj.get("headword", ""), obj.get("lexemeForm", ""), obj.get("citationForm", ""), obj.get("pos", "")]
        parts.append(obj.get("note", ""))
        for s in obj.get("senses", []):
            parts += [s.get("gloss", ""), s.get("definition", ""), s.get("pos", ""), s.get("note", "")] + list(s.get("domains", []))
            for ex in s.get("examples", []):
                parts += [ex.get("text", ""), ex.get("translation", "")]
    elif obj.get("kind") == "text":
        parts.append(obj.get("title", ""))
        for seg in obj.get("segments", []):
            parts += [seg.get("baseline", ""), seg.get("free", ""), seg.get("lit", "")]
            for w in seg.get("words", []):
                parts.append(w.get("gls", ""))
                for m in w.get("morphs", []):
                    parts += [m.get("form", ""), m.get("gls", "")]
        # its FLEx text markup tags: by name, and as ⚑name so `tagged:name` finds the note
        for name in tag_names(obj):
            parts += [name, "\u2691" + name.replace(" ", "_")]
    elif obj.get("kind") == "wordform":
        parts += [obj.get("form", "")] + list(obj.get("glosses", []))
    elif obj.get("kind") == "chart":
        parts.append(chart_searchable_text(obj))
    return " ".join(p for p in parts if p)


# --------------------------------------------------------------------------- text charts
# A FieldWorks constituent chart (Texts & Words › Text Chart; Seth, 2026-10-18), as plain dicts:
#
#   chart = {kind: 'chart', guid, name, text (guid), title, abbrev, url, ws: {vern, anal},
#            template: {guid, name, columns: [column…]},   column = tag_item + {n: 1-based index}
#            markers: [tag_item…]  (the project's Chart Markers list, with its hierarchy),
#            rows: [row…], rowCount, index: [{n, label, guid}], segments: [segment…] (the
#            text's segments the rows touch, whole, for the free translations), range, anchors}
#   row   = {guid, n, label, clause: normal|dependent|speech|song, endSent, endPara, depStart,
#            depEnd, notes, cells: [cell…]}
#   cell  = {kind: words, col (column guid), colN, mergeAfter, mergeBefore, guid,
#            seg, segTo (running numbers), from: {seg, w}, to: {seg, w}, words: [word…]}
#         | {kind: moved, col, colN, guid, target (word-group guid), preposed}
#         | {kind: clause, col, colN, guid, rows: [row guid…], labels: [label…]}
#         | {kind: tag, col, colN, guid, tag: tag_item | None}
#
# Word groups address words exactly as text markup tags do (segment + analysis index), so
# `cell_words` slices a segment's words by their `ai`. Rows are anchored by their GUIDs (the
# `at=` of a chart embed; `index` is the rows' index, so resolve_range works unchanged).

CLAUSE_TYPES = {0: "normal", 1: "dependent", 2: "song", 3: "speech"}


def make_column(guid: str, name: str, abbr: str = "", path: list | None = None, n: int = 0) -> dict:
    c = tag_item(guid, name, abbr, "", "", "", path=path)
    c["n"] = int(n)
    return c


def make_chart(guid: str, name: str, text_guid: str, title: str = "", ws_vern: dict | None = None,
               ws_anal: dict | None = None, template: dict | None = None, markers: list | None = None) -> dict:
    tname = (template or {}).get("name") or ""
    # FieldWorks' charts usually have no name of their own (Seth's project, 2026-10-18: none of 80
    # did): a nameless chart goes by its template, which is what tells a text's charts apart
    return {"kind": "chart", "guid": (guid or "").lower(), "name": name or (tname + " chart" if tname else ""), "named": bool(name), "text": (text_guid or "").lower(),
            "title": title or "", "abbrev": "", "url": "",
            "ws": {"vern": ws_vern or make_ws(), "anal": ws_anal or make_ws()},
            "template": template or {"guid": "", "name": "", "columns": []}, "markers": list(markers or []),
            "rows": [], "rowCount": 0, "index": [], "segments": [], "media": [], "range": [0, 0], "anchors": ["", ""]}


def make_row(guid: str, n: int, label: str, clause: str | int = "normal", end_sent: bool = False,
             end_para: bool = False, notes: str = "", cells: list | None = None,
             dep_start: bool = False, dep_end: bool = False) -> dict:
    if isinstance(clause, int):
        clause = CLAUSE_TYPES.get(clause, "normal")
    return {"guid": (guid or "").lower(), "n": int(n), "label": label or str(n), "clause": clause or "normal",
            "endSent": bool(end_sent), "endPara": bool(end_para), "depStart": bool(dep_start), "depEnd": bool(dep_end),
            "notes": notes or "", "cells": list(cells or [])}


def cell_words(seg: dict, ai_from: int, ai_to: int) -> list[dict]:
    """The words of a segment whose analysis index lies in ai_from..ai_to (what a word group
    covers); a word without `ai` counts by its position among the tokens."""
    out = []
    for i, w in enumerate(seg.get("words") or []):
        ai = w.get("ai") if w.get("ai") is not None else i
        if ai_from <= ai <= ai_to:
            out.append(dict(w, ai=ai))
    return out


def make_word_cell(guid: str, col: dict | None, seg_a: dict, ai_a: int, seg_b: dict, ai_b: int,
                   merge_after: bool = False, merge_before: bool = False) -> dict:
    """A word-group cell: its words taken from the segment(s) it spans. Spanning two segments,
    the group runs from ai_a to the end of the first and from 0 to ai_b of the last (anything
    between belongs whole — rare, and left to the caller to add)."""
    words = cell_words(seg_a, ai_a, ai_b if seg_a is seg_b or seg_a.get("n") == seg_b.get("n") else 10 ** 6)
    if seg_a.get("n") != seg_b.get("n"):
        words += cell_words(seg_b, 0, ai_b)
    return {"kind": "words", "col": (col or {}).get("guid", ""), "colN": (col or {}).get("n", 0), "guid": (guid or "").lower(),
            "mergeAfter": bool(merge_after), "mergeBefore": bool(merge_before),
            "seg": int(seg_a.get("n") or 0), "segTo": int(seg_b.get("n") or 0),
            "from": {"seg": int(seg_a.get("n") or 0), "w": int(ai_a)}, "to": {"seg": int(seg_b.get("n") or 0), "w": int(ai_b)},
            "words": words}


def make_marker_cell(kind: str, guid: str, col: dict | None, **extra) -> dict:
    d = {"kind": kind, "col": (col or {}).get("guid", ""), "colN": (col or {}).get("n", 0), "guid": (guid or "").lower(),
         "mergeAfter": bool(extra.pop("merge_after", False)), "mergeBefore": bool(extra.pop("merge_before", False))}
    d.update(extra)
    return d


def finish_chart(chart: dict, segments_by_n: dict | None = None) -> dict:
    """Fill the derived fields: row numbers, the rows' index, the segments the rows touch
    (sorted), each moved-text marker's target row / column, each clause marker's labels."""
    rows = chart.get("rows") or []
    for i, r in enumerate(rows, 1):
        r["n"] = i
    chart["rowCount"] = len(rows)
    chart["index"] = [{"n": r["n"], "label": r.get("label") or str(r["n"]), "guid": r.get("guid", "")} for r in rows]
    by_row = {r["guid"]: r for r in rows}
    groups = {}
    for r in rows:
        for c in r.get("cells") or []:
            if c.get("kind") == "words":
                groups[c["guid"]] = (r, c)
    for r in rows:
        for c in r.get("cells") or []:
            if c.get("kind") == "moved":
                t = groups.get(c.get("target", ""))
                c["targetRow"] = t[0]["label"] if t else ""
                c["targetCol"] = t[1]["col"] if t else ""
                c["targetColN"] = t[1]["colN"] if t else 0
            elif c.get("kind") == "clause":
                c["labels"] = [by_row[g]["label"] for g in c.get("rows") or [] if g in by_row]
    if segments_by_n is not None:
        used = set()
        for r in rows:
            for c in r.get("cells") or []:
                if c.get("kind") == "words":
                    used.update(range(c["seg"], c["segTo"] + 1))
        chart["segments"] = [segments_by_n[n] for n in sorted(used) if n in segments_by_n]
    chart["range"] = [1, len(rows)] if rows else [0, 0]
    chart["anchors"] = [anchor_of(rows[0]["guid"]), anchor_of(rows[-1]["guid"])] if rows else ["", ""]
    return chart


def slice_chart(chart: dict, row_from: int | None, row_to: int | None, at: list | None = None) -> dict:
    """The rows an embed asks for (1-based, inclusive; `at` = row anchors win over numbers, as
    for text segments). The whole chart's index, template, markers and segments stay, so the
    page can draw headers and translations for any slice."""
    import copy
    rows = chart.get("rows") or []
    index = chart.get("index") or [{"n": r["n"], "label": r["label"], "guid": r["guid"]} for r in rows]
    r = resolve_range(index, row_from, row_to, at)
    a = max(1, r["from"])
    b = min(len(rows), r["to"] if (row_to or at) else len(rows))
    out = copy.deepcopy(dict(chart))
    out["rows"] = [x for x in out["rows"] if a <= x["n"] <= b]
    out["range"] = [a, b] if rows else [0, 0]
    out["anchors"] = [anchor_of(out["rows"][0]["guid"]), anchor_of(out["rows"][-1]["guid"])] if out["rows"] else ["", ""]
    out["rangeMoved"] = bool(r["moved"])
    out["anchorsLost"] = bool(r["lost"])
    return out


def chart_searchable_text(obj: dict) -> str:
    """What the index sees for a chart embed: its name, the text's title, every row's label,
    words, glosses and notes, the column names, and the markers as ⚐name tokens (so
    `marker:name` in the search box finds the note)."""
    parts = [obj.get("name", ""), obj.get("title", "")]
    for c in (obj.get("template") or {}).get("columns") or []:
        parts += [c.get("name", ""), c.get("abbr", "")]
    for r in obj.get("rows") or []:
        parts += [r.get("label", ""), r.get("notes", "")]
        for c in r.get("cells") or []:
            if c.get("kind") == "words":
                for w in c.get("words") or []:
                    parts += [w.get("txt", ""), w.get("gls", "")]
                    for m in w.get("morphs") or []:
                        parts += [m.get("form", ""), m.get("gls", "")]
            elif c.get("kind") == "tag" and c.get("tag"):
                nm = c["tag"].get("name") or c["tag"].get("abbr") or ""
                if nm:
                    parts += [nm, "⚐" + nm.replace(" ", "_")]
    return " ".join(p for p in parts if p)


# -- doubled morph bundles (Seth, 2026-10-19) --------------------------------------------------
# FieldWorks' interlinear importer (BIRDInterlinearImporter.UpgradeToWordGloss) gives a glossed
# word with no <morphemes> block ONE morph bundle holding the word's form — once PER GLOSS
# LANGUAGE, on the same analysis. A word glossed in English and Indonesian comes out with two
# identical, sense-less bundles ("budu budu", "*** ***"). `doubled_bundles` finds them in a list of
# bundle records as `lcm.explain_doubled_bundles` reads them.
def doubled_bundles(bundles: list[dict]) -> list[list[int]]:
    """Groups (lists of bundle indexes, each ≥ 2 long) of bundles that are identical and linked to
    nothing: the same `forms` (writing system → form), and no `sense`, `msa` or `morph`."""
    groups: dict[str, list[int]] = {}
    for i, b in enumerate(bundles):
        if b.get("sense") or b.get("msa") or b.get("morph"):
            continue
        forms = b.get("forms") or {}
        if not any(v for v in forms.values()):
            continue
        key = json.dumps(sorted(forms.items()), ensure_ascii=False)
        groups.setdefault(key, []).append(i)
    return [g for g in groups.values() if len(g) >= 2]
