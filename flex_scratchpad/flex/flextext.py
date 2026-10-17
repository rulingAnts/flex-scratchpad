"""The `.flextext` fallback source: FLEx's own interlinear export, parsed into the same model
the LCM backend builds. A port of flextext-editor's `parseFlextext` (docs/js/flextext.js) that
also keeps morphemes, POS, notes and time offsets, which the editor preserves but does not render.

Lexicon entries are NOT available from a .flextext file — only texts. Reading the FLEx project
directly through flexicon is the primary path; this exists so notes still render on a machine
without FieldWorks and so the interlinear rendering can be tested end to end.
"""
from __future__ import annotations

import os
import re
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

from . import model


def _items(el: ET.Element, typ: str) -> list[ET.Element]:
    return [c for c in el if c.tag == "item" and c.get("type") == typ]


def _alts(items: list[ET.Element]) -> dict:
    """{lang: text} for every item of one type (every writing system the file carries)."""
    out: dict = {}
    for it in items:
        txt = (it.text or "").strip()
        if txt:
            out[it.get("lang") or "und"] = txt
    return out


def _pick(items: list[ET.Element], lang: str) -> ET.Element | None:
    if not items:
        return None
    if lang:
        for it in items:
            if it.get("lang") == lang:
                return it
    return items[0]


def _text(el: ET.Element | None) -> str:
    return (el.text or "") if el is not None else ""


def _ms(v: str | None) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(float(v))
    except ValueError:
        return None


