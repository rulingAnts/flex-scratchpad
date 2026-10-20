# FLEx Scratchpad — backlog

Things Seth has asked for that are not built yet, in his words where possible, so the shape is
not lost between sessions. Tracked in git, never served.

**Where people can see what is planned (2026-10-20):** every item below that is still open is also
a GitHub issue labelled `planned` —
https://github.com/rulingAnts/flex-scratchpad/issues?q=is%3Aissue+is%3Aopen+label%3Aplanned — the
issue is the short public statement, this file holds the design notes behind it. When an item ships,
close its issue in the same commit's message (`Closes #n`) and strike it here. A GitHub Project in
its *Roadmap* layout can be made from those issues in the repository's Projects tab (it cannot be
created from the API this session has), if a timeline view is ever wanted; the labelled issues are
the source either way.

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

**2026-10-20 (Seth): the formats, and XLingPaper, and copying.** *"We also want LaTeX export using
langsci-gb4e or expex or langsci or mit interlinear formats. Save that feature for later. Also
XLingPaper exports can be saved for later. (And copy to clipboard for either of those, including
highlighting an area that may or may not include some combination of text, table rows, and FLEx
objects of various types). That's for the future though."*

- **LaTeX, four interlinear dialects, chosen in the export dialog and remembered:**
  `langsci-gb4e` (`\ea … \gll … \glt … \z`, the Language Science Press house style),
  `expex` (`\ex \begingl \gla … // \glb … // \glft … // \endgl \xe`), `langsci` (langsci-gb4e
  as the langsci class loads it, with `\langinfo`), `mit` (the `gb4e`/`cgloss4e`-shaped
  `\exg.` of the MIT dissertation style). One serializer over the export model
  (`FS.exporter.buildDoc`), a table of macros per dialect; the prose as plain LaTeX, tables as
  `tabular`/`longtable`, headings as sections, the user's highlight / bold / underline / colour on
  words as `\hl` / `\textbf` / `\uline` / `\textcolor` (packages listed in the preamble it
  writes), charts as `longtable` with a `\multicolumn` header row per group, vernacular in the
  writing system's font with `fontspec` (XeLaTeX / LuaLaTeX). A `.tex` next to the note, or a
  folder with the audio clips when "with audio" is on (as `\href` links — LaTeX has no player).
- **XLingPaper** (SIL's XML for linguistics papers): `<example>` / `<interlinear>` /
  `<lineGroup>` / `<line>` / `<wrd>` with `<langData lang>` and `<gloss lang>` per writing system,
  `<free>`, sections for headings, `<table>` for tables and charts, the FLEx link as a comment;
  languages declared once at the top from the writing systems used. Validated against the
  XLingPaper DTD in a test the way the .flextext export is against FieldWorks' XSD.
- **Copy to the clipboard in either format** for the highlighted part of a note — a
  cross-block selection or a selection in one block that may hold text, table rows and FLEx
  objects of any kind (examples, entries, charts, chips) — from the note menu (*Copy as →
  LaTeX (dialect) / XLingPaper*) and the editor's context menu: `highlightedSource()` gives the
  markdown, the same serializer renders only that; a single example's ⋯ menu offers it too
  (the copy-as-LaTeX item above).

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

## Examples from FlexText Editor files, until FLEx has the text (Seth, 2026-10-18 — "to do soon")

> *"I'd like to add a feature to copy examples from FLExText Editor apps (including text
> title/flextext file name, which will get added to our text corpus audio segment timing and audio
> file name, which we can browse for). Also, I'd like a way for it to recognize when that text has
> been imported into FLEx and no longer needs to be kept as a separate flextext file embedded in
> our notebook."*

The situation: a text is transcribed, glossed and time-aligned in FlexText Editor (or the Audio
Segmenter / Recorder) days or weeks before anyone imports it into FieldWorks. Its examples should
be quotable in notes NOW, from the `.flextext` the editor saved, with the audio; and once the text
is in FLEx the notebook should notice, switch the examples over to the project and let go of its
private copy. The ELAN / SFM half of the older "Import .flextext and ELAN files as extra texts"
entry above stays separate; this one is the FlexText-Editor path, which has the most to gain.

**What the editor hands us** (read 2026-10-18 in flextext-editor's `docs/js/flextext.js`,
`serializeFlextext`, and `app.js`):
- The file is named after the title (`sanitizeBase(title) + '.flextext'`, app.js ~5929) and the
  recording is paired with it BY BASENAME (`satBase`, app.js ~9008) — so "the flextext file name"
  Seth mentions is also how we find the audio, and the title is `<item type="title">`.
