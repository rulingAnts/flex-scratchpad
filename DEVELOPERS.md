# FLEx Scratchpad — developer notes

## Architecture

```
┌─────────────────────────── pywebview window (WebView2 on Windows) ───────────────────────────┐
│  file:///…/flex_scratchpad/ui/index.html                                                      │
│  app.js (shell) · editor.js (blocks) · interlinear.js (FLEx rendering, styling, audio)        │
│  tables.js · charts.js · picker.js · markdown.js · flexref.js · api.js                        │
│                 window.pywebview.api.<method>(...)  →  Promise                                │
└──────────────────────────────────────────┬───────────────────────────────────────────────────┘
                                           │ js_api (JSON; one Python thread per call)
┌──────────────────────────────────────────▼───────────────────────────────────────────────────┐
│ api.Api ── notebook.Notebook (files + index, RLock)                                           │
│        └── flex.FlexService (RLock) ── backend: FlexiconBackend | FlextextBackend | DemoBackend│
│                                     ── cache.SnapshotCache (.scratchpad/flex-cache/<project>/) │
│                                     ── audio.cut_clip (wave → ffmpeg → UI capture)             │
│ FlexiconBackend → LcmWorker thread → flexicon.FLExProject (read-only) → FieldWorks LCM DLLs    │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

There is deliberately no network layer. The UI loads from the package's own files and every
call to Python is a pywebview `js_api` call (see `ui/js/api.js`). `ui/js/api.js` falls back to a
JavaScript mock with demo data when no bridge is present, so the page runs in any browser.

## Data flow for an embed

1. The note contains `{{flex:text <guid> seg=3-5 …}}` (a `flex` block on its own line, or an inline chip
   inside a line of text or a table cell).
2. `flexref.parse` → spec. `interlinear.render` asks `api.flex_get('text', guid, 3, 5)`.
3. `FlexService.get_object` tries the live backend (pages ≤ 60 segments), snapshots the result
   (`cache.merge_text` accumulates every range seen), and returns it with `cached: false`. If the
   backend is closed or fails, the snapshot comes back with `cached: true, liveError`.
4. `interlinear.renderText` lays out segments (word cells: txt / morph / mgls / cf / gls / pos;
   then free / literal / notes), applying `flexref.resolveStyles(spec, obj)` — an index keyed
   `segment|line|word` → `[{style, color, chars}]`, char ranges in grapheme clusters.
5. A click opens the style popover; `flexref.toggleStyle` mutates the spec; the editor writes
   `flexref.serialize(spec)` back into the block source (or the table cell) and autosaves.

## Exporting examples as a FLEx text

`Api.export_note_flextext(note_id, items, opts, path)` turns a note's text embeds (in note
order, from blocks, inline chips and table cells; the page collects them with
`FS.exporter.flextextItems`) into a `.flextext` that FieldWorks imports (File → Import → FLExText
Interlinear). The writer is `flex/flextext_writer.py`:

- one `<interlinear-text>` per baseline writing system (a FLEx text has exactly one), titled
  `<title> (<ws>)` when there are several; `opts.onlyWs` keeps one;
- one `<paragraph>` per example, one `<phrase>` per segment, `segnum` = paragraph.segment;
- every writing-system alternative of every string as its own `<item lang="…">` — the backends
  attach them under `*Alts` keys only when asked (`alts=True`), ordinary rendering never
  carries them;
- new GUIDs for text, paragraphs and phrases; word GUIDs kept (`opts.wordGuids`), morph `type`
  from the break characters, bare morph glosses (the break characters stay on the forms);
- a `note` item per phrase naming the source text, its FLEx number, the segment and text GUIDs,
  the embed's label and (`opts.includeLink`) the `flexscratchpad://note/<id>` link; the note's
  markdown as the text's `comment` when `opts.includeMarkdown`;
- audio (`opts.audio`): `clips` (default) writes one 16-bit mono WAV per timed line, named
  `<title>-<paragraph>.<segment>.wav`, into `opts.audioFolder` or `<title>-audio/` beside the
  file; each phrase points at its own `<media>` entry from 0 to its length. Choose the project's
  `LinkedFiles\AudioVisual` as the folder and the locations are written relative to
  `LinkedFiles` (`AudioVisual/x.wav`), the form FLEx stores; elsewhere they are full paths.
  `bundle` writes one `<title>.wav` — every clip in order with 600 ms gaps, offsets rewritten;
  `original` keeps the source recordings and offsets; `none` drops the timing.

`flexscratchpad://note/<id>` links (`links.py`): the scheme is registered per user on Windows
(HKCU, at start and from Settings), a second instance started with a URL writes it to
`open-request.txt` in the local data folder and exits, the running instance polls that file
and opens the note. No sockets, no server.

## The file format: Markdown with a declared extension vocabulary

Seth asked (2026-10-12) whether the raw format should be HTML under the hood, "tolerating and
auto-rendering markdown as well", for the things Markdown cannot say. The answer this app has
settled on is the other way round: **the file is Markdown, and every non-Markdown need gets one
small, named extension in a form a plain Markdown reader survives.** The current vocabulary:

