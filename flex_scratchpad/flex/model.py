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
from urllib.parse import parse_qs, quote, urlparse

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
        qs = parse_qs(u.query)
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
                 end: int | None = None, media: str | None = None) -> dict:
    return {
        "guid": guid, "n": n, "para": para, "baseline": baseline, "words": words,
        "free": free, "lit": lit, "notes": list(notes or []),
        "begin": begin, "end": end, "media": media,
    }


def make_word(txt: str, punct: bool = False, gls: str = "", pos: str = "",
              morphs: list[dict] | None = None, guid: str = "") -> dict:
    return {"txt": txt, "punct": bool(punct), "gls": gls, "pos": pos,
            "morphs": list(morphs or []), "guid": guid}


def make_morph(form: str, gls: str = "", msa: str = "", cf: str = "") -> dict:
    return {"form": form, "gls": gls, "msa": msa, "cf": cf}


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
