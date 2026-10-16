"""Write a note's examples as a FLEx interlinear `.flextext` file (Seth, 2026-10-16).

One `<document>` holds one `<interlinear-text>` PER BASELINE WRITING SYSTEM, because a FLEx
text has one vernacular writing system (Seth: "one text can only have one baseline"): examples
from texts in another vernacular WS go into a second text in the same file, and FLEx imports
each as its own text. Within a text every example is a PARAGRAPH (so FLEx numbers them 1.1,
2.1 …) and every segment of it a PHRASE. Every writing-system alternative a backend handed
over (`*Alts`, see model.fill_alts) is written as its own `<item lang="…">`; FLEx keeps them.

GUIDs: text / paragraph / phrase GUIDs are NEW (an existing GUID would make FLEx's import
touch the original text). Word GUIDs are the analyses' own and are kept by default, so the
imported text reuses the same analyses; `wordGuids=False` drops them.

The original place of every line goes into a Note item (text title, FLEx number, segment GUID)
and, when asked, a `flexscratchpad://note/<id>` link back to the note; the note's markdown can
ride as the text's comment (Info tab → Comment) — flextext carries that as `<item type="comment">`.
"""
from __future__ import annotations

import uuid
import xml.etree.ElementTree as ET

from . import model


def _item(parent: ET.Element, typ: str, alts: dict | None, fallback: str = "", lang: str = "en") -> None:
    """One <item> per writing-system alternative (or the single value under `lang`)."""
    pairs = [(k, v) for k, v in (alts or {}).items() if v]
    if not pairs and fallback:
        pairs = [(lang, fallback)]
    for tag, text in pairs:
        it = ET.SubElement(parent, "item", {"type": typ, "lang": tag})
        it.text = text


def _vern_tag(text: dict) -> str:
    return ((text.get("ws") or {}).get("vern") or {}).get("tag") or "und"


def _anal_tag(text: dict) -> str:
    return ((text.get("ws") or {}).get("anal") or {}).get("tag") or "en"


def group_by_baseline(examples: list[dict]) -> list[tuple[str, list[dict]]]:
    """[(vernacular tag, [examples…])] in order of first appearance."""
    groups: dict[str, list[dict]] = {}
    for ex in examples:
        groups.setdefault(_vern_tag(ex["text"]), []).append(ex)
    return list(groups.items())


def _source_note(ex: dict, seg: dict, note_url: str) -> str:
    text = ex["text"]
    parts = [f"Source: {text.get('title') or 'untitled text'} {seg.get('label') or seg.get('n')}"]
    if seg.get("guid"):
        parts.append(f"segment {seg['guid']}")
    if text.get("guid"):
        parts.append(f"text {text['guid']}")
    if ex.get("label"):
        parts.append(f"label: {ex['label']}")
    if note_url:
        parts.append(f"note: {note_url}")
    return " · ".join(parts)


def _word(words_el: ET.Element, w: dict, vern: str, anal: str, word_guids: bool) -> None:
    attrs = {}
    if word_guids and w.get("guid") and not w.get("punct"):
        attrs["guid"] = w["guid"]
    we = ET.SubElement(words_el, "word", attrs)
    if w.get("punct"):
        _item(we, "punct", w.get("txtAlts"), w.get("txt", ""), vern)
        return
    _item(we, "txt", w.get("txtAlts"), w.get("txt", ""), vern)
    morphs = w.get("morphs") or []
    if morphs:
        ms = ET.SubElement(we, "morphemes")
        for m in morphs:
            mtype = m.get("type") or model.morph_type_of(m.get("form", ""))
            me = ET.SubElement(ms, "morph", {"type": mtype})
            _item(me, "txt", m.get("formAlts"), m.get("form", ""), vern)
            _item(me, "cf", m.get("cfAlts"), m.get("cf", ""), vern)
            gls_alts = {k: model.strip_markers(v, m.get("form", "")) for k, v in (m.get("glsAlts") or {}).items()}
            _item(me, "gls", gls_alts, model.strip_markers(m.get("gls", ""), m.get("form", "")), anal)
            _item(me, "msa", m.get("msaAlts"), m.get("msa", ""), anal)
    _item(we, "gls", w.get("glsAlts"), w.get("gls", ""), anal)
    _item(we, "pos", w.get("posAlts"), w.get("pos", ""), anal)


def _languages(doc_texts: list[dict]) -> dict:
    """{tag: {font, vernacular, rtl}} over every writing system any item used."""
    langs: dict[str, dict] = {}
    for t in doc_texts:
        for w in (t.get("languages") or []):
            if w.get("tag"):
                langs.setdefault(w["tag"], {"font": w.get("font", ""), "vernacular": bool(w.get("vernacular")), "rtl": bool(w.get("rtl"))})
        for key, vern in (("vern", True), ("anal", False)):
            ws = (t.get("ws") or {}).get(key) or {}
            if ws.get("tag"):
                langs.setdefault(ws["tag"], {"font": ws.get("font", ""), "vernacular": vern, "rtl": bool(ws.get("rtl"))})
        opts = t.get("wsOptions") or {}
        for w in opts.get("vernacular", []):
            langs.setdefault(w["tag"], {"font": w.get("font", ""), "vernacular": True, "rtl": bool(w.get("rtl"))})
        for w in opts.get("analysis", []):
            langs.setdefault(w["tag"], {"font": w.get("font", ""), "vernacular": False, "rtl": bool(w.get("rtl"))})
    return langs