| need | extension | what a plain reader sees |
|---|---|---|
| live FLEx objects | `{{flex:… }}` line or inline | a literal `{{…}}` |
| numbered, indented examples | `ex` and `indent=N` keys on the embed line | the same literal |
| table styling, widths, frozen panes | a `{table: …}` line after the table | a stray `{…}` line |
| merged cells | `span R.C: RxC` in that line; covered cells left empty | the grid, with gaps |
| line breaks in a cell | `<br>` (GFM already allows it) | a line break |
| charts | a ```chart fence | a code block |

Why not HTML storage: the editor's one invariant is that a block's `textContent` **is** the
source (decoration only wraps characters), which is what makes typing, undo, search, cloud
sync, exports and "readable without the app" all cheap. HTML as the base would move every one
of those onto a DOM-diffing editor and a sanitiser, for the sake of merged cells and the like
that the style line already covers. The rule for the next need is therefore: **add a key to the
vocabulary above** (and to `tables.parseStyle` / `flexref` / `markdown.js`), and make sure the
Markdown export degrades to something readable. If a need ever does not fit a line in the style
line, a raw HTML block passed through verbatim is the escape hatch — but it has not been
needed yet.

## Audio

`FlexService.ensure_clip(text, media, begin, end)` resolves the media file (LinkedFiles + URI,
then the remembered mapping for that media guid, then basename search in remembered folders),
cuts the clip into `.scratchpad/flex-cache/<project>/audio/<text>_<begin>-<end>.wav` (stdlib
`wave` for WAV, `ffmpeg` if present for anything else) and tells the UI where to play from. If
neither cutter can do it, the UI records the range once with `MediaRecorder` and stores it
through `audio_store_clip`. Playback is a plain `<audio src="file://…">` seeking to `begin` and
pausing at `end` (requestAnimationFrame tick, ±15 ms).

## Search

`Notebook` keeps two normalised blobs per note (NFKC+casefold, and NFKD with marks stripped) built
from title, body, tags, folder, tab and `extra_text(body)` — which `FlexService.searchable_text_for_body`
fills with the headwords, glosses, baselines and free translations of every embedded object's
snapshot. Query grammar: words (AND), `"phrases"`, `tag:x` / `#x`, `tab:x`, `folder:x`. Ranking:
title 10, tag 5, body 0.5 per hit (capped). Snippets map normalised hit offsets back to the
original text through a per-character index map so marks land on the real characters.

## The flexicon backend, honestly

`flex/lcm.py` was written from flexicon 4.12's source (`FLExProject.OpenProject`, the
`Texts/Paragraphs/Segments/WfiAnalyses/WfiMorphBundles/Senses/Examples/WritingSystems` operation
namespaces, `LexiconGet*`, `Object(guid)`, `BuildGotoURL`) and the LCM property names
(`SegmentsOS`, `AnalysesRS`, `MediaFilesOA.MediaURIsOC`, `BeginTimeOffset`, `MorphTypeRA`…), on a
machine without FieldWorks. Every access goes through `_t(fn, default)`, so a wrong property name
yields an empty string rather than an exception, and `_friendly()` maps flexicon's exceptions to
plain messages (`FP_FileLockedError` → the Sharing-tab remedy; `FP_MigrationRequired`; missing
module). First contact checklist on Windows:

```bat
flex-scratchpad --check
flex-scratchpad --list-projects
python -c "from flex_scratchpad.flex.lcm import FlexiconBackend as B; b=B(); print(b.open('MyProject')); print(b.list_texts()[:3]); print(b.search_entries('a')[:3]); b.close()"
```

Then compare a rendered text with FLEx's interlinear view and fix property names in
`_segment_dict` / `_word_dict` / `_entry_dict` as needed.

## Packaging

`build/flex-scratchpad.spec` is a PyInstaller `--onedir` build (onefile would make a bootloader
parent + child pair that is easy to orphan). flexicon/pythonnet are not bundled: they depend on
the installed FieldWorks. `python -m flex_scratchpad --check` tells a user what is missing.

## Tests

- `tests/test_*.py` — notebook, FLEx layer (model, flextext fixture, demo, cache, audio,
  service), Api surface.
- `tests/js/*.test.js` — the classic UI scripts loaded into a `vm` context (`tests/js/load.js`):
  markdown blocks/decoration, embed grammar + style resolution, table parsing, chart DSL.
- `tests/e2e/test_ui.py` — Playwright drives `index.html` as a `file://` page; a single exposed
  binding routes `window.pywebview.api` calls into the real `Api` on a temp notebook with the demo
  backend (exactly pywebview's contract, including `{message, name}` rejections). Covers picker
  insert, click-to-highlight writing the embed attributes, pasted FLEx links, typing flows and
  undo, table cell editing with an embed in a cell, charts, RTL rendering, audio seek/stop and
  clip caching, search/tags/find, and the no-Python mock mode.
