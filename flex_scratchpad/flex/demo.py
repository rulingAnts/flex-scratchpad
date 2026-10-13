"""A built-in demo project: an invented language ("Kalu", not a real one) with a small lexicon
and two interlinear texts — one timed against a generated WAV, one in Arabic script (RTL) — so
the app, its tests and the in-browser mock all have the same data without FieldWorks.
"""
from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

from . import model

PROJECT = "Kalu Demo"

WS_VERN = model.make_ws("kal", "Kalu", "Charis SIL", False)
WS_ANAL = model.make_ws("en", "English", "", False)
WS_ARAB = model.make_ws("kal-Arab", "Kalu (Arabic script)", "Scheherazade New", True)

E = {  # entry guids
    "kabir": "6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0001",
    "tiket": "6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0002",
    "ka": "6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0003",
    "mo": "6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0004",
    "nuwa": "6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0005",
    "sila": "6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0006",
    "pemu": "6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0007",
    "lo": "6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0008",
    "haŋa": "6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0009",
    "ɲamú": "6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0010",
}
T_STORY = "9b1c2d3e-4f50-4a6b-8c7d-0e1f2a3b0001"
T_ARAB = "9b1c2d3e-4f50-4a6b-8c7d-0e1f2a3b0002"
MEDIA_STORY = "c0ffee00-0000-4000-8000-00000000a001"


def _entry(key, headword, pos, senses, morph_type="stem", lexeme=None, citation=None, homograph=0):
    e = model.empty_entry(E[key], headword)
    e.update({"lexemeForm": lexeme or headword, "citationForm": citation or headword,
              "morphType": morph_type, "homograph": homograph, "pos": pos,
              "ws": {"vern": WS_VERN, "anal": WS_ANAL}})
    for i, s in enumerate(senses, 1):
        number = s[4] if len(s) > 4 else str(i)                       # a sub-sense carries its own number ("2.1")
        e["senses"].append(model.make_sense(
            E[key][:-4] + E[key][-2:] + f"a{i}", number, s[0], s[1], s[2] if len(s) > 2 else pos,
            examples=[{"guid": "", "text": ex[0], "translation": ex[1]} for ex in (s[3] if len(s) > 3 else [])],
            note=s[5] if len(s) > 5 else "", domains=s[6] if len(s) > 6 else [],
        ))
    e["url"] = model.goto_url(PROJECT, "entry", e["guid"])
    return e


ENTRIES = [
    _entry("kabir", "kabir", "n", [("dog", "a domestic dog", "n", [("kabir ka-nuwa lo", "the dog is sleeping")], "1", "Also used of puppies.", ["1.6.1.1.2 Carnivore"]),
                                   ("wild dog", "any wild canid", "n", [], "2"),
                                   ("dingo", "the wild dog of the plains", "n", [], "2.1")]),
    _entry("tiket", "tiket", "n", [("child", "a child, boy or girl")]),
    _entry("ka", "ka-", "prefix", [("3SG", "third person singular subject")], morph_type="prefix"),
    _entry("mo", "-mo", "suffix", [("PST", "past tense")], morph_type="suffix"),
    _entry("nuwa", "nuwa", "v", [("sleep", "to sleep"), ("lie down", "to lie down to rest")]),
    _entry("sila", "sila", "v", [("see", "to see, to look at")]),
    _entry("pemu", "pemu", "n", [("river", "a river or large stream")]),
    _entry("lo", "lo", "part", [("DECL", "declarative particle, sentence-final")]),
    _entry("haŋa", "haŋa", "adv", [("yesterday", "the day before today")]),
    _entry("ɲamú", "ɲamú", "n", [("mother", "mother (vocative ɲamú!)")]),
]
ENTRY_BY_GUID = {e["guid"]: e for e in ENTRIES}


def W(txt, gls="", pos="", morphs=None, punct=False):
    return model.make_word(txt, punct=punct, gls=gls, pos=pos,
                           morphs=[model.make_morph(*m) for m in (morphs or [])])