def build_flextext(examples: list[dict], opts: dict | None = None) -> str:
    """`examples`: [{text: <text dict with the example's segments, alts filled>, label, note}] in note
    order. opts: title, abbrev, noteUrl, markdown, sourceNotes (True), wordGuids (True),
    onlyWs (a vernacular tag, to keep one baseline only)."""
    opts = dict(opts or {})
    title = (opts.get("title") or "Examples").strip()
    note_url = opts.get("noteUrl") or ""
    source_notes = opts.get("sourceNotes", True)
    word_guids = opts.get("wordGuids", True)
    groups = group_by_baseline(examples)
    if opts.get("onlyWs"):
        groups = [(k, v) for k, v in groups if k == opts["onlyWs"]]
    doc = ET.Element("document", {"version": "2"})
    used_langs: set[str] = set()
    all_texts = [ex["text"] for _, exs in groups for ex in exs]
    langs = _languages(all_texts)
    media_entries: dict[str, str] = {}      # location → media guid (per document, FLEx keys them per text; fine)
    for vern, exs in groups:
        first = exs[0]["text"]
        anal = _anal_tag(first)
        it = ET.SubElement(doc, "interlinear-text", {"guid": str(uuid.uuid4())})
        suffix = f" ({vern})" if len(groups) > 1 else ""
        _item(it, "title", None, title + suffix, anal)
        if opts.get("abbrev"):
            _item(it, "title-abbreviation", None, opts["abbrev"], anal)
        src = "FLEx Scratchpad" + (f" — {note_url}" if note_url else "")
        _item(it, "source", None, src, anal)
        if opts.get("markdown"):
            _item(it, "comment", None, opts["markdown"], anal)
        paras = ET.SubElement(it, "paragraphs")
        text_media: dict[str, str] = {}
        for ex in exs:
            text = ex["text"]
            pe = ET.SubElement(paras, "paragraph", {"guid": str(uuid.uuid4())})
            phs = ET.SubElement(pe, "phrases")
            seg_k = 0
            for seg in text.get("segments") or []:
                seg_k += 1
                attrs = {"guid": str(uuid.uuid4())}
                if seg.get("begin") is not None and seg.get("end") is not None:
                    m = next((x for x in (text.get("media") or []) if x.get("guid") == seg.get("media")), None) or (text.get("media") or [{}])[0]
                    loc = (m or {}).get("path") or (m or {}).get("uri") or ""
                    if loc:
                        mg = text_media.get(loc) or str(uuid.uuid4())
                        text_media[loc] = mg
                        attrs.update({"begin-time-offset": str(int(seg["begin"])), "end-time-offset": str(int(seg["end"])), "media-file": mg})
                ph = ET.SubElement(phs, "phrase", attrs)
                segnum = ET.SubElement(ph, "item", {"type": "segnum", "lang": anal})
                segnum.text = f"{len(paras)}.{seg_k}"
                words_el = ET.SubElement(ph, "words")
                for w in seg.get("words") or []:
                    _word(words_el, w, vern, anal, word_guids)
                _item(ph, "gls", seg.get("freeAlts"), seg.get("free", ""), anal)
                _item(ph, "lit", seg.get("litAlts"), seg.get("lit", ""), anal)
                notes_alts = seg.get("notesAlts")
                if notes_alts:
                    for na in notes_alts:
                        _item(ph, "note", na, "", anal)
                else:
                    for n in seg.get("notes") or []:
                        _item(ph, "note", None, n, anal)
                if seg_k == 1 and (ex.get("note") or "").strip():
                    # the author's own note on this example (a collection's "> " lines), on its
                    # first line, always — it is part of the analysis, not provenance
                    _item(ph, "note", None, ex["note"].strip(), anal)
                if source_notes:
                    _item(ph, "note", None, _source_note(ex, seg, note_url), anal)
                used_langs.update(i.get("lang") for i in ph.iter("item"))
        used_langs.update(i.get("lang") for i in it.findall("item"))
        lg = ET.SubElement(it, "languages")
        for tag, info in langs.items():
            if tag not in used_langs:
                continue
            a = {"lang": tag}
            if info.get("font"):
                a["font"] = info["font"]
            if info.get("vernacular") or tag == vern:
                a["vernacular"] = "true"
            if info.get("rtl"):
                a["RightToLeft"] = "true"
            ET.SubElement(lg, "language", a)
        for tag in sorted(used_langs - set(langs)):
            a = {"lang": tag}
            if tag == vern:
                a["vernacular"] = "true"
            ET.SubElement(lg, "language", a)
        if text_media:
            mf = ET.SubElement(it, "media-files", {"offset-type": "milliseconds"})
            for loc, mg in text_media.items():
                ET.SubElement(mf, "media", {"guid": mg, "location": loc})
        media_entries.update(text_media)
    ET.indent(doc, space="  ")
    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(doc, encoding="unicode") + "\n"
