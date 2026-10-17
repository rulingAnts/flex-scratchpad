"""The notebook on disk: markdown files in folders, plus a full-text index in memory.

Layout (the notebook folder is self-describing; nothing here needs the app to be readable):

    <notebook>/notebook.json                       tabs, tags, FLEx source, media mappings
    <notebook>/<Tab>/<Folder>/<Sub>/<slug>--<id>.md one note; directories ARE the tabs and folders
    <notebook>/.scratchpad/                        trash, flex-cache, attachments (never scanned)

A note file is a small front-matter header followed by the markdown body:

    ---
    id: n_k3v8q2m7
    title: Aspect marking
    tags: [grammar, todo]
    created: 2026-10-12T09:30:00
    updated: 2026-10-12T10:05:12
    pinned: false
    ---
    body…

An EXAMPLE COLLECTION (Seth, 2026-10-16) is a note whose header also says `kind: examples`: its
body is nothing but interlinear examples, one `{{flex:text …}}` per paragraph, in order, and it
is the one kind of note that exports as a FLEx text. Ordinary notes carry no `kind` line.

Only a YAML *subset* is written and read (scalars, `[a, b]` lists, JSON-quoted strings), so there
is no PyYAML dependency. Everything is UTF-8 with `\n` newlines; user text is never normalised or
folded on save (only the search index normalises, in memory).
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import threading
import unicodedata
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

CONFIG_NAME = "notebook.json"
NOTE_KINDS = ("", "examples")
EXAMPLE_LINE_RE = re.compile(r"^\s*\{\{flex:text\b[^\n]*\}\}\s*$", re.M)
PRIVATE_DIR = ".scratchpad"
DEFAULT_TAB = "Notes"
NOTE_SUFFIX = ".md"

TAB_COLORS = ["#2f6fdb", "#0f766e", "#b45309", "#7c3aed", "#be185d", "#4d7c0f", "#0e7490", "#9f1239"]
TAG_COLORS = ["#2a6e2a", "#1f4f8f", "#b45309", "#7c3aed", "#be185d", "#0e7490", "#6b7280"]

_UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')
_WS = re.compile(r"\s+")


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def new_id() -> str:
    return "n_" + secrets.token_hex(5)


def slugify(title: str, fallback: str = "note", limit: int = 60) -> str:
    """A filesystem-safe name that keeps Unicode letters (a Tamil title stays Tamil)."""
    s = unicodedata.normalize("NFC", title or "").strip()
    s = _UNSAFE.sub("-", s)
    s = _WS.sub(" ", s).strip(" .-")
    if len(s) > limit:
        s = s[:limit].rstrip(" .-")
    return s or fallback


def safe_dirname(name: str, fallback: str = "Folder") -> str:
    return slugify(name, fallback=fallback, limit=80)


# ----------------------------------------------------------------------------
# Front matter (YAML subset)
# ----------------------------------------------------------------------------

def _fm_dump_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_fm_dump_value(x) for x in v) + "]"
    if v is None:
        return '""'
    s = str(v)
    # Quote anything that would not read back as the same plain scalar.
    if s == "" or s != s.strip() or any(c in s for c in '#[]{}"\n') or s[:1] in ("'", "-", "*", "&", "!", "%", "@", "`") \
            or s.lower() in ("true", "false", "null"):
        return json.dumps(s, ensure_ascii=False)
    return s


def _fm_parse_value(raw: str):
    s = raw.strip()
    if s == "":
        return ""
    if s.startswith('"'):
        try:
            return json.loads(s)
        except ValueError:
            return s.strip('"')
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        if not inner:
            return []
        items, buf, quoted = [], "", False
        for ch in inner:
            if ch == '"':
                quoted = not quoted
                buf += ch
            elif ch == "," and not quoted:
                items.append(buf)
                buf = ""
            else:
                buf += ch
        items.append(buf)
        return [_fm_parse_value(x) for x in items if x.strip() != ""]
    if s in ("true", "false"):
        return s == "true"
    return s


def dump_front_matter(meta: dict) -> str:
    lines = ["---"]
    for k, v in meta.items():
        lines.append(f"{k}: {_fm_dump_value(v)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def parse_note_file(text: str) -> tuple[dict, str]:
    """Split a note file into (meta, body). A file without front matter is all body."""
    if not text.startswith("---\n") and not text.startswith("---\r\n"):
        return {}, text
    lines = text.splitlines()
    meta: dict = {}
    i = 1
    while i < len(lines):
        line = lines[i]
        if line.strip() == "---":
            body = "\n".join(lines[i + 1:])
            return meta, body
        if ":" in line and not line.startswith(" "):
            k, _, v = line.partition(":")
            meta[k.strip()] = _fm_parse_value(v)
        i += 1
    return {}, text  # unterminated header: treat the whole file as body


# ----------------------------------------------------------------------------
# Notes
# ----------------------------------------------------------------------------

@dataclass
class Note:
    id: str
    title: str
    tab: str                 # tab directory name
    folder: str              # '' or 'A/B' (directory names joined with '/')
    tags: list[str] = field(default_factory=list)
    created: str = ""
    updated: str = ""
    pinned: bool = False
    kind: str = ""           # '' = an ordinary note; 'examples' = an example collection
    body: str = ""
    path: Path | None = None

    def meta(self) -> dict:
        d = asdict(self)
        d.pop("body", None)
        d["path"] = str(self.path) if self.path else ""
        return d

    def summary(self, excerpt_len: int = 160) -> dict:
        d = self.meta()
        d["excerpt"] = excerpt(self.body, excerpt_len)
        if self.kind == "examples":
            d["exampleCount"] = len(EXAMPLE_LINE_RE.findall(self.body))
        d["inlineTags"] = inline_tags(self.body)
        return d


_EMBED = re.compile(r"\{\{[^}]*\}\}")
_MD_NOISE = re.compile(r"^(#{1,6}\s+|[-*+]\s+(\[[ xX]\]\s+)?|\d+[.)]\s+|>\s+)", re.M)
# a closed heading's fold marker (" {collapsed}", the editor's and a collection's) is view state,
# never text: excerpts, search and the Markdown export leave it out
FOLD_MARK = re.compile(r"^(#{1,6}\s.*?)\s+\{collapsed\}[ \t]*$", re.M)


def without_fold_marks(body: str) -> str:
    return FOLD_MARK.sub(r"\1", body or "")
_INLINE_TAG = re.compile(r"(?<![\w#/&])#([\w][\w\-]*)", re.UNICODE)


def excerpt(body: str, n: int = 160) -> str:
    s = _EMBED.sub(" ", without_fold_marks(body))
    s = re.sub(r"```[\s\S]*?```", " ", s)
    s = _MD_NOISE.sub("", s)
    s = re.sub(r"[*_`~=]{1,3}", "", s)
    s = _WS.sub(" ", s).strip()
    return s[:n]


def inline_tags(body: str) -> list[str]:
    """`#tag` written in the body counts as a tag (Seth, 2026-10-12). Not inside code/embeds."""
    s = re.sub(r"```[\s\S]*?```|`[^`\n]*`", " ", body or "")
    s = _EMBED.sub(" ", s)
    out: list[str] = []
    for m in _INLINE_TAG.finditer(s):
        t = m.group(1)
        if t.isdigit():
            continue
        if t not in out:
            out.append(t)
    return out


# ----------------------------------------------------------------------------
# Search normalisation
# ----------------------------------------------------------------------------

def normalize_with_map(text: str, strip_marks: bool = False) -> tuple[str, list[int]]:
    """Casefolded (and optionally mark-stripped) text plus a map from each normalised
    character back to the ORIGINAL character index, so hits can be highlighted in the real text.
    Per-character normalisation keeps the map exact (normalising the whole string would not).
    Characters are DECOMPOSED (NFKD) so precomposed and combining-sequence spellings of the same
    letter (ú vs u+́) meet in one form whether the marks are then stripped or not."""
    out: list[str] = []
    idx: list[int] = []
    for i, ch in enumerate(text):
        n = unicodedata.normalize("NFKD", ch)
        if strip_marks:
            n = "".join(c for c in n if not unicodedata.category(c).startswith("M"))
        n = n.casefold()
        for c in n:
            if not strip_marks and out and unicodedata.category(c).startswith("M"):
                # keep marks, but COMPOSED onto their base where Unicode has a single character
                # for the pair, so an unaccented query does not match the accented letter
                comp = unicodedata.normalize("NFC", out[-1] + c)
                if len(comp) == 1:
                    out[-1] = comp
                    continue
            out.append(c)
            idx.append(i)
    return "".join(out), idx


def normalize(text: str, strip_marks: bool = False) -> str:
    return normalize_with_map(text, strip_marks)[0]


_QUERY_TOKEN = re.compile(r'"([^"]*)"|(\S+)')


def parse_query(q: str) -> dict:
    """`aspect "free translation" tag:todo tab:Grammar folder:Verbs` → terms + filters."""
    terms: list[str] = []
    filters: dict[str, list[str]] = {"tag": [], "tab": [], "folder": []}
    for m in _QUERY_TOKEN.finditer(q or ""):
        phrase, word = m.group(1), m.group(2)
        if phrase is not None:
            if phrase.strip():
                terms.append(phrase.strip())
            continue
        k, _, v = word.partition(":")
        if _ and k.lower() in filters and v:
            filters[k.lower()].append(v)
        elif word.startswith("#") and len(word) > 1:
            filters["tag"].append(word[1:])
        else:
            terms.append(word)
    return {"terms": terms, "filters": filters}


# ----------------------------------------------------------------------------
# Notebook
# ----------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "version": 1,
    "tabs": [],                      # [{dir, name, color}]
    "tags": [],                      # [{name, color}]
    "flex": {"source": "lcm", "project": "", "flextextPath": ""},
    "media": {"byGuid": {}, "folders": []},
    "settings": {"diacriticsInsensitive": True},
}


class Notebook:
    """All file access to one notebook folder. Thread-safe through one lock (pywebview calls
    arrive on arbitrary threads)."""

    def __init__(self, root: str | Path, extra_text: Callable[[str], str] | None = None):
        self.root = Path(root)
        self.lock = threading.RLock()
        self.notes: dict[str, Note] = {}
        self.config: dict = json.loads(json.dumps(DEFAULT_CONFIG))
        # extra_text(body) → text that should be searchable too (FLEx snapshot text for embeds)
        self.extra_text = extra_text or (lambda body: "")
        self._index: dict[str, str] = {}
        self._index_marks: dict[str, str] = {}
        self.ensure()
        self.load()

    # -- folders ---------------------------------------------------------------

    @property
    def private_dir(self) -> Path:
        return self.root / PRIVATE_DIR

    @property
    def trash_dir(self) -> Path:
        return self.private_dir / "trash"

    @property
    def cache_dir(self) -> Path:
        return self.private_dir / "flex-cache"

    @property
    def attachments_dir(self) -> Path:
        return self.private_dir / "attachments"

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.private_dir.mkdir(exist_ok=True)
        cfg = self.root / CONFIG_NAME
        if not cfg.exists():
            self.config["tabs"] = [{"dir": DEFAULT_TAB, "name": DEFAULT_TAB, "color": TAB_COLORS[0]}]
            (self.root / DEFAULT_TAB).mkdir(exist_ok=True)
            self._write_config()

    # -- config ----------------------------------------------------------------

    def _write_config(self) -> None:
        _atomic_write(self.root / CONFIG_NAME, json.dumps(self.config, indent=2, ensure_ascii=False) + "\n")

    def save_config(self) -> None:
        with self.lock:
            self._write_config()

    def load(self) -> None:
        with self.lock:
            try:
                with open(self.root / CONFIG_NAME, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                base = json.loads(json.dumps(DEFAULT_CONFIG))
                for k, v in (loaded or {}).items():
                    if isinstance(v, dict) and isinstance(base.get(k), dict):
                        base[k].update(v)
                    else:
                        base[k] = v
                self.config = base
            except (OSError, ValueError):
                pass
            self.scan()

    # -- scanning ----------------------------------------------------------------

    def scan(self) -> None:
        """Rebuild the note table from disk. Unknown top-level directories become tabs."""
        with self.lock:
            self.notes.clear()
            self._index.clear()
            self._index_marks.clear()
            known = {t["dir"] for t in self.config["tabs"]}
            changed = False
            for entry in sorted(self.root.iterdir(), key=lambda p: p.name.casefold()):
                if not entry.is_dir() or entry.name.startswith("."):
                    continue
                if entry.name not in known:
                    self.config["tabs"].append({
                        "dir": entry.name, "name": entry.name,
                        "color": TAB_COLORS[len(self.config["tabs"]) % len(TAB_COLORS)],
                    })
                    known.add(entry.name)
                    changed = True
                self._scan_tab(entry)
            if changed:
                self._write_config()

    def _scan_tab(self, tab_dir: Path) -> None:
        for dirpath, dirnames, filenames in os.walk(tab_dir):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            rel = Path(dirpath).relative_to(tab_dir)
            folder = "/".join(rel.parts)
            for fn in sorted(filenames):
                if not fn.endswith(NOTE_SUFFIX) or fn.startswith("."):
                    continue
                path = Path(dirpath) / fn
                note = self._read_note(path, tab_dir.name, folder)
                if note:
                    self.notes[note.id] = note
                    self._reindex(note)

    def _read_note(self, path: Path, tab: str, folder: str) -> Note | None:
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                text = f.read()
        except OSError:
            return None
        meta, body = parse_note_file(text)
        nid = str(meta.get("id") or "")
        m = re.search(r"--(n_[0-9a-f]{10})\.md$", path.name)
        if not nid:
            nid = m.group(1) if m else new_id()
        if nid in self.notes:  # duplicate id (a copied file): give the copy a new identity
            nid = new_id()
        title = str(meta.get("title") or _title_from_filename(path.name))
        stat = path.stat()
        tags = meta.get("tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        return Note(
            id=nid, title=title, tab=tab, folder=folder,
            tags=[str(t) for t in tags],
            created=str(meta.get("created") or datetime.fromtimestamp(stat.st_ctime).replace(microsecond=0).isoformat()),
            updated=str(meta.get("updated") or datetime.fromtimestamp(stat.st_mtime).replace(microsecond=0).isoformat()),
            pinned=bool(meta.get("pinned", False)),
            kind=str(meta.get("kind") or ""),
            body=body.replace("\r\n", "\n"),
            path=path,
        )

    # -- index -----------------------------------------------------------------

    def _reindex(self, note: Note) -> None:
        try:
            extra = self.extra_text(note.body) or ""
        except Exception:  # a cache problem must never break note loading
            extra = ""
        blob = "\n".join([note.title, without_fold_marks(note.body), " ".join(note.tags), note.folder, note.tab, extra])
        self._index[note.id] = normalize(blob)
        self._index_marks[note.id] = normalize(blob, strip_marks=True)

    def reindex_all(self) -> None:
        with self.lock:
            for n in self.notes.values():
                self._reindex(n)

    # -- queries ---------------------------------------------------------------

    def tab_dirs(self) -> list[str]:
        return [t["dir"] for t in self.config["tabs"]]

    def tab_info(self, tab: str) -> dict | None:
        for t in self.config["tabs"]:
            if t["dir"] == tab:
                return t
        return None

    def list_notes(self) -> list[dict]:
        with self.lock:
            notes = sorted(self.notes.values(), key=lambda n: (not n.pinned, n.updated), reverse=False)
            notes.sort(key=lambda n: n.updated, reverse=True)
            notes.sort(key=lambda n: not n.pinned)
            return [n.summary() for n in notes]

    def folders(self) -> dict[str, list[str]]:
        """Every folder path per tab, including empty directories."""
        with self.lock:
            out: dict[str, list[str]] = {}
            for tab in self.tab_dirs():
                paths: set[str] = set()
                tab_dir = self.root / tab
                if tab_dir.is_dir():
                    for dirpath, dirnames, _ in os.walk(tab_dir):
                        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                        rel = Path(dirpath).relative_to(tab_dir)
                        if rel.parts:
                            paths.add("/".join(rel.parts))
                out[tab] = sorted(paths, key=str.casefold)
            return out

    def get_note(self, note_id: str) -> Note:
        with self.lock:
            n = self.notes.get(note_id)
            if not n:
                raise KeyError(f"No such note: {note_id}")
            return n

    def all_tags(self) -> list[dict]:
        """Configured tags first (with colours), then any tag seen on notes."""
        with self.lock:
            seen = {t["name"]: dict(t) for t in self.config["tags"]}
            for n in self.notes.values():
                for t in list(n.tags) + inline_tags(n.body):
                    if t not in seen:
                        seen[t] = {"name": t, "color": TAG_COLORS[len(seen) % len(TAG_COLORS)], "implicit": True}
            counts: dict[str, int] = {}
            for n in self.notes.values():
                for t in set(list(n.tags) + inline_tags(n.body)):
                    counts[t] = counts.get(t, 0) + 1
            out = []
            for name, t in seen.items():
                t = dict(t)
                t["count"] = counts.get(name, 0)
                out.append(t)
            return out

    # -- writes ----------------------------------------------------------------

    def _note_dir(self, tab: str, folder: str) -> Path:
        d = self.root / tab
        if folder:
            d = d.joinpath(*[p for p in folder.split("/") if p])
        return d

    def _note_path(self, note: Note) -> Path:
        return self._note_dir(note.tab, note.folder) / f"{slugify(note.title)}--{note.id}{NOTE_SUFFIX}"

    def _write_note(self, note: Note) -> None:
        meta = {
            "id": note.id, "title": note.title, "tags": note.tags,
            "created": note.created, "updated": note.updated, "pinned": note.pinned,
        }
        if note.kind:                       # only collections carry it: ordinary files are unchanged
            meta["kind"] = note.kind
        target = self._note_path(note)
        target.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(target, dump_front_matter(meta) + note.body)
        if note.path and note.path != target and note.path.exists():
            try:
                note.path.unlink()
            except OSError:
                pass
        note.path = target
        self._reindex(note)

    def create_note(self, tab: str | None = None, folder: str = "", title: str = "", body: str = "", kind: str = "") -> Note:
        if kind not in NOTE_KINDS:
            raise ValueError(f"Unknown kind of note: {kind}")
        with self.lock:
            tab = tab or (self.tab_dirs()[0] if self.tab_dirs() else DEFAULT_TAB)
            if tab not in self.tab_dirs():
                self.add_tab(tab)
            ts = now_iso()
            note = Note(id=new_id(), title=title or "", tab=tab, folder=folder or "",
                        created=ts, updated=ts, body=body, kind=kind)
            self.notes[note.id] = note
            self._write_note(note)
            return note

    def duplicate_note(self, note_id: str, tab: str | None = None, folder: str | None = None, title: str | None = None) -> Note:
        """A copy of a note (Seth, 2026-10-16): same body and tags, a new id, in the same place
        unless a tab / folder is given ("copy to"). Not pinned. Titled "<title> (copy)" in the
        same place, the original title elsewhere, unless `title` says otherwise."""
        with self.lock:
            src = self.get_note(note_id)
            same_place = (tab is None or tab == src.tab) and (folder is None or (folder or "") == (src.folder or ""))
            new_title = title if title is not None else ((src.title + " (copy)") if same_place and src.title else src.title)
            copy = self.create_note(tab or src.tab, src.folder if folder is None else (folder or ""), new_title, src.body, src.kind)
            if src.tags:
                copy = self.save_note(copy.id, tags=list(src.tags))
            return copy

    def save_note(self, note_id: str, title: str | None = None, body: str | None = None,
                  tags: list[str] | None = None, pinned: bool | None = None) -> Note:
        with self.lock:
            note = self.get_note(note_id)
            changed = False
            if title is not None and title != note.title:
                note.title = title
                changed = True
            if body is not None and body.replace("\r\n", "\n") != note.body:
                note.body = body.replace("\r\n", "\n")
                changed = True
            if tags is not None and list(tags) != note.tags:
                note.tags = [str(t).strip() for t in tags if str(t).strip()]
                changed = True
            if pinned is not None and bool(pinned) != note.pinned:
                note.pinned = bool(pinned)
                changed = True
            if changed:
                note.updated = now_iso()
                self._write_note(note)
            return note

    def append_examples(self, note_id: str, embeds: list[str]) -> Note:
        """Add examples to the END of an example collection, one paragraph each (the "Add to
        collection" of an example in any note). Only collections take them."""
        with self.lock:
            note = self.get_note(note_id)
            if note.kind != "examples":
                raise ValueError(f"“{note.title or 'Untitled'}” is not an example collection")
            add = [e.strip() for e in embeds or [] if str(e).strip()]
            if not add:
                return note
            body = note.body.rstrip("\n")
            body = (body + "\n\n" if body.strip() else "") + "\n\n".join(add) + "\n"
            return self.save_note(note_id, body=body)

    def collections(self) -> list[dict]:
        """Every example collection, most recently edited first, with its example count."""
        with self.lock:
            out = [{"id": n.id, "title": n.title, "tab": n.tab, "folder": n.folder, "updated": n.updated,
                    "count": len(EXAMPLE_LINE_RE.findall(n.body))}
                   for n in self.notes.values() if n.kind == "examples"]
        out.sort(key=lambda d: d["updated"], reverse=True)
        return out

    def move_note(self, note_id: str, tab: str, folder: str = "") -> Note:
        with self.lock:
            note = self.get_note(note_id)
            if tab not in self.tab_dirs():
                raise KeyError(f"No such tab: {tab}")
            note.tab, note.folder = tab, folder or ""
            self._write_note(note)
            return note

    def delete_note(self, note_id: str) -> None:
        """Soft delete: the file goes to .scratchpad/trash (nothing is ever destroyed)."""
        with self.lock:
            note = self.get_note(note_id)
            self.trash_dir.mkdir(parents=True, exist_ok=True)
            if note.path and note.path.exists():
                dest = self.trash_dir / f"{now_iso().replace(':', '-')}--{note.path.name}"
                shutil.move(str(note.path), str(dest))
            self.notes.pop(note_id, None)
            self._index.pop(note_id, None)
            self._index_marks.pop(note_id, None)

    # -- tabs / folders / tags -------------------------------------------------

    def add_tab(self, name: str, color: str | None = None) -> dict:
        with self.lock:
            d = safe_dirname(name, "Tab")
            base, i = d, 2
            while any(t["dir"] == d for t in self.config["tabs"]):
                d = f"{base} {i}"
                i += 1
            tab = {"dir": d, "name": name.strip() or d, "color": color or TAB_COLORS[len(self.config["tabs"]) % len(TAB_COLORS)]}
            self.config["tabs"].append(tab)
            (self.root / d).mkdir(exist_ok=True)
            self._write_config()
            return tab

    def update_tab(self, tab: str, name: str | None = None, color: str | None = None) -> dict:
        with self.lock:
            t = self.tab_info(tab)
            if not t:
                raise KeyError(f"No such tab: {tab}")
            if name is not None:
                t["name"] = name.strip() or t["name"]
            if color:
                t["color"] = color
            self._write_config()
            return t

    def reorder_tabs(self, dirs: list[str]) -> None:
        with self.lock:
            by = {t["dir"]: t for t in self.config["tabs"]}
            ordered = [by[d] for d in dirs if d in by] + [t for t in self.config["tabs"] if t["dir"] not in dirs]
            self.config["tabs"] = ordered
            self._write_config()

    def delete_tab(self, tab: str) -> None:
        """Only an empty tab can be deleted (its notes must be moved or trashed first)."""
        with self.lock:
            if any(n.tab == tab for n in self.notes.values()):
                raise ValueError("Move or delete the notes in this tab first.")
            self.config["tabs"] = [t for t in self.config["tabs"] if t["dir"] != tab]
            d = self.root / tab
            if d.is_dir():
                shutil.rmtree(d, ignore_errors=True)
            self._write_config()

    def create_folder(self, tab: str, folder: str) -> str:
        with self.lock:
            parts = [safe_dirname(p) for p in folder.split("/") if p.strip()]
            if not parts:
                raise ValueError("Folder name is empty.")
            self._note_dir(tab, "/".join(parts)).mkdir(parents=True, exist_ok=True)
            return "/".join(parts)

    def rename_folder(self, tab: str, folder: str, new_name: str) -> str:
        with self.lock:
            parts = [p for p in folder.split("/") if p]
            if not parts:
                raise ValueError("Cannot rename the tab root.")
            new_parts = parts[:-1] + [safe_dirname(new_name)]
            src, dst = self._note_dir(tab, "/".join(parts)), self._note_dir(tab, "/".join(new_parts))
            if dst.exists():
                raise ValueError("A folder with that name already exists.")
            src.rename(dst)
            old, new = "/".join(parts), "/".join(new_parts)
            for n in self.notes.values():
                if n.tab == tab and (n.folder == old or n.folder.startswith(old + "/")):
                    n.folder = new + n.folder[len(old):]
                    n.path = self._note_path(n)
            return new

    def delete_folder(self, tab: str, folder: str) -> None:
        with self.lock:
            if any(n.tab == tab and (n.folder == folder or n.folder.startswith(folder + "/")) for n in self.notes.values()):
                raise ValueError("Move or delete the notes in this folder first.")
            d = self._note_dir(tab, folder)
            if d.is_dir():
                shutil.rmtree(d, ignore_errors=True)

    def set_tags(self, tags: list[dict]) -> list[dict]:
        with self.lock:
            clean = []
            for t in tags:
                name = str(t.get("name", "")).strip().lstrip("#")
                if name and not any(c["name"] == name for c in clean):
                    clean.append({"name": name, "color": t.get("color") or TAG_COLORS[len(clean) % len(TAG_COLORS)]})
            self.config["tags"] = clean
            self._write_config()
            return clean

    def rename_tag(self, old: str, new: str) -> int:
        """Rename a tag everywhere (note headers; inline #old in bodies). Returns notes changed."""
        with self.lock:
            new = new.strip().lstrip("#")
            if not new:
                raise ValueError("Tag name is empty.")
            for t in self.config["tags"]:
                if t["name"] == old:
                    t["name"] = new
            self._write_config()
            changed = 0
            pat = re.compile(r"(?<![\w#/&])#" + re.escape(old) + r"(?![\w\-])")
            for n in list(self.notes.values()):
                tags = [new if t == old else t for t in n.tags]
                body = pat.sub("#" + new, n.body)
                if tags != n.tags or body != n.body:
                    self.save_note(n.id, body=body, tags=tags)
                    changed += 1
            return changed

    # -- search ------------------------------------------------------------------

    def search(self, q: str, tab: str | None = None, folder: str | None = None,
               tags: Iterable[str] | None = None, limit: int = 100) -> list[dict]:
        """Ranked full-text search. All terms must match (title > tag > body). Diacritics-
        insensitive when the notebook setting says so (or when the query itself has no marks)."""
        with self.lock:
            parsed = parse_query(q)
            terms = parsed["terms"]
            f = parsed["filters"]
            want_tags = set(t.casefold() for t in (list(tags or []) + f["tag"]))
            strip = bool(self.config.get("settings", {}).get("diacriticsInsensitive", True))
            index = self._index_marks if strip else self._index
            nterms = [normalize(t, strip) for t in terms if t.strip()]
            results = []
            for n in self.notes.values():
                if tab and n.tab != tab:
                    continue
                if f["tab"] and not any(_match_tab(self, x, n.tab) for x in f["tab"]):
                    continue
                if folder is not None and folder != "" and not (n.folder == folder or n.folder.startswith(folder + "/")):
                    continue
                if f["folder"] and not any(normalize(x, strip) in normalize(n.folder, strip) for x in f["folder"]):
                    continue
                note_tags = set(t.casefold() for t in list(n.tags) + inline_tags(n.body))
                if want_tags and not want_tags.issubset(note_tags):
                    continue
                blob = index.get(n.id, "")
                if nterms and not all(t in blob for t in nterms):
                    continue
                score = 0.0
                ntitle = normalize(n.title, strip)
                for t in nterms:
                    if t in ntitle:
                        score += 10
                    if any(t in normalize(x, strip) for x in note_tags):
                        score += 5
                    score += min(blob.count(t), 20) * 0.5
                if n.pinned:
                    score += 0.5
                results.append((score, n))
            results.sort(key=lambda r: (-r[0], r[1].updated), reverse=False)
            results.sort(key=lambda r: r[0], reverse=True)
            out = []
            for score, n in results[:limit]:
                hit = n.summary()
                hit["score"] = score
                hit["snippet"], hit["snippetMarks"] = make_snippet(n.body, terms, strip)
                out.append(hit)
            return out

    # -- sync awareness ------------------------------------------------------------

    def fingerprint(self) -> str:
        """A cheap stamp of the notebook on disk (file count + newest mtime of notes and
        config), so the UI can notice a cloud-sync client changing files underneath it."""
        newest = 0.0
        count = 0
        try:
            for root, dirs, files in os.walk(self.root):
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                for fn in files:
                    if fn.endswith(NOTE_SUFFIX) or fn == CONFIG_NAME:
                        count += 1
                        try:
                            newest = max(newest, os.stat(os.path.join(root, fn)).st_mtime)
                        except OSError:
                            pass
        except OSError:
            pass
        return f"{count}:{int(newest * 1000)}"

    def note_mtime(self, note_id: str) -> float:
        n = self.notes.get(note_id)
        try:
            return n.path.stat().st_mtime if n and n.path else 0.0
        except OSError:
            return 0.0

    def export_zip(self, target: str | Path, include_cache: bool = True) -> Path:
        """The whole notebook as a zip: notes, notebook.json and (optionally) the FLEx
        snapshots and audio clips, so it can be moved to another computer and opened there."""
        import zipfile
        target = Path(target)
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
            for root, dirs, files in os.walk(self.root):
                rel_root = Path(root).relative_to(self.root)
                if rel_root.parts and rel_root.parts[0] == PRIVATE_DIR:
                    if not include_cache or (len(rel_root.parts) > 1 and rel_root.parts[1] == "trash"):
                        dirs[:] = []
                        continue
                for fn in files:
                    if fn.endswith(".tmp"):
                        continue
                    full = Path(root) / fn
                    if full == target:
                        continue
                    z.write(full, str(rel_root / fn))
        return target

    # -- attachments -------------------------------------------------------------

    def save_attachment(self, name: str, data: bytes) -> Path:
        with self.lock:
            self.attachments_dir.mkdir(parents=True, exist_ok=True)
            safe = slugify(Path(name).stem, "image", 40)
            ext = Path(name).suffix.lower() or ".bin"
            target = self.attachments_dir / f"{safe}-{secrets.token_hex(3)}{ext}"
            with open(target, "wb") as fh:
                fh.write(data)
            return target


def _match_tab(nb: Notebook, wanted: str, tab_dir: str) -> bool:
    info = nb.tab_info(tab_dir) or {}
    w = wanted.casefold()
    return w in tab_dir.casefold() or w in str(info.get("name", "")).casefold()


def make_snippet(body: str, terms: list[str], strip_marks: bool, width: int = 70) -> tuple[str, list[list[int]]]:
    """A short window of the ORIGINAL body around the first hit, plus [start,end] mark ranges
    (snippet-relative) for every term occurrence inside the window."""
    text = excerpt(body, 100000) if body else ""
    if not text:
        return "", []
    norm, idx = normalize_with_map(text, strip_marks)
    nterms = [normalize(t, strip_marks) for t in terms if t.strip()]
    first = None
    for t in nterms:
        p = norm.find(t)
        if p >= 0 and (first is None or p < first):
            first = p
    if first is None:
        return text[: width * 2], []
    start_o = idx[first]
    lo = max(0, start_o - width)
    hi = min(len(text), start_o + width * 2)
    snippet = text[lo:hi]
    snorm, sidx = normalize_with_map(snippet, strip_marks)
    marks: list[list[int]] = []
    for t in nterms:
        p = snorm.find(t)
        while p >= 0 and t:
            s = sidx[p]
            e = sidx[min(p + len(t) - 1, len(sidx) - 1)] + 1
            marks.append([s, e])
            p = snorm.find(t, p + len(t))
    marks.sort()
    prefix = "…" if lo > 0 else ""
    suffix = "…" if hi < len(text) else ""
    if prefix:
        marks = [[a + 1, b + 1] for a, b in marks]
    return prefix + snippet + suffix, marks


def _title_from_filename(name: str) -> str:
    base = name[: -len(NOTE_SUFFIX)] if name.endswith(NOTE_SUFFIX) else name
    base = re.sub(r"--n_[0-9a-f]{10}$", "", base)
    return base


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)
