"""The `js_api` object: every public method here is callable from the page as
`window.pywebview.api.<name>(...)`. Arguments and results are JSON only.

pywebview runs each call on its own thread; the notebook and the FLEx service serialise
themselves, so these methods are thin. Errors raise and reach the page as rejected promises
(pywebview wraps them as `{message, name, stack}`), so the UI shows the message as-is.
"""
from __future__ import annotations

import base64
import json
import re
import uuid
import os
import subprocess
import sys
import threading
from pathlib import Path

from . import APP_NAME, __version__, build_id
from .config import AppConfig
from .flex import FlexService
from .flex.lcm import FlexError
from .fsutil import replace_file
from .log import LOG, logged as _logged
from .notebook import ATTACH_DIR, Notebook, clean_rule, example_keys, inline_tags, match_embed, match_keys


def safe_filename(name: str) -> str:
    """`name` with the characters Windows refuses in a filename (\\ / : * ? " < > | and controls)
    turned into "-", Unicode kept; never empty."""
    import re
    out = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "-", name or "").strip().rstrip(".")
    stem = Path(out).stem.strip(" -.")
    return out if stem else "untitled" + Path(out).suffix


def with_suffix(path: str, ext: str) -> str:
    """`path`, with `ext` added when it does not already end in it (any case)."""
    if ext and not str(path).lower().endswith(ext.lower()):
        return str(path) + ext
    return str(path)


# What an attachment is, by extension: what the page can preview, and what is never STARTED
# from a note (a click shows it in its folder instead, so opening a note's chip cannot run a
# program).
_KINDS = {
    "html": {".html", ".htm", ".xhtml"},
    "pdf": {".pdf"},
    "image": {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".ico"},
    "audio": {".wav", ".mp3", ".m4a", ".ogg", ".oga", ".opus", ".flac", ".aac", ".weba"},
    "video": {".mp4", ".webm", ".m4v", ".mov", ".ogv"},
    "program": {".exe", ".com", ".bat", ".cmd", ".ps1", ".psm1", ".psd1", ".vbs", ".vbe", ".js", ".jse",
                ".wsf", ".wsh", ".msi", ".msp", ".mst", ".scr", ".pif", ".lnk", ".reg", ".hta", ".cpl",
                ".jar", ".appref-ms", ".application", ".msc", ".gadget", ".inf", ".sct", ".url", ".dll",
                ".sys", ".ocx", ".psc1", ".appx", ".msix", ".appinstaller", ".py", ".pyw", ".sh"},
}


def file_kind(p: Path) -> str:
    if p.is_dir():
        return "folder"
    ext = p.suffix.lower()
    for kind, exts in _KINDS.items():
        if ext in exts:
            return kind
    return "file"