def _story() -> dict:
    t = model.empty_text(T_STORY, "The dog and the river", WS_VERN, WS_ANAL)
    t["abbrev"] = "DOG"
    t["wsOptions"] = {"vernacular": [WS_VERN, WS_ARAB], "analysis": [WS_ANAL]}
    t["titleAlternatives"] = {"en": "The dog and the river", "kal": "Kabir pemu"}
    t["url"] = model.goto_url(PROJECT, "text", T_STORY)
    t["media"] = [{"guid": MEDIA_STORY, "uri": "AudioVisual/kalu-story.wav", "path": "", "fileUrl": "", "found": False}]
    segs = [
        (1, "Kabir ka-nuwa-mo lo.", [W("Kabir", "dog", "n", [("kabir", "dog", "n")]),
                                      W("ka-nuwa-mo", "slept", "v", [("ka-", "3SG", "prefix"), ("nuwa", "sleep", "v"), ("-mo", "PST", "suffix")]),
                                      W("lo", "DECL", "part", [("lo", "DECL", "part")]), W(".", punct=True)],
         "The dog slept.", 0, 1500),
        (1, "Haŋa tiket ka-sila-mo pemu.", [W("Haŋa", "yesterday", "adv", [("haŋa", "yesterday", "adv")]),
                                            W("tiket", "child", "n", [("tiket", "child", "n")]),
                                            W("ka-sila-mo", "saw", "v", [("ka-", "3SG", "prefix"), ("sila", "see", "v"), ("-mo", "PST", "suffix")]),
                                            W("pemu", "river", "n", [("pemu", "river", "n")]), W(".", punct=True)],
         "Yesterday the child saw the river.", 1500, 3200),
        (2, "“Ɲamú!” ka-sila lo.", [W("“", punct=True), W("Ɲamú", "mother", "n", [("ɲamú", "mother", "n")]),
                                              W("!”", punct=True),
                                              W("ka-sila", "sees", "v", [("ka-", "3SG", "prefix"), ("sila", "see", "v")]),
                                              W("lo", "DECL", "part", [("lo", "DECL", "part")]), W(".", punct=True)],
         "“Mother!” he sees.", 3200, 4600),
        (2, "Kabir pemu ka-nuwa lo.", [W("Kabir", "dog", "n", [("kabir", "dog", "n")]),
                                        W("pemu", "river", "n", [("pemu", "river", "n")]),
                                        W("ka-nuwa", "sleeps", "v", [("ka-", "3SG", "prefix"), ("nuwa", "sleep", "v")]),
                                        W("lo", "DECL", "part", [("lo", "DECL", "part")]), W(".", punct=True)],
         "The dog sleeps by the river.", 4600, 6000),
        (3, "Tiket ka-nuwa-mo.", [W("Tiket", "child", "n", [("tiket", "child", "n")]),
                                  W("ka-nuwa-mo", "slept", "v", [("ka-", "3SG", "prefix"), ("nuwa", "sleep", "v"), ("-mo", "PST", "suffix")]),
                                  W(".", punct=True)],
         "The child slept.", 6000, 7000),
        (3, "Kabir lo.", [W("Kabir", "dog", "n", [("kabir", "dog", "n")]), W("lo", "DECL", "part", [("lo", "DECL", "part")]), W(".", punct=True)],
         "The dog.", 7000, 8000),
    ]
    kk: dict = {}
    for i, (para, base, words, free, b, e) in enumerate(segs, 1):
        kk[para] = kk.get(para, 0) + 1
        t["segments"].append(model.make_segment(
            f"9b1c2d3e-4f50-4a6b-8c7d-0e1f2a3b1{i:03d}", i, para, base, words, free=free, k=kk[para],
            begin=b, end=e, media=MEDIA_STORY, notes=["Segment one has a note."] if i == 1 else []))
    t["segmentCount"] = len(t["segments"])
    return t


def _arabic() -> dict:
    """A right-to-left text (Arabic script, real Arabic words used as sample vernacular)."""
    t = model.empty_text(T_ARAB, "الكلب والنهر", WS_ARAB, WS_ANAL)
    t["abbrev"] = "RTL"
    t["url"] = model.goto_url(PROJECT, "text", T_ARAB)
    segs = [
        (1, "الكلب نام.", [
            W("الكلب", "the.dog", "n", [("ال-", "DEF", "prefix"), ("كلب", "dog", "n")]),
            W("نام", "slept", "v", [("نام", "sleep.PST", "v")]), W(".", punct=True)],
         "The dog slept."),
        (1, "رأى الولد النهر أمس.", [
            W("رأى", "saw", "v", [("رأى", "see.PST", "v")]),
            W("الولد", "the.child", "n", [("ال-", "DEF", "prefix"), ("ولد", "child", "n")]),
            W("النهر", "the.river", "n", [("ال-", "DEF", "prefix"), ("نهر", "river", "n")]),
            W("أمس", "yesterday", "adv", [("أمس", "yesterday", "adv")]), W(".", punct=True)],
         "The child saw the river yesterday."),
    ]
    kk: dict = {}
    for i, (para, base, words, free) in enumerate(segs, 1):
        kk[para] = kk.get(para, 0) + 1
        t["segments"].append(model.make_segment(f"9b1c2d3e-4f50-4a6b-8c7d-0e1f2a3b2{i:03d}", i, para, base, words, free=free, k=kk[para]))
    t["segmentCount"] = len(t["segments"])
    return t


