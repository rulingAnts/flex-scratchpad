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
        "media": [], "segments": [],
    }


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


def empty_entry(guid: str, headword: str = "") -> dict:
    return {
        "kind": "entry", "guid": guid, "headword": headword, "lexemeForm": "", "citationForm": "",
        "morphType": "", "homograph": 0, "pos": "", "ws": {"vern": make_ws(), "anal": make_ws()},
        "senses": [], "url": "",
    }


def make_sense(guid: str, number: str, gloss: str = "", definition: str = "", pos: str = "",
               examples: list[dict] | None = None) -> dict:
    return {"guid": guid, "number": number, "gloss": gloss, "definition": definition,
            "pos": pos, "examples": list(examples or [])}


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


# --------------------------------------------------------------------------- search text

def searchable_text(obj: dict) -> str:
    """What the notebook index should see for an embedded object: headword, glosses,
    baselines, free translations — so a search for a vernacular word finds the note."""
    if not obj:
        return ""
    parts: list[str] = []
    if obj.get("kind") == "entry":
        parts += [obj.get("headword", ""), obj.get("lexemeForm", ""), obj.get("citationForm", ""), obj.get("pos", "")]
        for s in obj.get("senses", []):
            parts += [s.get("gloss", ""), s.get("definition", ""), s.get("pos", "")]
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
    elif obj.get("kind") == "wordform":
        parts += [obj.get("form", "")] + list(obj.get("glosses", []))
    return " ".join(p for p in parts if p)
