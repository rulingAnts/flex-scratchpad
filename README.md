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
  hint) or hidden — then only the markup at the caret shows, the way a chat app does it —
  nested lists (Tab / Shift+Tab; a bullet per level, numbers 1. a. i.), checklists, quotes, code,
  images, `[[links to other notes]]`, `#tags`. A bar between blocks adds or removes one.
- **Tables** with line breaks in cells, interlinear examples in cells, and per-row/column styling
  (bold, alignment, width, colours, vernacular font, striped, borders).
- **Charts** (bar, stacked, horizontal, line, area, pie, donut) from a small readable block.
- **Search** the whole notebook, including the vernacular words and glosses of embedded FLEx
  objects; diacritics-insensitive; filters by tab, folder and tag; find-in-note.
- **Plain files**: the notebook is a folder of markdown files; tabs and folders are directories. Each FLEx example and entry is also written into the file as plain text, with a link that opens it in FLEx, so a note reads in any text editor or Markdown viewer; the app itself never shows that copy.
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
| A chart note | *+ New ▾ → New chart note…* (or a chart's `⋯` → *Open as a chart note…*): a note that is one text chart, with **your own columns** — a choice list shared by the whole notebook, free notes, or a *rule* that fills each row from its markers and columns — built in the column dialog's **Builder** (pick a marker, a column, a clause type, a word field; *is* / *contains* / *matches pattern*; a writing system; "in <column>"; the text to show and a row or cell style) or typed (`marker:Topic → Top [row hl#fde68a]; col:Subject[txt:/^ka-/i] → S; gls@fr:/dorm/ → sleep`): the word, gloss, morpheme form, morpheme gloss, category, lexeme form or free translation, as text or as a regular expression, in any writing system the chart carries, in one column or anywhere. A rule reads the chart itself, so a marker you have hidden still counts — and your styling of words, cells, rows and columns. Everything is saved in the note's file as tables and found by search |
| Search the charts | In the FLEx object dialog's *Text charts* tab, type a search: words, `col:Subject`, `marker:Topic` (`marker:*` any), `lex:kabir`, `gloss:dog`, `clause:dependent`, `moved`, `-marker:Topic` to exclude; any value may be a regular expression, `word:/^ka-/i`, `col:/^Post/ gloss:/river/`. The matching rows are listed: click one to insert it, *Insert all* for every one, *Column profile…* to see which columns a lexical item sits in, *Collect into a new collection…* for a collection of the rows that can take in new rows later (*⟳ Find new rows*) |
| Chart columns on an example | The `⋯` of an example → *Chart columns*: the columns its words sit in, in the text's charts, drawn like tags (and styled like them: `column:Nucleus/Subject` in any scope). A chart's `⋯` → *FLEx tags* shows the text's markup tags inside its cells; *Pivot: markers × columns…* counts rows by marker and column; an entry card's *▦ In charts* shows which columns the item sits in |
| Style chart markers | ⚑ on a chart: show, hide and style each marker for this chart, the note, a folder, the tab, the text or the whole notebook, or in a visual filter; *whole row* colours every row the marker is in |
| Insert a text chart | **Ctrl+Shift+L** → *Text charts* → pick the chart → click the first and last row → *Insert rows* (the column headings always come along), or *Whole chart*. Its `⋯` chooses the lines, the columns, how the free translations are spliced in (a row after each segment's rows, a Free column, a tip for the clicked cell, or hidden), and exports the chart as FLEx's chart XML or JSON. Click a word, a cell, a row label or a column heading to style it |
| Style words in an example | Click a word → Highlight / Bold / Underline / Italic / Strike / Colour; Shift+click another word for a range; *Characters* for part of a word; *match text* (then a colour or style) for every occurrence |
| Style part of a free translation | Drag across the words in the free (or literal) translation, release, and pick a colour or style; a plain click styles the whole line |
| Choose the lines shown | The `⋯` on an embed: Word, Morphemes, Morph glosses, Lex. entries, Word gloss, Category, Free, Literal, Notes; segment range |
| Play audio | `▶` beside a timed segment; *Play 3–5* on a range; loop and scrub in the transport strip |
| Table | *Table* button; click a cell to edit (**Tab** moves on, **Shift+Enter** breaks a line, **Enter** goes down); *Column ▾ / Row ▾ / Table ▾* for styling |
| Chart | *Chart* button; double-click the chart or use *Edit chart* |
| Search | The box at the top left (**Ctrl+Shift+F**); `tag:todo`, `tab:Grammar`, `"exact phrase"`; **Ctrl+F** finds in the open note |
| Links | **Ctrl+K** or the 🔗 button: the selected text becomes the link, an address on the clipboard fills in; with the caret in a link it edits or removes it. *Another note in this notebook* makes a `[[Note title]]` link. Click a link and a strip under it offers *Follow · Edit · Copy · Unlink*; Ctrl+click follows it at once |
| Keyboard shortcuts | **Ctrl+/** lists them all (also in Settings): Ctrl+B / I / E / Shift+X / Shift+H for bold, italic, code, strikethrough, highlight; Ctrl+Shift+7 / 8 / 9 for a numbered, bulleted list or checklist; Ctrl+Alt+0 plain text; Ctrl+Enter / Ctrl+Shift+Enter a paragraph below / above; Ctrl+D duplicate the block; F2 rename; Ctrl+Shift+N a new collection |
| Tags | `+ tag` on the note, or type `#tag` anywhere in the text |
| Headings | `#`…`######` or the toolbar's H ▾ (Ctrl+Alt+1…6); *Promote / Demote all headings* there (Ctrl+Alt+[ / ]) move every heading in the note, or in the selected blocks, one level, keeping their distances; ▾ in the margin collapses a section. The headings above the part of the note in view stay at the top of the window; their ▾ collapses that section in place and goes to the heading (switch it off in the H ▾ menu or Settings) |
| Insert a block | Right-click an example, a table cell, or the space between blocks (or the ⋮ beside any block) → *Insert a new block*: paragraph, heading, list, checklist, quote, table, FLEx example or divider, above or below |
| A paste lands wrong | `flex-scratchpad --project NAME --locate clip` with the rows still copied writes `flex-scratchpad-locate.json`, which shows what the app read and what the project holds there |
| Tags look wrong | `flex-scratchpad --project NAME --dump-tags` writes `flex-scratchpad-tags.json`: the tag list and the first tagged texts exactly as the project returns them. Send that file |
| A chart looks wrong | `flex-scratchpad --project NAME --dump-charts [TEXT]` writes `flex-scratchpad-charts.json`: every chart, the Chart Markers list, and the rows of one chart exactly as the project returns them — the fullest chart on TEXT, or add the template's name to choose (`--dump-charts "Siakai SVC"`). Send that file |
| Something else goes wrong | Run `flex-scratchpad -v` from a terminal (a pip install logs everything there by default): every call the page makes, every FLEx read, every file written, with times — copy the transcript. The same goes to `%LOCALAPPDATA%\FLEx Scratchpad\log\flex-scratchpad.log`, also for the installed program. `--devtools` turns the browser developer tools on (F12 in the app opens them in their own window) |
| The left pane | Each part (Tabs, Folders, Tags, FLEx tags) folds with a click on its heading and the dividers between them drag; headings always stay in view, so nothing is ever out of reach |
| Folders | A folder shows the notes directly in it; tick *Show notes in subfolders* under the list title to see everything below it |
| Move a note | Drag it onto a tab or folder, or `⋯ → Move to…` |
| Collect examples for FLEx | `+ New ▾` → *New example collection*: a note that is only interlinear examples, numbered in order. Paste FLEx rows into its paste box, use *Add from FLEx…*, or choose *Add to an example collection…* on any example (its `⋯`, or *＋ Collection* on a chip's preview). Reorder with the arrows or the `⠿` grip |
| Collect every line with a tag | `+ New ▾` → *New collection from tagged lines…* (or *Collect into a new collection…* on a tag in the picker's *FLEx tags*): tick FLEx text markup tags (a group's box takes every tag under it; a visual filter's tags can be ticked in one go) and every line in the project carrying one becomes an example. The rule stays with the collection: *⟳ Find new lines* later adds the matches that are not in it yet (lines you removed come back; keep them in a group instead), *Edit rule…* changes the tags |
| Between blocks | Rest the pointer in the gap between two blocks (or under the last) and a bar offers *+ Paragraph · + Example · + Table · + More ▾* and *− Above / − Below*; a − button asks twice ("Remove?") and the message after a removal has *Undo*. Switch the bar off in Settings if you never want it; a table's bar shows once you have clicked into the table, with *Delete row / column* in its *Row ▾ / Column ▾* menus |
| Sort a collection | *＋ Group…* adds a labelled block; ▸ / ▾ collapses it (or *Collapse all*); double-click its label to rename; drag examples onto it or use ↑ ↓. Groups are for sorting only and are not exported |
| Note on an example | ✎ beside the example in a collection. The note IS exported: FLEx shows it as a note on the example's first line |
| FLEx text markup tags | Tags from FieldWorks' Text Tagging view are drawn under the words of an example as bars — or on the text itself: brackets round the tagged words (`[` `]`, `⟨` `⟩`, `⌈` `⌉`…), a marker, a tinted tile or a border round the words and their lines, a colour, bold. Set per project, tab, folder or chosen examples (`⚑` on an example, or a selection); the most specific wins. **Visual filters** (⚑ in the rail's *FLEx tags*, Settings) are named sets of tag styles switched on and off together, like Logos's. The rail's *FLEx tags* lists the tags the tab's notes use: click one to see only those notes, with the examples that carry it marked and the others dimmed; `tagged:Topic` in the search box does the same, and the FLEx object dialog's *FLEx tags* finds every place a tag is used in the project |
| Export a note | The note's `⋯` → *Export*: **Markdown**, a **web page** (self-contained; with the recordings embedded as players if you say so — a ▶ per line, the playing line lit, a bar to pause and stop), **Word** (charts on landscape pages), **Excel** (the note, a sheet per chart with its rows flat for filtering, an Examples sheet with one row per line), **PDF** (saved straight away on Windows, else the print dialog's *Save as PDF*), a **slideshow** (one web page: a slide per heading, example, chart and table — arrow keys, T for contents, F full screen; the players ride along) and **PowerPoint** |
| Resize chart columns | Drag the right edge of a column heading (a wide chart scrolls sideways under its headings, which stay put while you scroll down); double-click the edge, or `⋯ → Reset column widths`, to let it size itself. The widths are kept in the note |
| What a Word export shows | An expanded example is a LingTeX-Word table (the add-in's own styles: *LingTeX Interlinear*, the tier styles, grammatical glosses in small capitals, Word's own (1) numbering, the free translation in quotes with a link to the line in FLEx), so a document with LingTeX-Word installed re-wraps it. A collapsed example, an inline chip or an object in a table cell becomes a link into FLEx: the text's abbreviation and line numbers |
| Play a chart | ▶ beside the first row of each line (and in the `#` corner for all of them): the line plays from the text's recording and the cells holding its words light up; the same in the web page and slideshow exports. ▶§ plays a whole sentence (the rows 4a, 4b, 4c of sentence 4), ▶¶ a whole paragraph |
| Chart columns | The row labels (with the ▶s) stay put while a wide chart scrolls sideways. A column heading's popover has *Hide this column*; the `⋯` menu's *Columns* brings columns back, *Hide empty columns* drops the ones with nothing in these rows, *Zoom* makes the chart larger or smaller, and *Layout → One column* (or the ▤ button) shows each row in one cell, every word group labelled with its column, so visual filters by column (`column:Nucleus/Subject`) and by marker take the place of the columns; ▦ brings the columns back. *Change the chart…* shows another of the project's charts with the same view settings |
| Custom columns' place | A chart note's custom column can sit left or right of the chart and be frozen (it stays put while the chart scrolls sideways): the heading's `⋯`, or the column dialog's *Place* |
| Chart structure as filters | ⚑ on a chart also lists its **header groups** (*All of Nucleus*: the group's columns styled as one box) and its **structure**: dependent, speech and song clauses (the whole row), the `[2a]` clause markers, and **moved text** — preposed or postposed word groups get a tint, border, brackets or colour of their own, the look of the column they came from or the one they sit in, and a label such as *‹‹ Subj*. A group heading's box switches everything under it on, off, or back to the mix it had |
| Style a column | ⚑ on a chart lists its columns with the markers and the text's tags: *Style ▾* on a column gives its cells a tint, a border, a colour, bold / italic / underline (brackets and the rest in the one-column view and on examples), for this chart, the note, a folder, the tab, the text, the whole notebook or a visual filter; the checkbox hides the column. A column heading's popover has *Style this column everywhere…* |
| Export a FLEx text | Only an example collection exports: *Export as FLEx text…* at its top. An ordinary note's `⋯ → Collect the examples into a new collection…` copies its examples into one: the examples in the highlighted part of the note if you selected some, else all of them |
| Audio in the export | The export dialog's *Audio*: **one audio file for the text** (the default: each example's audio in order, a click between examples, named like the .flextext and saved beside it) or **one small file per line**; or into a folder you choose — pick the project's `LinkedFiles\AudioVisual` and FLEx finds it on import. Examples from texts in different baseline writing systems become one .flextext each, with its own audio |
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

### FLEx text markup tags and visual filters — how they work

The tags come from FieldWorks' **Text Tagging** view: each is an item of the project's *Text
Markup Tags* list (which has groups — "Syntax", "Discourse", your own) placed over one or more
words of a text. FLEx Scratchpad reads them with the text and draws them in every example that
shows those words.

**What a tag can look like.** By default a tag is a small bar under the words it covers, in FLEx's
own colour or one from a palette, with its abbreviation on the first word. A *rule* can change
that for one tag, for every tag of a FLEx group (*All of "Syntax"*), or for all tags (*All tags*):

| the bar | the text itself |
|---|---|
| its colour and text colour; the abbreviation on or off; `bar: always / never` | brackets round the tagged words — `[ ]`, `( )`, `{ }`, `⟨ ⟩`, `⟦ ⟧`, `⌈ ⌉`, `⌊ ⌋`, `\| \|` — with the abbreviation on the closing one; a **highlight** marker over the word line; a **tile** (a tinted box, in the tag's colour or one of your own) or a **border** (solid, dashed, dotted or double, 1–6 px) round the words *and the glosses under them*; the words' colour; **B** / *I* / U |

A rule that styles the text hides the bar unless you ask for both; tags that overlap nest their
brackets and boxes. A rule can also just switch a tag **off** (or back **on**).

**Where a rule lives decides what it covers.** From the most specific to the broadest:

1. **one example** — `⚑` on the example, or select several examples and use *FLEx tag styles for
   the selected examples…*; written into the example itself (`tags=…` in its `{{flex …}}`)
2. **one note** — the ⚑ Filters button (which visual filters are on for this page)
3. **a folder** (right-click it), then its parent folders
4. **a tab** (right-click it)
5. **one FLEx text** — every example drawn from it, in whatever note it appears
6. **the visual filters that are on**, in their order
7. **the whole notebook** (Settings › FLEx text markup tags)

The `⚑` on any example is the one place to do all of this: *Changes apply to* chooses the scope —
this example, this note, its folder, its tab, its text, the whole notebook, or a visual filter —
and the toggles and styles below write there. *All rules for …* opens the full list of a scope.

The most specific place that says something about a tag wins; a place that says nothing about a
tag leaves it exactly as the broader places have it. *Shown or hidden* and *the look* are decided
separately, so a folder can turn a tag off that the project styles, and an example can turn it
back on without choosing a colour.

**Visual filters** (modelled on Logos's) are **named sets of rules you switch on and off as a
whole**, for example *Grammatical relations* (brackets round S, A and P) or *SVC types* (a tile
behind each serial verb construction, coloured by type). Set them up once — ⚑ Filters › *Set up
visual filters…*, or Settings — then turn any number of them on or off:

- **for one note** (⚑ Filters › *This note*): the page keeps its own choice; *this note only ↺*
  goes back to the default;
- **everywhere** (⚑ Filters › *Everywhere*): the default for every note; a tab or folder can
  still differ (its tag-styles dialog has a *Visual filters here* section), and so can an example.

A filter starts **empty**; add the tags (or groups) it should style one at a time with *+ Add a
tag…*. **A tag you have not added to a filter is not affected by that filter at all** — not shown,
not hidden, not restyled. When several filters are on and more than one styles the same tag, the
one higher in the list decides; a note's, folder's, tab's or example's own rules win over every
filter.

**Finding things by tag.** The rail's **FLEx tags** lists the tags the notes of the tab use; click
one to see only those notes, with the examples that carry the tag marked and the others dimmed
(▲ ▼ step through them). `tagged:Topic` in the search box does the same across the notebook, and
the FLEx object dialog's *FLEx tags* lists every place a tag is used in the project, ready to
insert.

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
