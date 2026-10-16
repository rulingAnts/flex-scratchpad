"""The `js_api` object: every public method here is callable from the page as
`window.pywebview.api.<name>(...)`. Arguments and results are JSON only.

pywebview runs each call on its own thread; the notebook and the FLEx service serialise
themselves, so these methods are thin. Errors raise and reach the page as rejected promises
(pywebview wraps them as `{message, name, stack}`), so the UI shows the message as-is.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

from . import APP_NAME, __version__, build_id
from .config import AppConfig
from .flex import FlexService
from .flex.lcm import FlexError
from .notebook import Notebook, inline_tags


class Api:
    """Only the public METHODS of this object are the API. pywebview inspects every public
    attribute (and recurses into objects), so all state lives in underscored attributes."""

    def __init__(self, config: AppConfig, notebook_dir: str | Path | None = None, demo: bool = False):
        self._config = config
        self._window = None                     # set by app.py once the window exists
        self._lock = threading.RLock()
        self._demo = demo
        self._open_notebook(notebook_dir or config.notebook_dir)


    # -- plumbing ----------------------------------------------------------------

    def _open_notebook(self, path: str | Path) -> None:
        with self._lock:
            svc_holder: dict = {}
            nb = Notebook(path, extra_text=lambda body: svc_holder["svc"].searchable_text_for_body(body) if "svc" in svc_holder else "")
            svc = FlexService(nb, progress=self._progress)
            svc_holder["svc"] = svc
            nb.reindex_all()
            self._nb, self._flex = nb, svc
            if self._demo:
                svc.configure(source="demo", project="Kalu Demo")
            svc.open()

    def _progress(self, message: str) -> None:
        self._emit("progress", {"message": message})

    def _emit(self, event: str, data: dict) -> None:
        """Push an event into the page (window.FS.onEvent). Safe to call from any thread."""
        w = self._window
        if w is None:
            return
        try:
            w.evaluate_js(f"window.FS && FS.onEvent({json.dumps({'event': event, **data}, ensure_ascii=False)})")
        except Exception:  # noqa: BLE001 — the window may be closing
            pass

    # -- app ----------------------------------------------------------------------

    def init(self) -> dict:
        """Everything the page needs on load."""
        with self._lock:
            return {
                "app": APP_NAME, "version": __version__, "build": build_id(), "platform": sys.platform,
                "notebook": str(self._nb.root),
                "config": self._nb.config,
                "notes": self._nb.list_notes(),
                "folders": self._nb.folders(),
                "tags": self._nb.all_tags(),
                "flex": self._flex.status(),
                "canBrowse": self._window is not None,
            }

    def choose_notebook_folder(self) -> dict | None:
        """Native folder dialog; switches the notebook if the user picks one."""
        path = self._folder_dialog()
        if not path:
            return None
        self._flex.close()
        self._open_notebook(path)
        self._config.notebook_dir = path
        return self.init()

    def open_notebook(self, path: str) -> dict:
        self._flex.close()
        self._open_notebook(path)
        self._config.notebook_dir = path
        return self.init()

    def reveal_notebook(self) -> bool:
        return self._reveal(self._nb.root)

    def reveal_note(self, note_id: str) -> bool:
        n = self._nb.get_note(note_id)
        return self._reveal(n.path or self._nb.root)

    # -- notes --------------------------------------------------------------------

    def list_notes(self) -> list[dict]:
        return self._nb.list_notes()

    def folders(self) -> dict:
        return self._nb.folders()

    def tags(self) -> list[dict]:
        return self._nb.all_tags()

    def get_note(self, note_id: str) -> dict:
        n = self._nb.get_note(note_id)
        d = n.meta()
        d["body"] = n.body
        d["inlineTags"] = inline_tags(n.body)
        return d

    def create_note(self, tab: str | None = None, folder: str = "", title: str = "", body: str = "", kind: str = "") -> dict:
        n = self._nb.create_note(tab, folder, title, body, kind or "")
        return self.get_note(n.id)

    def list_collections(self) -> list[dict]:
        """The example collections, for "Add to collection…" (newest first, with counts)."""
        return self._nb.collections()

    def add_to_collection(self, note_id: str, embeds: list[str]) -> dict:
        """Append examples (embed sources) to an example collection; returns its summary."""
        return self._nb.append_examples(note_id, list(embeds or [])).summary()

    def save_note(self, note_id: str, patch: dict) -> dict:
        patch = patch or {}
        n = self._nb.save_note(note_id, title=patch.get("title"), body=patch.get("body"),
                              tags=patch.get("tags"), pinned=patch.get("pinned"))
        return n.summary()

    def duplicate_note(self, note_id: str, tab: str | None = None, folder: str | None = None, title: str | None = None) -> dict:
        n = self._nb.duplicate_note(note_id, tab, folder, title)
        return self.get_note(n.id)

    def move_note(self, note_id: str, tab: str, folder: str = "") -> dict:
        return self._nb.move_note(note_id, tab, folder).summary()

    def delete_note(self, note_id: str) -> bool:
        self._nb.delete_note(note_id)
        return True

    def search(self, q: str, filters: dict | None = None) -> list[dict]:
        f = filters or {}
        return self._nb.search(q, tab=f.get("tab") or None, folder=f.get("folder"), tags=f.get("tags") or [],
                              limit=int(f.get("limit") or 100))

    def rescan(self) -> dict:
        self._nb.scan()
        self._nb.reindex_all()
        return self.init()

    # -- tabs / folders / tags ----------------------------------------------------------

    def add_tab(self, name: str, color: str | None = None) -> dict:
        return self._nb.add_tab(name, color)

    def update_tab(self, tab: str, patch: dict) -> dict:
        patch = patch or {}
        return self._nb.update_tab(tab, name=patch.get("name"), color=patch.get("color"))

    def reorder_tabs(self, dirs: list[str]) -> list[dict]:
        self._nb.reorder_tabs(dirs)
        return self._nb.config["tabs"]

    def delete_tab(self, tab: str) -> bool:
        self._nb.delete_tab(tab)
        return True

    def create_folder(self, tab: str, folder: str) -> str:
        return self._nb.create_folder(tab, folder)

    def rename_folder(self, tab: str, folder: str, new_name: str) -> str:
        return self._nb.rename_folder(tab, folder, new_name)

    def delete_folder(self, tab: str, folder: str) -> bool:
        self._nb.delete_folder(tab, folder)
        return True

    def set_tags(self, tags: list[dict]) -> list[dict]:
        return self._nb.set_tags(tags)

    def rename_tag(self, old: str, new: str) -> int:
        return self._nb.rename_tag(old, new)

    def set_setting(self, key: str, value) -> dict:
        s = self._nb.config.setdefault("settings", {})
        s[key] = value
        self._nb.save_config()
        if key == "diacriticsInsensitive":
            self._nb.reindex_all()
        return s

    # -- sync awareness / export ---------------------------------------------------------

    def notebook_stamp(self) -> dict:
        """For the UI's poll: has anything changed on disk (cloud sync, another machine)?"""
        return {"stamp": self._nb.fingerprint()}

    def note_changed_on_disk(self, note_id: str, known_updated: str) -> dict | None:
        """If the note's file carries a newer `updated` than the UI holds, return the fresh
        note (after a rescan); None when nothing changed."""
        self._nb.scan()
        self._nb.reindex_all()
        try:
            n = self._nb.get_note(note_id)
        except KeyError:
            return {"deleted": True}
        if n.updated != known_updated:
            d = n.meta()
            d["body"] = n.body
            d["inlineTags"] = inline_tags(n.body)
            return d
        return None

    def export_note_html(self, note_id: str, html: str, path: str | None = None) -> str | None:
        """Save a self-contained HTML export (built by the page) through a save dialog."""
        n = self._nb.get_note(note_id)
        target = path or self._save_dialog((n.title or "note") + ".html")
        if not target:
            return None
        Path(target).write_text(html, encoding="utf-8", newline="\n")
        return target

    def export_note_markdown(self, note_id: str, path: str | None = None) -> str | None:
        n = self._nb.get_note(note_id)
        target = path or self._save_dialog((n.title or "note") + ".md")
        if not target:
            return None
        import shutil
        shutil.copyfile(n.path, target)
        return target

    def export_note_docx(self, note_id: str, doc: dict, path: str | None = None) -> str | None:
        """Word document from the page's export model (zero-dependency writer)."""
        from .docx_writer import build_docx
        n = self._nb.get_note(note_id)
        target = path or self._save_dialog((n.title or "note") + ".docx")
        if not target:
            return None
        Path(target).write_bytes(build_docx(doc))
        return target

    def export_note_flextext(self, note_id: str, items: list[dict], opts: dict | None = None, path: str | None = None) -> dict | None:
        """A note's text examples as one .flextext (Seth, 2026-10-16): `items` are the note's
        text embeds in order ([{guid, seg, at, label}], from the page's parser); one FLEx text
        per baseline writing system; options: title, includeLink, includeMarkdown, sourceNotes,
        wordGuids, onlyWs. Returns {path, examples, texts, skipped} or None when cancelled."""
        from .flex.flextext_writer import build_flextext, group_by_baseline
        from .links import note_url
        opts = dict(opts or {})
        n = self._nb.get_note(note_id)
        # Seth, 2026-10-16: only an example collection exports as a FLEx text
        if n.kind != "examples":
            raise ValueError("Only an example collection exports as a FLEx text. Use “Collect the examples into a new collection…” on this note first.")
        examples, skipped = [], []
        for it in items or []:
            if (it.get("kind") or "text") != "text":
                skipped.append(it)
                continue
            try:
                text = self._flex.example_text(it["guid"], it.get("seg"), it.get("at"))
            except FlexError as e:
                skipped.append(dict(it, error=e.message))
                continue
            except Exception as e:  # noqa: BLE001
                skipped.append(dict(it, error=str(e)))
                continue
            if not text.get("segments"):
                skipped.append(dict(it, error="no segments"))
                continue
            examples.append({"text": text, "label": it.get("label") or "", "note": it.get("note") or ""})
        if not examples:
            raise RuntimeError("This note has no text examples to export" + (f" ({len(skipped)} could not be read)" if skipped else "") + ".")
        wopts = {
            "title": opts.get("title") or n.title or "Examples",
            "abbrev": opts.get("abbrev") or "",
            "noteUrl": note_url(note_id) if opts.get("includeLink", True) else "",
            "markdown": n.body if opts.get("includeMarkdown") else "",
            "sourceNotes": opts.get("sourceNotes", True),
            "wordGuids": opts.get("wordGuids", True),
            "onlyWs": opts.get("onlyWs") or "",
        }
        groups = group_by_baseline(examples)
        if wopts["onlyWs"]:
            groups = [g for g in groups if g[0] == wopts["onlyWs"]]
        target = path or self._save_dialog((wopts["title"] or "examples") + ".flextext")
        if not target:
            return None
        # audio (Seth, 2026-10-16: "grab audio segments and match them"): one recording per
        # exported text next to the file, every example's clip in order, offsets rewritten;
        # 'original' keeps the source recordings and offsets; 'none' drops the timing
        audio = opts.get("audio") or "clips"
        audio_out = {"path": "", "matched": 0, "missing": 0}
        if audio == "clips":
            # one 16-bit mono WAV per line, into the chosen folder (a project's
            # LinkedFiles/AudioVisual, ideally) or a folder next to the file
            folder = Path(opts.get("audioFolder") or Path(target).with_name(Path(target).stem + "-audio"))
            linked_root = next((p for p in [folder] + list(folder.parents) if p.name.lower() == "linkedfiles"), None)
            stem = "".join(c if c.isalnum() or c in "-_" else "-" for c in (wopts["title"] or "examples")).strip("-") or "examples"
            for k, v in groups:
                r = self._flex.clip_audio(v, folder, stem + (f"-{k}" if len(groups) > 1 else ""), linked_root)
                audio_out["matched"] += r["matched"]
                audio_out["missing"] += r["missing"]
                if r["folder"]:
                    audio_out["path"] = r["folder"]
        elif audio == "bundle":
            kept = [ex for k, v in groups for ex in v]
            per_text = {}
            for k, v in groups:
                suffix = f"-{k}" if len(groups) > 1 else ""
                dst = Path(target).with_name(Path(target).stem + suffix + ".wav")
                r = self._flex.bundle_audio(v, dst)
                per_text[k] = r
                audio_out["matched"] += r["matched"]
                audio_out["missing"] += r["missing"]
                if r["path"]:
                    audio_out["path"] = (audio_out["path"] + "; " if audio_out["path"] else "") + r["path"]
            del kept
        elif audio == "none":
            for _, v in groups:
                for ex in v:
                    for seg in ex["text"].get("segments") or []:
                        seg["begin"] = seg["end"] = None
        xml = build_flextext([ex for _, v in groups for ex in v], wopts)
        Path(target).write_text(xml, encoding="utf-8", newline="\n")
        return {"path": target, "examples": sum(len(v) for _, v in groups), "texts": [{"ws": k, "examples": len(v)} for k, v in groups], "skipped": len(skipped),
                "audio": audio_out["path"], "audioMatched": audio_out["matched"], "audioMissing": audio_out["missing"]}

    def flextext_preview(self, items: list[dict]) -> dict:
        """What an export of these items would produce: the baseline writing systems and
        their example counts (for the export dialog), without writing anything."""
        from collections import OrderedDict
        groups: "OrderedDict[str, int]" = OrderedDict()
        skipped = 0
        for it in items or []:
            if (it.get("kind") or "text") != "text":
                skipped += 1
                continue
            try:
                obj = self._flex.get_object("text", it["guid"], 1, 1)
                tag = ((obj.get("ws") or {}).get("vern") or {}).get("tag") or "und"
            except Exception:  # noqa: BLE001
                tag = "?"
            groups[tag] = groups.get(tag, 0) + 1
        return {"texts": [{"ws": k, "examples": v} for k, v in groups.items()], "skipped": skipped}

    def pick_folder(self) -> str | None:
        """A folder chosen by the user (the export dialog's clip destination)."""
        return self._folder_dialog()

    def note_link(self, note_id: str) -> str:
        from .links import note_url
        return note_url(note_id)

    def register_links(self) -> bool:
        """Register flexscratchpad:// for this user (Windows); False where that is not possible."""
        from .links import register_scheme
        return bool(register_scheme())

    def export_notebook_zip(self, path: str | None = None, include_cache: bool = True) -> str | None:
        target = path or self._save_dialog(self._nb.root.name + ".zip")
        if not target:
            return None
        return str(self._nb.export_zip(target, include_cache))

    def import_notebook_zip(self, zip_path: str | None = None, folder: str | None = None) -> dict | None:
        """Unpack a notebook zip into a (new) folder and open it."""
        import zipfile
        zp = zip_path or self._file_dialog(("Notebook archive", "*.zip"))
        if not zp:
            return None
        dest = folder or self._folder_dialog()
        if not dest:
            return None
        with zipfile.ZipFile(zp) as z:
            for info in z.infolist():
                # never let an archive write outside the chosen folder
                target = (Path(dest) / info.filename).resolve()
                if not str(target).startswith(str(Path(dest).resolve())):
                    continue
                z.extract(info, dest)
        return self.open_notebook(dest)

    # -- attachments ------------------------------------------------------------------

    def save_attachment(self, name: str, data_base64: str) -> dict:
        raw = base64.b64decode(data_base64.split(",", 1)[-1])
        p = self._nb.save_attachment(name, raw)
        return {"path": str(p), "fileUrl": p.resolve().as_uri(), "name": p.name}

    # -- FLEx ---------------------------------------------------------------------------

    def flex_status(self) -> dict:
        return self._flex.status()

    def flex_projects(self) -> list[str]:
        try:
            return self._flex.list_projects()
        except FlexError as e:
            raise RuntimeError(e.message)

    def flex_configure(self, source: str | None = None, project: str | None = None,
                       flextext_path: str | None = None) -> dict:
        self._flex.configure(source, project, flextext_path)
        st = self._flex.open()
        self._nb.reindex_all()
        return st

    def flex_open(self) -> dict:
        return self._flex.open()

    def flex_refresh(self) -> dict:
        return self._flex.refresh()

    def flex_reload(self) -> dict:
        """The ↻ on one example: take in what FieldWorks saved since the project was opened,
        keeping the indexes (Seth, 2026-10-16: ↻ on an example in a collection did not show a
        fix just made in FLEx — it re-read the backend's in-memory copy, not the disk)."""
        return self._flex.refresh(indexes=False)

    def flex_refresh_all(self) -> dict:
        """Reload the project's data, then re-fetch every example embedded in every note."""
        try:
            self._flex.refresh()
            bodies = [self._nb.get_note(n["id"]).body for n in self._nb.list_notes()]
            return self._flex.refresh_all(bodies)
        except FlexError as e:
            raise RuntimeError(e.message)

    def flex_get(self, kind: str, guid: str, seg_from: int | None = None, seg_to: int | None = None,
                 prefer_cache: bool = False, ws: dict | None = None, at: list | None = None) -> dict:
        try:
            return self._flex.get_object(kind, guid, seg_from, seg_to, prefer_cache, ws or None, at or None)
        except FlexError as e:
            raise RuntimeError(e.message)

    def flex_search_entries(self, q: str, limit: int = 30) -> list[dict]:
        try:
            return self._flex.search_entries(q, limit)
        except FlexError as e:
            raise RuntimeError(e.message)

    def flex_texts(self, q: str = "") -> list[dict]:
        try:
            return self._flex.search_texts(q) if q else self._flex.list_texts()
        except FlexError as e:
            raise RuntimeError(e.message)

    def flex_find_in_text(self, guid: str, phrase: str) -> list[int]:
        try:
            return self._flex.find_in_text(guid, phrase)
        except FlexError as e:
            raise RuntimeError(e.message)

    def flex_locate(self, pasted: str) -> list[dict]:
        """Pasted interlinear lines → where they come from (text + segment range)."""
        try:
            return self._flex.locate(pasted)
        except FlexError:
            return []

    def flex_resolve_link(self, text: str) -> dict | None:
        return self._flex.resolve_link(text)

    def flex_choose_file(self) -> dict | None:
        """Pick a .flextext file (fallback source)."""
        p = self._file_dialog(("FLEx interlinear export", "*.flextext"), ("All files", "*.*"))
        return {"path": p} if p else None

    def flex_open_object(self, kind: str, guid: str) -> bool:
        """Jump to an object in FieldWorks by kind + GUID (a link chip was clicked)."""
        from .flex import model
        url = model.goto_url(self._flex.project_name, kind, guid)
        return self._open_url(url)

    def open_in_flex(self, url: str) -> bool:
        """Hand a silfw:// link to the OS; Windows routes it to FieldWorks."""
        if not url or not url.lower().startswith("silfw:"):
            raise RuntimeError("Not a FieldWorks link.")
        return self._open_url(url)

    # -- audio ------------------------------------------------------------------------------

    def audio_clip(self, text_guid: str, media_guid: str | None, begin: int, end: int) -> dict:
        try:
            return self._flex.ensure_clip(text_guid, media_guid, begin, end)
        except FlexError as e:
            raise RuntimeError(e.message)

    def audio_store_clip(self, text_guid: str, begin: int, end: int, data_base64: str, mime: str = "audio/webm") -> dict:
        return self._flex.store_captured_clip(text_guid, begin, end, data_base64, mime)

    def audio_browse_media(self, media_guid: str) -> dict | None:
        p = self._file_dialog(("Audio", "*.wav;*.mp3;*.m4a;*.ogg;*.flac;*.wma;*.aac;*.opus"), ("All files", "*.*"))
        if not p:
            return None
        self._flex.set_media_path(media_guid, p)
        return {"path": p, "fileUrl": Path(p).resolve().as_uri()}

    def audio_set_media_path(self, media_guid: str, path: str) -> dict:
        return self._flex.set_media_path(media_guid, path)

    def audio_tools(self) -> dict:
        """Where clips come from: ffmpeg (FLAC slices of any format) or the stdlib (WAV only)."""
        from .flex.audio import find_ffmpeg
        exe = find_ffmpeg(self._nb.config.get("settings", {}).get("ffmpegPath", ""))
        return {"ffmpeg": exe or "", "clipFormat": "flac" if exe else "wav"}

    def save_file_as(self, suggested_name: str, source_path: str) -> str | None:
        """Save dialog + copy (used for *Save clip…*)."""
        target = self._save_dialog(suggested_name)
        if not target:
            return None
        import shutil
        shutil.copyfile(source_path, target)
        return target

    # -- native helpers ---------------------------------------------------------------------

    def _dialog(self, kind: str, **kw):
        if self._window is None:
            return None
        import webview  # local import: only the real app has it
        try:
            dt = {"folder": webview.FileDialog.FOLDER, "open": webview.FileDialog.OPEN, "save": webview.FileDialog.SAVE}[kind]
        except AttributeError:  # pywebview 4
            dt = {"folder": webview.FOLDER_DIALOG, "open": webview.OPEN_DIALOG, "save": webview.SAVE_DIALOG}[kind]
        res = self._window.create_file_dialog(dt, **kw)
        if not res:
            return None
        return res[0] if isinstance(res, (list, tuple)) else res

    def _folder_dialog(self) -> str | None:
        return self._dialog("folder")

    def _file_dialog(self, *filters: tuple[str, str]) -> str | None:
        """pywebview wants 'Description (*.ext;*.ext)' — exactly one parenthesised pattern list.
        (Seth's run, 2026-10-13: a description that already carried the patterns produced
        'Audio (*.wav…) (*.wav…)', "not a valid file filter".)"""
        types = []
        for a, b in filters:
            a = a.strip()
            if a.endswith(")") and "(" in a:
                a = a[:a.rfind("(")].strip()
            types.append(f"{a} ({b})")
        return self._dialog("open", allow_multiple=False, file_types=tuple(types))

    def _save_dialog(self, name: str) -> str | None:
        return self._dialog("save", save_filename=name)

    @staticmethod
    def _open_url(url: str) -> bool:
        if sys.platform == "win32":
            os.startfile(url)  # type: ignore[attr-defined]
            return True
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        try:
            subprocess.Popen([opener, url])
            return True
        except OSError:
            return False

    @staticmethod
    def _reveal(path: Path) -> bool:
        try:
            if sys.platform == "win32":
                if path.is_file():
                    subprocess.Popen(["explorer", "/select,", str(path)])
                else:
                    os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R" if path.is_file() else "", str(path)] if path.is_file() else ["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path.parent if path.is_file() else path)])
            return True
        except OSError:
            return False