- `<interlinear-text>` carries `doc.textAttrs` — a `guid` ONLY when the document came out of FLEx
  (an authored text has no text GUID); `<paragraph guid>` always; `<phrase>` keeps `seg.attrs`
  (a GUID only for imported phrases) plus `begin-time-offset` / `end-time-offset` and `media-file`
  → the `<media-files><media guid location="<audio name>"/>` block the editor mints; `<word guid>`.
- No clipboard format exists: the editor offers no "copy example", and a web app cannot hand us a
  file path. So "copy examples from the editor" = drop / browse the `.flextext` (and its audio)
  into the notebook, then pick lines from it exactly like a FLEx text. (A real copy-paste from the
  editor's page would need a text format we define on both sides — a `flextext-editor/` item in
  its CLAUDE.md later, not a blocker: the file route gives everything, timing included.)

**Design**
1. **A corpus of embedded texts** in the notebook: `<notebook>/texts/<base>/` holding the
   `.flextext` as dropped, the audio beside it (copied by default, linked on request — the same
   choice as attachments; "browse for it" when the basename pairing finds nothing), and
   `texts.json` (or front matter in a `<base>.md` note card) with: title, the text GUID (from the
   file, or MINTED and WRITTEN BACK into our copy of the file as `<interlinear-text guid>` so the
   notes' `{{flex:text <guid>}}` are stable and FLEx will keep it on import), segment GUIDs (same:
   minted into our copy when the phrases have none — the importer reuses a phrase GUID when the
   project has it and creates the segment WITH it when not, `BIRDInterlinearImporter.cs` ~108–120
   / ~280), the audio file, when it was added, `inFlex: null | {project, seenAt}`.
2. **A composite FLEx source.** `FlexService` today opens ONE backend (`lcm` | `flextext` | `demo`).
   The corpus becomes a second, always-on backend layered under the project: `get_object('text',
   guid)` asks the project first, then the corpus (`FlextextBackend` over the folder's files —
   `flex/flextext.py` already parses media, offsets, alternatives); the picker's Texts tab lists
   corpus texts with a badge ("from FlexText Editor · not in FLEx yet"); `all_baselines` /
   `locate` include them so pasted rows from the editor's preview land; `texts_used`, snapshots,
   the clip cutter and the `.flextext` export all work unchanged because they see plain text
   dicts. "Open in FLEx ↗" is hidden for a corpus text until it is in FLEx.
3. **Audio & timing**: the phrases' offsets drive ▶ and the clips as now (the fallback reader
   already fills `begin/end/media`); the media record resolves to the file in the text's folder.
   A text whose audio is missing shows the existing "media file not found — Browse…" affordance,
   and the chosen file is copied into the folder.
4. **Recognising the import.** On project open, after "Refresh all", and when a corpus text is
   drawn: ask the project for the text GUID (`Object(guid)` → an `IText`). Found ⇒ mark
   `inFlex = {project, seenAt}`, redraw the examples from the project (tracking.py's ledger maps
   the segments: same GUIDs when the import kept them, else "found again by TEXT"), and show a
   one-line notice on the text's card and in the picker: "This text is now in FLEx (imported
   <date>). Keep the embedded copy? [Move to trash] [Keep]". Nothing is deleted on its own — the
   copy goes to `.scratchpad/trash/` like a note. Fallback when the GUID was not kept (a text
   re-created rather than imported): a title + first-baseline match offered as "This looks like
   ‘<title>’ in FLEx — link them?", written as `inFlex.guid` so later lookups go straight there.
   ⚠ Verify on a real project: whether FLEx's import keeps the `<interlinear-text guid>` for a NEW
   text (the importer merges into an existing text by GUID, `MergeTextWithBIRDDoc`; what creates
   the `IText` for a new one lives in the caller — read `LinguaLinksImport.ImportInterlinear` in
   `Src/LexText/Interlinear/` before relying on it) and whether phrase GUIDs survive.
5. **UI**: drop a `.flextext` (and its `.wav` / `.mp3`) on the note or the rail → "Add to the
   notebook's texts" (vs. attach as a file); Settings › Texts (the corpus list: title, lines, audio
   ✓/✗ Browse…, "in FLEx since …", Remove); the picker's Texts tab shows them; a text card note
   (`kind: text`?) is optional — the folder is enough.
6. **Tests**: a fixture `.flextext` written by the editor's own `serializeFlextext` (run in node, as
   the Segmenter cross-check does) with timing and a `media-files` block; e2e: drop it, insert a
   line, play its clip, "import" it into the demo backend (a test hook that adds the text to the
   demo project under the same GUID) and see the notice + the switch-over.

**Open questions for Seth**: copy the audio into the notebook (safe, bigger backups) or link it by
default? Should a corpus text be exportable again (it is a source now, so the `.flextext` export
of a collection quoting it just works)? Several notebooks sharing one corpus folder — later.

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

