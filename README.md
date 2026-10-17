<img src="flex_scratchpad/ui/img/icon-128.png" width="96" height="96" alt="FLEx Scratchpad icon: a scratchpad page of IPA words (ʃə ŋɔ ʔa) glossed beneath, with a pencil" align="right">

# FLEx Scratchpad

A notebook for [FieldWorks Language Explorer](https://software.sil.org/fieldworks/) (FLEx).
Quick notes with tabs, folders and tags; tables and charts; and **live FLEx objects inside the
notes** — a lexical entry, or a range of interlinear text segments, rendered in place from the
project database and linked back to FLEx.

- **Reads the FLEx project directly** through [flexicon](https://github.com/MattGyverLee/flexicon)
  (the successor of flexlibs / flexlibs2): LCM via Python.NET, read-only. Nothing is written to
  the project.
- **Interlinear examples** show word, morphemes, morpheme glosses, word gloss, category and the
  free translation, with FLEx's own writing-system fonts and right-to-left scripts. Click a word
  to **highlight, bold, underline or colour** it — a word, a range of words, a few characters, a
  whole line, or every match of a string.
- **Audio**: a timed segment plays straight from the project's media file (`▶` on the segment,
  *Play 3–5* on a range); the clip is cached in the notebook so it keeps playing when the media
  isn't reachable. If FLEx's media file isn't found, *Browse…* for the real one.
- **Links both ways**: *Open in FLEx ↗* jumps to the object; FLEx's *Edit → Copy Location as
  Hyperlink* pasted into a note becomes a rendered embed or a chip.
- **Markdown**, shown with the markers kept faint (`**bold**` reads bold, the stars stay as a
  hint), checklists, quotes, code, images, `[[links to other notes]]`, `#tags`.
- **Tables** with line breaks in cells, interlinear examples in cells, and per-row/column styling
  (bold, alignment, width, colours, vernacular font, striped, borders).
- **Charts** (bar, stacked, horizontal, line, area, pie, donut) from a small readable block.
- **Search** the whole notebook, including the vernacular words and glosses of embedded FLEx
  objects; diacritics-insensitive; filters by tab, folder and tag; find-in-note.
- **Plain files**: the notebook is a folder of markdown files; tabs and folders are directories.
- **Attached files**: drop a file on a note (or 📎 Attach): a chip that opens it in its own program; web
  pages, PDFs, pictures, audio and video preview in the window. Copied into the notebook's
  `attachments/` folder, or linked where it is.
- **Backup & storage**: back the notebook up to a OneDrive, Google Drive or Dropbox folder (found for
  you), or to S3-compatible storage (Amazon S3, Cloudflare R2, Backblaze B2, Wasabi, MinIO…) through
  the bundled rclone, optionally encrypted; the keys live in the Windows Credential Manager. Every
  backup keeps dated older versions; see what the notebook and its backup take, and clean up.
  Readable without the app, syncable, git-friendly.

No web server, no cloud: a native window (pywebview / WebView2) over local HTML + JavaScript,
talking to Python through pywebview's exposed API only.

## Download (Windows)

**The easiest way: the Setup .exe or the portable zip from the
[latest release](https://github.com/rulingAnts/flex-scratchpad/releases)** (a pre-release for now).
Nothing else to install: Python, flexicon and ffmpeg are inside. It needs Windows 10/11 (64-bit),
FieldWorks 9 on the same computer to read a project, and the Edge WebView2 runtime (Windows 11 has
it; Setup says when it is missing). It isn't signed yet: on "Windows protected your PC" choose
**More info → Run anyway**. Setup installs per user (no administrator), a newer Setup upgrades in
place, and uninstalling keeps your notebooks. `FLEx Scratchpad.exe --selftest report.json` reports
what a copy can and cannot find. The user-facing page is [`docs/index.html`](docs/index.html).

## Install from source (Windows, with FieldWorks)

Requirements: Windows 10/11, FieldWorks 9.x installed, 64-bit Python 3.10–3.13 (match FieldWorks:
x64), the Edge WebView2 runtime (already on Windows 10/11). Installing from GitHub or a clone also
needs [Git for Windows](https://git-scm.com/download/win).

The repository is **https://github.com/rulingAnts/flex-scratchpad**. Until the current work is
merged into `main`, it lives on the branch **`claude/trusting-cori-k4jhvy`** — the commands below
name it; drop the `@…` / `--branch …` part once it is on `main`.

### A. Straight from GitHub (pip)

```bat
py -m pip install "flex-scratchpad[flex] @ git+https://github.com/rulingAnts/flex-scratchpad@claude/trusting-cori-k4jhvy"
flex-scratchpad --check        :: reports whether pywebview, pythonnet and flexicon import
flex-scratchpad --list-projects
flex-scratchpad
```

**Updating.** The version number does not change between commits, so `pip install --upgrade`
keeps the copy you already have. Close the app, then reinstall the app itself (its dependencies
stay as they are):

```bat
py -m pip install --force-reinstall --no-deps "flex-scratchpad[flex] @ git+https://github.com/rulingAnts/flex-scratchpad@claude/trusting-cori-k4jhvy"
flex-scratchpad --version      :: prints the build fingerprint, also shown in Settings
```

### B. From a clone (updates are a `git pull`)

```bat
git clone --branch claude/trusting-cori-k4jhvy https://github.com/rulingAnts/flex-scratchpad.git
cd flex-scratchpad
py -m pip install -e ".[flex]"
flex-scratchpad
```

`-e` installs the clone itself, so **updating is `git pull` in that folder** and restarting the
app — no reinstall. (`py -m flex_scratchpad` runs it too.)

### C. A wheel, for a laptop without internet

On a machine with internet and the **same Python version** as the field laptop, build the app's
wheel and download everything it needs into one folder:

```bat
py -m pip wheel --no-deps -w wheels "git+https://github.com/rulingAnts/flex-scratchpad@claude/trusting-cori-k4jhvy"
py -m pip download -d wheels "flex-scratchpad[flex] @ git+https://github.com/rulingAnts/flex-scratchpad@claude/trusting-cori-k4jhvy"
```

(From a clone, `py -m pip wheel --no-deps -w wheels .` builds the same wheel.) Copy the `wheels`
folder to the laptop and install from it alone:

```bat
py -m pip install --no-index --find-links wheels "flex-scratchpad[flex]"
```

To update, build a new wheel the same way and install it with `--force-reinstall --no-deps`.

### Which build is installed?

`flex-scratchpad --version` (and Settings) shows a build fingerprint computed from the installed
files: two installs of the same code show the same build, and any difference in the code shows a
different one. Start the app again after an update — if an older window is still open, starting
it only brings that window forward, and it says that a different build is installed.

On first run the notebook is created at `Documents\FLEx Scratchpad`. Open **Settings** (⚙, or the
FLEx pill at the bottom left), pick the FieldWorks project, **Connect**.

**If FLEx is open at the same time**, LCM needs the project shared: in FLEx, *Project Properties →
Sharing → "Share project contents with programs on this computer"*. Otherwise close FLEx while
the Scratchpad reads it (the app tells you which).

### Without FieldWorks (any OS)

`pip install -e .` and `python -m flex_scratchpad --demo` runs with a built-in demo project.
Settings also accepts a **`.flextext` export** as a fallback text source (texts only, no lexicon).
Rendered objects are cached in the notebook, so notes made on the Windows machine still display
elsewhere (marked *cached*).

## Using it

| Do | How |
|---|---|
| New note / tab / folder | **Ctrl+N**; the `+` next to *Tabs* / *Folders*; right-click a tab or folder for rename, colour, delete |
| Insert a FLEx object | **Ctrl+Shift+L** → search the lexicon or the texts → click the first and last segment → *Insert segments*; or paste a FLEx hyperlink (*Edit → Copy Location as Hyperlink* in FLEx) |
| Find a segment by its text | In the picker's text view, *find segment by text…* |
| Style words in an example | Click a word → Highlight / Bold / Underline / Italic / Strike / Colour; Shift+click another word for a range; *Characters* for part of a word; *match text* (then a colour or style) for every occurrence |
| Style part of a free translation | Drag across the words in the free (or literal) translation, release, and pick a colour or style; a plain click styles the whole line |
| Choose the lines shown | The `⋯` on an embed: Word, Morphemes, Morph glosses, Lex. entries, Word gloss, Category, Free, Literal, Notes; segment range |
| Play audio | `▶` beside a timed segment; *Play 3–5* on a range; loop and scrub in the transport strip |
| Table | *Table* button; click a cell to edit (**Tab** moves on, **Shift+Enter** breaks a line, **Enter** goes down); *Column ▾ / Row ▾ / Table ▾* for styling |
| Chart | *Chart* button; double-click the chart or use *Edit chart* |
| Search | The box at the top left (**Ctrl+Shift+F**); `tag:todo`, `tab:Grammar`, `"exact phrase"`; **Ctrl+F** finds in the open note |
| Tags | `+ tag` on the note, or type `#tag` anywhere in the text |
| Insert a block | Right-click an example, a table cell, or the space between blocks (or the ⋮ beside any block) → *Insert a new block*: paragraph, heading, list, checklist, quote, table, FLEx example or divider, above or below |
| A paste lands wrong | `flex-scratchpad --project NAME --locate clip` with the rows still copied writes `flex-scratchpad-locate.json`, which shows what the app read and what the project holds there |
| Folders | A folder shows the notes directly in it; tick *Show notes in subfolders* under the list title to see everything below it |
| Move a note | Drag it onto a tab or folder, or `⋯ → Move to…` |
| Collect examples for FLEx | `+ New ▾` → *New example collection*: a note that is only interlinear examples, numbered in order. Paste FLEx rows into its paste box, use *Add from FLEx…*, or choose *Add to an example collection…* on any example (its `⋯`, or *＋ Collection* on a chip's preview). Reorder with the arrows or the `⠿` grip |
| Sort a collection | *＋ Group…* adds a labelled block; ▸ / ▾ collapses it (or *Collapse all*); double-click its label to rename; drag examples onto it or use ↑ ↓. Groups are for sorting only and are not exported |
| Note on an example | ✎ beside the example in a collection. The note IS exported: FLEx shows it as a note on the example's first line |
| Export a FLEx text | Only an example collection exports: *Export as FLEx text…* at its top. An ordinary note's `⋯ → Collect the examples into a new collection…` copies its examples into one: the examples in the highlighted part of the note if you selected some, else all of them |
| Audio in the export | The export dialog's *Audio*: **one audio file for the text** (the default: every line's clip in order, a click at each join, as the text's media file) or **one small file per line**; either into a folder you choose — pick the project's `LinkedFiles\AudioVisual` and FLEx finds it on import |
| Audio in the export | The export dialog's *Audio*: **one audio file for the text** (the default: every line's clip in order, a click at each join, as the text's media file) or **one small file per line**; either into a folder you choose — pick the project's `LinkedFiles\AudioVisual` and FLEx finds it on import |

### What a note looks like on disk

```markdown
---
id: n_3f9a1c2b7d
title: Past tense -mo
tags: [grammar, todo]
created: 2026-10-12T09:30:00
updated: 2026-10-12T10:05:12
pinned: false
---
The suffix **-mo** marks past tense:

{{flex:text 9b1c2d3e-4f50-4a6b-8c7d-0e1f2a3b0001 seg=1-2 u=morph:"-mo" hl=ft:1}}

| Form | Gloss |
|---|---|
| kabir | dog |
{table: striped; col 1: bold}
```

On first start (and whenever the linked project cannot be opened) the app asks whether to link or
fix it; the FLEx pill at the bottom left explains the state and, when a project is open in FLEx
without sharing, shows a warning with the exact steps (Project Properties → Sharing).

Tables: click the strip above a column or left of a row to select it (drag or Shift-click for
several, the corner for the whole table); Ctrl+C / Ctrl+X / Delete act on the selection, and
Ctrl+V pastes a grid over the cells, or as new rows / columns when whole rows / columns are
selected (also in the menu: Paste rows above/below, Paste columns left/right). Right-click any cell for every command (insert/delete rows and columns, merge or unmerge
cells, freeze panes, split or merge tables, styles). Shift-click or drag across cells to select a
range and merge it. Columns resize by dragging; merged cells are kept as `span 2.1: 1x2` in the
style line and survive a paste from Excel, Word or a browser; `freeze rows 1; freeze cols 1` pins
panes. The bar under a table sticks to the bottom of the pane while the table is scrolled past it. Drag the
corner grip under a table to give it a frame of its own size (height and width) that scrolls inside;
scrolling fast through the note passes over the frame, pausing on it scrolls the frame.

Entry embeds choose their fields with `fields=cf,mt,gl,def,ex,tr,sub` and their senses with
`senses=1,2.1` (the ⋯ menu offers both); text embeds choose lines with `lines=` and are anchored to
their segments' GUIDs with `at=` so a renumbered text keeps the right segments.

The embed line is the whole contract: `{{flex:entry <guid>}}`, `{{flex:sense <guid>}}`,
`{{flex:text <guid> seg=3-5 lines=txt,morph,mgls,gls,pos,ft hl=3.2 b=3.1-3.4 u="ka-"}}`. Targets
are `[line:]segment[.word[:from-to]]` (words counted without punctuation, characters as grapheme
clusters) or a quoted string (`morph:"ka-"`, `*"ka-"` for every match); styles are `hl`, `b`, `u`,
`i`, `s`, `color`, with a colour in brackets (`hl[#fff2a8]=…`). You never have to type it — the
click popovers write it — but it is readable and diffable.

## Development

```sh
pip install -e ".[dev]"
python -m pytest tests --ignore=tests/e2e      # Python unit tests
node --test tests/js/*.test.js                 # UI logic (markdown, embed grammar, tables, charts)
python -m playwright install chromium
python -m pytest tests/e2e                     # end-to-end: Chromium on file://index.html with the
                                               # real Python Api bridged in — no server anywhere
python -m flex_scratchpad --demo               # the app with the demo project (needs pywebview)
```

Opening `flex_scratchpad/ui/index.html` straight in a browser runs the UI on an in-memory mock
with the demo data (regenerate it with `python tools/gen_demo_js.py` after editing `demo.py`).

See `DEVELOPERS.md` for the architecture and `CLAUDE.md` for the working rules of this repo.

⚠ **Status:** the flexicon/LCM backend (`flex_scratchpad/flex/lcm.py`) was written against
flexicon 4.12's API and the LCM model without a FieldWorks machine to run it on. Everything else
is exercised by the test suite; the first run against a real project is the step that still
needs a human with FieldWorks (`flex-scratchpad --check`, then connect in Settings).

## Licence

AGPL-3.0-or-later. flexicon is LGPL-2.1-or-later and is used as a library; it is not bundled.
