# FLEx Scratchpad — backlog

Things Seth has asked for that are not built yet, in his words where possible, so the shape is
not lost between sessions. Tracked in git, never served.

## Copy an example as FLEx TSV or langsci-gb4e LaTeX (Seth, 2026-10-12)

**FLEx TSV: done 2026-10-13** (⋯ → Copy as FLEx TSV, the ⎘ TSV button on the header and the
overlay; `interlinear.flexTsv`; what it writes is what `locate()` reads). LaTeX remains.

> *"I'd also like to be able to copy FLEx TSV or langsci-gb4e latex from a flex object without
> having to open FLEx. We'll have to fine tune how to work that exactly later. But I will want
> that feature for when my notes turn into paper details."*

Where it goes: the embed's ⋯ menu (and the overlay's bar) gets *Copy as → FLEx TSV / LaTeX
(langsci-gb4e)*. Both come straight from the object model the export already builds
(`ui/js/export.js` → `flexBlock`): one segment = one example, word cells = the aligned columns.

- **FLEx TSV**: the layout FLEx's own *Copy* of an interlinear selection produces — one line per
  interlinear row (Word / Morphemes / Lex. Gloss / Word Gloss / Word Cat. …), tab-separated,
  the free translation on its own line; only the lines the embed shows (`lines=`), in the embed's
  writing systems (`ws=`).
- **langsci-gb4e**: `\ea \label{…} \gll <words> \\ <glosses> \\ \glt `free' \z`, with
  `\textbf`/`\uline`/`\hl` for the embed's styles, `=` and `-` left as in the morph line; a
  `\ex`/`\xlist` wrapper when a range of segments is copied. Exact macros to be settled with
  Seth ("fine tune how to work that exactly later").

## Writing systems — remaining pieces

- Per-embed `ws=` exists (line → tag, title included). Still to do: remember the last choice
  per text as the default for the next embed of that text; a per-WS font/size override in
  Settings; an RTL layout for the app chrome.
- Rule (Seth, 2026-10-12): *"if a vernacular writing system is blank for a certain wordform, the
  fallback should be another vernacular writing system, not an analysis writing system or a
  different field."* `_vern_text` in `flex/lcm.py` does exactly that chain (selected WS → best
  vernacular → each vernacular WS); keep it that way.

## Reverse links (FLEx → note)

`flexscratchpad://note/<id>` registered per user, a second instance handing the URL to the
running one through a file in the app data folder (no sockets). **Done 2026-10-16**
(`links.py`): the flextext export writes the link into each phrase's Source note and the
text's source field, and "Copy link to this note" is on the note menu. Still open: inserting
such a link into a FLEx field from here (a write — shelved with the rest, see below).

## Several FLEx projects in one notebook (Seth, 2026-10-12)

> *"Is there any reason we couldn't connect multiple FLEx projects to one scratchpad (though I
> realize we'd only want to SEARCH one at a time)?"*

No fundamental one. GUIDs are globally unique, FLEx links already carry `database=`, and the
snapshot cache is already per project (`.scratchpad/flex-cache/<project>/`). What it takes:

- **Embed grammar:** an optional `project=<name>` key (round-trips through `spec.extra` today);
  absent means the notebook's default project. Inserts from the picker and pasted links write it
  when the object's project is not the default.
- **Backend:** keep ONE project open at a time (flexicon initialises the CLR once per process;
  opening two LcmCaches side by side is untested and the worker thread model assumes one).
  `flex_get` for another project renders from the snapshot with a *"from project X — open it to
  refresh"* affordance; opening is a few seconds and closes the current one. The picker searches
  whichever project is open, with a project switcher in its title bar.
- **Links:** `open_in_flex` already passes the project in the URL, so a link to a closed project
  still opens FLEx on the right object.
- **Settings:** `notebook.json` `flex.project` becomes a default plus a list of known projects.

## Getting the SELECTED object out of FLEx with precision (research, Seth, 2026-10-13)

> *"Is there ANY possible way for our app to inject a keyboard shortcut, context menu item, or
> otherwise that would pass the GUID of the currently selected item to our app (or to the
> clipboard so we can paste it in our app)? And with more precision than just the whole text?"*