## Text Charts in notes (Seth, 2026-10-17 — "that's for later. Much later"; moved up 2026-10-18)

**Phase 1 shipped 2026-10-18** (CLAUDE.md › TEXT CHARTS): the reader, `{{flex:chart …}}` with rows /
columns / lines / free translations / styles, the renderer with headings, the readable copy, the
HTML / Word exports, FLEx's chart XML + JSON, `--dump-charts`, `marker:` search. Still to build, in
order (Seth, 2026-10-18, "go ahead and start building all this"):

1. ~~A chart note type~~ — DONE 2026-10-18 (CLAUDE.md › CHART NOTES).
2. ~~Custom columns~~ — DONE 2026-10-18 (list / notes / rule columns, project-wide lists, rules
   with row styles; since the same day the columns and row colours are in every export — HTML,
   Word, Excel, PDF, slides, PowerPoint). Still open: the custom columns in the TSV copy; counts in
   rule outputs; filtering the rows by a rule.
3. ~~Visual filters on chart markers~~ — DONE 2026-10-18 (marker rules with `row`). Still open:
   pseudo-markers (clause:dependent, moved:preposed) as filter targets.
4. ~~Search and collect~~ — DONE 2026-10-18 (`chart_search`, the column profile, chart collections
   with Find new rows). Still open: lexeme / sense GUIDs in the index (the search is by form and
   gloss text today); the profile on the entry card; filter-in-place in a chart note (rows by
   marker / column content / clause type, fold column groups — chart order always kept; "group by
   marker" as a compiled view, never a sort; hide EMPTY columns is done, 2026-10-18); pivots
   (marker × column, category × column) to a table block or CSV.
7. Done 2026-10-18 (CLAUDE.md › TEXT CHARTS): frozen row labels and frozen / left-or-right custom
   columns, hide a column from its heading, hide empty columns, zoom, the one-column layout with
   column labels and column / marker visual filters, ▶§ / ▶¶, boundaries under the free row,
   "Change the chart…". Still open from that round: the one-column layout in the Word / Excel /
   PowerPoint writers keeps the column labels only as the plain `‹abbr›` text of the TSV copy (the
   HTML and the page draw them); a frozen column in the exports means nothing (print has no
   scrolling); zoom is a view setting and is not exported; a paragraph ▶¶ needs FLEx's end-paragraph
   flags on the rows (a chart without them has only ▶§).
8. Done 2026-10-19: column styles from the ⚑ popover, header groups as one unit, the chart's
   structure (clause types, [2a] markers, moved text with ms / ml) as filter targets, the group
   on/off/previous box. Still open: the moved-text look in the exports (the page and Word show the
   ‹‹ marker and the column tint, not the moved group's own look or label).
9. A PARAGRAPH ANALYSIS COLUMN (Seth, 2026-10-19, "soon"): a custom column of a chart note that
   draws a horizontal, right-angle tree over the rows — its terminal branches facing inward toward
   the chart lines — from a grouping the user builds (which rows form a unit, which units a larger
   one, labelled); the paragraph engine in flextext-editor (`paragraph-model.js`, the `.fxpa` file)
   is the model for the data; drawn as an SVG in a frozen column, exported as a picture.
5. ~~Text markup tags inside chart cells, and chart columns on examples~~ — DONE 2026-10-18 (the
   `cols` line turns the text's chart spans into column tags; `lines=…,tag` on a chart; the pivot;
   the entry card's profile). Still open: choosing ONE template / chart when a text has several
   (every chart's spans are drawn today); the pivot by category × column.
6. The chart XML re-import belongs in flexicon (`plans/flexicon-requests.md` §4).

Original note:

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

## Exports (Seth, 2026-10-18 — shipped the same day: HTML with embedded audio, Word, Excel, PDF, slideshow, PowerPoint)

Open after the first build (CLAUDE.md › EXPORTS):

- **The direct PDF on Windows** (`pdf_print.py`, WebView2's `PrintToPdfAsync` through a hidden
  pywebview window) has not run on a real machine; the print dialog is the fallback. When it works,
  consider a page-size / margin choice in the dialog, and headers / footers (note title, page n).
- **PowerPoint audio**: the clips could be embedded as PowerPoint media (a `p:pic` with
  `a:audioFile`, a media relationship and a `p:timing` tree); the slideshow page carries them today.
- **Nested examples in table cells** are plain text in Excel and PowerPoint (their text; the HTML
  and Word exports draw them).
- **An export settings dialog** (which lines, fonts, paper size, "one example per page", a cover
  page) instead of the one audio question; remember the last choices.
- **Export a folder or a tab** as one document / deck / workbook (today: one note at a time; the
  notebook zip holds everything).
- **Print preview and print ranges** (Seth, 2026-10-18: "We may need some advanced print
  preview/print range editing later for the pretty export to PDF or DOCX. But later."): a preview
  of the pages before the PDF / Word export, choosing the blocks or the page range, page breaks
  by hand, a chart's columns split over pages.
- **LingTeX-Word parity in the Word export**: our tables carry the add-in's styles and shape (CLAUDE.md
  › EXPORTS); still to do when the add-in's repo settles: the document variables it reads its
  settings from (number hang, gaps), the `LingTeX Left/Shared Boundary` character styles on
  morpheme boundaries (ours are word-aligned, so no boundary is split), a column per MORPHEME
  when the Morphemes line is shown (LingTeX's "a column is an alignment slot"), and charts in the
  same style family. The reference clone is read-only: `/home/user/rulingants/lingtex-tools`.
- **The slideshow's speaker notes** (a note's `> quote` block under an example as the presenter's
  note; `S` to show them) and a "section" slide per H1 with its sub-headings as an agenda.

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


## Known issue: one short example keeps slipping off its lines (Seth, 2026-10-20 — "to look into later, not to fix now")

> *"sometimes shorter examples continuously misalign with their original source and require
> re-pointing every time I visit them."* — *"One example in particular."*

Not reproduced here yet. What to collect when it is looked at, from that one example:

1. Its embed source before and after a visit (⋯ → Edit source): does it carry `at=` anchors, and
   do they change? What does the "lines changed in FLEx" message under it say (`obj.track.change`:
   moved / reshaped / found / lost, and `how`)?
2. The text's ledger, `ledger-<text guid>.json` in the snapshot folder
   (`<notebook>/.scratchpad/flex-cache/<project>/`), and `flex-scratchpad --project NAME --dump "TITLE"
   --seg <its numbers>` for the lines it should show.

Where to look first (`flex/tracking.py`): a SHORT line is the weak case of every fallback — when
its anchors are not in the index (a re-imported text, a rebuilt paragraph, an embed written with
`seg=` only), `track()` falls back to finding it by TEXT with `difflib` at `FIND_MIN` 0.6 "nearest
the old place", and a line of two or three words clears 0.6 against several other lines; each visit
then re-finds it, possibly somewhere else, and rewrites `seg=` / `at=` (so it "needs re-pointing
every time"). Likely fixes: require a higher ratio for short lines (or an exact word match), prefer
the old numbers when the text at them is a near match, and never rewrite the embed from a text
match alone without saying so — and stop re-finding once the user has re-pointed it (the new
anchors must be written and then win). Also check `blankSeg` / `is_blank_segment`: an empty FLEx
segment counted by one side and not the other shifts every `seg=` after it by one.

## Known issue elsewhere: FieldWorks doubles the morph bundle of a two-language-glossed word on import (Seth, 2026-10-19)

Seen on texts imported from FlexText Editor (`Tosokai`: every word; `Wahuka Arsen incident`: a few): the
Morphemes line shows the word twice (`budu budu`) with `*** ***` under it. Not the editor's data and not
this app (read-only): FieldWorks' `BIRDInterlinearImporter.UpgradeToWordGloss` creates "a single morpheme
for the word" when the word has no `<morphemes>` block — INSIDE its loop over the word's `gls` items, so a
word glossed in English and Indonesian gets two identical, sense-less bundles on one analysis. Such texts
were never morpheme-glossed, so nothing is lost: one bundle too many per word.
- `flex-scratchpad --project NAME --doubled-morphs` (lcm `explain_doubled_bundles`, `model.doubled_bundles`)
  lists them with their uses; the fix is in FLEx's Word Analyses (or a FLExTools script that removes the
  duplicate bundles), never here.
- DONE 2026-10-20 on fau-iya-flex by a FLExTools module (`RemoveDoubledMorphBundles.py`, kept in the session's
  scratchpad): 5833 analyses checked, 174 bundles removed, `hodidi` / `bedidide` (genuinely repeated morphs)
  skipped; a byte-verified copy of the project folder taken first. Lessons for the next FLExTools script:
  `cache.ServiceLocator.GetService(IRepo)` (pythonnet cannot resolve `GetInstance<T>()`), and NO unit of work of
  its own (FLExTools / the MCP runner hold a session-long one: "Nested tasks are not supported").
- FlexText Editor side (to look into later, Seth: "a possible bug known issue"): its export writes every
  gloss language it holds (`w.gls` + the preserved other-language `gls` items) and no `<morphemes>`, which is
  correct .flextext — the importer is at fault. Options if it keeps hurting: a note in the editor's import
  guide, or an FLEx issue (sillsdev/FieldWorks) pointing at the loop.
