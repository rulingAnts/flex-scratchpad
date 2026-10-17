"""Reading the FieldWorks project directly, through flexicon (LCM via pythonnet).

⚠ Written without a FieldWorks installation to run against (as fdat's sidecar was). The
property names follow the LCM model (SIL.LCModel) and flexicon 4.12's operation namespaces,
and every access is guarded so one odd object degrades to a plainer rendering instead of
failing the whole text or entry. Expect to adjust details on first contact with a real project.

Threading: pywebview invokes `js_api` methods on arbitrary threads and LCM is not documented as
thread-safe, so ONE worker thread initialises flexicon, opens the project and runs every LCM
call; no .NET object ever leaves it — every call returns plain dicts.
"""
from __future__ import annotations

import os
import queue
import re
import threading
from concurrent.futures import Future
from pathlib import Path

from . import model

OPEN_TIMEOUT = 600      # a big project can take minutes to open
CALL_TIMEOUT = 180


class FlexError(RuntimeError):
    """A message fit for the UI (the LCM detail goes in `detail`)."""

    def __init__(self, message: str, detail: str = "", code: str = ""):
        super().__init__(message)
        self.message, self.detail, self.code = message, detail, code


def _friendly(exc: BaseException, project: str = "") -> FlexError:
    name = type(exc).__name__
    text = str(exc)
    if isinstance(exc, FlexError):
        return exc
    if isinstance(exc, ImportError) or name == "ModuleNotFoundError":
        return FlexError(
            "flexicon is not installed, so the FLEx project cannot be read directly. "
            "Install it with  pip install \"flex-scratchpad[flex]\"  (pyflexicon + pythonnet, "
            "64-bit Python to match FieldWorks) on a Windows machine with FieldWorks installed.",
            text, "no-flexicon")
    if name == "FP_FileLockedError":
        return FlexError(
            f"The project “{project}” is locked by FieldWorks. Either close FLEx, or turn on "
            "Project Properties → Sharing → “Share project contents with programs on this "
            "computer” in FLEx so both can read it at once.", text, "locked")
    if name == "FP_MigrationRequired":
        return FlexError(
            f"The project “{project}” needs a data migration. Open it in FieldWorks once, then try again.",
            text, "migration")
    if name == "FP_FileNotFoundError":
        return FlexError(f"No FieldWorks project named “{project}” was found.", text, "not-found")
    if name == "FP_ParameterError":
        return FlexError("That object does not exist in the open project (stale or foreign GUID).", text, "no-object")
    return FlexError(f"FieldWorks read failed: {text or name}", text, "lcm")


# ----------------------------------------------------------------------------
# The worker thread
# ----------------------------------------------------------------------------

class LcmWorker(threading.Thread):
    def __init__(self):
        super().__init__(name="lcm-worker", daemon=True)
        self.q: "queue.Queue[tuple | None]" = queue.Queue()
        self.start()

    def run(self) -> None:
        while True:
            item = self.q.get()
            if item is None:
                return
            fn, fut = item
            if fut.set_running_or_notify_cancel():
                try:
                    fut.set_result(fn())
                except BaseException as e:  # noqa: BLE001 — every failure goes back to the caller
                    fut.set_exception(e)

    def call(self, fn, timeout: float = CALL_TIMEOUT):
        fut: Future = Future()
        self.q.put((fn, fut))
        return fut.result(timeout=timeout)

    def stop(self) -> None:
        self.q.put(None)


# ----------------------------------------------------------------------------
# Helpers that run ON the worker (they touch .NET objects)
# ----------------------------------------------------------------------------

def _t(fn, default=""):
    """Call fn(); on any failure return default. The guard that keeps one odd object from
    taking the whole text down."""
    try:
        v = fn()
        return default if v is None else v
    except Exception:  # noqa: BLE001
        return default


def _s(v) -> str:
    """A Python str out of str / ITsString / anything with .Text. Total: never raises, and
    never calls str() on a .NET object — an ITsString with no text has Text == null, and
    pythonnet cannot make a Python string out of a null ToString() (Seth's run, 2026-10-12:
    "Object reference not set to an instance of an object … PyString_FromString")."""
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    try:
        t = getattr(v, "Text", None)
    except Exception:  # noqa: BLE001
        t = None
    if isinstance(t, str):
        return t
    try:
        if hasattr(v, "Text"):
            return ""
    except Exception:  # noqa: BLE001
        return ""
    if isinstance(v, (int, float, bool)):
        return str(v)
    try:
        r = v.ToString() if hasattr(v, "ToString") else str(v)
        return r if isinstance(r, str) else ""
    except Exception:  # noqa: BLE001
        return ""


def _guid(obj) -> str:
    return _t(lambda: str(obj.Guid).lower(), "")


def _ms(v) -> int | None:
    s = _s(v).strip()
    if not s:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