class FlextextFile:
    """All interlinear texts of one .flextext file (a file may hold several)."""

    def __init__(self, path: str | Path, media_folders: list[str] | None = None):
        self.path = Path(path)
        self.media_folders = [str(p) for p in (media_folders or [])]
        tree = ET.parse(self.path)
        self.root = tree.getroot()
        self.vern_lang, self.anal_lang = self._languages()
        self.texts: list[dict] = []
        for it in self.root.iter("interlinear-text"):
            self.texts.append(self._parse_text(it))

    # -- languages -------------------------------------------------------------

    def _languages(self) -> tuple[str, str]:
        vern, anal = "", ""
        for lg in self.root.iter("language"):
            lang = lg.get("lang") or ""
            if lg.get("vernacular") == "true":
                vern = vern or lang
            else:
                anal = anal or lang
        return vern, anal

    def _ws(self, lang: str) -> dict:
        rtl = False
        for lg in self.root.iter("language"):
            if (lg.get("lang") or "") == lang:
                rtl = (lg.get("RightToLeft") or lg.get("rtl") or "").lower() == "true"
                font = lg.get("font") or ""
                return model.make_ws(lang, lang, font, rtl)
        return model.make_ws(lang, lang, "", rtl)

    # -- texts -----------------------------------------------------------------

    def _parse_text(self, it: ET.Element) -> dict:
        guid = (it.get("guid") or str(uuid.uuid4())).lower()
        title = _text(_pick(_items(it, "title"), self.vern_lang)) or _text(_pick(_items(it, "title"), self.anal_lang))
        text = model.empty_text(guid, title, self._ws(self.vern_lang), self._ws(self.anal_lang))
        text["abbrev"] = _text(_pick(_items(it, "title-abbreviation"), self.vern_lang))
        text["source"] = _text(_pick(_items(it, "source"), self.anal_lang))
        text["comment"] = _text(_pick(_items(it, "comment"), self.anal_lang))
        text["titleAlts"] = _alts(_items(it, "title"))
        text["abbrevAlts"] = _alts(_items(it, "title-abbreviation"))
        text["sourceAlts"] = _alts(_items(it, "source"))
        text["commentAlts"] = _alts(_items(it, "comment"))
        text["languages"] = [{"tag": lg.get("lang") or "", "font": lg.get("font") or "", "vernacular": lg.get("vernacular") == "true", "rtl": lg.get("RightToLeft") == "true"} for lg in self.root.iter("language")]
        text["source"] = "flextext"
        langs = [self._ws(lg.get("lang") or "") for lg in self.root.iter("language")]
        text["wsOptions"] = {"vernacular": [w for w, lg in zip(langs, self.root.iter("language")) if lg.get("vernacular") == "true"],
                             "analysis": [w for w, lg in zip(langs, self.root.iter("language")) if lg.get("vernacular") != "true"]}
        text["media"] = self._media(it)
        n = 0
        pi = 0
        for paragraphs in it.findall("paragraphs"):
            for para in paragraphs.findall("paragraph"):
                pi += 1
                k = 0
                for phrases in para.findall("phrases"):
                    for ph in phrases.findall("phrase"):
                        n += 1
                        k += 1
                        text["segments"].append(self._parse_phrase(ph, n, pi, k))
        text["segmentCount"] = n
        return text

    def _media(self, it: ET.Element) -> list[dict]:
        out = []
        for mf in it.findall("media-files"):
            for m in mf.findall("media"):
                uri = m.get("location") or ""
                path, found = self.resolve_media(uri)
                out.append({
                    "guid": (m.get("guid") or "").lower(), "uri": uri,
                    "path": path, "fileUrl": Path(path).resolve().as_uri() if found else "",
                    "found": found,
                })
        return out

    def resolve_media(self, uri: str) -> tuple[str, bool]:
        """Export locations are usually absolute Windows paths from another machine; look
        next to the file, then by basename in the media folders."""
        if not uri:
            return "", False
        raw = uri.replace("\\", "/")
        base = os.path.basename(raw)
        candidates = [Path(uri)] if os.path.isabs(uri) else []
        candidates += [self.path.parent / raw, self.path.parent / base]
        for folder in self.media_folders:
            candidates.append(Path(folder) / base)
            candidates.append(Path(folder) / raw)
        for c in candidates:
            try:
                if c.is_file():
                    return str(c), True
            except OSError:
                pass
        for folder in self.media_folders:
            for dirpath, _dirs, files in os.walk(folder):
                if base in files:
                    return str(Path(dirpath) / base), True
        return uri, False

    def _parse_phrase(self, ph: ET.Element, n: int, para: int, k: int | None = None) -> dict:
        guid = (ph.get("guid") or str(uuid.uuid4())).lower()
        kids = list(ph)
        words_el = next((k for k in kids if k.tag == "words"), None)
        before = [k for k in kids if k.tag == "item" and (words_el is None or kids.index(k) < kids.index(words_el))]
        after = [k for k in kids if k.tag == "item" and words_el is not None and kids.index(k) > kids.index(words_el)]
        baseline = _text(_pick([i for i in before if i.get("type") == "txt"], self.vern_lang))
        gls_after = [i for i in after if i.get("type") == "gls"]
        gls_any = [i for i in kids if i.tag == "item" and i.get("type") == "gls"]
        free = _text(_pick(gls_after or gls_any, self.anal_lang))
        lit = _text(_pick([i for i in kids if i.tag == "item" and i.get("type") == "lit"], self.anal_lang))
        notes = [_text(i) for i in kids if i.tag == "item" and i.get("type") == "note" and _text(i)]
        words: list[dict] = []
        if words_el is not None:
            for w in words_el:
                if w.tag == "word":
                    words.append(self._parse_word(w))
        if not baseline:
            baseline = model.baseline_from_words(words)
        seg = model.make_segment(
            guid, n, para, baseline, words, k=k, free=free, lit=lit, notes=notes,
            begin=_ms(ph.get("begin-time-offset")), end=_ms(ph.get("end-time-offset")),
            media=(ph.get("media-file") or None),
        )
        seg["freeAlts"] = _alts(gls_after or gls_any)
        seg["litAlts"] = _alts([i for i in kids if i.tag == "item" and i.get("type") == "lit"])
        seg["notesAlts"] = [_alts([i]) for i in kids if i.tag == "item" and i.get("type") == "note" and _text(i)]
        return seg

    def _parse_word(self, w: ET.Element) -> dict:
        items = [c for c in w if c.tag == "item"]
        punct = _pick([i for i in items if i.get("type") == "punct"], self.vern_lang)
        if punct is not None:
            pw = model.make_word(_text(punct), punct=True, guid=(w.get("guid") or "").lower())
            pw["txtAlts"] = _alts([i for i in items if i.get("type") == "punct"])
            return pw
        txt = _text(_pick([i for i in items if i.get("type") == "txt"], self.vern_lang))
        gls = _text(_pick([i for i in items if i.get("type") == "gls"], self.anal_lang))
        pos = _text(_pick([i for i in items if i.get("type") == "pos"], self.anal_lang))
        morphs: list[dict] = []
        for ms in w.findall("morphemes"):
            for m in ms.findall("morph"):
                mi = [c for c in m if c.tag == "item"]
                md = model.make_morph(
                    form=_text(_pick([i for i in mi if i.get("type") == "txt"], self.vern_lang)),
                    gls=_text(_pick([i for i in mi if i.get("type") == "gls"], self.anal_lang)),
                    msa=_text(_pick([i for i in mi if i.get("type") == "msa"], self.anal_lang)),
                    cf=_text(_pick([i for i in mi if i.get("type") == "cf"], self.vern_lang)),
                )
                md["formAlts"] = _alts([i for i in mi if i.get("type") == "txt"])
                md["glsAlts"] = _alts([i for i in mi if i.get("type") == "gls"])
                md["msaAlts"] = _alts([i for i in mi if i.get("type") == "msa"])
                md["cfAlts"] = _alts([i for i in mi if i.get("type") == "cf"])
                if m.get("type"):
                    md["type"] = m.get("type")
                morphs.append(md)
        if not txt and morphs:
            txt = "".join(re.sub(r"^[-=~]+|[-=~]+$", "", m["form"]) for m in morphs)
        wd = model.make_word(txt, gls=gls, pos=pos, morphs=morphs, guid=(w.get("guid") or "").lower())
        wd["txtAlts"] = _alts([i for i in items if i.get("type") == "txt"])
        wd["glsAlts"] = _alts([i for i in items if i.get("type") == "gls"])
        wd["posAlts"] = _alts([i for i in items if i.get("type") == "pos"])
        return wd