What is known so far, to be verified on a Windows machine with FieldWorks installed:

- **What FLEx gives today.** *Edit → Copy Location as Hyperlink* puts the CURRENT RECORD on the
  clipboard: the entry in the Lexicon, the wordform in Word Analyses, the whole text in the
  interlinear views (an `StText`/`Text` guid, never a segment). Copying lines from the
  interlinear view gives tab-separated rows, which the app already resolves to the exact
  segment (`FlexService.locate`). Together they are already precise: text guid + lines.
- **Inside FLEx.** The menus and commands come from XML (`Language Explorer/Configuration/…`,
  xCore `Main.xml` in FW ≤ 9) but every command maps to a C# handler; there is no "run external
  program" command and no scripting hook. The supported extension point is a *Utility*
  (Tools → Utilities, an `IUtility` implementation in a DLL built against the FieldWorks
  assemblies) — a utility can read the current selection through the FLEx services and write to
  the clipboard, but it needs a compiled DLL per FW version and is invoked from a dialog, not a
  shortcut. Worth a prototype only if the clipboard route proves insufficient.
- **Outside FLEx (no FLEx change).** The app can register a global hotkey on Windows
  (`RegisterHotKey` via ctypes, no server, no extra dependency) and, when pressed with FLEx in
  front, drive FLEx through `SendInput`: Ctrl+C (the selected lines) then the *Edit* menu's
  *Copy Location as Hyperlink* item (Alt+E, its accelerator letter — FLEx has no default key for
  it), read both clipboards, and open the picker on the exact segment. Fragile across FLEx
  versions and keyboard layouts, but it needs nothing installed into FLEx. UI Automation cannot
  read the interlinear selection: the views are custom-drawn (RootSite), and expose no text
  pattern.
- **Reading FLEx's state from disk.** `Settings/…/db$local$Settings.xml` records the current
  record per tool, but only when the tool changes or FLEx exits — not live.