def write_demo_wav(path: Path, seconds: float = 8.0, rate: int = 16000) -> Path:
    """An 8 s WAV whose pitch steps every second, so a played range is audibly a range."""
    path.parent.mkdir(parents=True, exist_ok=True)
    n = int(seconds * rate)
    frames = bytearray()
    for i in range(n):
        t = i / rate
        step = int(t)
        f = 220.0 * (2 ** (step / 12 * 2))
        v = 0.35 * math.sin(2 * math.pi * f * t) * (0.5 + 0.5 * math.sin(2 * math.pi * 1.0 * t))
        frames += struct.pack("<h", int(v * 32767))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))
    return path


class DemoBackend:
    """The Backend protocol over the fixture above. `media_dir` (optional) receives the demo WAV."""

    kind = "demo"

    def __init__(self, media_dir: str | Path | None = None, media_map: dict | None = None):
        self.project_name = PROJECT
        self.texts = {T_STORY: _story(), T_ARAB: _arabic()}
        self.media_map = dict(media_map or {})
        self.media_dir = Path(media_dir) if media_dir else None
        if self.media_dir:
            wav = self.media_dir / "AudioVisual" / "kalu-story.wav"
            if not wav.exists():
                write_demo_wav(wav)
        self._resolve_media()

    def _resolve_media(self) -> None:
        for t in self.texts.values():
            for m in t["media"]:
                p = self.media_map.get(m["guid"])
                if not p and self.media_dir:
                    p = str(self.media_dir / m["uri"].replace("\\", "/"))
                found = bool(p) and Path(p).is_file()
                m["path"] = p or ""
                m["found"] = found
                m["fileUrl"] = Path(p).resolve().as_uri() if found else ""

    def set_media_map(self, media_map: dict) -> None:
        self.media_map = dict(media_map or {})
        self._resolve_media()

    def status(self) -> dict:
        return {"source": "demo", "project": PROJECT, "open": True,
                "texts": len(self.texts), "entries": len(ENTRIES)}

    def list_projects(self) -> list[str]:
        return [PROJECT]

    def search_entries(self, q: str, limit: int = 30) -> list[dict]:
        ql = (q or "").strip().casefold()
        out = []
        for e in ENTRIES:
            hay = [e["headword"], e["lexemeForm"], e["citationForm"]] + [s["gloss"] for s in e["senses"]]
            if not ql or any(ql in h.casefold() for h in hay):
                out.append(entry_summary(e))
            if len(out) >= limit:
                break
        return out

    def get_entry(self, guid: str) -> dict:
        e = ENTRY_BY_GUID.get((guid or "").lower())
        if not e:
            raise KeyError(f"No entry with guid {guid}")
        return e

    def list_texts(self) -> list[dict]:
        return [{"guid": t["guid"], "title": t["title"], "abbrev": t["abbrev"],
                 "segmentCount": t["segmentCount"], "hasMedia": any(m["found"] for m in t["media"])}
                for t in self.texts.values()]

    def search_texts(self, q: str) -> list[dict]:
        ql = (q or "").casefold()
        return [t for t in self.list_texts() if ql in t["title"].casefold()]

    def get_text(self, guid: str, seg_from=None, seg_to=None, max_segments: int = 60, ws=None, diag=False, at=None) -> dict:
        from .flextext import slice_text
        t = self.texts.get((guid or "").lower())
        if not t:
            raise KeyError(f"No text with guid {guid}")
        return slice_text(t, seg_from, seg_to, max_segments, at=at)

    def all_baselines(self) -> dict:
        return {g: {"title": t["title"], "segments": [(sg["n"], sg["baseline"], sg.get("free", "")) for sg in t["segments"]]}
                for g, t in self.texts.items()}

    def resolve_guid(self, guid: str) -> dict | None:
        g = (guid or "").lower()
        if g in ENTRY_BY_GUID:
            return {"kind": "entry", "guid": g, "title": ENTRY_BY_GUID[g]["headword"]}
        for e in ENTRIES:
            for s in e["senses"]:
                if s["guid"] == g:
                    return {"kind": "entry", "guid": e["guid"], "title": e["headword"], "sense": s["number"]}
        if g in self.texts:
            return {"kind": "text", "guid": g, "title": self.texts[g]["title"]}
        for t in self.texts.values():
            for s in t["segments"]:
                if s["guid"] == g:
                    return {"kind": "text", "guid": t["guid"], "title": t["title"], "seg": s["n"]}
        return None

    def close(self) -> None:
        pass


def entry_summary(e: dict) -> dict:
    return {"guid": e["guid"], "headword": e["headword"], "pos": e["pos"],
            "gloss": "; ".join(s["gloss"] for s in e["senses"] if s["gloss"]),
            "senses": len(e["senses"]), "morphType": e["morphType"]}