class FlextextBackend:
    """Backend over one or more .flextext files (texts only; no lexicon)."""

    kind = "flextext"

    def __init__(self, paths: list[str] | str, project_name: str = "", media_folders: list[str] | None = None):
        self.paths = [paths] if isinstance(paths, str) else list(paths)
        self.project_name = project_name or (Path(self.paths[0]).stem if self.paths else "")
        self.media_folders = media_folders or []
        self.files: list[FlextextFile] = []
        self.texts: dict[str, dict] = {}
        for p in self.paths:
            f = FlextextFile(p, self.media_folders)
            self.files.append(f)
            for t in f.texts:
                self.texts[t["guid"]] = t

    def status(self) -> dict:
        return {"source": "flextext", "project": self.project_name, "open": True,
                "paths": self.paths, "texts": len(self.texts), "entries": 0}

    def list_projects(self) -> list[str]:
        return [self.project_name]

    def list_texts(self) -> list[dict]:
        return [{"guid": t["guid"], "title": t["title"], "abbrev": t["abbrev"],
                 "segmentCount": t["segmentCount"], "hasMedia": any(m["found"] for m in t["media"])}
                for t in self.texts.values()]

    def get_text(self, guid: str, seg_from: int | None = None, seg_to: int | None = None,
                 max_segments: int = 60, ws=None, diag=False, at=None, alts: bool = False) -> dict:
        t = self.texts.get((guid or "").lower())
        if not t:
            raise KeyError(f"No text with guid {guid} in the .flextext file(s).")
        return slice_text(t, seg_from, seg_to, max_segments, at=at, alts=alts)

    def search_texts(self, q: str) -> list[dict]:
        ql = (q or "").casefold()
        return [t for t in self.list_texts() if ql in t["title"].casefold()]

    def search_entries(self, q: str, limit: int = 30) -> list[dict]:
        return []

    def get_entry(self, guid: str) -> dict:
        raise KeyError("Lexical entries are not available from a .flextext file; open the FLEx project.")

    def all_baselines(self) -> dict:
        return {g: {"title": t["title"], "segments": [(sg["n"], sg["baseline"], sg.get("free", "")) + model.index_lines(sg) + (sg.get("label") or str(sg["n"]), sg.get("guid", "")) for sg in t["segments"]]}
                for g, t in self.texts.items()}

    def text_baselines(self, guid: str) -> dict:
        t = self.texts.get((guid or "").lower()) or {"segments": []}
        return {model.anchor_of(sg.get("guid", "")): sg.get("baseline", "") for sg in t["segments"]}

    def resolve_guid(self, guid: str) -> dict | None:
        g = (guid or "").lower()
        if g in self.texts:
            return {"kind": "text", "guid": g, "title": self.texts[g]["title"]}
        for t in self.texts.values():
            for s in t["segments"]:
                if s["guid"] == g:
                    return {"kind": "text", "guid": t["guid"], "title": t["title"], "seg": s["n"]}
        return None

    def close(self) -> None:
        pass


def slice_text(text: dict, seg_from: int | None, seg_to: int | None, max_segments: int = 60, ws=None, diag=False,
               at: list | None = None, alts: bool = False) -> dict:
    """A copy of the text carrying only segments seg_from..seg_to (1-based, inclusive), capped;
    with `at` anchors the range follows the anchored segments (see model.resolve_range)."""
    segs = text["segments"]
    total = len(segs)
    index = model.index_of_segments(segs)
    r = model.resolve_range(index, seg_from, seg_to, at)
    a = max(1, r["from"])
    b = min(total, r["to"] if seg_to or at else total)
    if b - a + 1 > max_segments:
        b = a + max_segments - 1
    import copy
    out = copy.deepcopy(dict(text))
    out["segments"] = copy.deepcopy(segs[a - 1:b])
    # every writing-system alternative rides only when asked for (the flextext export);
    # ordinary rendering and snapshots carry the one value per line
    if alts:
        model.fill_alts(out)
    else:
        model.strip_alts(out)
    out["segmentCount"] = total
    out["range"] = [a, b] if total else [0, 0]
    out["index"] = index
    out["anchors"] = model.anchors_for(out["segments"])
    out["rangeMoved"] = bool(r["moved"])
    out["anchorsLost"] = bool(r["lost"])
    return out