**Chosen (Seth, 2026-10-13: "I like your idea for the combination of copy location + copy text
and getting the exact item from there"). Design, to build when it comes up:**

1. `flex_scratchpad/hotkey.py` (Windows only, ctypes, no new dependency): a thread with
   `RegisterHotKey` + a message loop; default **Ctrl+Alt+F**, changeable in Settings; nothing is
   registered on other platforms or when the setting is off.
2. On the key, with FieldWorks in front (`GetForegroundWindow` title contains "FieldWorks"):
   - `SendInput` Ctrl+C, wait for the clipboard sequence number to change, read the text
     (the selected interlinear lines, or a headword / baseline fragment).
   - Open FLEx's Edit menu with Alt+E and pick *Copy Location as Hyperlink* — NOT by typing a
     letter (Cut / Copy / Copy Location… share one), but by walking the open menu with
     `GetMenu`/`GetMenuItemCount`/`GetMenuString` to find the item's position and sending that
     many Down presses + Enter; if the menu cannot be read, skip this step and rely on the text.
     Read the clipboard again: `silfw://…guid=<text or entry guid>`.
   - Restore the user's original clipboard contents afterwards.
3. Hand both to the app window (`window.evaluate_js`): `flex_resolve_link` narrows to the object
   (text / entry / wordform), `locate` finds the segment(s) inside THAT text (scored on the
   pasted lines); the existing chooser offers *Insert rendered / Insert link / Paste as text*,
   with the picker on the exact range. With no hyperlink the match runs across all texts and
   the chooser lists candidates when more than one text matches.
4. Nothing is installed into FLEx; FLEx versions and keyboard layouts are the risk, so every
   step degrades to the next weaker one and the worst case is "copy it by hand", which works
   today.

## The ONE write to a FLEx project: correcting a text's media source (Seth, 2026-10-13)

**SHELVED 2026-10-17 (Seth): "Read-only is good for this project."** FLEx Scratchpad writes nothing
to a FLEx project, and the site says so; `tests/test_read_only.py` fails the build if the code
gains a way to. What follows is kept only as the record of what such a write would take.

> *"Eventually, I'd like correcting the media source for a text (on the info tab) to be the ONE
> write operation our app can perform on the FLEx project. (At least until we figure out if and
> how to do the note link insertion, which we should do eventually.)"*

Today the app only remaps the file for itself (`media.byGuid` in `notebook.json`); FLEx keeps
pointing at the wrong path. The write would set `ICmMediaURI.MediaURI` on the text's
`MediaFilesOA` entry — the field FLEx shows on the text's *Info* tab — to the chosen file,
relative to the project's LinkedFiles folder when it is inside it (copying it there first is
FLEx's own convention), absolute otherwise. Constraints that make it safe to allow this single
exception to the read-only rule:

- `OpenProject(name, writeEnabled=True)` for that one call only, inside a `NonUndoableUnitOfWork`
  (flexicon's `UndoableUnitOfWork` helper), then back to read-only; refuse while FLEx holds the
  project unshared (the same lock that blocks reading).
- A confirmation that shows old → new path and the text's title; nothing else is ever written.
- Keep the notebook-side mapping as the fallback for projects the user cannot or does not want
  to change (another person's project, a read-only share).

**Note links (FLEx → note), later:** inserting a `flexscratchpad://note/<id>` link into a FLEx
note or field would be a second write and needs the reverse-link scheme (see above) first.

## Word export: IGT rendering compatible with the LingTeX Word project (Seth, 2026-10-13)

> *"Making sure our Microsoft Word exports use IGT rendering and styling compatible with our
> LingTeX Word project would be good. That's for later though."*

`docx_writer.py` builds examples as borderless tables (one row per interlinear line, one
column per word) with its own run formatting. To match the LingTeX Word project: use its
paragraph / character style NAMES (example number, vernacular, gloss, free translation, …)
so a document pasted into that project picks up the project's definitions, its numbering
convention for examples, and its tab-or-table choice for the aligned lines. Needs the
project's template (`.dotx`) or a sample `.docx` to read the style names and layout from.

## LaTeX export (Seth, 2026-10-13: "LaTeX exports also for later")

A whole-note export next to Markdown / HTML / DOCX / PDF: prose as plain LaTeX (emphasis,
lists, tables as `tabular`), examples as langsci-gb4e (`\\ea … \\gll … \\glt … \\z`, see the
copy-as-LaTeX item above — the two share one serializer), vernacular in the writing system's
font via `fontspec`. Exact packages and macros to be settled with Seth.

## Import .flextext and ELAN files as extra texts (Seth, 2026-10-13)

> *"the ability to import flextext and elan files, regardless of whether they're in the FLEx
> database (as long as they've got matching writing systems) and have them included in the list of
> texts you can pull examples from"*

The `.flextext` parser exists (`flex/flextext.py`, the fallback source). What this adds: a
notebook-level list of extra text files (`notebook.json` → `extraTexts: [paths]`, files copied
into `.scratchpad/texts/`), merged into the picker's text list and `all_baselines` beside the
project's texts, with a source badge; GUIDs come from the file (flextext) or are minted and kept
(ELAN). ELAN (`.eaf`): the reverse of flextext-editor's `seg-exports.js` — phrase tier → segments
with times, word/gloss tiers → words; writing systems matched by the tier's language or chosen on
import. Embeds keep working through `{{flex:text <guid> …}}`; "Open in FLEx" is hidden for them.
SFM / UFM (standard-format interlinear, Toolbox-style `\\tx \\mb \\gl \\ft`) later, by the same
route (Seth, 2026-10-13: "Or SFM/UFM eventually. Later.").

## Edit a table in Excel, round-trip in place (Seth, 2026-10-13, "a later feature")

> *"open a table in Excel and then when they save it the results update in place (and using an
> Excel template that has a macro that can paste FLEx TSV and render it in a code that lets our
> app know when the table is repainted in our app that they need to be processed just as if they
> had been pasted in the app directly)"*

Shape: "Open in Excel" on a table writes `.scratchpad/excel/<note>-<table>.xlsx` from the grid
(cells as text, embeds as their `{{flex:…}}` source, merged cells as merges) and opens it with
the OS; the app watches the file (the sync poller already watches the notebook) and on save reads
the sheet back into the table block, keeping the style line. The template's macro pastes FLEx TSV
into a cell as a marked block (e.g. a cell starting `⟦flex-tsv⟧` + the rows), and the read-back
hands such cells to `locate()` exactly as a paste in the app does, replacing them with the embed
it finds. Needs openpyxl or a minimal xlsx writer/reader (zip + XML — like `docx_writer.py`).


## Release: ship ffmpeg, or install it on first use (Seth, 2026-10-16)

> *"If we need ffmpeg, we need to bundle it when we distribute (or auto install it on first run
> of first use). That's a thing to remember later when we go to building a release."*

What needs it: cutting clips from anything but a plain PCM WAV (`flex/audio.py`: `cut_clip`,
`to_mono16`, `concat_clips`); the flextext export's per-line clips of MP3/M4A/FLAC sources; the
FLAC clip cache. Without it the WAV paths still work through the stdlib and the UI records
other formats while they play. Options for the PyInstaller build (`build/flex-scratchpad.spec`):
bundle a static `ffmpeg.exe` next to the exe (licence: LGPL build, keep the notice) and have
`find_ffmpeg` look beside `sys.executable` first; or offer `winget install Gyan.FFmpeg` /
a download into `%LOCALAPPDATA%\FLEx Scratchpad\ffmpeg` on first use, with the Settings field
already there for a custom path. Decide at release time; nothing in the code assumes either.


## Readable without the app: a plain-text copy of every FLEx object IN the note (Seth, 2026-10-17 — "near future … soon")

**DONE 2026-10-17** (`ui/js/flexcopy.js`; see CLAUDE.md "READABLE WITHOUT THE APP"). Kept below as the record of the decisions.

> *"Make sure that our FLEx links save cached interlinear text (and text reference) so that a
> markdown file IS actually readable elsewhere. So that it doesn't 100% require our app to make
> heads or tails out of (though it would be enclosed in brackets such that our app won't render
> literal tab separated text lines, but rather just save them on refresh so that markdown readers
> or text editors see meaningful data)."*

Today a note holds only `{{flex:text <guid> seg=3-5 …}}`; the words live in the snapshot cache
(`.scratchpad/flex-cache/`), which only the app reads. The idea: beside each object, the note keeps
a plain-text COPY: the text title and FLEx number (e.g. *The dog and the river 1.2*), its
`silfw://` link, and the interlinear lines (Word / Morphemes / Gloss / Free), so that a text editor,
GitHub, Obsidian or a Markdown export shows the example without the app. The app treats the copy as
OUTPUT ONLY: it never draws it and never reads it back (the embed stays the one source), and it
rewrites it whenever the object is fetched fresh from FLEx and the result has changed.

A sketch, to be settled by the questions below: a fenced block right after the embed,

    {{flex:text 9b1c… seg=3-4 at=… ex}}
    ```flex-copy
    The dog and the river 1.2 · silfw://localhost/link?…
    Haŋa       tiket   ka-sila-mo     pemu
    yesterday  child   3SG-see-PST    river
    ‘Yesterday the child saw the river.’
    ```

It is visible in renderers and editors, keeps its columns (monospace, padded with spaces; tabs do
not line up in most renderers), and is one unit the app can find, hide and replace.
`ui/js/flexref.js` would treat the block as part of the embed (hidden, carried along on drag, cut
and copy), and excerpts and search would skip it (search already reads the snapshot).

DECIDED (Seth, 2026-10-17):

1. **A ` ```flex-copy ` fence right after the embed**, and the app NEVER paints it: "the inverse of
   the old convention of putting JavaScript inside HTML comment tags so that older browsers
   wouldn't print it … here it's the newer, higher tech thing that needs to not render the
   backward-compatible bit". Only a fence whose info string is exactly `flex-copy` is hidden; any
   other code block a user types draws as usual. In the app the unit is the `{{flex …}}` object
   alone: the copy is hidden, carried with it (drag, cut, copy, delete, undo) and never edited
   by hand.
2. **One line inside a table cell (and inside a line of text):** the reference and the free
   translation. The convention FOLLOWS THE OBJECT: dragged out of a cell into a block of its own,
   it gets the full fence; dragged into a cell, the fence becomes the one-line form. ("Our app
   should be smart enough though that if we move it OUT of a table cell, then it should switch to
   the other convention. And vice versa.")
3. **Only the lines the example shows** (`lines=`).
4. **Entries too**, and both entries and IGT examples carry a Markdown link to their `silfw://`
   address, so a Markdown reader can open the object in FLEx. All of it is invisible in the app,
   which draws the `{{ }}` object instead.
5. **Written when the example has changed**, and when it moves into or out of a table (the form
   changes). Opening a note never rewrites it.

Design points that follow, to check when this is built:
- A link does not work inside a code fence (it is shown as text there), so the fenced unit is
  three parts: the embed, ONE reference line that is a Markdown link
  (`[The dog and the river 1.2](silfw://localhost/link?…)`), then the `flex-copy` fence with the
  aligned lines. The app hides the link line and the fence, and treats all three as one object.
- The one-line form (cells, running text) needs a marker the app can recognise and readers ignore,
  e.g. a link right after the embed whose title is `flex-copy`:
  `{{flex:text …}}[The dog and the river 1.2: ‘Yesterday the child saw the river.’](silfw://… "flex-copy")`.
  Pipes in a cell are escaped as usual.
- Entries: `[ka-sila (v) ‘see’](silfw://…)`, plus the senses on lines of their own in the fenced
  form.
- Highlights are not marked in the copy (plain text) unless asked for later.
- `flexref.js` stays the only parser (the embed grammar contract); the copy is written from the same
  object model as the TSV copy (`interlinear.flexTsv`) and the exports. Excerpts, search, the
  Markdown export and the TSV / LaTeX copies must not see the copy twice. The note's Markdown export
  could keep the copies as they are (they are what a reader without the app sees).

## Text Charts in notes (Seth, 2026-10-17 — "that's for later. Much later")

> *"Later on, I'll want to add the ability to pull in a Text Chart, part of a text chart (including
> the headers), a range of rows from a text chart, and styling for text chart markers (and also our
> own custom system of row and word level text chart markers or collapsible custom columns)."*

Not started. What FLEx holds (liblcm): a text's charts are `IDsConstChart` objects
(`LangProject.DiscourseDataOA.ChartsOC`, each `BasedOnRA` a text), with a column template
(`TemplateRA`, a CmPossibility tree — the headers and their groups) and `RowsOS` of `IConstChartRow`
(label, `CellsOS`: `ConstChartWordGroup` spanning analyses `BeginSegmentRA / BeginAnalysisIndex …`
like a text tag, `ConstChartMovedTextMarker`, `ConstChartClauseMarker`, `ConstChartTag` — the
markers). The text markup tags (done 2026-10-17: `tags` on a text, `ui/js/tagstyles.js`) are the
model to follow: read into plain dicts on the worker, a new embed kind (`{{flex:chart <guid>
rows=3-7 cols=…}}`) drawn as a table of word groups under the template's headers, the markers
styled through the same scoped rules (project / tab / folder / example), our own row- and
word-level markers and collapsible columns as additive keys on the embed. FDAT
(rulingAnts/fdat) already renders FLEx charts from the project XML and is the reference for the
layout.

## Dekereke objects in notes (Seth, 2026-10-17 — "near future")

> *"I'd also like our app to be able to have Dekereke objects (linked to Dekereke XML line/ref
> number, column(s), and mapped audio file(s), both baseline and suffixed). But that's a future
> feature."*

A third embed kind beside `{{flex:…}}` and `{{file …}}`, extended additively in flexref.js (the
embed grammar contract): something like `{{dek <xml ref> ref=0123 cols=Phonetic,Gloss "label"}}`
— the Dekereke XML database (a path, notebook-relative or linked, like attachments), the record's
line / Reference number, the column(s) shown. Python reads the XML (stdlib ElementTree, read-only,
as with FLEx), resolves the record's mapped audio: the BASELINE file and the SUFFIXED variants
(Dekereke's per-record audio naming: the sound-file field plus its suffixes, e.g. `0123.wav`,
`0123_frame.wav` — confirm the convention against a real database and its settings), each
playable from the chip/card, and snapshots the record into the cache like a FLEx object so a note
still reads when the database is elsewhere. Open questions for Seth before building: which
columns matter by default, how the suffix list is configured (per database or per notebook), and
whether a range of records (a word list) is one embed or many.