class FlexiconBackend:
    """The Backend protocol over a FLEx project opened read-only through flexicon."""

    kind = "lcm"

    def __init__(self, media_map: dict | None = None, media_folders: list[str] | None = None,
                 progress=None):
        self.worker = LcmWorker()
        self.project_name = ""
        self.project = None           # flexicon FLExProject (worker-only)
        self._mod = None              # the flexicon module (worker-only)
        self.media_map = dict(media_map or {})
        self.media_folders = list(media_folders or [])
        self.progress = progress or (lambda msg: None)
        self._entry_index: list[dict] | None = None
        self._text_index: list[dict] | None = None
        self._ws: dict | None = None

    # -- lifecycle -------------------------------------------------------------

    def _import(self):
        if self._mod is None:
            import flexicon  # noqa: WPS433 — deliberately late: loads the CLR and FieldWorks DLLs
            flexicon.FLExInitialize()
            self._mod = flexicon
        return self._mod

    def _c(self, obj):
        """View an LCM object through its concrete interface. pythonnet exposes only the
        members of the interface an object was handed out as (ICmObject from most
        collections), so `text.ContentsOA`, `t.Name`, `seg.BeginTimeOffset` all come back
        empty without this (Seth's dumps, 2026-10-12). flexicon's cast_to_concrete is total:
        unknown objects come back unchanged."""
        if obj is None:
            return None
        try:
            return self._mod.cast_to_concrete(obj)
        except Exception:  # noqa: BLE001
            return obj

    def list_projects(self) -> list[str]:
        def go():
            mod = self._import()
            return sorted(str(p) for p in mod.AllProjectNames())
        try:
            return self.worker.call(go)
        except BaseException as e:
            raise _friendly(e)

    def open(self, name: str) -> dict:
        def go():
            mod = self._import()
            self.progress(f"Opening {name}…")
            if self.project is not None:
                _t(lambda: self.project.CloseProject(), None)
                self.project = None
            p = mod.FLExProject()
            p.OpenProject(name, writeEnabled=False)
            self.project = p
            self.project_name = name
            self._entry_index = None
            self._text_index = None
            self._ws = None
            return self._status()
        try:
            return self.worker.call(go, timeout=OPEN_TIMEOUT)
        except BaseException as e:
            raise _friendly(e, name)

    def close(self) -> None:
        def go():
            if self.project is not None:
                _t(lambda: self.project.CloseProject(), None)
                self.project = None
            if self._mod is not None:
                _t(lambda: self._mod.FLExCleanup(), None)
        try:
            self.worker.call(go, timeout=60)
        except BaseException:
            pass
        self.worker.stop()

    def refresh(self, indexes: bool = True) -> dict:
        """Take in what FieldWorks saved since the project was opened (RefreshFromDisk). With
        indexes=False the lexicon / text / paste indexes are kept — the ↻ on one example, which
        should not make the next paste rebuild the whole project's index."""
        def go():
            if self.project is not None:
                _t(lambda: self.project.RefreshFromDisk(), None)
            if indexes:
                self._entry_index = None
                self._text_index = None
                self._baseline_index = None
            return self._status()
        try:
            return self.worker.call(go)
        except BaseException as e:
            raise _friendly(e, self.project_name)

    def status(self) -> dict:
        return self.worker.call(self._status)

    def _status(self) -> dict:
        st = {"source": "lcm", "project": self.project_name, "open": self.project is not None,
              "ws": self._writing_systems() if self.project is not None else None}
        st.update(self._sharing_status(self.project_name))
        return st

    def _sharing_status(self, name: str) -> dict:
        """Is the project shared with other programs (FLEx: Project Properties → Sharing)?
        `shared`: True / False / None (unknown); `flexHasItOpen`: the .fwdata.lock file is
        there; `projectDir`. Read from the open cache's backend type when we have it (the
        shared XML backend is what sharing switches on), else unknown."""
        out: dict = {"shared": None, "flexHasItOpen": None, "projectDir": ""}
        if not name:
            return out
        pdir = self._project_dir(name)
        if pdir:
            out["projectDir"] = pdir
            out["flexHasItOpen"] = _t(lambda: (Path(pdir) / f"{name}.fwdata.lock").is_file(), None)
        if self.project is not None:
            kind = _s(_t(lambda: self.project.project.ProjectId.Type, "")) or _s(_t(lambda: str(self.project.project.ProjectId.Type), ""))
            if kind:
                # Only a positive answer is trusted. Seth's project (2026-10-16) is shared and
                # still reads as a plain XML backend here, so "not shared" is never concluded
                # from this; a real lock error is what says FieldWorks has it unshared.
                out["shared"] = True if "shared" in kind.lower() else None
                out["backendType"] = kind
        return out

    def _project_dir(self, name: str) -> str:
        mod = self._mod
        for fn in (lambda: str(mod.FLExLCM.FwDirectoryFinder.ProjectsDirectory),
                   lambda: str(mod.code.FLExLCM.FwDirectoryFinder.ProjectsDirectory)):
            base = _t(fn, "")
            if base:
                return str(Path(base) / name)
        return ""

    def set_media_map(self, media_map: dict) -> None:
        self.media_map = dict(media_map or {})

    # -- writing systems ---------------------------------------------------------
    #
    # ⚠ A text's vernacular is often NOT the project's default vernacular (an IPA or
    # phonemic WS beside the orthographic one, several languages in one project). Reading
    # forms with the default handle then returns '' (Seth's first run, 2026-10-12: "The
    # writing systems are all messed up"). So every vernacular string is read with the
    # TEXT'S OWN baseline WS first, then LCM's BestVernacularAlternative, then each
    # vernacular WS in turn — and never from a token's gloss.

    def _ws_info(self, tag: str, name: str) -> dict:
        ops = self.project.WritingSystems
        return model.make_ws(tag, name or _s(_t(lambda: ops.GetDisplayName(tag), "")) or tag,
                             _t(lambda: ops.GetFontName(tag), ""),
                             bool(_t(lambda: ops.GetRightToLeft(tag), False)))

    def _vern_handles(self) -> list:
        """Handles of every current vernacular WS, default first."""
        p = self.project
        out = []
        for item in _t(lambda: list(p.GetAllVernacularWSs()), []):
            tag = item[0] if isinstance(item, (tuple, list)) else item
            h = _t(lambda: p.WSHandle(tag), None)
            if h is not None and h not in out:
                out.append(h)
        dflt = _t(lambda: p.GetDefaultVernacularWSHandle(), None)
        if dflt is not None and dflt not in out:
            out.insert(0, dflt)
        return out

    def _ws_tag_of_handle(self, handle) -> str:
        p = self.project
        for fn in (lambda: p.project.WritingSystemFactory.GetStrFromWs(handle),
                   lambda: p.project.ServiceLocator.WritingSystemManager.Get(handle).Id,
                   lambda: p.project.ServiceLocator.WritingSystemManager.Get(handle).LanguageTag,
                   lambda: p.WritingSystems.GetLanguageTag(handle),
                   lambda: p.lp.Services.WritingSystemManager.Get(handle).Id):
            tag = _s(_t(fn, ""))
            if tag:
                return tag
        return ""

    def _vern_text(self, multi, ws_handle=None) -> str:
        """Vernacular text of an IMultiUnicode / IMultiString."""
        if multi is None:
            return ""
        if ws_handle is not None:
            s = _s(_t(lambda: multi.get_String(ws_handle), ""))
            if s:
                return s
        s = _s(_t(lambda: multi.BestVernacularAlternative, ""))
        if s and s != "***":
            return s
        for h in self._vern_handles():
            s = _s(_t(lambda: multi.get_String(h), ""))
            if s:
                return s
        return ""

    def _anal_text(self, multi, ws_handle=None) -> str:
        if multi is None:
            return ""
        if ws_handle is not None:
            s = _s(_t(lambda: multi.get_String(ws_handle), ""))
            if s:
                return s
        s = _s(_t(lambda: multi.BestAnalysisAlternative, ""))
        return "" if s == "***" else s

    def _ws_alternatives(self, multi) -> dict:
        """Every alternative stored on a multilingual string: {tag: text}. This is what the
        flextext export walks to write a `lang` on each item."""
        out = {}
        if multi is None:
            return out
        handles = _t(lambda: list(multi.AvailableWritingSystemIds), [])
        if not handles:
            # ITsMultiString's index walk; pythonnet returns the `out ws` as a second value
            n = int(_t(lambda: multi.StringCount, 0) or 0)
            for i in range(n):
                res = _t(lambda: multi.GetStringFromIndex(i), None)
                if isinstance(res, tuple) and len(res) == 2:
                    tss, h = res
                    txt = _s(_t(lambda: tss.Text, ""))
                    if txt:
                        out[self._ws_tag_of_handle(h) or str(h)] = txt
            return out
        for h in handles:
            txt = _s(_t(lambda: multi.get_String(h), ""))
            if txt:
                out[self._ws_tag_of_handle(h) or str(h)] = txt
        return out

    def _run_ws(self, tss):
        """Writing system of the first run of an ITsString, by whichever route works."""
        if tss is None:
            return None
        for fn in (lambda: tss.get_WritingSystemAt(0),
                   lambda: tss.get_WritingSystem(0),
                   lambda: tss.get_PropertiesAt(0).GetIntPropValues(6),   # FwTextPropType.ktptWs
                   lambda: tss.get_Properties(0).GetIntPropValues(6)):
            h = _t(fn, None)
            if isinstance(h, tuple):
                h = h[0]
            try:
                if h is not None and int(h) > 0:
                    return int(h)
            except (TypeError, ValueError):
                pass
        return None

    def _ws_lists(self) -> dict:
        """The project's current vernacular and analysis writing systems, with font/direction."""
        p = self.project
        def infos(items):
            out = []
            for item in items:
                tag = item[0] if isinstance(item, (tuple, list)) else item
                name = item[1] if isinstance(item, (tuple, list)) and len(item) > 1 else ""
                if tag and not any(x["tag"] == tag for x in out):
                    out.append(self._ws_info(str(tag), str(name or "")))
            return out
        return {"vernacular": infos(_t(lambda: list(p.GetAllVernacularWSs()), [])),
                "analysis": infos(_t(lambda: list(p.GetAllAnalysisWSs()), []))}

    VERN_LINES = ("txt", "morph", "cf")
    ANAL_LINES = ("gls", "mgls", "pos", "ft", "lit", "note")

    def _selection(self, ws: dict | None, vern_handle) -> dict:
        """line → WS handle for the lines the caller pinned (`ws=txt:fau-fonipa,gls:id`);
        vernacular lines default to the text's own WS, analysis lines to the default analysis WS."""
        p = self.project
        sel = {}
        for line in self.VERN_LINES:
            sel[line] = vern_handle
        for line in self.ANAL_LINES:
            sel[line] = None
        sel["title"] = None
        for line, tag in (ws or {}).items():
            if line in sel and tag:
                h = _t(lambda: p.WSHandle(tag), None)
                if h is not None:
                    sel[line] = h
        return sel

    def _baseline_ws(self, text):
        """(handle, tag) of the writing system the text is actually written in. FLEx records it
        on the text's contents (IStText.MainWritingSystem); failing that, the first run of the
        first paragraph. ⚠ Paragraphs come back typed as IStPara: cast to IStTxtPara before
        touching .Contents (Seth's dump, 2026-10-12: without the cast the detection failed and
        `deja` rendered as the orthographic `deia`)."""
        p = self.project
        text = self._c(text)
        contents = self._c(_t(lambda: text.ContentsOA, None))
        h = _t(lambda: int(contents.MainWritingSystem), None)
        if h and h > 0:
            tag = self._ws_tag_of_handle(h)
            if tag:
                return h, tag
        for para in _t(lambda: list(p.Paragraphs.GetAll(text)), [])[:3]:
            tp = self._c(para)
            tss = _t(lambda: tp.Contents, None)
            if tss is None or not _s(_t(lambda: tss.Text, "")):
                continue
            h = self._run_ws(tss)
            if h:
                tag = self._ws_tag_of_handle(h)
                if tag:
                    return h, tag
        # Last resort, and the one that cannot miss: the writing systems the text's own
        # wordforms are stored in (a wordform is created in the baseline's WS). Seth's dump
        # (2026-10-12): wordformAlternatives = {"fau-fonipa-x-etic": …} while both routes
        # above came back empty.
        votes: dict = {}
        for para in _t(lambda: list(p.Paragraphs.GetAll(text)), [])[:2]:
            for seg in _t(lambda: list(p.Segments.GetAll(para)), [])[:3]:
                for tok in _t(lambda: list(p.Segments.GetAnalyses(seg)), []):
                    cls = _t(lambda: tok.ClassName, "")
                    if cls == "PunctuationForm":
                        continue
                    tok = self._c(tok)
                    wf = self._c(tok if cls == "WfiWordform" else _t(lambda: tok.Wordform, None))
                    for h in _t(lambda: list(wf.Form.AvailableWritingSystemIds), []):
                        votes[h] = votes.get(h, 0) + 1
        if votes:
            best = max(votes, key=votes.get)
            tag = self._ws_tag_of_handle(best)
            if tag:
                return best, tag
        return None, ""

    def _writing_systems(self) -> dict:
        if self._ws is None:
            vt, vn = _t(lambda: tuple(self.project.GetDefaultVernacularWS()), ("", ""))
            at, an = _t(lambda: tuple(self.project.GetDefaultAnalysisWS()), ("", ""))
            self._ws = {"vern": self._ws_info(vt, vn), "anal": self._ws_info(at, an)}
        return self._ws

    # -- lexicon -----------------------------------------------------------------

    def _need(self):
        if self.project is None:
            raise FlexError("No FieldWorks project is open.", "", "no-project")

    def _build_entry_index(self) -> list[dict]:
        p = self.project
        out = []
        n = 0
        for e in p.LexiconAllEntries():
            e = self._c(e)
            n += 1
            if n % 500 == 0:
                self.progress(f"Indexing lexicon… {n}")
            senses = _t(lambda: list(e.SensesOS), [])
            glosses = [_s(_t(lambda s=s: p.LexiconGetSenseGloss(s), "")) for s in senses]
            out.append({
                "guid": _guid(e),
                "headword": _s(_t(lambda: p.LexiconGetHeadword(e), "")),
                "lexeme": _s(_t(lambda: p.LexiconGetLexemeForm(e), "")),
                "citation": _s(_t(lambda: p.LexiconGetCitationForm(e), "")),
                "gloss": "; ".join(g for g in glosses if g),
                "pos": _s(_t(lambda: p.LexiconGetSensePOS(senses[0]) if senses else "", "")),
                "senses": len(senses),
                "morphType": self._morph_type_name(e),
            })
        return out

    def _morph_type_name(self, e) -> str:
        e = self._c(e)
        mt = self._c(_t(lambda: self._c(e.LexemeFormOA).MorphTypeRA, None))
        if mt is None:
            return ""
        return _s(_t(lambda: self.project.BestStr(mt.Name), ""))

    def search_entries(self, q: str, limit: int = 30) -> list[dict]:
        def go():
            self._need()
            if self._entry_index is None:
                self._entry_index = self._build_entry_index()
            ql = (q or "").strip().casefold()
            hits = []
            for rec in self._entry_index:
                hay = (rec["headword"], rec["lexeme"], rec["citation"], rec["gloss"])
                score = 0
                for h in hay:
                    hc = h.casefold()
                    if not ql:
                        score = 1
                    elif hc == ql:
                        score = max(score, 3)
                    elif hc.startswith(ql):
                        score = max(score, 2)
                    elif ql in hc:
                        score = max(score, 1)
                if score:
                    hits.append((score, rec))
            hits.sort(key=lambda h: (-h[0], h[1]["headword"].casefold()))
            return [dict(r, gloss=r["gloss"]) for _, r in hits[:limit]]
        try:
            return self.worker.call(go, timeout=OPEN_TIMEOUT)
        except BaseException as e:
            raise _friendly(e, self.project_name)

    def get_entry(self, guid: str) -> dict:
        def go():
            self._need()
            obj = self._c(self.project.Object(guid))
            entry = self._owning_entry(obj)
            if entry is None:
                raise FlexError("That GUID is not a lexical entry or sense.", "", "no-object")
            return self._entry_dict(entry)
        try:
            return self.worker.call(go)
        except BaseException as e:
            raise _friendly(e, self.project_name)

    def _owning_entry(self, obj):
        cur = obj
        for _ in range(8):
            if cur is None:
                return None
            if _t(lambda: cur.ClassName, "") == "LexEntry":
                return self._c(cur)
            cur = self._c(_t(lambda: cur.Owner, None))
        return None

    def _entry_dict(self, e) -> dict:
        p = self.project
        e = self._c(e)
        d = model.empty_entry(_guid(e), _s(_t(lambda: p.LexiconGetHeadword(e), "")))
        d["lexemeForm"] = _s(_t(lambda: p.LexiconGetLexemeForm(e), "")) or self._vern_text(_t(lambda: e.LexemeFormOA.Form, None))
        d["citationForm"] = _s(_t(lambda: p.LexiconGetCitationForm(e), "")) or self._vern_text(_t(lambda: e.CitationForm, None))
        d["morphType"] = self._morph_type_name(e)
        d["homograph"] = int(_t(lambda: e.HomographNumber, 0) or 0)
        d["ws"] = self._writing_systems()
        d["url"] = self._goto(e, "entry")
        d["note"] = self._anal_text(_t(lambda: e.Comment, None))
        # senses and sub-senses in FLEx order (SensesOS, each sense's own SensesOS), numbered as
        # FLEx numbers them ("2.1"); flat in the dict, with level / parent for the renderer
        def walk(s, number):
            s = self._c(s)
            sd = model.make_sense(
                _guid(s),
                _s(_t(lambda: p.LexiconGetSenseNumber(s), "")) or number,
                _s(_t(lambda: p.LexiconGetSenseGloss(s), "")),
                _s(_t(lambda: p.LexiconGetSenseDefinition(s), "")),
                _s(_t(lambda: p.LexiconGetSensePOS(s), "")),
                note=self._anal_text(_t(lambda: s.GeneralNote, None)),
                domains=[x for x in (self._anal_text(_t(lambda: self._c(dm).Name, None)) or _s(_t(lambda: self._c(dm).ShortName, "")) for dm in _t(lambda: list(s.SemanticDomainsRC), [])) if x],
            )
            for ex in _t(lambda: list(s.ExamplesOS), []):
                ex = self._c(ex)
                sd["examples"].append({
                    "guid": _guid(ex),
                    "text": _s(_t(lambda: p.Examples.GetExample(ex), "")),
                    "translation": _s(_t(lambda: p.Examples.GetTranslation(ex), "")),
                })
            d["senses"].append(sd)
            for j, sub in enumerate(_t(lambda: list(s.SensesOS), []), 1):
                walk(sub, f"{sd['number']}.{j}")
        for i, s in enumerate(_t(lambda: list(e.SensesOS), []), 1):
            walk(s, str(i))
        d["pos"] = d["senses"][0]["pos"] if d["senses"] else ""
        return d

    # -- texts -------------------------------------------------------------------

    def _build_text_index(self) -> list[dict]:
        p = self.project
        out = []
        for t in p.Texts.GetAll():
            count = 0
            for para in _t(lambda: list(p.Paragraphs.GetAll(t)), []):
                count += int(_t(lambda: p.Paragraphs.GetSegmentCount(para), 0) or 0)
            tc = self._c(t)
            media = _t(lambda: list(self._c(tc.MediaFilesOA).MediaURIsOC), [])
            out.append({
                "guid": _guid(t),
                "title": self._text_title(t),
                "abbrev": _s(_t(lambda: p.Texts.GetAbbreviation(t), "")),
                "segmentCount": count,
                "hasMedia": bool(media),
            })
        out.sort(key=lambda r: r["title"].casefold())
        return out

    def _title_alternatives(self, t) -> dict:
        """{ws tag: title} for every writing system the text has a non-empty title in."""
        t = self._c(t)
        return self._ws_alternatives(_t(lambda: t.Name, None))

    def _text_title(self, t, ws_tag: str = "", vern_tag: str = "") -> str:
        """The title in the writing system asked for; otherwise the first non-empty one — the
        text's own vernacular WS, then the default analysis WS, then whatever exists (Seth's
        first run, 2026-10-12: a text titled only in the vernacular showed as untitled)."""
        p = self.project
        alts = self._title_alternatives(t)
        if ws_tag and alts.get(ws_tag):
            return alts[ws_tag]
        for fn in (lambda: p.Texts.GetName(t), lambda: p.Texts.GetTitle(t)):
            s = _s(_t(fn, ""))
            if s:
                return s
        if vern_tag and alts.get(vern_tag):
            return alts[vern_tag]
        for ws in self._ws_lists().get("vernacular", []) + self._ws_lists().get("analysis", []):
            if alts.get(ws["tag"]):
                return alts[ws["tag"]]
        for v in alts.values():
            if v:
                return v
        return "(untitled text)"

    def list_texts(self) -> list[dict]:
        def go():
            self._need()
            if self._text_index is None:
                self._text_index = self._build_text_index()
            return list(self._text_index)
        try:
            return self.worker.call(go, timeout=OPEN_TIMEOUT)
        except BaseException as e:
            raise _friendly(e, self.project_name)

    def all_baselines(self) -> dict:
        """{text guid: {title, segments: [(n, baseline, free, morphs, glosses, label, guid), …]}}
        for every text (label = FLEx's own paragraph.segment number, guid = the segment's) — one walk,
        kept for the session, so pasted interlinear lines can be located without knowing the
        text. Reset by refresh()."""
        def go():
            self._need()
            if getattr(self, "_baseline_index", None) is None:
                p = self.project
                index = {}
                texts = list(p.Texts.GetAll())
                for i, t in enumerate(texts):
                    if i % 10 == 0:
                        self.progress(f"Indexing texts\u2026 {i}/{len(texts)}")
                    segs = []
                    n = 0
                    vh = _t(lambda: self._baseline_ws(t)[0], None)     # the text's own WS for the morph forms
                    for pi, para in enumerate(_t(lambda: list(p.Paragraphs.GetAll(t)), []), 1):
                        for k, seg in enumerate(_t(lambda: list(p.Segments.GetAll(para)), []), 1):
                            n += 1
                            segs.append((n, _s(_t(lambda: p.Segments.GetBaselineText(seg), "")),
                                         _s(_t(lambda: p.Segments.GetFreeTranslation(seg), "")))
                                        + self._index_lines(seg, vh) + (f"{pi}.{k}", _guid(seg)))
                    index[_guid(t)] = {"title": self._text_title(t), "segments": segs}
                self._baseline_index = index
                self.progress("")                  # done: the pill shows the connection again
            return self._baseline_index
        try:
            return self.worker.call(go, timeout=OPEN_TIMEOUT)
        except BaseException as e:
            raise _friendly(e, self.project_name)

    def text_baselines(self, guid: str) -> dict:
        """{segment anchor: baseline} for one text as it is NOW (not the session's locate index,
        which a refresh keeps): what the line tracker compares (flex/tracking.py)."""
        def go():
            self._need()
            p = self.project
            text = self._owning_text(self._c(p.Object(guid)))
            if text is None:
                raise FlexError("That GUID is not an interlinear text.", "", "no-object")
            out = {}
            for para in _t(lambda: list(p.Paragraphs.GetAll(text)), []):
                for seg in _t(lambda: list(p.Segments.GetAll(para)), []):
                    out[model.anchor_of(_guid(seg))] = _s(_t(lambda: p.Segments.GetBaselineText(seg), ""))
            return out
        try:
            return self.worker.call(go, timeout=OPEN_TIMEOUT)
        except BaseException as e:
            raise _friendly(e, self.project_name)

    def _index_lines(self, seg, vh=None) -> tuple[str, str]:
        """The segment's Morphemes and Lex. Gloss lines (forms and glosses of every morph
        bundle), so rows pasted without a Word line can still be located. The forms are read in
        the text's own writing system (`vh`, from `_baseline_ws`) and an affix's gloss falls back
        to its sense, exactly as the rendered example does (Seth's locate report, 2026-10-16: the
        index held `bete` for `bɛtɛ` and no `.CMP`). Worker thread only."""
        p = self.project
        forms, glosses = [], []
        try:
            for tok in _t(lambda: list(p.Segments.GetAnalyses(self._c(seg))), []):
                analysis = self._c(_t(lambda: self._c(tok).Analysis, None))
                if analysis is None:
                    continue
                for b in _t(lambda: list(p.WfiMorphBundles.GetAll(analysis)), []):
                    b = self._c(b)
                    sense = self._c(_t(lambda: p.WfiMorphBundles.GetSense(b), None))
                    forms.append(self._bundle_form(b, vh))
                    glosses.append(self._bundle_gloss(b, sense))
        except Exception:  # noqa: BLE001 — the index degrades to baselines for this segment
            pass
        return " ".join(x for x in forms if x), " ".join(x for x in glosses if x)

    def _bundle_form(self, b, hm) -> str:
        """A morph bundle's form in writing system `hm` (the text's own): its own form, else its
        allomorph's — vernacular, never analysis."""
        p = self.project
        form = self._vern_text(_t(lambda: b.Form, None), hm)
        if not form:
            form = _s(_t(lambda: p.WfiMorphBundles.GetForm(b, hm) if hm is not None else p.WfiMorphBundles.GetForm(b), ""))
        if not form:
            form = self._vern_text(_t(lambda: self._c(b.MorphRA).Form, None), hm)
        return form

    def _bundle_gloss(self, b, sense, hmg=None) -> str:
        """A morph bundle's gloss: the chosen WS of its sense's gloss, else FLEx's own, else the
        sense's best (an affix often has only that)."""
        p = self.project
        mgls = self._anal_text(_t(lambda: sense.Gloss, None), hmg) if (sense is not None and hmg is not None) else ""
        if not mgls:
            mgls = _s(_t(lambda: p.WfiMorphBundles.GetGloss(b), "")) or self._anal_text(_t(lambda: sense.Gloss, None))
        return mgls

    def search_texts(self, q: str) -> list[dict]:
        ql = (q or "").casefold()
        return [t for t in self.list_texts() if ql in t["title"].casefold() or ql in t["abbrev"].casefold()]

    def get_text(self, guid: str, seg_from: int | None = None, seg_to: int | None = None,
                 max_segments: int = 60, ws: dict | None = None, diag: bool = False, at=None, alts: bool = False) -> dict:
        def go():
            self._need()
            self._alts = alts            # every writing-system alternative rides along (the flextext export)
            obj = self._c(self.project.Object(guid))
            text = self._owning_text(obj)
            if text is None:
                raise FlexError("That GUID is not an interlinear text.", "", "no-object")
            return self._text_dict(text, seg_from, seg_to, max_segments, ws, diag, at)
        try:
            return self.worker.call(go, timeout=OPEN_TIMEOUT)
        except BaseException as e:
            raise _friendly(e, self.project_name)

    def _owning_text(self, obj):
        cur = obj
        for _ in range(8):
            if cur is None:
                return None
            if _t(lambda: cur.ClassName, "") == "Text":
                return self._c(cur)
            cur = self._c(_t(lambda: cur.Owner, None))
        return None

    def _media(self, text) -> list[dict]:
        out = []
        linked = _s(_t(lambda: self.project.GetLinkedFilesDir(), ""))
        text = self._c(text)
        container = self._c(_t(lambda: text.MediaFilesOA, None))
        for m in _t(lambda: list(container.MediaURIsOC), []):
            m = self._c(m)
            uri = _s(_t(lambda: m.MediaURI, ""))
            guid = _guid(m)
            path, found = self._resolve_media(guid, uri, linked)
            out.append({"guid": guid, "uri": uri, "path": path,
                        "fileUrl": Path(path).resolve().as_uri() if found else "", "found": found})
        return out

    def _resolve_media(self, guid: str, uri: str, linked: str) -> tuple[str, bool]:
        mapped = self.media_map.get(guid)
        if mapped and Path(mapped).is_file():
            return mapped, True
        raw = uri.replace("\\", "/")
        base = os.path.basename(raw)
        cands = []
        if uri and os.path.isabs(uri):
            cands.append(Path(uri))
        if linked and raw:
            cands.append(Path(linked) / raw)
            cands.append(Path(linked) / "AudioVisual" / base)
        for folder in self.media_folders:
            cands.append(Path(folder) / base)
        for c in cands:
            if _t(lambda c=c: c.is_file(), False):
                return str(c), True
        for folder in self.media_folders:
            for dirpath, _d, files in os.walk(folder):
                if base and base in files:
                    return str(Path(dirpath) / base), True
        return uri, False

    def _segment_index(self, text) -> list[dict]:
        """[{n, label, guid}] for every segment of the text — guids only, no strings read, so
        it is cheap enough to build on every fetch (anchors, labels, the picker)."""
        p = self.project
        out = []
        n = 0
        pi = 0
        for para in _t(lambda: list(p.Paragraphs.GetAll(text)), []):
            pi += 1
            k = 0
            for seg in _t(lambda: list(p.Segments.GetAll(para)), []):
                n += 1
                k += 1
                out.append({"n": n, "label": f"{pi}.{k}", "guid": _guid(seg)})
        return out

    def _text_dict(self, text, seg_from, seg_to, max_segments: int = 60, ws_sel: dict | None = None, diag: bool = False, at=None) -> dict:
        p = self.project
        ws = self._writing_systems()
        vern_handle, vern_tag = self._baseline_ws(text)
        sel = self._selection(ws_sel, vern_handle)
        self._sel = sel
        # the WS info the renderer uses for the word line (font, direction) follows the selection
        txt_tag = (ws_sel or {}).get("txt") or vern_tag
        vern_ws = self._ws_info(txt_tag, "") if txt_tag else ws["vern"]
        anal_tag = (ws_sel or {}).get("gls") or (ws_sel or {}).get("ft") or ""
        anal_ws = self._ws_info(anal_tag, "") if anal_tag else ws["anal"]
        d = model.empty_text(_guid(text), self._text_title(text, (ws_sel or {}).get("title", ""), vern_tag), vern_ws, anal_ws)
        d["titleAlternatives"] = self._title_alternatives(text)
        d["wsOptions"] = self._ws_lists()
        d["wsDetected"] = {"tag": vern_tag, "handle": vern_handle}
        d["wsSelection"] = dict(ws_sel or {})
        self._cur_vern_handle = vern_handle
        self._diag = diag
        d["abbrev"] = _s(_t(lambda: p.Texts.GetAbbreviation(text), ""))
        d["url"] = self._goto(text, "text")
        d["media"] = self._media(text)
        if getattr(self, "_alts", False):
            d["titleAlts"] = self._title_alternatives(text)
            d["abbrevAlts"] = self._ws_alternatives(_t(lambda: text.Abbreviation, None))
            d["sourceAlts"] = self._ws_alternatives(_t(lambda: text.Source, None))
            d["commentAlts"] = self._ws_alternatives(_t(lambda: text.Description, None))
            lists = d["wsOptions"] or {}
            d["languages"] = [dict(w, vernacular=True) for w in lists.get("vernacular", [])] + [dict(w, vernacular=False) for w in lists.get("analysis", [])]
        media_by_guid = {m["guid"]: m for m in d["media"]}
        index = self._segment_index(text)
        r = model.resolve_range(index, seg_from, seg_to, at)
        a = max(1, r["from"])
        b = r["to"] if (seg_to or at) else None
        d["index"] = index
        d["rangeMoved"] = bool(r["moved"])
        d["anchorsLost"] = bool(r["lost"])
        n = 0
        pi = 0
        for para in _t(lambda: list(p.Paragraphs.GetAll(text)), []):
            pi += 1
            k = 0
            for seg in _t(lambda: list(p.Segments.GetAll(para)), []):
                n += 1
                k += 1
                if n < a or (b is not None and n > b) or (n - a) >= max_segments:
                    continue
                try:
                    d["segments"].append(self._segment_dict(seg, n, pi, media_by_guid, k))
                except Exception as exc:  # noqa: BLE001 — one odd segment must not take the text down
                    d["segments"].append(model.make_segment(_guid(seg), n, pi, "", [], notes=[f"⚠ could not read this segment: {exc}"], k=k))
                    d.setdefault("errors", []).append({"segment": n, "error": str(exc)})
        d["segmentCount"] = n
        d["range"] = [a, min(n, b or n)] if n else [0, 0]
        d["anchors"] = model.anchors_for(d["segments"])
        if getattr(self, "_alts", False):
            model.fill_alts(d)          # whatever LCM gave no alternative for keeps its one value
        return d

    def _segment_dict(self, seg, n: int, para: int, media_by_guid: dict, k: int | None = None) -> dict:
        p = self.project
        seg = self._c(seg)
        words = []
        for tok in _t(lambda: list(p.Segments.GetAnalyses(seg)), []):
            try:
                words.append(self._word_dict(tok))
            except Exception as exc:  # noqa: BLE001 — a word that cannot be read shows as "?" with the reason
                words.append(model.make_word("?", gls=f"⚠ {exc}", guid=_guid(tok)))
        baseline = _s(_t(lambda: p.Segments.GetBaselineText(seg), ""))
        words = model.fill_punctuation(words, baseline)
        baseline = baseline or model.baseline_from_words(words)
        # The baseline is already in the text's writing system; when its word tokens line up
        # with the analyses, show those surface forms (as FLEx and flextext-editor do) rather
        # than a wordform alternative from another WS.
        toks = [t["txt"] for t in model.tokenize(baseline) if not t["punct"]]
        lex = [w for w in words if not w["punct"]]
        if toks and len(toks) == len(lex):
            for w, tk in zip(lex, toks):
                if w["txt"] != tk:
                    w["wf"] = w["txt"]
                    w["txt"] = tk
        notes = []
        for note in _t(lambda: list(p.Segments.GetNotes(seg)), []):
            note = self._c(note)
            s = _s(_t(lambda: p.BestStr(note.Content), ""))
            if s:
                notes.append(s)
        media_guid = _guid(_t(lambda: seg.MediaURIRA, None)) or (next(iter(media_by_guid), None))
        sel = getattr(self, "_sel", {}) or {}
        hf, hl = sel.get("ft"), sel.get("lit")
        free = _s(_t(lambda: p.Segments.GetFreeTranslation(seg, hf) if hf is not None else p.Segments.GetFreeTranslation(seg), ""))
        lit = _s(_t(lambda: p.Segments.GetLiteralTranslation(seg, hl) if hl is not None else p.Segments.GetLiteralTranslation(seg), ""))
        out = model.make_segment(
            _guid(seg), n, para, baseline, words, k=k,
            free=free,
            lit=lit,
            notes=notes,
            begin=_ms(_t(lambda: seg.BeginTimeOffset, "")),
            end=_ms(_t(lambda: seg.EndTimeOffset, "")),
            media=media_guid or None,
        )
        if getattr(self, "_alts", False):
            out["freeAlts"] = self._ws_alternatives(_t(lambda: seg.FreeTranslation, None))
            out["litAlts"] = self._ws_alternatives(_t(lambda: seg.LiteralTranslation, None))
            out["notesAlts"] = [self._ws_alternatives(_t(lambda: self._c(note).Content, None)) for note in _t(lambda: list(p.Segments.GetNotes(seg)), [])]
        if getattr(self, "_diag", False) and n == 1:
            out["diagnostics"] = self._diagnostics(seg)
        return out

    def _diagnostics(self, seg) -> dict:
        """What is actually stored, for the first word of the first segment: every writing-
        system alternative of the baseline run, the wordform, the first morph bundle, the
        gloss, the free translation — the per-line `lang`s a flextext export would write."""
        p = self.project
        d = {"baselineRunWs": "", "wordformAlternatives": {}, "morphAlternatives": {}, "glossAlternatives": {}, "freeAlternatives": {}}
        seg = self._c(seg)
        tss = _t(lambda: seg.BaselineText, None)
        h = self._run_ws(tss)
        d["baselineRunWs"] = self._ws_tag_of_handle(h) if h else ""
        text = self._owning_text(seg)
        d["mainWritingSystem"] = _t(lambda: int(self._c(text.ContentsOA).MainWritingSystem), None) if text is not None else None
        d["titleAlternativesRaw"] = {"stringCount": _t(lambda: int(text.Name.StringCount), None), "available": _t(lambda: list(text.Name.AvailableWritingSystemIds), None)} if text is not None else {}
        toks = _t(lambda: list(p.Segments.GetAnalyses(seg)), [])
        for tok in toks:
            cls = _t(lambda: tok.ClassName, "")
            if cls == "PunctuationForm":
                continue
            tok = self._c(tok)
            wf = self._c(tok if cls == "WfiWordform" else _t(lambda: tok.Wordform, None))
            d["wordformAlternatives"] = self._ws_alternatives(_t(lambda: wf.Form, None))
            an = self._c(_t(lambda: tok.Analysis, None))
            b = self._c(next(iter(_t(lambda: list(p.WfiMorphBundles.GetAll(an)), [])), None)) if an is not None else None
            if b is not None:
                d["morphAlternatives"] = self._ws_alternatives(_t(lambda: b.Form, None))
                sense = self._c(_t(lambda: b.SenseRA, None))
                d["morphGlossAlternatives"] = self._ws_alternatives(_t(lambda: sense.Gloss, None)) if sense is not None else {}
            if cls == "WfiGloss":
                d["glossAlternatives"] = self._ws_alternatives(_t(lambda: tok.Form, None))
            break
        d["freeAlternatives"] = self._ws_alternatives(_t(lambda: seg.FreeTranslation, None))
        return d

    def _word_dict(self, tok) -> dict:
        p = self.project
        vh = getattr(self, "_cur_vern_handle", None)
        tok = self._c(tok)
        cls = _t(lambda: tok.ClassName, "")
        if cls == "PunctuationForm":
            form = _t(lambda: tok.Form, None)
            # ⚠ never tok.ShortName: for a PunctuationForm that is "A PunctuationForm" (Seth's
            # screen, 2026-10-16). An empty one is filled from the baseline in _segment_dict.
            txt = _s(_t(lambda: form.Text, "")) or _s(form)
            return model.make_word(txt, punct=True, guid=_guid(tok))
        # the wordform behind a WfiGloss / WfiAnalysis / WfiWordform token
        wf = tok if cls == "WfiWordform" else _t(lambda: tok.Wordform, None)
        if wf is None and cls == "WfiGloss":
            wf = _t(lambda: tok.Owner.Owner, None)
        elif wf is None and cls == "WfiAnalysis":
            wf = _t(lambda: tok.Owner, None)
        wf = self._c(wf)
        sel = getattr(self, "_sel", {}) or {}
        vh = sel.get("txt", vh)
        txt = self._vern_text(_t(lambda: wf.Form, None), vh) if wf is not None else ""
        if not txt and wf is not None:
            txt = _s(_t(lambda: p.Wordforms.GetForm(wf, vh) if vh is not None else p.Wordforms.GetForm(wf), ""))
        if not txt and cls == "WfiWordform":
            txt = self._vern_text(_t(lambda: tok.Form, None), vh)
        # ⚠ never fall back to tok.Form for a WfiGloss: that is the GLOSS, not the word
        hg, hp, hm, hmg, hcf = sel.get("gls"), sel.get("pos"), sel.get("morph", vh), sel.get("mgls"), sel.get("cf", vh)
        gls = _s(_t(lambda: p.Segments.GetGloss(tok, hg) if hg is not None else p.Segments.GetGloss(tok), ""))
        analysis = self._c(_t(lambda: tok.Analysis, None))
        pos = ""
        morphs: list[dict] = []
        if analysis is not None:
            pos = _s(_t(lambda: p.WfiAnalyses.GetCategoryAbbrev(analysis, hp) if hp is not None else p.WfiAnalyses.GetCategoryAbbrev(analysis), ""))
            for b in _t(lambda: list(p.WfiMorphBundles.GetAll(analysis)), []):
                b = self._c(b)
                msa = self._c(_t(lambda: p.WfiMorphBundles.GetMSA(b), None))
                sense = self._c(_t(lambda: p.WfiMorphBundles.GetSense(b), None))
                cf = ""
                if sense is not None:
                    ent = self._owning_entry(sense)
                    if ent is not None:
                        cf = (self._vern_text(_t(lambda: ent.HeadWordForWs(hcf), None), None) if hcf is not None else "") \
                            or _s(_t(lambda: p.LexiconGetHeadword(ent), ""))
                form = self._bundle_form(b, hm)
                mgls = self._bundle_gloss(b, sense, hmg)
                # break characters from the morph type (IMoMorphType.Prefix / Postfix: "-" for
                # affixes, "=" for clitics, "<"/">" for infixes), as FLEx's Morphemes line shows
                # them; falls back to the characters already on the form or the headword
                mt = self._c(_t(lambda: self._c(b.MorphRA).MorphTypeRA, None))
                pre = _s(_t(lambda: mt.Prefix, "")) if mt is not None else ""
                post = _s(_t(lambda: mt.Postfix, "")) if mt is not None else ""
                if not pre and not post:
                    pre, post = model.morph_markers(form)
                    if not pre and not post:
                        pre, post = model.morph_markers(cf)
                md = model.make_morph(
                    form,
                    mgls,
                    _s(_t(lambda: msa.InterlinearAbbr, "")) if msa is not None else "",
                    cf,
                    prefix=pre, postfix=post,
                )
                if getattr(self, "_alts", False):
                    md["formAlts"] = self._ws_alternatives(_t(lambda: b.Form, None)) or self._ws_alternatives(_t(lambda: self._c(b.MorphRA).Form, None))
                    md["glsAlts"] = self._ws_alternatives(_t(lambda: sense.Gloss, None)) if sense is not None else {}
                    ent = self._owning_entry(sense) if sense is not None else None
                    md["cfAlts"] = (self._ws_alternatives(_t(lambda: ent.CitationForm, None)) or self._ws_alternatives(_t(lambda: self._c(ent.LexemeFormOA).Form, None))) if ent is not None else {}
                    md["type"] = _s(_t(lambda: self._c(mt.Name).BestAnalysisAlternative, "")) if mt is not None else ""
                morphs.append(md)
        wd = model.make_word(txt, gls=gls, pos=pos, morphs=morphs, guid=_guid(tok))
        if getattr(self, "_alts", False):
            wd["txtAlts"] = self._ws_alternatives(_t(lambda: wf.Form, None)) if wf is not None else {}
            wd["glsAlts"] = self._ws_alternatives(_t(lambda: tok.Form, None)) if cls == "WfiGloss" else {}
            cat = self._c(_t(lambda: analysis.CategoryRA, None)) if analysis is not None else None
            wd["posAlts"] = self._ws_alternatives(_t(lambda: cat.Abbreviation, None)) if cat is not None else {}
        return wd

    # -- links -------------------------------------------------------------------

    def _goto(self, obj, kind: str) -> str:
        # Built by hand in the exact shape FLEx's own "Copy Location as Hyperlink" produces;
        # flexicon's BuildGotoURL returned a percent-encoded query (`database%3d…%26tool%3d…`)
        # on Seth's first run (2026-10-12).
        return model.goto_url(self.project_name, kind, _guid(obj))

    def resolve_guid(self, guid: str) -> dict | None:
        """What is this GUID? → {kind, guid, title, seg?, sense?} for the kinds the UI can embed."""
        def go():
            self._need()
            try:
                obj = self._c(self.project.Object(guid))
            except Exception:  # noqa: BLE001
                return None
            cls = _t(lambda: obj.ClassName, "")
            p = self.project
            if cls in ("LexEntry", "LexSense", "LexExampleSentence", "MoStemAllomorph", "MoAffixAllomorph"):
                ent = self._owning_entry(obj)
                if ent is None:
                    return None
                out = {"kind": "entry", "guid": _guid(ent), "title": _s(_t(lambda: p.LexiconGetHeadword(ent), ""))}
                if cls == "LexSense":
                    out["sense"] = _s(_t(lambda: p.LexiconGetSenseNumber(obj), ""))
                return out
            if cls in ("Text", "StText", "StTxtPara", "Segment"):
                text = self._owning_text(obj)
                if text is None:
                    return None
                out = {"kind": "text", "guid": _guid(text), "title": self._text_title(text)}
                if cls in ("StTxtPara", "Segment"):
                    out.update(self._locate(text, obj, cls))
                return out
            if cls in ("WfiWordform", "WfiAnalysis", "WfiGloss"):
                wf = self._c(_t(lambda: obj.Wordform, None) or obj)
                return {"kind": "wordform", "guid": _guid(wf), "title": _s(_t(lambda: p.Wordforms.GetForm(wf), ""))}
            return {"kind": "other", "guid": guid.lower(), "title": cls}
        try:
            return self.worker.call(go)
        except BaseException as e:
            raise _friendly(e, self.project_name)

    def _locate(self, text, obj, cls: str) -> dict:
        """Segment numbers (text-wide, 1-based) of a paragraph or segment inside its text."""
        p = self.project
        n = 0
        want = _guid(obj)
        first = last = None
        for para in _t(lambda: list(p.Paragraphs.GetAll(text)), []):
            in_para = cls == "StTxtPara" and _guid(para) == want
            for seg in _t(lambda: list(p.Segments.GetAll(para)), []):
                n += 1
                if in_para or (cls == "Segment" and _guid(seg) == want):
                    first = first or n
                    last = n
        return {"seg": first, "segTo": last} if first else {}

    def get_wordform(self, guid: str) -> dict:
        def go():
            self._need()
            p = self.project
            wf = self._c(p.Object(guid))
            d = {"kind": "wordform", "guid": _guid(wf), "form": _s(_t(lambda: p.Wordforms.GetForm(wf), "")),
                 "glosses": [], "pos": [], "url": self._goto(wf, "wordform"), "ws": self._writing_systems()}
            for an in _t(lambda: list(p.WfiAnalyses.GetAll(wf)), []):
                pos = _s(_t(lambda: p.WfiAnalyses.GetCategoryAbbrev(an), ""))
                if pos and pos not in d["pos"]:
                    d["pos"].append(pos)
                for g in _t(lambda: list(p.WfiGlosses.GetAll(an)), []):
                    s = _s(_t(lambda: p.WfiGlosses.GetForm(g), ""))
                    if s and s not in d["glosses"]:
                        d["glosses"].append(s)
            return d
        try:
            return self.worker.call(go)
        except BaseException as e:
            raise _friendly(e, self.project_name)



GUID_IN_TEXT = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
