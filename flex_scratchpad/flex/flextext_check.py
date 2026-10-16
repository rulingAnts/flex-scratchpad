"""What FLEx's interlinear import needs of a .flextext, beyond its schema.

FieldWorks publishes the format as `FlexInterlinear.xsd` (DistFiles/Language Explorer/Export
Templates/Interlinear in the FieldWorks repository; the tests validate every export against a copy,
tests/fixtures/FlexInterlinear.xsd). But FLEx never validates an import against it: it reads the file
with .NET's XmlSerializer and walks it in `BIRDInterlinearImporter.cs`, which assumes things the
schema leaves optional. A file can be schema-valid and still fail the import with "Object reference
not set to an instance of an object" — Seth's export did, 2026-10-16, on one `<word/>` with no items.

`import_problems` lists what the importer would trip over, read from that source (master,
2026-10-16). Stdlib only, so the export runs it before writing a file.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

# FlexInterlinear.xsd's morphTypes (FLEx's importer does not read the morph type at all, but a
# file that keeps to the schema is one other tools read too)
MORPH_TYPES = frozenset((
    "particle", "infix", "prefix", "simulfix", "suffix", "suprafix", "circumfix", "clitic",
    "enclitic", "proclitic", "bound root", "root", "bound stem", "stem", "infixing interfix",
    "prefixing interfix", "suffixing interfix", "phrase", "discontiguous phrase",
))


def _text(el) -> str:
    return "".join(el.itertext()) if el is not None else ""


def import_problems(xml: str) -> list[str]:
    """Each thing in `xml` that FLEx's interlinear import would fail on, as a sentence naming
    where it is ("text 1, phrase 3.1, word 4: …"). Empty when the file should import."""
    out: list[str] = []
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        return [f"not well-formed XML: {e}"]
    if root.tag != "document":
        return ["the root element is not <document>"]
    texts = root.findall("interlinear-text")
    if not texts:
        out.append("no <interlinear-text>")
    for ti, it in enumerate(texts, 1):
        where_t = f"text {ti}"
        # SetVernacularLanguagesByUsage walks interlinText.languages.language unchecked
        langs = {lg.get("lang") for lg in it.findall("languages/language")}
        if not langs:
            out.append(f"{where_t}: no <languages> list")
        if any(not item.get("lang") for item in it.findall("item")):
            out.append(f"{where_t}: an item without lang")
        media = {m.get("guid") for m in it.findall("media-files/media")}
        paras = it.findall("paragraphs/paragraph")
        if it.find("paragraphs") is None:
            out.append(f"{where_t}: no <paragraphs>")
        for pi, pe in enumerate(paras, 1):
            phrases = pe.findall("phrases/phrase")
            if not phrases:
                out.append(f"{where_t}, paragraph {pi}: no phrases")
            for ki, ph in enumerate(phrases, 1):
                num = ph.find("item[@type='segnum']")
                where_p = f"{where_t}, phrase {_text(num) or f'{pi}.{ki}'}"
                # AddSegmentItemData / SetVernacularLanguagesByUsage: phrase.Items unchecked
                if ph.find("item") is None:
                    out.append(f"{where_p}: a phrase with no items")
                if ph.find("words") is None:
                    out.append(f"{where_p}: no <words>")
                mf = ph.get("media-file")
                if mf and mf not in media:
                    # AddELANInfoToSegment: ObjectRepository.GetObject(new Guid(media-file)) throws
                    out.append(f"{where_p}: media-file {mf} is not in the text's <media-files>")
                if mf and (ph.get("begin-time-offset") is None or ph.get("end-time-offset") is None):
                    out.append(f"{where_p}: media-file without both time offsets")
                if any(not item.get("lang") for item in ph.findall("item")):
                    out.append(f"{where_p}: an item without lang")
                for wi, we in enumerate(ph.findall("words/word"), 1):
                    where_w = f"{where_p}, word {wi}"
                    items = we.findall("item")
                    # UpdatePhraseTextForWordItems / FindOrCreateWfiAnalysis: word.Items unchecked,
                    # and a word needs a txt or punct to become anything
                    forms = [i for i in items if i.get("type") in ("txt", "punct") and _text(i)]
                    if not forms:
                        out.append(f"{where_w}: no txt or punct item")
                    for i in items:
                        if not i.get("lang"):
                            out.append(f"{where_w}: an item without lang")
                        elif i.get("type") in ("txt", "punct") and langs and i.get("lang") not in langs:
                            out.append(f"{where_w}: writing system {i.get('lang')} is not in <languages>")
                    ms = we.find("morphemes")
                    if ms is not None:
                        morphs = ms.findall("morph")
                        # CreateWordformWithWfiAnalysis: morphemes.morphs.Length unchecked
                        if not morphs:
                            out.append(f"{where_w}: an empty <morphemes>")
                        for mi, m in enumerate(morphs, 1):
                            # the analysis match reads the FIRST txt item's lang (null → throws)
                            if not any(_text(x) and x.get("lang") for x in m.findall("item[@type='txt']")):
                                out.append(f"{where_w}, morph {mi}: no txt item")
                            if m.get("type") and m.get("type") not in MORPH_TYPES:
                                out.append(f"{where_w}, morph {mi}: morph type {m.get('type')!r} is not one of FLEx's")
    return out