class Api:
    """Only the public METHODS of this object are the API. pywebview inspects every public
    attribute (and recurses into objects), so all state lives in underscored attributes."""

    def __init__(self, config: AppConfig, notebook_dir: str | Path | None = None, demo: bool = False):
        self._config = config
        self._window = None                     # set by app.py once the window exists
        self._lock = threading.RLock()
        self._demo = demo
        self._drops: list[tuple[str, str, float]] = []   # (name, full path, when) from _on_drop
        self._drop_cv = threading.Condition()
        self._secrets = None                    # the secret store (tests set one); else the platform's
        self._backup_obj = None
        self._close_choice: str | None = None   # the answer while backing up before closing (app.py)
        self._close_evt = threading.Event()
        self._clips: dict[str, tuple[str, str]] = {}   # export clip token → (encoded file, mime): the audio stays in Python
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
        if message:
            LOG.info("progress: %s", message)
        self._emit("progress", {"message": message})

    def _job(self, job: str | None, **data) -> None:
        """A step of a queued job in the page (Seth, 2026-10-20: "queue that and have progress bars
        … similar to the FLEx project connection and backup status"): ui/js/jobs.js shows it."""
        if job:
            self._emit("job", {"job": job, **data})

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

    def client_log(self, level: str, message: str, where: str = "") -> bool:
        """What the page reports (window.onerror, unhandled promise rejections, console.error /
        console.warn — api.js `clientLog`): into the same log as everything else, so a JS failure
        shows in the terminal transcript without the developer tools."""
        lvl = {"error": 30 + 10, "warn": 30, "warning": 30, "info": 20, "debug": 10}.get(str(level or "").lower(), 20)
        LOG.log(lvl, "page %s: %s%s", level, str(message or "")[:2000], (" @ " + str(where)[:300]) if where else "")
        return True

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

    def create_note(self, tab: str | None = None, folder: str = "", title: str = "", body: str = "", kind: str = "", chart: str = "") -> dict:
        n = self._nb.create_note(tab, folder, title, body, kind or "", chart=chart or "")
        return self.get_note(n.id)

    # -- chart notes (Seth, 2026-10-18: "a text chart note type … custom columns … project-wide") --

    def create_chart_note(self, tab: str | None, folder: str, title: str, chart_guid: str, view: str = "") -> dict:
        """A note that IS one text chart (`kind: chart`, `chart: <guid>`): its body starts with the
        view embed (`{{flex:chart <guid> …}}`, every view setting and the user's styles) that
        ui/js/chartnote.js owns, the custom columns and their values after it."""
        g = (chart_guid or "").lower()
        try:
            ch = self._flex.get_object("chart", g, prefer_cache=False)
        except FlexError as e:
            raise RuntimeError(e.message) from e
        body = (view.strip() if view and view.strip().startswith("{{flex:chart " + g) else "{{flex:chart " + g + "}}") + "\n"
        n = self._nb.create_note(tab, folder, title or ((ch.get("name") or "Chart") + " \u2014 " + (ch.get("title") or "")), body, "chart", chart=g)
        return self.get_note(n.id)

    def set_note_chart(self, note_id: str, chart_guid: str) -> dict:
        """Change the chart a chart note shows (the page rewrites its view embed; the values it
        held stay in the file, keyed by the old rows' anchors)."""
        g = (chart_guid or "").lower()
        try:
            self._flex.get_object("chart", g, prefer_cache=False)
        except FlexError as e:
            raise RuntimeError(e.message) from e
        return self.get_note(self._nb.set_chart(note_id, g).id)

    def chart_lists(self) -> dict:
        """The notebook's choice lists for chart-note list columns: {name: {options: [...], open: bool}}."""
        return self._nb.config.setdefault("chartLists", {})

    def set_chart_list(self, name: str, options: list | None = None, open_: bool | None = None, rename: str | None = None) -> dict:
        """Create or change one list (project-wide: every chart note using the name sees it);
        `rename` moves it under a new name; options is None → delete it."""
        name = str(name or "").strip()[:80]
        if not name:
            raise ValueError("A list needs a name")
        lists = self._nb.config.setdefault("chartLists", {})
        if options is None and rename is None and open_ is None:
            lists.pop(name, None)
        else:
            cur = dict(lists.get(name) or {"options": [], "open": True})
            if options is not None:
                seen: list[str] = []
                for o in options:
                    o = str(o or "").strip()[:120]
                    if o and o not in seen:
                        seen.append(o)
                cur["options"] = seen
            if open_ is not None:
                cur["open"] = bool(open_)
            if rename and rename.strip() and rename.strip() != name:
                lists.pop(name, None)
                name = rename.strip()[:80]
            lists[name] = cur
        self._nb.save_config()
        return lists

    def list_collections(self) -> list[dict]:
        """The example collections, for "Add to collection…" (newest first, with counts)."""
        return self._nb.collections()

    def add_to_collection(self, note_id: str, embeds: list[str]) -> dict:
        """Append examples (embed sources) to an example collection; returns its summary."""
        return self._nb.append_examples(note_id, list(embeds or [])).summary()

    # RULE COLLECTIONS (Seth, 2026-10-18: "create a collection with ALL lines that match a
    # specific rule. And … have that collection add new matches found in the database that
    # aren't already in that collection"): the rule is kept in the collection's header.
    def rule_matches(self, rule: dict) -> list[dict]:
        """The lines a rule matches now (the dialog's count and preview)."""
        try:
            return self._flex.rule_matches(rule or {})
        except FlexError as e:
            raise RuntimeError(e.message) from e

    def create_rule_collection(self, tab: str | None, folder: str, title: str, rule: dict) -> dict:
        """A new collection holding every line the rule matches, one example each, in text order."""
        rule = clean_rule(rule)
        if not rule:
            raise RuntimeError("Choose at least one tag for the rule, or a chart search")
        rows = self.rule_matches(rule)
        body = "\n\n".join(match_embed(r) for r in rows)
        n = self._nb.create_note(tab, folder or "", title or "", body + ("\n" if body else ""), "examples", rule=rule)
        d = self.get_note(n.id)
        d["matched"] = len(rows)
        return d

    # -- a FLEx concordance export as a collection (Seth, 2026-10-20: "THAT would be HUGELY useful") --

    def read_concordance_file(self) -> dict | None:
        """Choose a concordance export (CSV) with the file dialog: {path, name, text}, or None."""
        p = self._file_dialog(("Concordance export (CSV)", "*.csv"), ("All files", "*.*"))
        if not p:
            return None
        path = Path(p)
        return {"path": str(path), "name": path.name, "text": self._read_concordance(path)}

    @staticmethod
    def _read_concordance(path: Path) -> str:
        raw = path.read_bytes()
        for enc in ("utf-8-sig", "utf-16"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode("cp1252", errors="replace")

    def concordance_preview(self, src: dict) -> dict:
        """Where the rows of a concordance export land: {rows, misses, matched, unmatched, texts,
        total}. `src` = {text} (the CSV's contents) or {path}."""
        src = src or {}
        text = src.get("text") or ""
        if not text and src.get("path"):
            text = self._read_concordance(Path(src["path"]))
        try:
            return self._flex.concordance_rows(text)
        except FlexError as e:
            raise RuntimeError(e.message) from e

    def create_concordance_collection(self, tab: str | None, folder: str, title: str, src: dict, opts: dict | None = None) -> dict:
        """A new collection with one example per line the export matched, in the file's order
        (a line matched several times once); the rows not found are listed in a paragraph at
        the end, so nothing is lost silently. `opts.note`: write each example's Ref as its note."""
        opts = opts or {}
        res = self.concordance_preview(src)
        rows = res["rows"]
        if not rows:
            raise RuntimeError("None of the export's rows was found in the open project")
        parts = []
        for r in rows:
            parts.append(match_embed(r) + (("\n> " + r["ref"] + (" (×%d)" % r["hits"] if r.get("hits", 1) > 1 else "")) if opts.get("note") else ""))
        body = "\n\n".join(parts)
        if res["misses"]:
            body += "\n\nNot found in the project: " + "; ".join(m["ref"] + " (" + m["why"] + ")" for m in res["misses"])
        n = self._nb.create_note(tab, folder or "", title or "", body + "\n", "examples")
        d = self.get_note(n.id)
        d.update({"matched": res["matched"], "unmatched": res["unmatched"], "total": res["total"]})
        return d

    def update_rule_collection(self, note_id: str) -> dict:
        """Add the lines the rule matches now that the collection does not hold yet, at its end.
        Returns {added: [embed sources], total, matched, note}."""
        n = self._nb.get_note(note_id)
        if n.kind != "examples" or not n.rule:
            raise RuntimeError("This collection has no rule")
        rows = self.rule_matches(n.rule)
        have = example_keys(n.body)
        add = [match_embed(r) for r in rows if not any(k in have for k in match_keys(r))]
        if add:
            n = self._nb.append_examples(note_id, add)
        return {"added": add, "matched": len(rows), "total": n.summary().get("exampleCount", 0), "note": self.get_note(n.id)}

    def set_note_rule(self, note_id: str, rule: dict | None) -> dict:
        """Change (or remove) a collection's rule; what it holds is left as it is."""
        return self.get_note(self._nb.set_rule(note_id, rule).id)

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

    def export_target(self, note_id: str, ext: str, suffix: str = "") -> str | None:
        """Where an export goes, asked FIRST (Seth, 2026-10-20: a click must answer at once, and the
        work then runs in the background with a progress bar): the save dialog for the note's title
        + `suffix` + `ext`; None when cancelled."""
        n = self._nb.get_note(note_id)
        ext = ext if ext.startswith(".") else "." + ext
        return self._save_dialog((n.title or "note") + (suffix or "") + ext)

    def export_note_html(self, note_id: str, html: str, path: str | None = None, suffix: str = "", job: str | None = None) -> str | None:
        """Save a self-contained HTML export (built by the page) through a save dialog; `suffix`
        is added to the suggested name (" slides" for a slideshow). Every `fs-clip:<token>` the
        page wrote (Api.export_clips) becomes that recording as a data: URL here, streamed into the
        file, so the audio never crosses into the page and back."""
        n = self._nb.get_note(note_id)
        target = path or self._save_dialog((n.title or "note") + (suffix or "") + ".html")
        if not target:
            return None
        self._job(job, step="write", text="Writing the page…")
        self._write_with_clips(Path(target), html)
        return target

    _CLIP_RE = re.compile(r"fs-clip:([0-9a-f]{16})")

    def _write_with_clips(self, target: Path, html: str) -> None:
        import base64
        tmp = target.with_name(target.name + ".part")
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            pos = 0
            for m in self._CLIP_RE.finditer(html):
                f.write(html[pos:m.start()])
                pos = m.end()
                clip = self._clips.get(m.group(1))
                if not clip or not Path(clip[0]).is_file():
                    f.write("")                 # a recording that went away: the player stays silent
                    continue
                f.write("data:" + clip[1] + ";base64,")
                with open(clip[0], "rb") as a:
                    while True:
                        chunk = a.read(3 * 65536)    # a multiple of 3: the pieces join into one base64 text
                        if not chunk:
                            break
                        f.write(base64.b64encode(chunk).decode("ascii"))
            f.write(html[pos:])
        replace_file(tmp, target)

    def export_note_markdown(self, note_id: str, path: str | None = None) -> str | None:
        n = self._nb.get_note(note_id)
        target = path or self._save_dialog((n.title or "note") + ".md")
        if not target:
            return None
        from .notebook import without_fold_marks
        # the note's own file, less the fold markers of closed headings (view state, not text)
        text = without_fold_marks(Path(n.path).read_text(encoding="utf-8"))
        Path(target).write_text(text, encoding="utf-8", newline="\n")
        self._copy_attachments(text, Path(target).parent)
        return target

    def _copy_attachments(self, text: str, dest: Path) -> int:
        """The files a note has COPIED in (`{{file attachments/…}}`) go beside an exported .md
        in an attachments/ folder of its own, so the export's references still find them.
        Linked files stay where they are. Never overwrites a different file of that name."""
        import re
        import shutil
        n = 0
        for m in re.finditer(r"\{\{\s*file\s+([^\s}]+)", text or ""):
            ref = re.sub(r"%([0-9A-Fa-f]{2})", lambda x: chr(int(x.group(1), 16)), m.group(1))
            if not ref.startswith(ATTACH_DIR + "/"):
                continue
            try:
                src = self._nb.resolve_file(ref)
                if not src.is_file():
                    continue
                out = (dest / ref).resolve()
                if dest.resolve() not in out.parents:
                    continue
                if out.exists() and out.stat().st_size == src.stat().st_size:
                    continue
                if out.exists():            # another file by that name is already there: keep it
                    continue
                out.parent.mkdir(parents=True, exist_ok=True)
                if out != src:
                    shutil.copy2(src, out)
                    n += 1
            except (OSError, ValueError):
                continue
        return n

    def export_note_docx(self, note_id: str, doc: dict, path: str | None = None, job: str | None = None) -> str | None:
        """Word document from the page's export model (zero-dependency writer)."""
        from .docx_writer import build_docx
        n = self._nb.get_note(note_id)
        target = path or self._save_dialog((n.title or "note") + ".docx")
        if not target:
            return None
        self._job(job, step="write", text="Writing the Word file…")
        Path(target).write_bytes(build_docx(doc))
        return target

    def export_pdf_direct(self) -> bool:
        """Whether this window can write a PDF itself (WebView2 on Windows): then the page asks for
        the file first; otherwise the print dialog has its own."""
        from . import pdf_print
        return bool(pdf_print.available(self._window))

    def export_note_pdf(self, note_id: str, html: str, path: str | None = None, landscape: bool = False, job: str | None = None) -> dict:
        """A PDF of the page's HTML export, written directly through WebView2 on Windows
        (pdf_print.py); {"fallback": True} tells the page to use the browser's print dialog
        instead (any other platform, or a WebView2 we cannot reach — the save dialog is then
        never shown, the print dialog has its own)."""
        from . import pdf_print
        if not pdf_print.available(self._window):
            return {"fallback": True}
        n = self._nb.get_note(note_id)
        target = path or self._save_dialog((n.title or "note") + ".pdf")
        if not target:
            return {"cancelled": True}
        self._job(job, step="write", text="Writing the PDF…")
        ok = pdf_print.print_to_pdf(html, target, self._nb.private_dir / "export-tmp", landscape=landscape)
        return {"path": target} if ok else {"fallback": True, "failed": True, "path": target}

    def export_note_pptx(self, note_id: str, deck: dict, path: str | None = None, job: str | None = None) -> str | None:
        """PowerPoint from the page's slide model (export.js slidesOf; zero-dependency writer)."""
        from .pptx_writer import build_pptx
        n = self._nb.get_note(note_id)
        target = path or self._save_dialog((n.title or "note") + ".pptx")
        if not target:
            return None
        self._job(job, step="write", text="Writing the PowerPoint file…")
        Path(target).write_bytes(build_pptx(deck))
        return target

    def export_note_xlsx(self, note_id: str, doc: dict, path: str | None = None, job: str | None = None) -> str | None:
        """Excel workbook from the page's export model (zero-dependency writer): the note, an
        Examples sheet, a rows sheet per chart."""
        from .xlsx_writer import build_xlsx
        n = self._nb.get_note(note_id)
        target = path or self._save_dialog((n.title or "note") + ".xlsx")
        if not target:
            return None
        self._job(job, step="write", text="Writing the Excel file…")
        Path(target).write_bytes(build_xlsx(doc))
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
        target = Path(target)
        # one FILE per baseline writing system (Seth, 2026-10-17: "handle different baseline
        # writing systems gracefully … by having one different text for each"): a FLEx text has
        # one vernacular WS, and the Audio Segmenter pairs a .flextext with the recording of the
        # SAME NAME and gives no recording to a file holding several texts. `oneFile` keeps them
        # together as several texts of one file instead.
        if len(groups) > 1 and not opts.get("oneFile"):
            plan = [(target.with_name(f"{target.stem} ({k}){target.suffix or '.flextext'}"), [(k, v)]) for k, v in groups]
        else:
            plan = [(target, groups)]
        # audio (Seth, 2026-10-16: "grab audio segments and match them"; 2026-10-17: "concatenate
        # the audio as a single audio file stored in the text media file … with a generated click
        # inserted at join points … default to concatenated … per flex object, not per flex text
        # line"): 'bundle' = one 16-bit mono WAV per text, one piece per EXAMPLE with a click
        # between, named like its .flextext and next to it (or in the chosen folder); 'clips' = one
        # small WAV per line, in `<name>-audio/` or the chosen folder; 'original' keeps the source
        # recordings and offsets; 'none' drops the timing. In a project's LinkedFiles/AudioVisual
        # the locations are relative, as FLEx stores them.
        audio = opts.get("audio") or "bundle"
        audio_out = {"path": "", "matched": 0, "missing": 0}
        chosen = Path(opts["audioFolder"]) if opts.get("audioFolder") else None
        stem = "".join(c if c.isalnum() or c in "-_" else "-" for c in (wopts["title"] or "examples")).strip("-") or "examples"
        for out, file_groups in plan:
            for k, v in file_groups:
                suffix = f"-{k}" if len(file_groups) > 1 else ""
                if audio == "clips":
                    folder = chosen or out.with_name(out.stem + "-audio")
                elif audio == "bundle":
                    folder = chosen or out.parent
                else:
                    if audio == "none":
                        for ex in v:
                            for seg in ex["text"].get("segments") or []:
                                seg["begin"] = seg["end"] = None
                    continue
                linked_root = next((p for p in [folder] + list(folder.parents) if p.name.lower() == "linkedfiles"), None)
                if audio == "clips":
                    r = self._flex.clip_audio(v, folder, stem + (f"-{k}" if len(groups) > 1 else ""), linked_root)
                    where = r["folder"]
                else:
                    r = self._flex.bundle_audio(v, folder / f"{out.stem}{suffix}.wav", linked_root)
                    where = r["path"]
                audio_out["matched"] += r["matched"]
                audio_out["missing"] += r["missing"]
                if where and where not in audio_out["path"].split("; "):
                    audio_out["path"] = (audio_out["path"] + "; " if audio_out["path"] else "") + where
        # never hand FLEx a file its importer would fail on (Seth, 2026-10-16: a schema-valid
        # export stopped FLEx with "Object reference not set…"); say what and where instead —
        # every file is checked before any is written
        from .flex.flextext_check import import_problems
        xmls = []
        for out, file_groups in plan:
            # a text per file keeps its writing system in its title, as in a shared file
            title = wopts["title"] + (f" ({file_groups[0][0]})" if len(plan) > 1 else "")
            xml = build_flextext([ex for _, v in file_groups for ex in v], dict(wopts, title=title))
            problems = import_problems(xml)
            if problems:
                raise ValueError("This export would not import into FLEx, so it was not saved: "
                                 + "; ".join(problems[:5]) + (f" (and {len(problems) - 5} more)" if len(problems) > 5 else ""))
            xmls.append((out, xml))
        for out, xml in xmls:
            out.write_text(xml, encoding="utf-8", newline="\n")
        return {"path": str(plan[0][0]), "paths": [str(out) for out, _ in plan],
                "examples": sum(len(v) for _, v in groups), "texts": [{"ws": k, "examples": len(v)} for k, v in groups], "skipped": len(skipped),
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

    # -- backup (Seth, 2026-10-17): a cloud sync folder, or S3-compatible storage via rclone ----

    @property
    def _backup(self):
        if getattr(self, "_backup_obj", None) is None:
            from .backup import Backup
            from .secrets_store import default_store
            self._backup_obj = Backup(self._config, self._secrets or default_store(), lambda: self._nb.root, progress=self._progress,
                                      report=lambda st: self._emit("backup", st))
        return self._backup_obj

    def backup_status(self) -> dict:
        return self._backup.status()

    def backup_save(self, settings: dict, secrets: dict | None = None, forget: list | None = None) -> dict:
        """Settings go to the per-user config; secrets ONLY to the secret store (the Windows
        Credential Manager) — they never come back to the page, which only learns which are set."""
        return self._backup.save(settings or {}, secrets or {}, forget or [])

    def backup_test(self) -> dict:
        return self._backup.test()

    def backup_now(self) -> dict:
        return self._backup.run("manual")

    def backup_cancel(self) -> bool:
        """Stop the running backup (the dialog's Cancel)."""
        return self._backup.cancel()

    def backup_close_choice(self, choice: str) -> bool:
        """The page's answer while the app backs up before closing (app.py): 'background' (close
        now, a quiet process finishes the backup), 'skip' (close without it), 'close' / 'retry'
        after a failed one."""
        if choice not in ("background", "skip", "close", "retry"):
            return False
        self._close_choice = choice
        if choice in ("background", "skip"):
            self._backup.cancel()
        self._close_evt.set()
        return True

    def backup_versions(self) -> list[str]:
        return self._backup.versions()

    def backup_usage(self) -> dict:
        """The backup's size: its current copy and each dated version (may be slow for S3)."""
        return self._backup.usage()

    def backup_prune(self, names: list | None = None, older_than_days: int | None = None) -> dict:
        return self._backup.prune(names=names, older_than_days=older_than_days)

    def storage_usage(self) -> dict:
        """What the notebook folder takes, by kind, and the attached files no note uses."""
        unused = self._nb.unused_files()
        return {"notebook": self._nb.storage(), "path": str(self._nb.root),
                "unused": {"files": len(unused), "bytes": sum(f["bytes"] for f in unused), "list": unused[:200]}}

    def storage_trash_unused(self) -> dict:
        return self._nb.trash_unused_files()

    def storage_empty_trash(self) -> dict:
        return self._nb.empty_trash()

    def storage_clear_clips(self) -> dict:
        return self._nb.clear_audio_clips()

    def backup_choose_folder(self) -> str | None:
        return self._folder_dialog()

    def backup_restore(self, version: str = "") -> dict | None:
        """Restore into a NEW folder the user picks a place for (never over the notebook)."""
        parent = self._folder_dialog()
        if not parent:
            return None
        from datetime import datetime
        name = "FLEx Scratchpad restored " + (version or datetime.now().strftime("%Y-%m-%d_%H%M%S"))
        target = Path(parent) / name
        k = 2
        while target.exists():
            target = Path(parent) / f"{name} ({k})"
            k += 1
        self._backup.restore(target, version)
        return {"path": str(target)}

    # -- files attached to notes (Seth, 2026-10-17) ------------------------------------
    #
    # A `{{file <ref> "label"}}` embed: `ref` is `attachments/<name>` for a file COPIED into the
    # notebook (the default), or an absolute path for a file LINKED where it is (the user's
    # choice). A click opens it in the program Windows associates with it; web pages, PDFs,
    # pictures, audio and video can also be previewed in the window.

    def _file_item(self, ref: str) -> dict:
        p = self._nb.resolve_file(ref)
        linked = Path(ref).is_absolute() or ref[1:3] in (":\\", ":/") or ref.startswith("\\\\")
        info = {"ref": ref, "name": p.name, "linked": bool(linked), "path": str(p), "kind": file_kind(p),
                "exists": p.exists(), "size": None, "fileUrl": None}
        if info["exists"]:
            info["fileUrl"] = p.resolve().as_uri()
            if p.is_file():
                try:
                    info["size"] = p.stat().st_size
                except OSError:
                    pass
        return info

    def _attach_path(self, path: str, link: bool) -> dict:
        p = Path(path)
        if not p.exists():
            raise ValueError(f"Not found: {path}")
        if p.is_dir() or link:          # a folder is always linked: copying one could be anything
            return self._file_item(str(p.resolve()))
        return self._file_item(self._nb.add_file(p.name, src=p))

    def attach_files(self, link: bool = False) -> list[dict]:
        """Pick files to attach; copied into attachments/ unless `link`. [] when cancelled."""
        if self._window is None:
            return []
        import webview
        try:
            dt = webview.FileDialog.OPEN
        except AttributeError:  # pywebview 4
            dt = webview.OPEN_DIALOG
        res = self._window.create_file_dialog(dt, allow_multiple=True)
        return [self._attach_path(p, link) for p in (res or [])]

    def attach_paths(self, paths: list[str], link: bool = False) -> list[dict]:
        return [self._attach_path(p, link) for p in paths or []]

    def attach_data(self, name: str, data_base64: str) -> dict:
        """A file whose bytes the page has but whose path it does not (copied, never linked)."""
        raw = base64.b64decode((data_base64 or "").split(",", 1)[-1])
        return self._file_item(self._nb.add_file(name, data=raw))

    def _on_drop(self, event: dict) -> None:
        """pywebview's own drop handler (app.py): the only place a dropped file's full path is
        known. Kept for a few seconds for the page's drop handler to claim by name."""
        import time
        files = ((event or {}).get("dataTransfer") or {}).get("files") or []
        with self._drop_cv:
            now = time.monotonic()
            self._drops = [d for d in self._drops if now - d[2] < 10]
            for f in files:
                if f.get("pywebviewFullPath"):
                    self._drops.append((f.get("name") or Path(f["pywebviewFullPath"]).name, f["pywebviewFullPath"], now))
            self._drop_cv.notify_all()

    def attach_dropped(self, names: list[str], link: bool = False) -> dict:
        """Attach files just dropped on the page, by name. pywebview reports their paths on
        another thread, so wait for them briefly. {files: [...], missing: [names]} — the page
        sends a missing file's bytes instead (attach_data), which can only copy it."""
        import time
        want = list(names or [])
        found: dict[str, str] = {}
        deadline = time.monotonic() + 1.5
        with self._drop_cv:
            while True:
                for name in want:
                    if name in found:
                        continue
                    for d in self._drops:
                        if d[0] == name:
                            found[name] = d[1]
                            self._drops.remove(d)
                            break
                left = deadline - time.monotonic()
                if len(found) == len(want) or left <= 0:
                    break
                self._drop_cv.wait(left)
        return {"files": [self._attach_path(found[n], link) for n in want if n in found],
                "missing": [n for n in want if n not in found]}

    def file_info(self, ref: str) -> dict:
        return self._file_item(ref)

    def open_file(self, ref: str) -> dict:
        """Open an attachment in its default program. A program or script is never started from
        a note: it is shown in its folder instead ({opened: False, shown: True})."""
        p = self._nb.resolve_file(ref)
        if not p.exists():
            raise ValueError(f"The file is missing: {p}")
        if file_kind(p) == "program":
            return {"opened": False, "shown": self._reveal(p), "reason": "program"}
        return {"opened": self._open_url(str(p))}

    def reveal_file(self, ref: str) -> bool:
        p = self._nb.resolve_file(ref)
        return self._reveal(p if p.exists() else p.parent)

    def locate_file(self, ref: str) -> dict | None:
        """A missing attachment: pick the file again. A copied one is copied again, a linked one
        is linked to the new place. None when cancelled."""
        if self._window is None:
            return None
        item = self._file_item(ref)
        picked = self._dialog("open", allow_multiple=False)
        return self._attach_path(picked, item["linked"]) if picked else None

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
            obj = self._flex.get_object(kind, guid, seg_from, seg_to, prefer_cache, ws or None, at or None)
        except FlexError as e:
            raise RuntimeError(e.message)
        if not obj.get("cached"):
            # the snapshot just gained this object's words and tags: the notes quoting it are searchable by them now
            try:
                self._nb.reindex_mentioning(guid)
            except Exception:  # noqa: BLE001 — never let the index fail a rendering
                pass
        return obj

    def flex_search_entries(self, q: str, limit: int = 30) -> list[dict]:
        try:
            return self._flex.search_entries(q, limit)
        except FlexError as e:
            raise RuntimeError(e.message)

    def flex_text_tags(self) -> list[dict]:
        """The project's text markup tags (the picker's Tags search, the tag style editors)."""
        return self._flex.text_tags()

    def export_chart(self, guid: str, fmt: str = "xml", rows: list | None = None, path: str | None = None) -> str | None:
        """A text chart (or rows a..b of it) as FieldWorks' discourse-chart XML or as JSON with
        every GUID (flex/chart_export.py); `path` skips the save dialog (tests)."""
        from .flex import chart_export
        fmt = (fmt or "xml").lower()
        if fmt not in ("xml", "json"):
            raise ValueError("fmt is xml or json")
        try:
            chart = self._flex.get_object("chart", guid, prefer_cache=False)
        except FlexError as e:
            raise RuntimeError(e.message) from e
        rr = None
        if rows and len(rows) >= 1 and rows[0]:
            rr = (int(rows[0]), int(rows[1] if len(rows) > 1 and rows[1] else rows[0]))
        name = safe_filename((chart.get("name") or "chart") + " - " + (chart.get("title") or "") + (f" rows {rr[0]}-{rr[1]}" if rr else "")) + "." + fmt
        target = path or self._save_dialog(name)
        if not target:
            return None
        app = f"{APP_NAME} {__version__} (build {build_id()})"
        text = chart_export.discourse_xml(chart, rr, app) if fmt == "xml" else chart_export.chart_json(chart, rr, app)
        Path(target).write_text(text, encoding="utf-8", newline="\n")
        LOG.info("chart %s exported as %s → %s", guid[:8], fmt, target)
        return target

    def chart_search(self, q: str) -> list[dict]:
        """The chart rows a query matches (FlexService.chart_search): the picker's chart search."""
        try:
            return self._flex.chart_search(q or "")
        except FlexError as e:
            raise RuntimeError(e.message) from e

    def chart_profile(self, term: str) -> dict:
        """Where a lexical item sits in the charts: counts per template and column, with the rows."""
        try:
            return self._flex.chart_profile(term or "")
        except FlexError as e:
            raise RuntimeError(e.message) from e

    def flex_charts(self, text_guid: str = "") -> list[dict]:
        """The project's text charts, or one text's (the picker's Charts tab, a chart note)."""
        return self._flex.charts(text_guid or None)

    def flex_chart_markers(self) -> list[dict]:
        return self._flex.chart_markers()

    def flex_tag_occurrences(self, tag_guid: str, q: str = "") -> list[dict]:
        try:
            return self._flex.tag_occurrences(tag_guid, q)
        except FlexError as e:
            raise RuntimeError(e.message) from e

    # FLEx tag STYLES (Seth, 2026-10-17: project-, tab-, folder- and example-scoped, "the most
    # specific one takes precedent"): the notebook keeps the first three in notebook.json
    # (`tagStyles.project[<project>]`, `.tab[<dir>]`, `.folder[<tab>/<path>]`); an example's own
    # are in its embed (`tags=`). A rule: {tag, enabled, hide, bg, fg, b, i, u, label}.
    _BRACKETS = ("sq", "rd", "cu", "an", "db", "ce", "fl", "bar")

    @classmethod
    def _clean_tag_rules(cls, rules) -> list[dict]:
        """A rule list as the page sends it, kept to what tagstyles.js understands: the tag (a
        name, abbreviation, GUID, `group:<name>`, `filter:<id>` or `*`), on/off, the bar's colours,
        B I U, and the text styles (brackets, hl, tile, box, the words' colour, the bar switch)."""
        clean = []
        for r in rules or []:
            if not isinstance(r, dict) or not str(r.get("tag") or "").strip():
                continue
            out = {"tag": str(r["tag"]).strip()[:120], "enabled": r.get("enabled", True) is not False}
            if r.get("hide") is not None:
                out["hide"] = bool(r["hide"])
            if r.get("empty") is not None:        # a chart marker in a cell with no words (Seth, 2026-10-19)
                out["empty"] = bool(r["empty"])
            for k in ("bg", "fg", "c", "tc", "bc"):
                v = str(r.get(k) or "")
                if re.fullmatch(r"#[0-9a-fA-F]{6}", v):
                    out[k] = v.lower()
            # the border's line style and thickness (Seth, 2026-10-18)
            if r.get("bs") in ("solid", "dashed", "dotted", "double"):
                out["bs"] = r["bs"]
            try:
                bw = int(r.get("bw") or 0)
            except (TypeError, ValueError):
                bw = 0
            if 1 <= bw <= 6:
                out["bw"] = bw
            for k in ("b", "i", "u", "hl", "tile", "box"):
                if r.get(k):
                    out[k] = True
            if r.get("br") in cls._BRACKETS:
                out["br"] = r["br"]
            if r.get("bar") is not None:
                out["bar"] = bool(r["bar"])
            if r.get("label") is False:
                out["label"] = False
            # moved text (Seth, 2026-10-19): whose look it wears, and its label
            if r.get("ms") in ("from", "to", "own"):
                out["ms"] = r["ms"]
            if r.get("ml") in ("from", "to", "off"):
                out["ml"] = r["ml"]
            clean.append(out)
        return clean

    def _tag_styles(self) -> dict:
        ts = self._nb.config.setdefault("tagStyles", {})
        for k in ("project", "tab", "folder", "note", "text"):
            ts.setdefault(k, {})
        ts.setdefault("filters", [])
        return ts

    def set_tag_styles(self, kind: str, key: str, rules: list[dict]) -> dict:
        if kind not in ("project", "tab", "folder", "note", "text"):
            raise ValueError("tag styles are kept per project, tab, folder, note or text")
        clean = self._clean_tag_rules(rules)
        ts = self._tag_styles()
        bucket = ts.setdefault(kind, {})
        if clean:
            bucket[key or ""] = clean
        else:
            bucket.pop(key or "", None)
        self._nb.save_config()
        return ts

    def set_tag_filters(self, filters: list[dict]) -> dict:
        """The notebook's visual filters (Seth, 2026-10-18: "various 'visual filters' based on text
        tags like … in Logos"): [{id, name, enabled, rules}], in the order they are consulted."""
        clean = []
        seen = set()
        for f in filters or []:
            if not isinstance(f, dict):
                continue
            fid = re.sub(r"[^a-z0-9_-]", "", str(f.get("id") or "").lower())[:40] or ("f" + uuid.uuid4().hex[:10])
            if fid in seen:
                continue
            seen.add(fid)
            clean.append({"id": fid, "name": str(f.get("name") or "").strip()[:80], "enabled": f.get("enabled", True) is not False,
                          "rules": self._clean_tag_rules(f.get("rules"))})
        ts = self._tag_styles()
        ts["filters"] = clean
        self._nb.save_config()
        return ts

    def flex_tags_used(self) -> dict:
        return self._nb.flex_tags_used()

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
        if kind == "chart":
            # FieldWorks has no link to a chart itself: open its text (the Text Chart tab is there)
            try:
                chart = self._flex.get_object("chart", guid, prefer_cache=True)
            except FlexError:
                chart = {}
            url = chart.get("url") or model.goto_url(self._flex.project_name, "text", chart.get("text") or guid)
            return self._open_url(url)
        url = model.goto_url(self._flex.project_name, kind, guid)
        return self._open_url(url)

    def texts_used(self, scope: dict) -> dict:
        """The FLEx texts the examples come from, one row per text (Seth, 2026-10-16: "list which
        texts are referenced in a [note], a folder, or a selected range … not individual items,
        but texts they come from", and "a FLEx hyperlink for each"). scope: {"note": id} — that
        note; {"note": id, "markdown": md} — the highlighted part of it; {"tab": t, "folder": f} —
        every note in that folder AND its subfolders ("" = the whole tab).
        → {texts: [FlexService.texts_used rows], notes: n notes looked at}."""
        scope = scope or {}
        sources: list[tuple[str, str, str]] = []
        with self._lock:
            if scope.get("note"):
                n = self._nb.get_note(scope["note"])
                sources.append((n.id, n.title, scope["markdown"] if scope.get("markdown") is not None else n.body))
            else:
                tab, folder = scope.get("tab") or "", (scope.get("folder") or "").strip("/")
                for s in self._nb.list_notes():
                    if tab and s.get("tab") != tab:
                        continue
                    f = s.get("folder") or ""
                    if folder and not (f == folder or f.startswith(folder + "/")):
                        continue
                    n = self._nb.get_note(s["id"])
                    sources.append((n.id, n.title, n.body))
        return {"texts": self._flex.texts_used(sources), "notes": len(sources)}

    def open_in_flex(self, url: str) -> bool:
        """Hand a silfw:// link to the OS; Windows routes it to FieldWorks."""
        if not url or not url.lower().startswith("silfw:"):
            raise RuntimeError("Not a FieldWorks link.")
        return self._open_url(url)

    def open_web(self, url: str) -> bool:
        """Open an http(s) page in the default browser (the regex help links). Nothing else."""
        if not url or not re.match(r"^https?://", url, re.I):
            raise RuntimeError("Not a web address.")
        return self._open_url(url)

    # -- audio ------------------------------------------------------------------------------

    def audio_clip(self, text_guid: str, media_guid: str | None, begin: int, end: int) -> dict:
        try:
            return self._flex.ensure_clip(text_guid, media_guid, begin, end)
        except FlexError as e:
            raise RuntimeError(e.message)

    def export_clips(self, items: list[dict], job: str | None = None) -> list[dict]:
        """The recordings an HTML export embeds, one compressed clip per example: cut and encoded
        here (or taken from the cache), kept here, and handed to the page as a TOKEN — the page writes
        `fs-clip:<token>` where the audio goes and export_note_html puts the recording in the file."""
        import secrets
        prog = (lambda done, total, label: self._job(job, step="audio", done=done, total=total, text=("Preparing the recordings " + str(min(done + 1, total)) + " of " + str(total) + (" — " + label if label else "")) if done < total else "Recordings ready")) if job else None
        out = self._flex.export_clips(items or [], progress=prog)
        for r in out:
            p = r.pop("path", None)
            if p:
                token = secrets.token_hex(8)
                self._clips[token] = (p, r.get("mime") or "application/octet-stream")
                r["token"] = token
        return out

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

    _SAVE_TYPES = {".flextext": "FLEx interlinear text", ".html": "Web page", ".md": "Markdown",
                   ".docx": "Word document", ".xlsx": "Excel workbook", ".pptx": "PowerPoint presentation", ".pdf": "PDF document", ".zip": "Zip archive", ".wav": "WAV audio"}

    def _save_dialog(self, name: str) -> str | None:
        """A save dialog suggesting `name`, made safe for a Windows filename, and a path that
        always ends in the suggested extension (Seth, 2026-10-16: a title with "/" in it saved
        an export with no .flextext, which FLEx then refused)."""
        name = safe_filename(name)
        ext = Path(name).suffix.lower()
        kw = {"save_filename": name}
        if ext:
            kw["file_types"] = (f"{self._SAVE_TYPES.get(ext, ext[1:].upper() + ' file')} (*{ext})",)
        try:
            target = self._dialog("save", **kw)
        except Exception:  # noqa: BLE001 — a backend that refuses the filter: ask without it
            target = self._dialog("save", save_filename=name)
        return with_suffix(target, ext) if target else target

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


# Every public method of Api is the js_api surface; each call is logged (flex_scratchpad/log.py:
# the arguments, the result in short, the time; secrets redacted) so a run from a terminal says
# exactly what the page asked for and what came back.
for _name, _fn in list(vars(Api).items()):
    if not _name.startswith("_") and callable(_fn) and not isinstance(_fn, (staticmethod, classmethod, property)):
        setattr(Api, _name, _logged(_fn))
