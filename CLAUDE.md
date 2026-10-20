# FLEx Scratchpad — repo guide for Claude / LLMs

A Windows notebook app for FieldWorks: notes (markdown files in folders) that embed live FLEx
objects — lexical entries and interlinear text segments — read directly from the project through
**flexicon** (PyPI `pyflexicon`, `import flexicon`; the successor of flexlibs / flexlibs2; LCM via
Python.NET). Python owns the data; the UI is HTML + JavaScript in a **pywebview** window.
Built 2026-10-12 with Seth; the decisions below are his.

## 🚩 Rules that shape everything

- **NO HTTP SERVER. EVER.** (Seth, 2026-10-12: *"That triggers anti-malware software."*) Not a
  loopback server, not pywebview's `http_server=True`, not a dev server. The page is a `file://`
  document and the only bridge is pywebview's `js_api` (`window.pywebview.api.<method>()`). The
  Playwright tests honour this too: `tests/e2e/bridge.py` exposes a binding into the real `Api`.
  Consequences: classic `<script>` files only (no ES modules, no `fetch`, no workers on file://),
  `url=app.ui_url()` — a `file://` URL — on `create_window`, never `html=` and NEVER A PLAIN PATH:
  pywebview starts its built-in HTTP server on 127.0.0.1 for any url that is not http(s):// or
  file://. Until 2026-10-16 the app passed a plain path, so that server ran on Windows, and the
  persistent WebView2 profile cached its responses: a reinstalled app kept showing its old page.
  `webview.start(..., http_server=False)` says it too; `tests/test_app_url.py` guards both.
  Media and images are loaded as `file://` URLs.
- **THE PAGE NEVER STANDS IN FOR THE APP** (Seth, 2026-10-19: "AAUUHG!! My data's gone" — the newest wheel came up on the page's
  in-browser demo, "Kalu Demo" and nothing else, once; the next start was fine). pywebview injects `window.pywebview` only
  AFTER the page has loaded and fills `api` a moment later, on a thread; api.js used to switch to `FS.mockApi()` when no
  `window.pywebview` existed 600 ms after load, or when it stayed empty for 15 s — a start-up race on a slow machine, or
  a failure of pywebview's api walk, both looked like an empty demo notebook. Now: a hosted page is known from
  `window.chrome.webview` / `window.webkit.messageHandlers` from the first script on; there the page WAITS (`showWait`:
  the `#bridge-wait` screen with the log path and a Reload button, an automatic reload after 45 s, twice at most,
  `sessionStorage fs:bridgeReloads`), and the mock is for a plain browser only. Python: `app.check_bridge` (on `loaded`)
  asks the page whether `init` arrived and logs `bridge: …` with `bridge_check.report(api)` — pywebview's own walk of
  the Api (`dir()`, every public bound method's `getfullargspec`, recursion into public non-callable attributes; ONE
  attribute that raises leaves the page with NO api), so never give `Api` a public attribute or property;
  `log.adopt_logger("pywebview")` puts pywebview's own log lines in our log. `tests/test_bridge.py` and the e2e
  `test_inside_the_app_the_page_waits_for_the_api…` keep all of it.
- **FLEx is read directly, read-only.** `OpenProject(name, writeEnabled=False)`. The app never
  writes to a project, and none is planned (Seth, 2026-10-17: "Read-only is good for this
  project" — the media-source correction once planned is SHELVED in `plans/BACKLOG.md`); the site
  promises it to users, and `tests/test_read_only.py` fails on any write access in the code
  (`writeEnabled=True`, a unit of work, an undo task, a save). The only files written are the
  notebook's own and the exports the user saves (a `.flextext` is a NEW text with new GUIDs,
  imported by the user; its audio may go into LinkedFiles only when the user chooses that folder).
  The `.flextext` file source is a *fallback* (texts only), the demo is for
  tests; LCM is the product.
- **One LCM thread.** pywebview calls `js_api` methods on arbitrary threads and LCM is not
  thread-safe, so `flex/lcm.py` runs every flexicon call on its single `LcmWorker` and returns
  plain dicts. **No .NET object may leave that thread.**
- **The notebook is files.** `<notebook>/<Tab>/<Folder>/<slug>--<id>.md` with a small front
  matter; `notebook.json` for tabs/tags/FLEx settings; `.scratchpad/` for cache, trash,
  attachments. Human-readable without the app; nothing is ever destroyed (delete = trash).
- **Unicode and RTL are first-class.** UTF-8 everywhere, Unicode kept in filenames, `dir="auto"`
  on text, `dir="rtl"` + the WS font on interlinear rows, character ranges count grapheme
  clusters (`Intl.Segmenter`), search normalises NFKC/casefold with optional mark stripping.
  Per-WS font overrides and an RTL app chrome are future work.

## Layout

```
flex_scratchpad/
  __main__.py   CLI (--demo, --notebook, --check, --list-projects)      app.py  the pywebview window
  api.py        class Api = the js_api surface (JSON in/out, thread-safe, errors → RuntimeError)
  log.py        the troubleshooting log (-v on a terminal; a log file in the local data folder)
  notebook.py   files, front matter, tabs/folders/tags, full-text index + search, snippets
  config.py     per-user config (%APPDATA%)                              flex/model.py  object model, silfw links, tokeniser
  backup.py     notebook backup (sync folder / S3 via rclone), storage    secrets_store.py  Windows Credential Manager
  flex/__init__.py  FlexService: backend + snapshot cache + audio clips + media mapping + link resolution
  flex/lcm.py   flexicon backend (worker thread)   flex/flextext.py  .flextext fallback   flex/demo.py  fixture
  flex/cache.py snapshots + clip paths            flex/audio.py     wave / ffmpeg cutting
  flex/tracking.py  keeps an example on its lines when FLEx splits, merges, deletes or rebuilds them
  flex/chart_export.py  a text chart as FieldWorks' discourse-chart XML (GUIDs added) or as JSON
  docx_writer.py xlsx_writer.py pptx_writer.py  Word / Excel / PowerPoint from the page's export model, stdlib only
  pdf_print.py  a PDF written by WebView2 itself on Windows (the print dialog elsewhere)
  ui/index.html, ui/css/app.css, ui/js/
    util.js api.js(+mock) flexref.js markdown.js interlinear.js files.js backup.js charts.js tables.js editor.js picker.js
    export.js collection.js (example collections) flexcopy.js (the readable copies in the file)
    tagstyles.js (FLEx text markup tags: scoped styles, the ⚑ popover, the editors) app.js
    chart.js (FieldWorks text charts: the table, markers, free translations, the style popover)
    chartnote.js (the chart NOTE kind: its body format, custom columns, the rule language)
    demo-data.js  GENERATED by tools/gen_demo_js.py — never edit by hand
tests/  test_*.py (pytest) · js/*.test.js (node:test, vm-loaded scripts) · e2e/ (Playwright, bridged)
build/flex-scratchpad.spec  PyInstaller --onedir     .github/workflows/ci.yml  tests on push, Windows build on dispatch
```

## The embed grammar is a contract

`{{flex:text <guid> seg=3-5 lines=… hl=3.2 b=3.1-3.4 u=morph:"-mo" hl[#fff2a8]=ft:3 "label"}}`
(and `{{flex:chart <guid> rows=2-5 at=… cols=… free=row hl=r2 b=r3c4.1 "label"}}`, see TEXT CHARTS below)
lives in people's notes. `ui/js/flexref.js` is its only parser/serialiser; `tests/js/flexref.test.js`
pins it. Extend it additively (unknown keys round-trip through `spec.extra`), never change the
meaning of an existing key. Python only needs the kind + guid (`flex/__init__.py` EMBED_RE).

READABLE WITHOUT THE APP (Seth, 2026-10-17: "make sure that our FLEx links save cached interlinear
text (and text reference) so that a markdown file IS actually readable elsewhere"): the FILE carries
a plain-text copy after every FLEx object, and the app never shows it — "the inverse of the old
convention of putting JavaScript inside HTML comment tags". `ui/js/flexcopy.js`: an object on a line
of its own gets `[<title> <FLEx numbers>](silfw://… "flex-copy")` on the next line and a
` ```flex-copy ` fence with the lines the example shows (`lines=`), each word a column padded with
spaces (an entry: its senses); an object in a line of text or a table cell gets ONE link right after
it, `{{flex:…}}[<ref>: ‘<free translation>’](silfw://… "flex-copy")`, pipes escaped in a cell. Only a
fence whose info string is exactly `flex-copy` and a link titled "flex-copy" right after an object are
ours. `strip()` takes them out when a note is opened (app.js `openNote`, the reload from disk), so the
editor, drag, cut, undo and a collection only ever see the `{{ }}` object; `attach()` writes them back
on save (`saveNow`, `create_note` / `add_to_collection` bodies) from the object as last fetched
(`FS.interlinear.peek`, never a new fetch), in the form the object's PLACE calls for — so moving it
into or out of a cell switches the form; an object not fetched this session keeps the copy its file
had. WHEN (Seth): when the example has changed (`stale()` after a fetch: a stored copy that no longer
matches FLEx; a pending save is never postponed) and when it moves; opening a note never rewrites
it, and a note without copies gets them at its next save. Python strips the same two shapes
(`notebook.without_flex_copies`) for excerpts, search and #tags; the Markdown export and "Copy
markdown" keep them. `tests/js/flexcopy.test.js` writes `tests/fixtures/flexcopy-note.md`, which
`tests/test_flexcopy.py` strips with Python: keep the two regexes alike. The e2e `body_of` helper
compares notes WITHOUT their copies; `test_flex_objects_get_a_readable_copy_in_the_file` checks them.

## Editor invariants (ui/js/editor.js, markdown.js)

- An embed on a line of its own is a `flex` block (expanded, or a chip with `collapsed`). An
  embed INSIDE a line of text is an inline chip: `decorate()` emits it as a
  `contenteditable=false` `.md-embed` span whose text is still the raw `{{flex …}}`, the chip is
  drawn by CSS from `data-icon/title/range` (filled by `FS.interlinear.hydrateInline`), the
  caret never lands inside it (`outsideChip`) and Backspace removes it whole. The picker inserts
  inline when there is text before the caret on the line, else as a block.
- Example layout keys on a block embed (`spec.extra`): `ex` = numbered (1), (2)… through the
  note (`renumberExamples` on every change), `indent=N` (1–4) steps it in like a list level.
  Tab / Shift+Tab on the focused block, or the ⋯ menu. Exports carry `exNum` / `indent`.
- Objects are dragged (Seth, 2026-10-16): the ⠿ handle on a block object, a collapsed chip, an
  inline `.md-embed`, or an object in a cell; dropped into a line of text (inline, at the point),
  a table cell, or between blocks (on a block's top/bottom half = before/after, which re-orders).
  One delegated handler on the editor root (`wireDrag` → `dragSourceOf` / `dropTargetAt` /
  `moveEmbed`): string surgery on the markdown, a move unless Ctrl/Alt (copy). `FS.drag` holds
  the source during the drag; the `application/x-flex-embed` type marks our drags. A chip's
  hover preview (`hoverPreview` in interlinear.js) yields to the drag: a press cancels the
  pending preview and drops an unpinned one, `dragstart` closes any overlay, and only a click
  without a drag pins it open.
- A text block's `textContent` **is** the markdown. `decorate()` only wraps characters in spans;
  it must never add or remove text (the node tests check this). Empty lines render a `<br>`.
  Outline numbers are COMPUTED (`markdown.numberLines`, per level, carried across blocks by the
  editor's `numCtx`) and shown over the typed number via `data-num`; the typed digits stay.
  The typed number of a block's first TOP-LEVEL item restarts the count when it is `1.` or
  jumps forward (`3.` starts at 3, `1.` after a blank line starts over); a smaller typed number
  is stale (an item was added above) and the count continues; nested items always count under
  their parent. The block ⋮ menu has "Start numbering at…". NESTED LISTS (Seth, 2026-10-18:
  "increase and decrease the indent (and display it prettily)"): `editor.indent(body, b, dir)`
  steps every line under the selection in or out by two spaces (≤ 4 levels) and keeps the
  selection on the same text — Tab / Shift+Tab, Ctrl+] / Ctrl+[, the toolbar's ⇥ ⇤
  (`indentActive`, the active list block) and the block menu's "List indent" row. Each level has
  its own bullet (• ◦ ▪ ‣, CSS on `.md-indentN .md-bullet::before`) and nested numbers are shown
  as letters one level in and roman two levels in (`markdown.numberLabel(n, level)`, the
  `data-num` the editor draws; the typed digits stay in the file). The indent spaces are a
  zero-width `md-ind` span of their own (inside the 22px bullet span they wrapped the item onto a
  second line); the bullet and number spans are `white-space: pre` — `nowrap` COLLAPSES the
  trailing space and Chromium then drops it from the text on the next keystroke ("- item" became
  "-item"). SINGLE-SPACED LINES (Seth, 2026-10-18: "we don't really want double-line spacing in
  our list items within a single block"): the `\n` between two lines is the LAST character of the
  first line's `.md-line` span (`decorate` joins with ''): a newline text node BETWEEN two
  `display: block` spans is laid out as an empty line of its own under `pre-wrap`. An empty line
  that is not the last is just its `\n`; only the last line, when empty, gets the `<br>`.
  `pointAt` steps from the end of a line's `\n` to the start of the next span.
- THE BAR BETWEEN BLOCKS (Seth, 2026-10-18: "Between blocks an empty line is allowed (in fact, it
  would be a convenient place for an 'add/remove block' bar similar to the bar at the end of our
  table)"): blocks are 8px apart; `wireGapBar` keeps one floating `#blk-gap` beside the root (the
  root is emptied by `renderAll`) and shows it while the pointer rests in a gap — between two
  blocks, just above the first, under the last (`gapAt`): + Paragraph · + Example · + Table ·
  + More ▾ (`insertSection` with only the side that means "here") insert at that gap through
  `insertNewBlock`; − Above / − Below `deleteBlock` the neighbour, marked `.del-hint` while the
  button is hovered. It hides on scroll, keys, a drag and when the pointer leaves (160 ms grace
  so it can be reached). SAFE TO HAVE AROUND (Seth, 2026-10-18: the bars are "frequently under
  foot and easy to click on accident (with drastic consequences)"): the zone is the 8px gap
  ± 2px, not the blocks' edges; the bar appears only once the pointer has RESTED in one gap for
  350 ms (passing through shows nothing); the − buttons are `FS.armed` (util.js: the first click
  turns the button into "Remove?" for 2 s, the second fires); every removal leaves
  `FS.toast(…, {action: {label: 'Undo', fn}})` → `undoStep`; and Settings "Show the bar between
  blocks" (`settings.gapBar`, `editor.gapBarOn`) turns it off. THE TABLE BAR shows for a table
  that was CLICKED INTO (`.tbl-active` on the table's host: a mousedown or focusin inside it; a
  press anywhere else takes it away), never on mere hover; − Row / − Column moved into the Row ▾ /
  Column ▾ menus ("Delete row(s)", `row-delete` / `col-delete`) and, like the cell menu's
  deletions, leave an Undo toast (`opts.onUndo` from the editor).
- New blocks (Seth, 2026-10-16): right-click a block that is not running text (an example, a
  chart, a divider…) or the space between blocks, a table cell, or open the ⋮ block menu →
  "Insert a new block": paragraph, heading, bulleted / numbered list, checklist, quote, table,
  FLEx example (opens the picker for the spot), divider, ↑ above or ↓ below (`insertNewBlock`,
  `insertSection`, `NEW_BLOCKS`). Right-click inside running text keeps the browser's menu.
- A table's indent in the note is `indent N` (1–4) in its style line: Tab / Shift+Tab on the
  focused table, the context menu, Table style. Exports carry it (`indent` on the table block).
- Table structure ops (`tables.js` `ops.*`) FINISH THE OPEN CELL FIRST (Seth, 2026-10-16: insert
  row above while typing put the text in the wrong row). The bar under the table acts on the
  gutter SELECTION when there is one, else on the cell last edited; `deleteRow/deleteCol` take a
  range. Copying cells also keeps the rows in `FS.tableClip`: the menu's Paste… items read the
  system clipboard for at most 400 ms (WebView2 / headless Chromium may never answer) and fall
  back to it. A TSV grid pasted into an open cell fills cells from that one (`pasteOver`) unless
  it looks like FLEx rows (Word / Morphemes / Free …), which still go to the locator.
- Selecting across blocks (Seth, 2026-10-16) is ours, because Chromium confines a mouse selection
  to the editable block it started in: `wireMultiSelect` keeps `editor.msel = {a:{b,off}, z:{b,off}}`
  (partial text at the ends, whole blocks between), painted with the CSS highlight API
  (`::highlight(fs-msel)`) plus `.msel-block` on whole blocks. Drag out of a block, Shift+click,
  Shift+Arrow Up/Down extend it; Ctrl+A twice takes the note; cut / copy / paste / delete /
  type-over / Enter act on it (`deleteSelection` joins the two ends into one block).
- Moving SEVERAL blocks (Seth, 2026-10-16: "select and move/copy/cut/etc multiple blocks at a
  time (including FLEx objects)"): the ⋮ handle is also the block's DRAG GRIP (draggable; its
  mousedown opens the menu WITHOUT preventDefault, which would stop the drag) — with a cross-block
  selection it drags every selected block (`blockRangeFor`, whole blocks, a closed heading's
  section included), dropped before/after a block (`blockDropAt`, `moveBlocksTo`; Ctrl/Alt copies).
  Alt+Shift+↑/↓ moves the selection or the current block (`moveSelection` → `moveRange`, which
  steps over closed sections), and the selection stays selected for the next move. The ⋮ menu
  of a selected block offers Move / Cut / Copy / Duplicate / Delete for all of them.
- THE VIEW NEVER JUMPS (Seth, 2026-10-16: "I don't want the scroll jumping to the end of the
  document after edits or de-select/focus change"): a click on the editor's background only puts
  the caret at the end of the note when it is BELOW the last block; anywhere else it lets go of
  the cell / table / selection and `keepScroll` holds the position (now and two frames on). The
  press must start on the background too: a table tool redraws under the pointer and the release
  that lands on the background was the "+ Row jumps to the bottom". `renderAll` and the table's
  `refresh` restore the scroll position. Explicit navigation (focus moves, Find) still scrolls.
  A FLEx object redrawn after an edit (a style, its lines, its range) keeps its old drawing until
  the new one is ready (`keepView` in the note's, the collection's and the preview's render opts:
  no "Loading…" in between to shrink it) and `holdScroll` puts back every scroll position around
  it — ONLY when a drawing is replaced (holding scroll on every first drawing broke a collection's
  drag) (Seth, 2026-10-17: styling inside a collapsed example's preview jumped to the top of it).
- Headings 1–6 FOLD (Seth, 2026-10-16): a closed heading hides everything after it up to the next
  heading of the same or a higher level (`markdown.hiddenByFolds` / `sectionEnd`, the editor's
  `applyFolds`, ▾/▸ in the left margin, "⋯ N blocks" under it). The state is the block's
  `folded` flag, written as ` {collapsed}` after the heading in the file (the collection groups'
  marker) and stripped from the editable text, so the marker is never typed into or shown;
  excerpts, search and the Markdown export drop it (`notebook.without_fold_marks`). Hidden blocks
  stay in the model: focus steps over them (up lands on the heading), Backspace/Delete never merge
  into them, Enter at the end of a closed heading starts the NEXT heading of its level after the
  section (a paragraph there would belong to the closed section), a closed heading MOVES with its
  section, Find opens what hides a hit, and an edit that leaves the caret in a hidden block opens
  its section. The toolbar's H ▾ picks levels 1–6 (Ctrl+Alt+1…6) and folds all; the ⋮ menu of a
  heading has its levels and the folds. Word export maps levels 1–6 to Heading 1–6. PROMOTE /
  DEMOTE ALL (Seth, 2026-10-18: "promote and demote all headers in a note or within a selected
  range"): `editor.shiftHeadings(dir, range?)` moves every heading of the note, of the cross-block
  selection (`msel`, kept afterwards) or of a block range one level, as ONE undo step; it refuses
  (`blocked`) when a heading is already at H1 / H6, since merging two levels would lose the
  outline. The H ▾ menu's "Promote / Demote all headings in the note / selection" (Ctrl+Alt+[ /
  Ctrl+Alt+]) and the ⋮ menu of several selected blocks ("the headings here").
  STICKY HEADINGS (Seth, 2026-10-17: "make whatever headings apply to the current viewport be
  sticky (optionally, give the user the ability to turn this feature on and off)"): the editor's
  `updateSticky` (on scroll, resize and every `applyFolds`, one rAF) finds the first block whose
  bottom is under the top of the view and shows its outline chain — the nearest heading above it,
  that one's nearest heading of a higher level, … (`stickyChain`; a heading counts once its own top
  has passed the line, a folded heading never) — in `#sticky-heads`, a strip laid over the top of
  `#editor` (a sibling in `#editor-pane`, NOT inside the root: `renderAll` empties the root),
  outermost first, each row stepped in by depth. Its ▾ folds the heading IN PLACE and the view
  then goes TO THAT HEADING, under the rows of its ancestors (`foldFromSticky` → `scrollToHeading`;
  Seth: "instead of skipping ahead or going to the start or end of the note"); the title scrolls
  to it. `scroll-padding-top` on the scroller equals the strip's height, so focus moves and Find
  never land under it. Off/on: `settings.stickyHeadings` (default on) in Settings and the H ▾ menu
  (`applySticky` → `setSticky`). Collections' groups do not have it yet.
- `beforeinput` is whitelisted; Enter/paste/bold/undo are ours. Chromium must never inject HTML.
- A `<br>` (a line break in a table cell, or typed in text) deletes WHOLE (Seth, 2026-10-17: one
  Backspace "deletes part and leaves the text behind"): a document-level keydown (capture) in
  editor.js selects the whole token when Backspace is just after it, Delete just before it, or
  either is pressed inside it, in a `.blk-body` or `.cell-edit`; the key's own deletion then
  removes it through the usual input handling (`brAround`).
- MARKERS HIDDEN (`body.md-hide`, Settings / the ** Markup button): ONLY THE MARKUP AT THE CARET
  SHOWS (Seth, 2026-10-18: "whatever character or style markup applies to the current cursor
  position should be visible, but none of the rest of it … roughly how WhatsApp works"):
  `revealMarkers` (editor.js, on selectionchange) pairs the marker spans of the caret's line left
  to right (same delimiter text; `[`…`](…)`, `[[`…`]]`) and reveals every pair whose span holds or
  touches the caret — nested ones too — plus the line's own `###` / `>` prefix; a bullet, number
  or checkbox is drawn as its glyph and never revealed as text. Table markup is a widget anyway.
  The caret NEVER rests inside a
  line's hidden prefix (Seth, 2026-10-18: "the cursor goes to the left of the ### and makes the ###
  appear … text should automatically start typing to the RIGHT of a heading or list markup tag").
  `snapPastPrefix` (on selectionchange and before any insert) moves a caret inside the prefix to
  just after it; Home lands there, Left from there steps to the line before (or the block above);
  Backspace there removes the whole prefix. A line that is ONLY its prefix (a new heading, an empty
  quote line) gets `md-line-empty` from `decorate`, and its markers show faintly — a caret has no
  visible place in a wholly hidden line, so Chromium would put it before the hidden text and the
  typed letter would land in front of the `##`.
- Undo is our own snapshot stack (innerHTML rebuilds break native undo).
- LINKS AND SHORTCUTS (Seth, 2026-10-18: "a hyperlink feature … button and keyboard shortcut …
  investigate what common keyboard shortcuts we should add"): `linkDialog` (app.js; Ctrl+K, the 🔗
  button, Ctrl+K in a table cell) reads `editor.linkContext()` — the focused text block, its
  selection, and the `[text](url)` / `[[note]]` under the caret found with `MD.markInline` on the
  caret's line — and writes `[text](url)` (`normalizeUrl`: `https://` for a bare host, `mailto:` for
  an address) or `[[Title]]` for a note through `editor.replaceRange` (one undo step); in a cell the
  markdown is typed with `execCommand('insertText')` after the saved selection is put back. A URL
  on the clipboard fills the address (400 ms race, as the tables' paste). The complete list of
  shortcuts is `SHORTCUTS` in app.js → `shortcutsDialog` (Ctrl+/, Settings): keep it true when a
  key is added. Shift+digit keys are matched by `e.code` (`Digit7`), since `e.key` is the shifted
  character on most layouts. Not added on purpose: Ctrl+U (Markdown has no underline), Ctrl+H
  (no replace yet), Ctrl+P. THE LINK PILL (Seth: "make it easy to click to follow or edit links"):
  `setupLinkPill` (app.js) watches `selectionchange` (one rAF) and, when `linkContext()` finds a
  link under a collapsed caret, shows `#link-pill` (beside the root, in `#editor-pane`) under the
  link's first `.md-link` / `.md-wiki` span: the address, Follow ↗ / Open note, Edit (the dialog),
  Copy, Unlink (`replaceRange` with the text). Its buttons preventDefault on mousedown so the caret
  stays in the block; it hides when the caret leaves, on Esc and on scroll. A link's text has a
  pointer cursor and underlines on hover, so a click (caret → pill) then Follow is the two-click
  path; Ctrl+click follows at once as before.

## Working here

- Python ≥3.10, no third-party runtime deps except pywebview (Windows) and the optional `[flex]`
  extra. Keep it that way; the app has to install on a field laptop with `pip`.
- Run `python -m pytest tests --ignore=tests/e2e`, `node --test tests/js/*.test.js`, and
  `python -m pytest tests/e2e` (needs Playwright's Chromium) before pushing. CI runs all three.
- After editing `flex/demo.py` run `python tools/gen_demo_js.py` (the in-browser mock data).
- Segment numbers: `n` counts through the text (what `seg=` addresses), `label` is FLEx's own
  `paragraph.segment` (what people read, shown everywhere). BLANK LINES (Seth, 2026-10-17: a Shift+Enter in FLEx leaves
  an empty 1.2 that FLEx numbers but never shows): a segment with no word or text (only spaces,
  U+2028 or other invisibles) and no free / literal translation or note is left out of every
  example, preview, context view, the picker, the TSV copy and every export (`blankSeg` in
  interlinear.js, `model.is_blank_segment` for the .flextext writer — keep the two alike); the rest
  keep FLEx's numbers (1.1 then 1.3), `seg=` still counts it, and an example that is only blank
  lines says "This line is empty in FLEx." Punctuation alone is not blank. Morph glosses wear the morph type's
  break characters (`-PST`, `3SG-`, `=lo`), from `IMoMorphType.Prefix/Postfix` with a fallback
  to the markers already on the form or headword — unverified against a real project yet.
- Locating pasted FLEx rows (`FlexService.locate`): the per-session index (`all_baselines`) holds
  every segment's baseline, free translation, Morphemes line and Lex. Gloss line. A Word row
  matches the baseline; without one, Morphemes rows match the segment's OWN morpheme line
  (Seth, 2026-10-14: morph forms need not spell the surface word), then Lex. Gloss rows its
  gloss line. When nothing matches, the picker tells the user to copy with the Word line showing.
  A pasted RANGE matches its segments in order but may skip up to `LOCATE_GAP` (3) of the
  text's segments between two of its own: FLEx's copy can leave segments out (Seth,
  2026-10-16: 12.1, 12.3, 13, 14 with no 12.2 found only 12.1); the range runs first to last.
  FLEx's OWN NUMBERS on the pasted rows ("12.3", "13" = 13.1) decide the place when the matched
  text has them and the first pasted segment's content agrees there (`_place_by_labels`; the
  index rows carry the label as their 6th item): content alone picked the first copy of a
  repeated line, "two lines above" (Seth, 2026-10-16). Unnumbered pastes rank by content, then
  by fewest skipped segments. Every hit also carries the located segments' FLEx numbers
  (`label`/`labelTo`, what the dialog shows) and their GUID anchors (`at`, the index rows' 7th
  item), and the inserted embed is written with `at=`: an anchor wins over `seg=` when the
  example is drawn, so a running count that differs between the index and the text can never
  move the example (Seth, 2026-10-16: the dialog was right, the example two lines above).
  A LINE THAT LOOKS WRONG (Seth, 2026-10-19: every morph shown twice in a Morphemes line): ask first for
  `flex-scratchpad --project NAME --dump "TITLE" --seg 11.1` (`dump_range` in __main__: FLEx's number or a
  range, or the running count), which prints the line's words and morph bundles exactly as read.
  THAT ONE WAS FIELDWORKS (same day): its importer gives a glossed word with no <morphemes> one bundle
  holding the word's form PER GLOSS LANGUAGE (`BIRDInterlinearImporter.UpgradeToWordGloss`), so texts from
  FlexText Editor glossed in two languages show `budu budu` / `*** ***`. `--doubled-morphs [TEXT]`
  (`explain_doubled_bundles`, `model.doubled_bundles`; texts first, line by line with a progress line per text — the
  whole-project wordform walk sat on one number for minutes — then, with no TEXT, the wordforms no text uses) lists
  every such analysis with its uses, read-only;
  the fix is FLEx's Word Analyses. plans/BACKLOG.md › Known issue elsewhere.
  When a paste does not land, `flex-scratchpad --project NAME --locate clip` (or a file) runs the
  locator against the real project and writes `flex-scratchpad-locate.json`: the rows as read,
  the hits, the best segments per pasted segment, and what the texts holding the pasted numbers
  have there, raw and normalised (`FlexService.explain_locate`) — ask for that file first.
  Seth's first report (2026-10-16) placed its paste right, and showed the index's Morphemes
  line read in the wrong writing system (`bete` for `bɛtɛ`) without affix glosses, and "Free Eng
  …" keeping its `Eng`: the index now reads morph forms in the text's own WS (`_baseline_ws`)
  through the same `_bundle_form` / `_bundle_gloss` the rendering uses, and the parser drops a
  WS code after Free (`_paste_ws_codes`).
  While a pasted example or `silfw://` link is being looked up, `FS.busy` (util.js) shows a
  spinner pill by the caret after 200 ms (a quick answer never flashes it), with "Paste as
  text" / Esc to stop waiting; a late answer after that is ignored (Seth, 2026-10-16).
- AN EXAMPLE STAYS ON ITS LINES (Seth, 2026-10-17: "lines deleted, merged, or split in baseline …
  Will that throw off all of our object references … We'd really like our flex objects to be more
  reliable, stable, and intelligent"). What FieldWorks does (liblcm `DomainImpl/AnalysisAdjuster.cs`,
  read 2026-10-17): an untouched segment keeps its object/GUID; a SPLIT keeps it on the FIRST piece
  (the rest are new segments); a MERGE keeps the FIRST segment and deletes the second; a re-import
  or a rebuilt paragraph gives new GUIDs. `flex/tracking.py` keeps a LEDGER per text in the snapshot
  folder (`ledger-<text>.json`: the last orders of its segment anchors, and per segment its last
  texts, words and drawn copy) and `FlexService._tracked_text` runs every text fetch through
  `track()`: the embed's OWN old range (the stored order whose anchors sit at its `seg=` numbers),
  survivors mapped, widened over a split last line's NEW pieces whose text was in it, and over the
  line a deleted first line was merged into; no survivors → found again by TEXT (difflib, ≥0.6,
  nearest the old place); else LOST → the saved copy with a warning, never whatever now has those
  numbers. `obj.track = {change: none|moved|reshaped|found|lost, how, map, oldWords}`; the page
  (`syncAnchors` → `remapStyles`, interlinear.js) moves every `hl= b= u= …` target with its LINE
  (a deleted line's go) and a word target with its WORD (or drops it rather than mark another
  word), then rewrites `seg=` / `at=` and says what happened. A plain redraw reads no extra text
  from FLEx (texts come from the fetched range; the whole text is read only for a NEW segment
  next to the range, a missing first line, or a search). The snapshot no longer keeps an old
  segment under a number the text has since given to another (`cache.merge_text`). Inline chips
  are titled only (they are not rewritten). Not yet run against a real FieldWorks project.
- EXAMPLE COLLECTIONS (Seth, 2026-10-16: *"a special notes type that is JUST IGT examples"*, and
  *"have just that special note/document type be the one that can export"*): `kind: examples` in
  the front matter (written only for collections, so ordinary files are unchanged), body = one
  `{{flex:text …}}` per paragraph. `ui/js/collection.js` draws it in place of the editor (the
  hidden editor must never write into it: `isCollection()` guards in app.js). Only a collection
  exports a `.flextext` — the API refuses other notes; ordinary notes get "Collect the examples
  into a new collection…" (the HIGHLIGHTED part when it holds examples — a cross-block selection,
  a selection in one text block, table cells, or a click into an example; `highlightedSource()`,
  read on mousedown of the note menu because opening it can clear the selection — else the
  whole note), every example gets "Add to an example collection…". The body format
  (`FS.collection.parse/serialize`, pinned by `tests/js/collection.test.js`): `## Label` is a
  GROUP (` {collapsed}` when closed) — it only organises the view and is NOT exported; `> `
  lines after an example are its NOTE, which IS exported (a `note` item on the example's first
  phrase, after FLEx's own notes, whatever the Source-note option); anything else is kept as
  is. Numbering runs straight through the groups (it is the export order). Groups have LEVELS
  (`#`…`######`, Seth, 2026-10-16): a group holds everything up to the next group of the same or a
  higher level, sub-groups included (`blockOf`, `hiddenItems`), steps in by level, and ⇤ / ⇥ change
  it; a group moves whole with its sub-groups; adding or moving an example into a closed group opens
  every group around it (`openAround`). Old files' `## Group` is level 2. Still never exported.
  SEVERAL ITEMS at once: a checkbox per card and group (Shift: a range, Ctrl+A: all) and a bar in
  the sticky header — ↑ ↓ (Alt+Shift+↑/↓), Move into group…, Cut / Copy / Paste (Ctrl+X/C/V; the
  copy is the collection's own markdown, `FS.collClip` too, so it pastes into a note or another
  collection), Duplicate (Ctrl+D), Remove (Delete, with Undo); dragging a selected card moves them
  all. A selected group stands for its whole block (`selectedIdx`). A redraw keeps the keyboard
  focus in the collection.
  An EXAMPLE collapses to a chip too (Seth, 2026-10-17: "we DO want flex objects in example
  collection notes to be collapsible"): ⤡ on the example, ⤢ on the chip or "⤢ Expand" in its
  preview, and "Examples as chips / in full" in the header. The embed keeps `collapsed` in the
  collection's file (`cleanEmbed(src, keepCollapsed)`; examples arriving from a note still come
  open), the chip is not draggable there (cards move by their grip), and the export takes every
  example, open or not.
  RULE COLLECTIONS (Seth, 2026-10-18: "create a collection with ALL lines that match a specific
  rule. And to be able to have that collection add new matches found in the database that aren't
  already in that collection"): the note's `rule` = {tags: [selectors], texts?: [guids]}, in the
  file as `rule-tags: [Topic, group:Arguments]` (+ `rule-texts:`), `Note.rule`, `clean_rule`,
  `rule_from_meta`. A selector is a tag's name (what the UI writes: readable in the file),
  abbreviation or GUID, `group:<name>` (every tag under that group at any depth) or `*`.
  `FlexService.rule_matches(rule)` runs `tag_occurrences` per tag and keeps ONE row per distinct
  LINE (text, seg, segTo — a tag spanning 5–6 is one line, two tags on one segment one line, with
  both names in `tags`), in text order. `Api.create_rule_collection` writes one anchored example
  per row (`match_embed`: `{{flex:text <guid> seg=a-b at=x-y}}`, flexref's own shape);
  `Api.update_rule_collection` appends the rows whose keys (`match_keys`: by anchors AND by
  numbers) are not among the collection's (`example_keys` reads both from every example), so a
  line added by hand with `seg=` only still counts as present; groups and notes are untouched, the
  new lines go to the END and the page SELECTS them (`Collection.selectBySrc`). A line the user
  removed comes back at the next update (the semantics Seth asked for, said in the README).
  A CONCORDANCE EXPORT (Seth, 2026-10-20: "paste the results of a FLEx concordance (or complex concordance)
  search and get an example collection … you can't actually 'paste' concordance search results, but you could
  open the CSV results" — "THAT would be HUGELY useful"): FLEx's File › Export Concordance Results… writes
  `Ref,Occurrence` rows — Ref = the text's abbreviation (or its title, or its title cut to eight letters) +
  FLEx's paragraph.segment number, Occurrence = the whole paragraph's baseline with `§` between segments, a
  row PER MATCH (a line matched twice is there twice). `flex/concordance.py` (pure, stdlib csv): `parse(text)`,
  `match(rows, texts, index)` places each row in the per-session index (the text by `abbrev` / title / title
  prefix — in EVERY writing system: `list_texts` rows carry `names`, every title and abbreviation alternative
  (`lcm._text_names`; Seth, 2026-10-20: texts titled in the vernacular were not found), and `search_texts` reads
  them too — the line by `label_key`, the baseline checked against the `§` pieces — `how` number | number? | text,
  the last found by its baseline when the number is not in the text), one row per distinct line (`hits`) in
  file order, the misses with a `why`. `FlexService.concordance_rows(text)`, `Api.read_concordance_file()`
  (the CSV dialog → {path, name, text}; BOM / UTF-16 / cp1252 tolerated), `Api.concordance_preview({text|path})`,
  `Api.create_concordance_collection(tab, folder, title, src, {note})` (an ordinary collection, no rule:
  `match_embed` per row, `> Ref (×n)` notes on request, the misses as a closing paragraph). UI:
  `concordanceDialog` (app.js; `+ New ▾` → "New collection from a FLEx concordance export…"): Open CSV… or a
  textarea for the file's contents, the live placement (found / not found per row), Create. The mock has the
  three methods (no dialog in a browser: the textarea). `tests/test_concordance.py`, e2e
  `test_a_flex_concordance_export_becomes_a_collection`. Seth's two real exports (41 and 1087 rows) are the
  shapes it was written from; not yet run against his project.
  `Api.set_note_rule` changes the rule, what is held stays. UI: `ruleCollectionDialog` (app.js;
  `+ New ▾` → "New collection from tagged lines…", the picker's tag view "Collect into a new
  collection…" pre-ticked, a collection's "Edit rule…"): the tag tree with a box per tag and an
  "all of these" box per group (`group:<name>`, which disables the boxes under it), a select that
  ticks a visual filter's tags, the live count + preview (`Api.rule_matches`); the collection
  header's `ruleBar` (⚑ the selectors, "⟳ Find new lines" → `updateRuleCollection`, "Edit rule…").
  The in-browser mock has the same four methods (they call each other through `this`: the
  mock is a plain object the Proxy applies them on).
- FLEx TEXT MARKUP TAGS (Seth, 2026-10-17: "read and render (with custom styles) FLEx's TextMarkup
  tags in our examples … project-scoped, folder-scoped, tab-scoped, and specific example-scoped …
  style settings … the most specific one takes precedent … easy to see which ones apply and click
  them on and off. Kind of like highlighting filters in Logos. Also make them searchable"). WHAT
  FLEx HAS (liblcm, read 2026-10-17): `IStText.TagsOC` holds `ITextTag`s — BeginSegmentRA /
  EndSegmentRA, BeginAnalysisIndex / EndAnalysisIndex (0-based over the segment's analyses,
  punctuation forms included) and TagRA, an item of `LangProject.TextMarkupTagsOA` (two levels: a
  group, its tags; CmPossibility ForeColor / BackColor are BGR ints, kclrTransparent = unset —
  `model.fw_color`). READ: `lcm._text_tags` → `text.tags = [{guid, tag: {guid, name, abbr, group,
  fore, back}, from: {seg, w}, to: {seg, w}}]`, ALL of the text's tags whatever range was fetched (so
  the snapshot always holds them; `merge_text` keeps the newest list); every word carries `ai`, its
  analysis index (`fill_punctuation` may drop an empty punctuation token; the page falls back to the
  token index for the demo). `lcm.list_text_tags` (the list; kept in the snapshot folder as
  `list-texttags.json` for a session without FLEx) and `lcm.tag_occurrences` (every text's tags of
  one item: {text, title, seg, segTo, label, labelTo, at, words}) feed `Api.flex_text_tags` /
  `flex_tag_occurrences`; the demo has a list and eight tags on the story (one spanning two
  segments); a .flextext has none. DRAWN (`interlinear.segTags`, `renderSegment`): when the `tag`
  line is on (`R.showsTags`: in DEFAULT_LINES, off when an explicit `lines=` leaves it out; "FLEx
  text markup tags" in the ⋯ lines menu), a `.tagbar` row per LANE under the words (overlapping tags
  stack; a bar runs across its words — the continuing pieces bridge the 18px between cells — with
  the abbreviation on the first, `…Abbr` when it continues from an earlier segment, dotted ends
  where it goes on), `tag-b/i/u` on the word line when the style says so. STYLES
  (`ui/js/tagstyles.js`): a RULE = {tag (name / abbreviation / GUID / `*`), enabled?, hide?, bg?,
  fg?, b?, i?, u?, label?}; scopes most specific first: the EXAMPLE's own in its embed (`tags=`,
  `flexref.tagRules/setTagRules`: `tags=Subject:off,Topic_shift:bg#d1fae5+b,*:on`), the FOLDER
  (`notebook.json tagStyles.folder["<tab>/<path>"]`, nearest first, then its parents), the TAB
  (`tagStyles.tab[dir]`), the PROJECT (`tagStyles.project[name]`; `Api.set_tag_styles` validates
  and saves); `resolve()` settles SHOWN (the first rule that says on/off) and LOOK (the first rule
  with style keys) separately, so "off here" / "back on here" keep the broader colours; within one
  scope a tag's own rule beats `*`; `enabled:false` keeps a rule unused; no rule → FLEx's own
  colours when the item has a background, else the palette (by the tag's place in the list). UI:
  `⚑ N` on an example → `examplePopover` (each tag: swatch, "styled by the tab" / "hidden by this
  example", a show/hide toggle, Style ▾ = the example's own look, 🔍 = the picker on that tag, links
  to the folder / tab / project editors); `dialog(scope)` (tab and folder menus, Settings › FLEx
  text markup tags; every tag of the project and `*`, the rule here with its on/off, the effect at
  that scope) and for a SELECTION (`tagStylesForEmbeds` in app.js: the note menu's "FLEx tag styles
  for the selected examples…", a collection's selection bar "Tag styles…") the same dialog in
  example scope, written into every selected embed (`editor.mapEmbeds`, `collection.mapSelected`).
  A change anywhere emits `tagstyles` and the note redraws. SEARCH: `model.searchable_text` adds the
  tag names and `⚑name` tokens, `tagged:Topic` in the search box is that token; the picker's "FLEx
  tags" tab lists the tags, then every place one is used (click: the preview on that range; "Insert
  all N as examples"). Exports: a `tag` line per lane (HTML / Word / PDF, the colour behind the
  abbreviation), the plain-text copy a row per lane.
  TEXT STYLES AND VISUAL FILTERS (Seth, 2026-10-18: "the option to style the TEXT, not the tags …
  brackets around words (and their glosses, etc), highlight/background/border/tile … 'visual
  filters' based on text tags like … in Logos … search or filter notes and specific flex objects
  in notes by text markup tags"). A rule's text keys: `br` (sq rd cu an db ce fl bar —
  `tagstyles.BRACKETS`), `hl` (a marker over the word line), `tile` (a tinted box behind the whole
  column), `box` (a border round it), `c` (the words' colour), and `bar` true/false; `res.showBar`
  is `bar` when set, else "no text style is on" — "those styles can overlap with tags optionally
  displayed underneath". In `tags=`: `brsq hl tile box c#rrggbb bar nobar`. DRAWN: brackets are
  `.br-cell`s of their own in the word row (the outer tag's outside the inner's by span; the
  abbreviation as a `<sub>` on the closing one when the tag has no bar); hl / tile / box are
  `.tag-ov` overlays in a `.tag-ovl` layer of the `.word-row`, placed from the cells' geometry
  (`placeTagOverlays`: one piece per visual line of a wrapped row, nesting depth insets them, a
  ResizeObserver re-places them), so `.word-row` is `position: relative` and `.word-cell` sits
  above the layer; `segTags` gives a LANE only to bar tags (lane -1 otherwise) and `depth` to the
  overlays. Exports and the plain copy wrap the baseline in the brackets (HTML / Word also tint
  hl/tile words). A BORDER's line (Seth, 2026-10-18: "edit line style and thickness"): `bs`
  (solid | dashed | dotted | double) and `bw` (1–6 px; the overlay's borderStyle / borderWidth,
  2px solid when unset) — `bsdashed+bw3` in `tags=`; a TILE's own colour ("edit the background
  color"): `tc#rrggbb`, drawn at 0.55 alpha (the tag's colour at 0.38 when unset — a chosen colour
  is meant to be seen), `tc#…` in `tags=`; the controls appear under the border / tile toggles
  (`tag-bs`, `tag-bw`, `tag-tc`), switching the toggle off drops them. A rule's `tag` may also be `group:<FLEx group>` (every tag of the group; its own
  rule still wins) — the dialog lists a row per group. VISUAL FILTERS: `tagStyles.filters =
  [{id, name, enabled, rules}]` (`Api.set_tag_filters`), consulted in order between the tab and the
  project (`scopesFor`); a scope turns one on/off for itself with a rule on the pseudo-tag
  `filter:<id>` (`hide` = off; `filterSwitches` in the tab / folder dialogs and the ⚑ popover,
  `tags=filter%3Aid:off` on an example). FILTERS ARE A VIEW SETTING (Seth, 2026-10-18: "a view
  setting for the whole app or for notebook pages. You set them up and then turn them on and off
  (multiples allowed)"): a NOTE scope (`tagStyles.note[<id>]`, between example and folder;
  `ctx.note`) holds a page's own switches; the toolbar's ⚑ Filters = `filtersPopover` with "This
  note" (writes `filter:<id>` rules into the note scope; "this note only ↺" drops one) /
  "Everywhere" (the filter's `enabled`); "Set up visual filters…" / Settings = `filtersDialog`
  (add, rename, order, Rules… = the scope dialog in filter scope). THE SCOPE DIALOG STARTS EMPTY
  (Seth: "a new rule should have nothing in it and have tags added manually one at a time, chosen
  from a list … If the user hasn't manually added a tag to a visual filter rule, then that visual
  filter rule has no effect on that tag one way or another"): it lists only the rules present
  (plus tags just added and not yet styled, `pending`, which are not saved) and "+ Add a tag…"
  (`addTagPicker`: All tags, each group as `group:<name>`, each tag, with a search box) — never
  every tag of the project with an empty control. THE LIST IS A HIERARCHY (Seth, 2026-10-18:
  "the text markup tags list has at least two levels … show that collapsible hierarchy in the UI"
  wherever tags are chosen, searched, switched or added — not on the drawn tags, which only tier
  when they overlap, nor in the list of filters): every tag carries `path` (its ancestors in
  FLEx's list, top first; `lcm._tag_path` walks `Owner` while it is a CmPossibility, the demo nests
  Subject / Object under Syntax › Arguments) and `group` = the nearest; `tagstyles.tagTree(items)`
  folds a list into nodes in FLEx's order and `renderTagTree(host, items, {leaf, head, open,
  flat})` draws fold-able group headings (`.tag-tree-head`, state in localStorage `fs:tagTree`,
  shared by every list; a search opens all). Used by `addTagPicker` ("+ all of these" on a heading
  = `group:<name>`), the scope dialog (`*` and group rules first, then the tags' tree), the ⚑
  popover, the picker's FLEx tags tab and the rail's FLEx tags. A `group:<name>` rule matches any
  ANCESTOR of that name. A RULE CHOOSES ITS SCOPE (Seth, 2026-10-18:
  "whole notebook, tab, folder, notes doc, selected range in a note, specific texts anywhere they
  appear"): the ⚑ popover's "Changes apply to" select (`tag-scope-pick`) aims every toggle and
  style at this example / this note / each folder / the tab / the TEXT / the whole notebook / a
  filter (`examplePopover`: `target`, `rulesFor`, `write`); a selected range is the note menu's
  "FLEx tag styles for the selected examples…". The TEXT scope (`tagStyles.text[<guid>]`, between
  the tab and the filters) comes from the example's own `spec.guid` (`resolve` puts it in
  `ctx.text`), its label from the titles the renderer registers (`noteTextTitle`); "the project"
  scope is labelled "the whole notebook" for users. FILTERING BY TAG: `Notebook.flex_tags_used()` reads the
  index's ⚑ tokens → {token: [note ids]} (`Api.flex_tags_used`; `Api.flex_get` re-indexes the
  notes quoting a text as soon as it is fetched, `reindex_mentioning`, so the rail does not wait
  for a save); app.js `ftagRows` merges a tag's name and abbreviation tokens through the project
  list and lists them for the tab; a click sets `S.ftag`, the list runs the search with
  `tagged:<token>` (`runSearch`), and in the open note `applyTagFocus` (a MutationObserver on the
  pane, since examples draw late) marks `.text-obj.tag-hit` / dims `.tag-miss` by the
  `data-tags` the renderer puts on each example, with the `#tagfocus` bar (count, ▲▼, clear).
  FIRST CONTACT (Seth's project, 2026-10-18:
  every tag "?" with a black bar): names must never go through flexicon's `BestStr` — it checks
  `isinstance(x, (IMultiUnicode, IMultiString))`, and pythonnet types what it hands out by the
  runtime class (liblcm's internal accessor), whose Python bases hold no interfaces, so it raises
  for every real multistring; `lcm._best()` reads `BestAnalysisVernacularAlternative` & co.
  directly (`tests/test_tags.py` keeps `BestStr` out of lcm.py). An item nobody coloured has 0 in
  every colour field (black on black) — `model.tag_item` treats that as no colour. When tags
  still look wrong, ask for `flex-scratchpad --project NAME --dump-tags [TEXT]` →
  `flex-scratchpad-tags.json` (`lcm.explain_tags`: the list through every accessor, and per tag
  its segments, analysis indexes and the first segment's analyses).
- TEXT CHARTS (Seth, 2026-10-18: "a Text Chart, part of a text chart (including the headers), a
  range of rows … styling for text chart markers … free translations spliced in … searchable"). WHAT
  FLEx HAS (liblcm, read 2026-10-18): `LangProject.DiscourseDataOA.ChartsOC` holds `IDsConstChart`s —
  `BasedOnRA` (the text's IStText), `TemplateRA` (a CmPossibility whose sub-items are the column
  GROUPS and their COLUMNS; names repeat across groups: Prenuclear › Inner, Postnuclear › Inner,
  so a column is addressed by GUID or path, never by name alone), `RowsOS` of `IConstChartRow`
  (`Label` "1a", `Notes`, `ClauseType` normal/dependent/song/speech, `EndSentence`, `EndParagraph`,
  `Start/EndDependentClauseGroup`, `CellsOS`). A cell part (`ColumnRA`, `MergesAfter/Before` = merge
  with ONE neighbour) is a `ConstChartWordGroup` (Begin/EndSegmentRA + Begin/EndAnalysisIndex — the
  shape of a text tag, so `model.cell_words` slices a segment's words by `ai`), a
  `ConstChartMovedTextMarker` (WordGroupRA, Preposed), a `ConstChartClauseMarker` (DependentClausesRS)
  or a `ConstChartTag` (TagRA, an item of `DiscourseDataOA.ChartMarkersOA`). FLEx exports a chart
  (`DiscourseExporter.cs`) and never imports one. READ: flexicon 4.12 has ConstCharts / Discourse
  .GetCells but not the analysis indexes, row flags or template tree, so `lcm._chart_dict` reads the
  fields directly (read-only, behind `_t()`; `plans/flexicon-requests.md` asks for them); the WHOLE
  chart is read and snapshotted (`chart-<guid>.json`; charts are small), `model.slice_chart` cuts the
  rows an embed asks for; `Api.flex_charts(text?)`, `flex_chart_markers()`, `flex_get('chart', …)`;
  `--dump-charts [WHICH]` writes `flex-scratchpad-charts.json` (`lcm.explain_charts`: every chart with
  every stored alternative of its name, the markers, and ONE chart's rows with their cell parts raw —
  `pick_chart`: every word of WHICH in the text title / name / template / GUID, a chart with rows
  first, so `Siakai` is the fullest Siakai chart and `"Siakai SVC"` the SVC one; `Siakai` alone once
  picked the first of five charts on that text, an empty one) — ASK FOR THAT FIRST when a chart
  comes out wrong; the demo has
  one chart on the story with every kind of cell. FIRST CONTACT (Seth's project, 2026-10-18): the
  reader worked as written — word groups with analysis indexes, columns under their groups
  ("Fronted Material › Outer" and "Post-Material › Outer" share a name), the text's tags, a
  142-item marker list three levels deep. What it taught: FLEx charts have NO name of their own
  (none of 80 did), so a nameless chart goes by its template ("Default chart", `named: false`),
  and a text has one chart PER TEMPLATE it was ever opened with, most of them empty — the picker
  and the chart-note dialog list the charts with rows first and say "empty", and the search
  index (`chart_rows`) reads only charts with rows, with a progress message per chart. The dict: `flex/model.py` "text charts" (rows
  numbered 1.. through the chart = what `rows=` counts; `index` is the rows' index so
  `resolve_range` / `at=` anchors work unchanged, by ROW GUIDs; `segments` = the text's segments
  the rows touch, for the free translations). THE EMBED (flexref.js): `{{flex:chart <guid>
  rows=2-5 at=<a>-<b> cols=Nucleus,Postnuclear/Inner,c3-c5 lines=txt,gls free=row|col|tip|off
  headers=off notes=off hl=r2 b=r3c4 u=r2c3.1 color[red]=c4 "label"}}` — `rows=` is held in
  `spec.seg` (so flexGet / chips / anchors are shared with texts; `seg=` is accepted and written
  back as `rows=`), chart targets are rN / cN / rNcM / rNcM.W with ranges (`parseChartTarget`,
  `resolveChartStyles`, `chartStylesFor`: a row, a column, a cell and a word level, gathered), a
  word target's implicit line is txt. DRAWN (`ui/js/chart.js`, called by `interlinear.render` for
  kind chart): ONE table — header rows from the columns' paths (a group spans its columns;
  ALWAYS on a range of rows, Seth: "the column headings should be included"; `headers=off` for a
  continuation), the row label (`.rlab`; dependent rows ↳ italic, speech “, song ♪; `end-sent` /
  `end-para` borders), a `td.ccell[data-row][data-col]` per visible column (`layoutRow` merges one
  neighbour per MergesAfter/Before), word groups as `.cw` word cells with the lines chosen (Words +
  Word gloss by default), ‹‹ / ›› moved-text markers (hover lights the word group they point at,
  which is dotted-underlined), [2a] clause markers (click flashes the rows), chart tags as chips
  (FLEx's colours, else the palette). FREE TRANSLATIONS (Seth's four ways): `free=row` (default) a
  translation row after the LAST row that holds any of a segment's words, naming the rows since the
  previous one (`freeRuns`: each segment's translation ONCE, runs never overlap — Siakai's row 1 holds
  the end of 1.1 and the start of 2.1, 2a–2b the rest of 2.1), `col` a Free column spanning the run's
  rows, `tip` a strip under the chart for the clicked cell, `off`. Row notes in a last column
  (`notes=off`). A click on a word / cell / row label / column heading opens `stylePopover`
  (scope: this word · the cell · the row · the column; the same hl/b/u/i/s/colour as examples) →
  `R.toggleStyle` with a chart target. The ⋯ menu: label, rows, lines, free translations,
  headings / notes, the columns (per group), Copy as TSV, Export as FLEx chart XML / JSON
  (`Api.export_chart` → `flex/chart_export.py`: FLEx's own `<document><chart><row><cell><main>`
  shape with `guid` / `text` / `col` attributes ADDED — a future importer can be exact; the JSON is
  the chart dict), Edit source, Duplicate, Remove. Chips: icon ▦, "Story chart · The dog and the
  river", range "rows 1b–2b". The readable copy (flexcopy.js `chartRef` / `chartBody` from
  `FS.chart.chartGrid`): the header rows and a row per chart row as padded columns, words as
  word/gloss. Exports: `export.js chartBlock` → `{type: 'chart'}` → an HTML `table.tchart`, a Word
  table (`docx_writer.chart`: header spans, a cell's own `bg` shades it). Search: `marker:Topic`
  = the ⚐name token `model.chart_searchable_text` adds; `texts_used` counts a chart under its
  text (`charts`). A chart link (`flex:chart/<guid>`) opens the TEXT in FLEx. PLAYBACK (Seth,
  2026-10-18: "audio playback in the chart, with play controls on the first row that starts an
  interlinear line. And highlighting (while playing) the cells that contain data from that line"):
  a chart carries its text's `media` (lcm `_chart_dict`, the demo); `chart.lineStarts(rows,
  segments)` puts a ▶ (`.seg-play`) in the label cell of the FIRST row holding a timed line's words
  (▶ in the `#` corner plays every line of the rows shown); it calls the examples' own
  `interlinear.playRange` with the chart as a text (`guid` = the TEXT's, for the clip cache), and
  `light()` there now marks every `.ccell[data-segs~="n"]` of the playing line as well as an
  example's `.segment` (`playing-line`). COLUMN WIDTHS (Seth, 2026-10-18: "adjust column sizes
  (including off the right side, requiring rightward scroll)"): a grip (`.col-rs`) on the right edge
  of every header cell (a template column, a custom column, Free, Notes) drags its `<col>` width;
  `cw=4:300,free:160,x0:120` in the embed (`colWidths` / `setColWidths`, pixels; `spec.extra.cw`,
  round-tripped by flexref like any key); a sized table is `width: max-content` and scrolls
  sideways in `.chart-scroll` (dragging past the pane's right edge scrolls along); double-click a
  grip or ⋯ → "Reset column widths" lets go; the HTML export writes the same `<col>` widths. STICKY
  HEADER ROWS (Seth, 2026-10-18): CSS sticky cannot do it (the table's sticky box is its sideways
  scroller), so `wireStickyHead` keeps a fixed COPY of the thead (`.tchart-sticky`, the live
  columns' widths on its `<col>`s, shifted with the sideways scroll) over the top of the pane —
  under `#sticky-heads` and a collection's / chart note's `.coll-head` — while the header has passed
  the top and the rows are still in view; on the pane's scroll, the chart's sideways scroll, resize
  and a ResizeObserver on the table; it goes with the chart — a 500 ms sweep removes the copy when
  its chart has left the page without a scroll (Seth, 2026-10-19: a header "left behind that never
  goes away" over another note). Not in a cell or the exports (the
  page's print stylesheet repeats `thead` instead). RESIZEOBSERVERS DRAW ON THE NEXT FRAME: every
  observer here (the ghost header, `placeFrozen`, the tag overlays in interlinear.js) queues its
  work in a requestAnimationFrame and writes a style only when it changed — writing layout inside
  the callback is what Chromium logs as "ResizeObserver loop completed with undelivered
  notifications" (Seth's log, 2026-10-19), and a loop that re-lays the page out every frame is
  the likeliest reason the whole-chart dialog and the picker would not scroll for him. FROZEN COLUMNS (Seth, 2026-10-18: "we always
  want the play buttons column to be sticky"; "freeze columns … for custom columns, on either or
  both sides of the chart"): the row-label column (the ▶s) is always `position: sticky` inside
  `.chart-scroll`, and a chart note's custom column when its Place says so; `renderChart` marks the
  cells `data-frz="l|r"` + `data-ck=<column key>` (`frz()`), `placeFrozen` sets each one's `left` /
  `right` from the `<col>` widths of the frozen columns before / after it (a ResizeObserver keeps
  them right); the ghost header copies the offsets and now follows the sideways scroll by its own
  `scrollLeft` (a transform would carry the sticky cells along). A custom column's Place is LEFT or
  RIGHT of the FLEx columns (`xc.side`; `xL` / `xR` in `renderChart`; the export writers split
  `xcols` / `xcells` by index the same way, `side` on the block's xcols); the translation row gives
  every custom column an empty cell so a frozen one never covers the text. ⚑ ON EVERY CHART (Seth,
  2026-10-18: the Great Flood chart, which has no chart markers, "doesn't include a visual filters
  button"): the button is always there on an editable chart, counting the markers AND the text's
  tags; the popover in marker mode lists both (`markersIn(obj).concat(tagsIn(obj))`) and says when
  there is nothing, the filter switches and scopes apply regardless. HIDE COLUMNS: a column
  heading's popover has "Hide this column" (writes `cols=` like the ⋯ menu's checkboxes, which bring
  it back); `empty=off` ("Hide empty columns" in the ⋯ menu) drops the columns with no cell part in
  the rows shown (`visibleColumns` = `selectedColumns` less the empty ones, never all). ZOOM
  (Seth: "zoom in and out option for our chart notes (and chart examples)"): `zoom=NN` (50–200,
  steps of 10, 100 not written; `zoomOf` / `setZoom`, the ⋯ menu's − N% +) sets `--cz` on the
  `.chart-obj`; every font size in `.tchart` is `calc(Npx * var(--cz, 1))`. ONE COLUMN (Seth:
  "collapse the text chart data into a single display column that just displays the row all in one
  cell with visual filters … the option to switch back and forth"): `view=flat` (the head's
  "▤ One column" / "▦ Columns", the ⋯ menu's Layout) — `flatten(obj, spec)` rebuilds the chart with
  ONE template column ("Text") and every cell part of a row on it in the columns' order, its own
  column kept as `srcCol`; the renderer, `chartGrid` / the TSV copy and `export.js chartBlock` all
  take the flattened chart, so the exports follow. Each word group is wrapped (`flatWrap`,
  `.cflat-g`) with its column's abbreviation as a label (`collab=off` hides them) and the look the
  column's rules give it — the SAME `column:<Group/Name>` rules that style chart columns on an
  example (brackets, tile, box, colour, b/i/u, hide), resolved through `tagstyles.resolve` — so a
  visual filter by column or marker does the work the columns did. Styles on `rNcM` targets keep
  their meaning (the part's own column). The parts of ONE chart cell share ONE box (Seth,
  2026-10-18: a marker "should be inside the same border as the cell they apply to"): consecutive
  parts with the same `srcCol` go into the same `.cflat-g` (`flatWrap` returns {wrap, add}).
  THE GROUPS VIEW (Seth, 2026-10-19: "a major-column view … just the 3 parent columns (and then
  style text from sub columns within each cell per visual filter rules)"): `view=groups`
  (`viewOf(spec)` = cols | flat | groups; `isFlat` is true for both flat views) — `flatten` makes one
  column PER HEADER GROUP (`groupNameOf`: the first path element, else the column itself; n = 1000+,
  `guid: group:<name>`, `obj.grouped`), each row's parts on their group's cell in column order with
  `srcCol` kept, so the flat machinery (labels, `columnLook` styles, `applyMovedLooks`, the copy and
  the exports) does the rest; `flatUnitKey` never forms a group unit there (the cell is the group).
  The head's "▥ Groups" (`chart-view-groups`, shown when the template has groups) and the ⋯ Layout
  select. LINE UP ON A COLUMN (Seth, 2026-10-19: in the one-column view "align elements from one or
  more specific columns so that they do line up … center arrange/align, not center of the column,
  not center of the page … other elements just adjacent to the left or right and wrapped as
  needed"): `align=c4,Object` (the `cols=` selectors, `alignedColumns(spec, full)`; the ⋯ menu's "Line
  up on" boxes, flat and groups views only). In a cell holding an aligned column the parts go into a
  3-track `.al-grid`: `.al-l` (before the first aligned run, right-aligned to the axis), `.al-a` (the
  run of neighbouring aligned parts, centred), `.al-r` (the rest); a later aligned part after a gap
  goes right (one axis per row). `alignFlat(table)` measures after the draw (`--al-l` / `--al-a` set
  to max-content, the widest left and anchor across the rows taken, the left capped at 45 % of the
  cell) and sets the two custom properties on the table — a ResizeObserver re-measures on the next
  frame, writing only on change. Which EDGE meets the axis (Seth, 2026-10-19: "line up the left edge,
  right edge, or center of that column"): `alignat=left|center|right` (`alignEdge`, centre when
  unset; the select under the "Line up on" boxes, `chart-align-edge`) puts `al-left` / `al-right` /
  `al-center` on the table and the CSS justifies `.al-a` accordingly. A header GROUP lines up as one
  block (Seth: "either the parent column header or the daughter"): `align=Nucleus` is its columns
  (the `cols=` selectors), and the menu's group boxes (`chart-align-group`) tick them. A row without
  the column flows as before. Not in the exports. MARKER CHIPS ON THEIR OWN LINE (Seth, 2026-10-19:
  "display marker chips on a separate line (to make column widths smaller) … wrap at word width"):
  `chips=line|wrap` (`chipsMode`; the ⋯ menu's "Marker chips") — `addPart(container, node, mode)`
  puts every `.ctag` into one `.chips-line` kept last in its container (a td, a flat group's body, a
  line-up zone), `.void` when every chip in it is hidden; `wrap` adds `.wrap` and `placeChipLines`
  sets each line's `max-width` to the widest sibling (the words) after the draw, with the usual rAF
  ResizeObserver, so a column is never widened by its chips. POPOVERS AND MODALS STAY ON SCREEN
  (Seth, 2026-10-19: settings "running off the screen … including close buttons. That should never
  happen"): every `.popover` has `max-height: calc(100vh - 16px)` / `max-width` and scrolls;
  `FS.popover` pins one taller than the window to the top and sets its `maxHeight` to the room left;
  `.modal` is capped at `calc(100vh - 24px)` with `.modal-body { min-height: 0; flex: 1 1 auto }` so
  the body scrolls and the head stays. The ⋯ menu's "Merged cells" and "Marker chips" rows sit right
  under Layout, before the long column lists.
  A TITLED POPOVER HAS A STICKY HEAD (Seth, 2026-10-20: the ⚑ popover's close "is not clearly visible. It should
  be clearly visible and it should be sticky"): `FS.popover(anchor, build, {title})` prepends `.pop-head` — the
  title and a ✕ (`pop-close`) — sticky at the top of the scrolling popover; the ⚑ popover ("What this chart draws,
  and how" / "FLEx text markup tags on this example") and the chart's ⋯ menu ("Chart options") use it.
  MERGED CELLS (Seth, 2026-10-19, agreed after the question was put to him: "I merge columns when
  I'm unsure which column it is because it could be either"): a part merged with its empty
  neighbour (FLEx's MergesAfter / MergesBefore, on word groups and markers alike) belongs to BOTH
  columns. `mergeMode(spec)` = `both` (default) | `labels` | `lookowner` | `owner` (`merge=` in the embed, the
  ⋯ menu's "Merged cells" select — Seth, 2026-10-20: "that needs to be clear in the documentation", so the README
  row says where; `labels` = both for the data, both NAMED in the flat views, the owner's look only: "both labels …
  but not both borders"; `lookowner` = the owner's look AND name); `mergedNeighbour(part, allCols)` = the TEMPLATE neighbour (flat
  views keep the flags as `srcMergeAfter` / `srcMergeBefore` and clear the real ones, so a group cell
  never spans into the next); `partColumns(part, allCols, spec, forLook)` = [owner, neighbour]. DATA:
  `visibleColumns`'s empty check counts the neighbour as used; `layoutRow(row, cols, allCols)` spans
  only into the template neighbour (with a hidden column between, no span — it once swallowed
  whatever showed next); the line-up and `cellHasWords` use `partColumns`; the pivot counts both;
  `chartnote.rowCtx(…, {mergeOwner})` gives a merged cell both columns' keys (`ctxOpts()` on the
  note); Python `merged_neighbour` adds a MIRROR cell record (`mirror`, `mergedInto`) under the
  neighbour in `_chart_index_rows`, so `col:Verb kabir` finds 3b and the profile counts it under both
  (the picker's row text skips mirrors), and `_chart_spans` emits a second span (`merged: true`), so
  an example's chart-column tags name both. LOOK: the owner's look round the contents, the
  neighbour's round that when it has a written rule and is not already the same group unit — in the
  columns view `td.cmerged` wears the neighbour's look and `.cmerge-in` the owner's; in the flat views
  `flatWrap` labels the part `S+V` and wraps `.cflat-outer` (tint / border / brackets / colour of the
  neighbour) round the owner's `.cflat-g`; `unitOf(i, span)` closes a group unit after the span. The
  Python search always counts both (it cannot see an embed's choice). Exports: the owner's look.
  MERGED CELLS AS A FILTER TARGET (Seth, 2026-10-20: "a special visual filter just for merged cells of any kind? Or
  for merged cells that start with a certain column, so for example PRED that is merged right"): rules keyed
  `merged:*`, `merged:right` / `merged:left` (the side the owner's cell extends into: MergesAfter = right), `merged:<Group/Name>`
  (also the column's name or abbreviation) and `merged:<Group/Name>:right|left` — a fifth namespace in `matches`
  (a drawn part carries `merged: {col, name, abbr, dir}`, `T.mergedItem(col, dir)`; the popover's own rows are
  pseudo-items `merged:*|right|left` in STRUCTURE, `skind: 'merged'`, plus one per present (owner column, side) from
  `structureIn`), ranked column+side < column < side < any (`rank`). `chart.mergedLook(part, allCols, obj, spec)`
  resolves it; `flatWrap` lays its keys over the column look (`lookKeys`), the columns view applies it on the cell after
  the column looks (`.merged-styled`). `addTagPicker` lists `merged:*|right|left` under Chart structure and, under
  "Merged cells, by column", every known column × (either side, right, left); `T.mergedFromKey` names a written key
  in the rule lists. `tests/js/tagstyles.test.js` pins the matching and ranking.
  CHIPS UNDER THE WORDS (Seth, 2026-10-20: in the groups view "on a line of their own" stacked the chips to the right
  of the words): `.cflat-body` is an inline-flex ROW, so a block `.chips-line` was just another flex item — and as a wrapped
  flex item it still COUNTED in the body's intrinsic width (a box twice as wide as its words). `flatWrap`'s `add`
  now puts a chip line (`chips=line|wrap`) in the `.cflat-g` wrapper AFTER the body, a block of its own; `wrap`'s
  `max-width` is the widest non-chip sibling (the body), with a 48px floor (`placeChipLines`).
  COLUMN STYLES (Seth, 2026-10-18: "apply specific styles to specific columns … and configure them
  myself"): the chart's ⚑ popover lists its template COLUMNS after the markers and the text's tags
  (`tagstyles.columnsIn(obj)` — tag items with `column: true`, `opts.fullChart` so the one-column
  view still lists the real columns), each with the full text controls, written as
  `column:<Group/Name>` rules at the chosen scope (this chart's `tags=`, the note, folder, tab,
  text, notebook, a filter) — the same namespace that styles chart columns on an example and the
  one-column view's groups. In the columns view `columnLook(col, obj, spec)` resolves each visible
  column and `applyColumnLook` tints its cells and heading (tile / marker → a tint, box → an inset
  border, colour, b/i/u; `look.styled` = a rule somebody wrote, the palette's default is not a
  style); the user's own cell styles are applied after it and win; a column whose rule says `hide`
  leaves the table (never all of them). `export.js chartBlock` carries the same tint / b / i / u /
  colour into the export model and drops hidden columns. A column heading's popover has "Style
  this column everywhere… (⚑)", which opens that popover. HEADER GROUPS AS ONE (Seth, 2026-10-19:
  "higher level chart columns as visual filter options too … applied as a group, combined to
  everything within, so not 3 minor columns styled the same"): `columnsIn` also lists every header
  group as an item (`column:group:<name>`, "All of Nucleus"); a look whose rule is a group rule
  (`look.styledBy`, which `resolve` now records) is drawn as a UNIT: the group heading wears it,
  the leaf headings do not, and in each row the run of the group's cells (`unitOf` → first / mid /
  last) shares one box — ONE look for the whole unit, resolved for the group item itself
  (`groupLook`; the per-column palette once tinted three cells three colours), the border on the
  outer edges only (`applyColumnLook(node, look, heading, unit)`), the inner cell borders transparent (`.cgrp`); in the one-column view the group's parts
  share one `.cflat-group` wrapper labelled with the group's name (`flatUnitKey`), each column's
  own small label after its words. CHART STRUCTURE AS FILTER TARGETS (Seth, 2026-10-19: "visual
  filter styling … for subordinate clauses (and sub clause marker) and speech and song clauses
  (and their markers) … clauses marked as pre-posed from or postposed from"): `tagstyles.STRUCTURE`
  = pseudo-items `clause:dependent` / `clause:speech` / `clause:song` (the whole row: `skind` row),
  `clauseref` (the [2a] chips: chip colours, hide), `moved:*` / `moved:preposed` / `moved:postposed`
  (the moved WORD GROUP: the full text controls plus `ms` = whose look it wears — its own, the
  column it came FROM, the column it sits IN — and `ml` = its label: ‹‹ / ›› + the home column's
  abbreviation (default), the current column's, or none; `msfrom` / `mlto` in `tags=`,
  `_clean_tag_rules` takes both), and `boundary:sentence` / `boundary:paragraph` (Seth, 2026-10-19:
  "custom style sentence boundaries and paragraph boundaries … last row in sentence, last row in
  paragraph checkboxes in FLEx"; `skind` line: the controls are the line's style, thickness and
  colour only, plus shown / hidden; the renderer sets `--bnd-s` / `--bnd-p` on every `tr.end-sent` /
  `tr.end-para` — the free row that carries the boundary too — from the resolved look, `.bnd-styled`,
  or the ordinary cell border when hidden, `.bnd-off`; the CSS reads the variables); a fourth
  namespace in `matches` (`PSEUDO_RE`; `moved:*` covers both directions, ranked broad), `structureIn(obj)` lists those present with counts, the ⚑ popover
  shows them under "Chart structure", `addTagPicker` offers all seven, `T.structureItem(key)` /
  `chart.pseudoLook` resolve one. chart.js: a clause row gets `.clause-styled` with the look; a
  [2a] chip its colours or `.hidden`; a moved-text marker (which sits in the column the words came
  FROM and names the word group) is collected per row and `applyMovedLooks` styles the target
  `.cwords` after the body is built (`.moved-styled`, `applyGroupLook`: tint / border / brackets /
  colour / B I U, the label as a `sub.moved-lab`), in both layouts (`srcCol` for the current column
  in the flat one). THE ⚑ POPOVER SAYS WHAT IT IS (Seth, 2026-10-19: "UI labels … need to make
  that clear"): its first line explains that ☑ shows or hides an item, Style ▾ sets how it is
  DRAWN, and a visual filter is a named set of the same rules. A group heading carries an ON / OFF /
  PREVIOUS box (`tag-group-toggle`): all shown → all hidden; all hidden → the mix the group had
  (`groupMix`, remembered per scope while the page lives) or all shown; a mix → all shown with the
  mix remembered. A group with nothing in this chart starts FOLDED (`renderTagTree`'s
  `closedByDefault`; the user's own fold choice is kept as true / false in `fs:tagTree`). A missing
  🔍 button was once appended as the text "null" after every row — `row.append(null)` prints it.
  NOT YET: a paragraph-analysis column (Seth, 2026-10-19: "a horizontal, right-angle tree whose
  terminal branches face inward toward the chart lines") — plans/BACKLOG.md › Text Charts. SENTENCE / PARAGRAPH PLAY (Seth: "a play button for 4, not
  just for 4a, 4b, 4c"): `playGroups(rows, segments)` — a SENTENCE is the rows sharing a label
  number, a PARAGRAPH runs up to a row that ends one; the first row of a group spanning several
  rows with timed lines gets ▶§ / ▶¶ (`.chart-play-sent` / `.chart-play-para`) before its line ▶,
  playing the group's lines through the same `playRange`. BOUNDARIES (Seth: "draw that boundary
  UNDERNEATH the free translation row"): a row's `end-sent` / `end-para` class moves to the
  `cfree-row` that follows it when `free=row` puts one there. SELECTED LINES AND ROWS (Seth, 2026-10-20: "copy TSV for individual or multiple selected rows in flex objects
  (either table or IGT) … paste them in a notes document elsewhere as a new example"): a click on a `.segnum`
  (Shift: a range; `toggleLineSel`, `.segment.line-sel`) or Ctrl/Shift+click on a chart row's `.rlab` (or "Select
  this row" in its popover; `chart.toggleRowSel`, `tr.crow.row-sel`) shows `interlinear.selectionBar` above the
  lines / the chart (`sel-bar`: count, ⎘ Copy, Clear). The copy is the selection's OWN reference on the first
  line (`{{flex:text g seg=a-b at=…}}` with the example's lines / ws; `{{flex:chart g rows=a-b at=…}}` with the
  view keys, not cw / ex / indent / collapsed) and `flexTsv` / `chartTsv` of just those lines or rows under it
  (a chart's header rows always); a gap in the selection still pastes as the whole range. `editor.pasteText`
  takes a text whose first line is such a reference followed by tab-separated rows as the reference alone
  (the collection's paste box too); a sheet gets the rows. Ctrl+C (document capture) copies `R.lastSel` when
  nothing editable has the focus and no text is selected. e2e
  `test_selected_lines_and_rows_copy_and_paste_as_a_new_example`.
  A CHART AS AN EXAMPLE AND BACK (Seth, 2026-10-20: "convert a flex text-chart object to a regular
  interlinear example object (including the lines that chart rows touch) or vice versa (text chart touching all
  the lines in the example). They won't line up perfectly, either direction should be inclusive"): the chart's ⋯
  → "Show these lines as an interlinear example" (`to-example`: the lowest `seg` to the highest `segTo` of the
  shown rows' word groups, `at=` from `obj.segments`); an example's ⋯ → "Show these lines as a text chart…"
  (`interlinear.toChart`: `flex_charts(text)` with rows — one → it, several → `FS.pickChart({text})`, which now
  lists one text's charts — then the first to the last row holding words of the example's lines, `at=` the row
  GUIDs). Both rewrite the spec in place (kind, guid, seg, at; lines / ws / styles / view keys dropped, `ex` /
  `indent` / `collapsed` kept, the label kept) and call `onSpecChange`, so the editor, a cell and a collection
  all take it. e2e `test_a_chart_becomes_an_example_and_an_example_a_chart`. CHANGE THE CHART (Seth: "change the
  text chart source for a text chart note or a text chart object, just like I can for interlinear
  objects"): ⋯ → "Change the chart…" → `FS.pickChart` (app.js `chartChooser`, the same list as the
  new-chart-note dialog, the current one marked) → the spec is retargeted in place (`guid`; `seg` /
  `at` / `cw` / `cols` and the styles, which name the old chart's rows and columns, dropped; the
  view settings stay); a chart note first changes its front matter through `opts.changeChart` →
  `Api.set_note_chart` (`Notebook.set_chart`; the values it held stay in the file under the old
  rows' anchors). The chart NOTE kind, the marker filters, the
  chart search / profile / collections and the columns-as-tags are the three bullets below; what is
  still open is in plans/BACKLOG.md › Text Charts.
- CHART NOTES (Seth, 2026-10-18: "a text chart note type (similar to the example collection, except
  that it would focus on one text chart …)" with "custom columns … (a) a user-custom-defined list of
  choices … project-wide … (b) some kind of formula or rule … (c) just an extra notes column …
  searchable"): `kind: chart` + `chart: <guid>` in the front matter (`Note.chart`, `NOTE_KINDS`;
  `Api.create_chart_note(tab, folder, title, guid, view?)` — the title defaults to "<chart> — <text>";
  several notes may share one chart). THE BODY is ours (`ui/js/chartnote.js` `parse` / `serialize`,
  pinned by `tests/js/chartnote.test.js`): the VIEW embed first (`{{flex:chart <guid> lines=… free=…
  cols=… hl=r2 …}}` — every view setting and the user's styling, edited through the chart's own
  popovers / ⋯ menu via `onSpecChange`), any other text kept, then `## Custom columns` (a pipe
  table: Column | Kind (list / notes / rule) | Settings — and a 4th column Place, `left` and/or
  `frozen`, written ONLY when some column needs it so older files stay byte-identical; `side` /
  `frozen` on the column, the dialog's Place select + Freeze box, the heading's ⋯ toggles) and
  `## Values` (Row `1a #<anchor>` | one
  column per stored column) — Markdown tables, so the file reads anywhere and the notebook index
  searches the values for free; rule columns are computed, never stored; values are keyed by the
  row's anchor (its GUID's last 12 hex) so renumbering never moves them. CHOICE LISTS are
  project-wide: `notebook.json chartLists = {name: {options, open}}` (`Api.chart_lists`,
  `set_chart_list(name, options, open, rename)`; options=None and nothing else deletes); a list
  column's Settings is the list's name; an `open` list offers "+ Add an option…" in the cell's
  select. RULES (`parseRule` / `evalExpr` / `applyRule`, `rowCtx` builds what a row offers): cases
  split on `;`, each `<expr> → <text> [styles]` (no → gives ✓), first match wins; terms marker:Name
  (name, abbr or any group name; `*` = any), col:Name (name, Group/Name, abbr, cN, guid), clause:…,
  moved / moved:preposed|postposed, clauseref, endsent, endpara, depstart, depend, the WORD FIELDS
  (Seth, 2026-10-19: "regex for text in a column on any interlinear word field/writing system (or
  any combination to query)"; `FIELDS` / `fieldValues`): `txt:` (= `words:` of old: the word and
  its morpheme forms), `gls:` (= `gloss:`: the word gloss and the morpheme glosses), `pos:` (exact),
  `form:`, `mgls:`, `cf:`, `lex:` (any form), `free:` (the free translation of the line the row's
  words come from — `rowCtx` collects the row's segments), `label:"…"`, and `<ListColumn>:value` /
  `:*`; a VALUE may be a pattern `/re/i` (one token however many `;` `(` `/` it holds — the
  tokenizer takes `key:/…/flags` first; tested on the text as written, NFC, `matchVal`; plain
  values still match the normalised substring), a FIELD may name a writing system `gls@fr:` (read
  from the word's `glsAlts` & co. — present only when the chart carries alternatives; the chart
  reader hands out the default writing systems until asked for more, so the builder offers the
  systems it finds, `chartWritingSystems`), and a term may be scoped to ONE column
  `col:Subject[txt:/^ka-/ and not gls:/x/]` (`{op: 'in'}`: the inner expression sees that column's
  cells only; `col:/^Post/[…]` by pattern); and / or / not / ( ); styles `row` or `cell` (default),
  hl, hl#rrggbb, b, i, u, c#rrggbb — a `row` case styles the whole `tr` (`opts.rowDecor` in
  chart.js). A rule reads the CHART, never the drawing (Seth, 2026-10-19: "the absence or presence
  of a marker in the DATA SOURCE, regardless of whether it's visible or invisible"): a marker
  hidden by a visual filter or the empty-cell switch still counts. The dialog (`columnDialog`)
  tests a rule live against the chart (rows per case). THE BUILDER (Seth, 2026-10-19: "a UI for
  building formulas rather than just a query language"): `ruleBuilder(host, opts)` — Builder / Text
  tabs (`cn-rule-mode`; a new rule opens in the builder, an existing one in Text); each CASE a list
  of conditions joined by all / any (`rb-what`: marker, column, clause type, moved text, row flag,
  the word fields, row label, a list column; `rb-how`: is / any / contains / matches pattern; the
  value from the chart's markers / columns or typed; `rb-ws` a writing system; `rb-incol` "in
  <column>" = the `col:X[…]` scope), the text shown (`rb-out`) and the style (scope, highlight, B I
  U, text colour); it WRITES the rule text (`casesText` / `condText`) on every change, and READS one
  back (`casesFrom`: a flat and / or of terms, `not` terms and `col:X[term]` scopes; anything
  cleverer is left to the Text tab with a note). `tests/js/chartnote.test.js` pins the terms.
  MARKER CHIPS AND JOINED ROWS (Seth, 2026-10-19: "custom columns … show chips (or custom text
  chips or styling) for specific markers"; a `^ShdArg` row shares its argument with the row above —
  "remove the border between them and custom style a range on those rows"): an output token
  `@markers` / `@markers:Name` / `@markers:group` / `@markers:/re/` (`case.chips`, resolved by
  `applyRule` against `ctx.markerItems`, the row's tag items; `markerIs`) draws the matching markers
  as `.ctag.xmark` chips in the look `chart.markerLook` gives them; the style token `chip` draws the
  text as a `.ctag.xchip`; `join` puts `join-up` on the row (`rowDecor.classes`) and the renderer
  gives the previous `tr.crow` `join-down` and the case's row style (`d.joinStyle`; `lastCrow` in
  `renderChart`) — CSS makes the shared border transparent. A pattern on `marker:` / `col:` is tested
  on the names AS WRITTEN (`ctx.markerItems`, `cell.raw`), never on the lowercased keys, so
  `/^(New|Given)$/` works; a `col:X[…]` scope also sees the MARKERS in that column (a tag cell is a
  cell too, with `tags`). The builder's Show row has the chips select (`rb-chips`, named / pattern)
  and the toggles "as a chip" / "join with the row above". REGEX FLAVOURS (Seth, 2026-10-19: "which
  type of regex … a link to a regex builder site"): `FS.REGEX_FLAVOURS` / `FS.regexHelp(flavour)`
  (util.js) is the link every pattern-taking place shows — `js` (the page's RegExp: rules, builders)
  or `py` (Python's re: the chart search) — opening regex101 set to that flavour through
  `FS.openWeb` → `Api.open_web` (http(s) only; the mock uses window.open). README › Query languages
  documents the notebook search, the chart search and the rule language with the flavour
  differences (FLEx's own Find is .NET). THE CHART SEARCH IS ONE CLICK AWAY (Seth, 2026-10-19: "easy
  to find and … visually creatable"): the toolbar's `#btn-chart-search` / Ctrl+Shift+K →
  `FS.searchCharts()` opens the picker on Text charts (in a chart note or a collection the picked
  rows go into a NEW note "Chart rows"); the picker's Text charts tab has "☰ Build a search…"
  (`chart-search-build`) → `chartnote.searchBuilder` (`FS.chartSearchBuilder`): one "in column" and
  a list of conditions (`sb-what` / `sb-how` / `sb-val`, not), the query shown as text (`search-q`)
  with a live row count, Search → the box; `searchText` / `searchFrom` round-trip the flat language
  (`-`, `col:`, `/re/i`), and the tab's footer lists the terms with the Python regex link. DRAWN by `FS.chart.renderChart` through `opts.extraCols` (`th.th-x` with the
  column's ⋯: rename / settings, move, remove with Undo; `td.xcell` — notes: click → textarea, Enter
  saves; list: click → select; rule: the text, styled) after the FLEx columns and before Free /
  Notes; `opts.onObject` hands the owner the fetched chart (the header, the rule preview).
  app.js: `isChartNote()`, `isSpecial()` (= collection or chart note: the block editor is not the
  view — every editor guard uses it), `ensureChartNote()`, `newChartNoteDialog()` (New ▾ → "New chart
  note…", a list of the project's charts), `FS.newChartNote(guid, view)` (a chart embed's ⋯ → "Open
  as a chart note…" carries its view over), the `#chartnote` host, the "Chart" badge on the card.
  Exports: `asEditor()` gives the view embed with `extras` (`exportExtras()`: the custom columns and
  the rule / marker row styles, read by export.js `chartBlock`) and then the note's own text as
  markdown blocks — see EXPORTS below. The in-browser mock has `create_chart_note`, `chart_lists`,
  `set_chart_list`.
- CHART MARKER FILTERS AND CHART SEARCH (Seth, 2026-10-18: "visual filters using textchartmarkers
  instead of textmarkuptags … 'row-level' markers, so that when they are found anywhere in a row,
  that whole row is styled"; "FLEx does not give us great ways to search text charts … returning
  cells or rows with a certain text chart markers or which column a certain lexical item is found
  in"). MARKERS go through the SAME scoped rules as the text tags (tagstyles.js): a marker is a tag
  item with `marker: true` (`T.markers()` / `loadMarkers`, `markersIn(obj)` from a chart's tag
  cells) and its rules are keyed `marker:<name>` / `marker:group:<g>` / `marker:*` — `matches`
  keeps the two namespaces apart (a tag rule never touches a marker and the reverse), `rank`
  strips the prefix. A rule's `row` flag (`row` in `tags=`; `controls({marker: true})` shows
  "whole row" + a text colour and hides the text-only controls) styles the WHOLE `tr` the marker
  is in (`.marker-row`, `data-marker-row`, the colour at 0.45 alpha), else the chip; `hide`
  drops the chip (`.ctag.hidden`). MARKERS IN CELLS WITH NO WORDS (Seth, 2026-10-19: "show or
  hide markers associated with empty cells (and … configure this for specific markers)"): the ⋯
  menu's "Markers in cells with no words" writes `emptymarkers=off` (a VIEW setting in `spec.extra`,
  round-tripped like any key); a marker rule's `empty` / `noempty` (`empty: true|false` in the rule,
  `resolve` → `look.onEmpty` / `emptyVia`, the marker controls' "in an empty cell" select,
  `tag-empty`; `_clean_tag_rules` keeps it) overrides the switch for that marker; `chart.markerShown
  (look, spec, cellHasWords)` decides, the chip becomes `.ctag.hidden[data-empty]`, the export
  model follows (`export.js chartBlock`). A cell "has words" when a word-group part of the SAME
  column (its `srcCol` in the one-column view) sits in it. The chart's search and rule columns are
  untouched by it. A ONE-COLUMN BOX THAT HOLDS NOTHING VISIBLE DRAWS NOTHING (Seth, 2026-10-19:
  "if whatever chips were in that cell are invisible, then the cell border, tile or whatever
  shouldn't draw"): `flatWrap` counts the chips it was given that are not `.hidden` and marks the
  wrapper `.cflat-void` (display none) when there are none. The chart's ⚑ N button → `examplePopover(…, {markers: true})`
  (the same scope select: this chart / note / folder / tab / the TEXT / the notebook / a filter);
  `addTagPicker` lists the Chart Markers under their own heading (`marker:*`, groups, leaves);
  the scope dialog shows marker rules as their own rows after the tags. SEARCH
  (`FlexService.chart_rows` — one record per chart row across every chart, built from the
  snapshots on first use and dropped by `refresh(indexes=True)`; `chart_search(q)`;
  `chart_profile(term)`; `Api.chart_search` / `chart_profile`): the query is words (the row's
  words, glosses, morpheme forms, lexeme forms, notes), `col:Subject` (name, Group/Name, abbr,
  c3; content terms then apply to THAT column's cells, and `hits` names the matching columns),
  `marker:Topic` (or its group; `*`), `lex:kabir`, `gloss:dog`, `word:`, `form:`, `pos:n`,
  `clause:speech`, `moved[:preposed]`, `clauseref`, `endsent`, `endpara`, `chart:`, `text:`,
  `template:`, `row:2a`, `note:`; `-key:value` excludes (a bare `-mo` is the suffix "-mo").
  `chart_profile` counts the cells holding a term per template and column, with their rows
  (`chartProfileDialog` in app.js: a bar per column, the rows under a count, "Collect…"). The
  picker's Text charts tab lists the matching rows under the charts when something is typed
  (click → the chart at that row; "Insert all N as rows"; "Column profile…" when the query has
  lex: / word:; "Collect into a new collection…"). CHART COLLECTIONS: a rule may be
  `{charts: "<query>"}` (`rule-charts:` in the file; `clean_rule`, `rule_from_meta`;
  `rule_matches` dispatches to `chart_search`), its matches written as `{{flex:chart <guid>
  rows=n at=<anchor>}}` (`match_embed` / `match_keys` by anchor and by number; `example_keys`
  reads `rows=` too), so `create_rule_collection` / `update_rule_collection` ("⟳ Find new
  rows") work unchanged; `collection.js` takes chart rows as cards (kind chart in `parse` and
  `add`; `flextextItems` keeps texts only, so the .flextext export skips them); the rule bar
  shows the query; `chartCollectionDialog` (app.js; `FS.chartCollection(query)`) makes or edits
  one (`ruleCollectionDialog` routes a chart rule to it). `EXAMPLE_LINE_RE` counts chart rows
  as examples.
- CHART COLUMNS ON EXAMPLES, TEXT TAGS IN CHARTS, PIVOTS (Seth, 2026-10-18, "MAYBE (more advanced)":
  "show textmarkup tags in charts … or … style spans of non-chart interlinear text objects that
  are mapped to text chart columns"). A text object carries `chartSpans` (`FlexService._chart_spans`:
  every word group of the text's charts from the snapshots — {chart, chartName, template, row,
  column: {guid, name, abbr, path}, from, to}; attached live and offline); a chart carries the
  text's `tags` (`lcm._chart_dict`, the demo). ON AN EXAMPLE the `cols` pseudo-line (flexref
  `LINES`, `showsCols`; off by default; "Chart columns" in the ⋯ lines menu) turns the spans into
  SYNTHETIC TAGS (`interlinear.chartTags` / `withChartTags`: tag items with `column: true`, name
  `Group/Name`, abbr the column's; `segTags` and `renderText` apply them), so the whole tag
  machinery draws them — bars, brackets, tiles, the ⚑ popover, exports — and rules key them
  `column:<Group/Name>` / `column:group:<g>` / `column:*` (a third namespace in `matches`, apart
  from tags and markers; `T.columns()` lists the columns seen, `noteColumn` registers them, the
  picker has a "Chart columns" section). IN A CHART `lines=…,tag` ("FLEx tags" in the ⋯ lines row;
  off by default) draws the text's markup tags on each cell's words as `.ctexttag` chips in the look
  their scopes give them. PIVOT (`FS.chart.pivot(obj, spec)` / `pivotDialog`; the chart's ⋯ →
  "Pivot: markers × columns…", a chart note's "Pivot…"): rows = each marker, clause type, moved
  text and clause marker; columns = the visible template columns; a cell counts the rows carrying
  the marker with words in the column; Copy as TSV. The entry card's "▦ In charts" opens the
  column profile for the lexeme form (`FS.chartProfile`).
- EXPORTS (Seth, 2026-10-18: "pretty exports for chart-type notes. HTML, DOCX, Excel, and PDF … for
  our collection-type and regular notes, too … including audio players and base64 embedded audio
  where audio files and segmentation data are available and match"; "Slideshow HTML export (and
  PowerPoint?)"). ONE MODEL: `FS.exporter.buildDoc(note, editor)` (export.js) turns a note into
  `{title, where, project, date, blocks}` — the shapes in docx_writer.py's docstring; a chart block
  carries `columns`, `xcols` (a chart note's custom columns), per row `xcells`, `rowStyle` (a marker's
  whole-row look, a rule's row case — `tint()` blends the app's alpha onto white), `segs`, per cell
  `segs` and `plain` {txt, gls, marks, moved, clauses}; an interlinear segment its `begin / end /
  media`. Every writer reads that model: `toHtml` (the page), `toSlides` (the slideshow),
  `docx_writer.build_docx`, `xlsx_writer.build_xlsx`, `pptx_writer.build_pptx` (from `slidesOf(doc)`),
  the PDF (the page, printed). A collection exports through `asEditor()` as before; a chart note's
  `asEditor()` adds `extras` (CHART NOTES). THE PAGE (`toHtml`): a header (title, tab › folder, FLEx
  project, date), the stylesheet `CSS` with a print half (`@page landscape` and `body.wide` when the
  note holds a chart, `thead` repeated, rows never split, colours kept, players hidden), a footer.
  AUDIO IN THE PAGE: `timedBlocks(doc)` = every example and chart with timed lines; `embedAudio(doc)`
  asks Python for ONE clip per object (`Api.export_clips` → `FlexService.export_clips`: `ensure_clip`
  from the object's first timed begin to its last end — the cache, else the live file — then
  `audio.encode_for_embed`: Opus in Ogg at 40 kb/s mono through ffmpeg, MP3 when there is no Opus,
  the WAV / FLAC slice itself without ffmpeg; the copy is kept as `<clip>.export.ogg`, a name
  `find_audio_clip` never mistakes for the clip) and puts it in the block as a `data:` URL
  (`block.audio = {id, src, begin, segs: {n: [b, e]}}`); the markup is an `<audio data-a data-begin
  data-segs>` per object and a `button.play[data-a][data-segs]` per line, per example and in a
  chart's `#` corner and first rows (the same `lineStarts`); `PLAYER_JS`, a plain script in the page,
  seeks inside the clip, lights `.seg[data-n]` / `td[data-segs~=n]` (`.playing`), and runs the `#np`
  bar (pause, stop, seek, Esc). `askEmbedAudio` asks first (the file grows ~300 KB a minute
  compressed); an object whose recording is not there exports without a player. THE SLIDESHOW
  (`slidesOf` → `toSlides`): a title slide; every heading starts a slide; every example, chart,
  table, entry and picture gets a slide of its own, titled by its section, a short lead-in line
  ending in ":" riding along; running text fills slides and continues on "(cont.)" slides;
  `SLIDES_CSS` / `SLIDES_JS` scale a 1280×720 slide to the window and shrink content that overflows,
  keys → ← Space PgUp/PgDn Home End, T contents, F full screen, P print (one slide a page), `#n`
  in the URL; the players ride along. COLLAPSED OBJECTS AND CHIPS (Seth, 2026-10-18: "When not
  expanded, then just a text abbreviation or title and line range that is a hyperlink to that text
  in FLEx"): `linkRun(spec)` — a block embed with `collapsed`, every inline chip, and an object in
  a table cell unless `expanded` — exports as ONE run: the text's abbreviation (its title when it
  has none) + its FLEx line numbers (`chipRange`), a chart's name + rows, an entry's headword,
  `href` = the object's `silfw://` link; every writer shows it as a link (Word: an external
  hyperlink relationship). WORD (docx_writer): every table writes `<w:tblGrid>` with widths from
  its content (`grid_widths`; LibreOffice shows nothing without it) and every cell ends in a
  paragraph; a CHART gets a LANDSCAPE section of its own (`SECT_PORTRAIT` / `SECT_LANDSCAPE`
  paragraphs around it, never inside a table cell), its label column narrow, its cells' words as a
  nested borderless `wordgrid` (each word's lines under it) plus a line of marker chips, custom
  columns and row shading. EXAMPLES IN WORD ARE LINGTEX-WORD TABLES (Seth, 2026-10-18: "all of our
  IGTs should be rendered using LingTeX Word styling wherever they're expanded"; the add-in is
  `rulingAnts/LingTeX-Tools/LingTeX-Word`, a REFERENCE clone at `/home/user/rulingants/lingtex-tools`,
  never changed from here; its `src/modStyles.bas`, `modRender.bas`, `modFlexParse.bas` are the
  spec): per line of text ONE table styled "LingTeX Interlinear" (borderless, no cell margins, fixed
  layout; the table style IS the add-in's tag, so a document with the add-in re-wraps ours), one row
  per tier whose paragraphs carry the tier style — "LingTeX Vernacular" and "LingTeX Morphemes"
  (italic, Charis SIL pinned), "LingTeX Gloss", "LingTeX Word Gloss", "LingTeX Category" (our lines
  map txt→Vernacular, morph/cf→Morphemes, mgls→Gloss, gls→Word Gloss, pos/tag→Category, `LT_ROLES`),
  all based on Normal, size inherited, tight, left, `noProof`; GRAMMATICAL GLOSSES in the three
  meta-language tiers are found structurally (`is_gram_gloss`: all capitals or digit-initial, a lone
  capital or "N." is not), split on `- = ~ < >` and `. : ;` (`split_gloss_segments`), LOWERCASED with
  the first letter kept (`small_caps_form`: Erg, 3Sg — Word's small caps only shrink lowercase
  letters) and set in the "LingTeX Gram Gloss" character style (`<w:smallCaps/>`); the baseline's
  spaces become NBSP; the FREE translation is a "LingTeX Free" paragraph AFTER the table in ‘single
  quotes’ (6 pt above, 3 pt after, indented past the number column), the literal translation and
  notes the same style, and the SOURCE (text title + FLEx line) follows the free translation as a
  small grey hyperlink into FLEx (the block's `url`); the NUMBER, when the embed is `ex`-numbered,
  is Word's own: a first cell 36 pt wide whose paragraph is "LingTeX Example" (linked to numId 1 =
  the "LingTeX Example Number" list in numbering.xml, "(%1)" at level 0, "%2." lowerLetter at level
  1), and an example of several lines gets a second cell "a.", "b."… (level 1) with the number on
  the first line only — LingTeX's xlist shape; a long line WRAPS into further row groups of the same
  table (ragged rows, `cantSplit`, 6 pt between groups); the app's own line colours
  (`LT_BASE_COLORS`) and sizes are dropped (the styles carry the look), the user's highlight / bold /
  underline / colour stay (`lt_clean`). `tests/test_export.py::test_docx_examples_are_lingtex_word_tables`.
  Not written: a Word document SETTING for the add-in (it reads its settings from document
  variables); its defaults match what we write. EXCEL (xlsx_writer, inline rich strings,
  styles built as used, merges, frozen headers): sheet "Note" (the blocks in order, an example as
  rows per line with the words across, the chart named and pointed at its sheet), a sheet per chart
  ("Chart", "Chart 2"…: the table with merged header groups, two-colour `word⏎gloss` cells, Free
  / Notes / custom columns, the row colours) with "Chart rows" after it (one FLAT row per chart row:
  label, clause type, flags, each template column's words and then their glosses, markers, moved
  text, clause refs, custom columns, free translation, notes — what Excel filters and pivots), and
  "Examples" (one row per interlinear line across the note). POWERPOINT (pptx_writer: the smallest
  package PowerPoint opens — one master, one blank layout, a theme; checked in LibreOffice): a title
  slide on blue, a heading bar per slide, text as paragraphs, an example as a borderless table per
  line (fonts shrink to fit, `fit_widths` from the words), a chart as a table filling the slide
  (header groups merged, a cell's words on one line and glosses on the next, markers, Free, custom
  columns, row fills), a Markdown table, an entry, a picture; no audio (the slideshow carries it).
  PDF (`Api.export_note_pdf` → pdf_print.py): on Windows a HIDDEN pywebview window loads the page
  (a `file://` temp file in `.scratchpad/export-tmp`) and `CoreWebView2.PrintToPdfAsync` writes the
  PDF (landscape when the page says so, backgrounds on) — pywebview exposes none of this, so the
  WebView2 control is reached through `window.native.browser.web_view.CoreWebView2` with every step
  guarded; anywhere else, or when that fails, `{"fallback": True}` and the page prints the same
  HTML in a hidden frame (the browser's dialog has "Save as PDF"). NOT YET RUN ON WINDOWS: the
  direct PDF; when it fails the log says "direct PDF: …". The note menu: Markdown, Web page,
  Word, Excel, PDF, Slideshow, PowerPoint (+ FLEx text for a collection). Tests:
  tests/test_xlsx.py (openpyxl reads it back when installed, dev only), tests/test_pptx.py,
  tests/test_pdf_print.py, tests/test_export.py, the e2e `test_html_export_embeds_the_recordings_as_players`
  (the written page is opened in a second tab and plays), `test_a_chart_note_with_custom_columns`
  (HTML, Word, Excel of a chart note), `test_a_chart_plays_its_lines_and_lights_their_cells`. Look
  at the outputs when a writer changes: LibreOffice (`soffice --headless --convert-to pdf`) renders
  .docx / .xlsx / .pptx here, `pdftoppm` makes PNGs of them.
- TROUBLESHOOTING LOG (Seth, 2026-10-18: "make our cli, interpreted python very verbose so that it's
  easy to troubleshoot … What I install and test via pip install, I'd like to see verbose debugging
  output to tty that I can copy and send to you"): `flex_scratchpad/log.py`. From a pip install in a
  terminal the console gets DEBUG: every Api call with its arguments, result in short and time
  (`log.logged` wraps every public method of `Api` at import; secrets, passwords and file bytes are
  REDACTED — `tests/test_log.py`), every LCM worker call with its duration (`LcmWorker.call`), the
  raw flexicon exception behind every friendly message (`_friendly`), FLEx source open / snapshot
  fallbacks, notebook writes, the window's lifecycle, and the page's own errors (`api.js
  clientLog`: window.onerror, unhandled rejections, console.error / warn → `Api.client_log`, ≤ 40
  a minute). The frozen windowed exe has no console and only writes the file. ALWAYS a log file:
  `<local data folder>/log/flex-scratchpad.log` (INFO, 1 MB × 3; `FLEX_SCRATCHPAD_LOGFILE=` moves or
  disables it). `-v` / `--verbose`, `-q` / `--quiet`, `FLEX_SCRATCHPAD_LOG=level`. `--devtools`
  (`--debug` still works) turns the browser developer tools on; WebView2 opens them in their own
  window (F12 in the app, or right-click → Inspect). Nothing in the log must ever hold a secret.
- TEXTS USED (Seth, 2026-10-16: "list which texts are referenced in a [note], a folder, or a
  selected range … not individual items, but texts they come from … a FLEx hyperlink for each"):
  `Api.texts_used(scope)` → `FlexService.texts_used` — one row per source TEXT (the guid of every
  `{{flex:text …}}` and `(flex:text/…)` link), with its example and link counts, the notes it is
  in, its title (snapshot cache, else the open project) and its `silfw://` link. Scopes: a note,
  the highlighted part of it (`markdown`), a folder WITH its subfolders, a whole tab. The dialog
  (`textsUsedDialog`, app.js) is in the note menu ("…in this note" / "…in the selection"), the
  folder and tab menus, and a collection's selection bar; Copy list / Copy with FLEx links (a
  Markdown list of links) put it on the clipboard.
- ATTACHED FILES (Seth, 2026-10-17: "attachments embedded in notes with a chip that opens the file
  with its default associated app (or if it's an HTML file, an inline HTML previewer with the
  option to open it in a browser)"): `{{file <ref> [preview] [h=N] [indent=N] "label"}}`, parsed
  by flexref.js like any embed (`kind: 'file'`, `ref`; the ref is percent-encoded only for
  % space " { } | and controls, so Unicode names stay readable). COPIED by default into
  `<notebook>/attachments/` (at the ROOT, not per tab, so a chip moved to another tab's note still
  finds its file; never a tab, never scanned; same name + same content is reused, another file
  becomes `name (2).ext`, nothing is overwritten) → `attachments/<name>`; LINKED on request
  (▾ next to 📎 Attach, Alt+click, Alt+drop) → an absolute path. A relative ref may never leave
  the notebook (`Notebook.resolve_file`). `ui/js/files.js` draws the chip (in a line), the card
  (a line of its own; `preview` shows the file IN the note, `h=` its height, dragged on the grip)
  and the in-cell chip; `FS.interlinear.render` / `hydrateInline` hand `file` specs to it. A click
  opens the file in its Windows program (`Api.open_file` → `os.startfile`), a web page opens the
  PREVIEW panel instead (Open in browser there); a web page is always shown in an
  `<iframe sandbox="allow-scripts allow-popups allow-forms allow-modals">` — its scripts run (a
  flextext-editor .preview.html plays), the app window and `pywebview.api` are out of its reach
  (the e2e test checks both). A program or script (`api._KINDS["program"]`) is never started: the
  click shows it in its folder. Dropped files: only pywebview's own drop handler learns a file's
  path (`app.py` registers `api._on_drop` on the document; the editor's drop must NOT
  stopPropagation), the page claims it by name (`attach_dropped`, waits ≤1.5 s) and falls back to
  sending the bytes (`attach_data`, copy only). Pictures and videos come with `preview` on (Seth:
  "dragging in images and videos would also work"); a pasted SCREENSHOT keeps the old `![](…)`
  path, a pasted file is attached. Exports: Word / HTML / PDF write 📎 label as a link to the
  file (`href` runs; docx hyperlinks are external relationships), the Markdown export copies the
  copied files into an `attachments/` beside the .md, the notebook zip has them anyway; excerpts
  read a file as its label or name. A file dropped outside the note is refused (app.js), never
  allowed to navigate the window to it.
- BACKUP & STORAGE (Seth, 2026-10-17: "a backup with rclone option … S3 compatible … store secrets
  securely or put them in Windows' equivalent of keychain"; "ordinary user cloud drive storage …
  OneDrive / Google Drive / Dropbox sync folder … a simple file browse operation that makes an
  educated guess at the correct folders"; "cleanup options and storage size tracking … how much
  storage space is used by their backup and … their note data folder"). Decisions (Seth, same day):
  rclone BUNDLED like ffmpeg (`tools/fetch_rclone.py`, its own release checked against its
  SHA256SUMS, `<app>/rclone/rclone.exe`); a MIRROR that keeps old versions (`<dest>/current/` +
  `<dest>/versions/<YYYY-MM-DD_HHMMSS>/` holding what each backup replaced or removed — rclone
  `sync --backup-dir`, or `backup._mirror_folder` in plain Python for an unencrypted folder); on
  demand + ON CLOSE (app.py starts `<exe> --backup --notebook …` detached and windowless, only when
  `Backup.needed()`: set up, on, and the notebook's `tree_stamp` differs from the last good one);
  encryption OPTIONAL, off by default (rclone `crypt`). `flex_scratchpad/backup.py` is the engine,
  `ui/js/backup.js` the dialog (Settings › Backup & storage…, and the ☁ line under the FLEx pill).
  SECRETS (`secrets_store.py`): the access key ID, secret key and encryption password go to the
  Windows Credential Manager (advapi32 CredWrite/CredRead through ctypes, generic credentials
  "FLEx Scratchpad/backup/…", persisted for this account on this computer); off Windows a mode-600
  file stands in. The page sends a secret once and only ever learns WHETHER each is set; rclone
  gets them only through its environment (`RCLONE_CONFIG_FSBACKUP_*`, the crypt password through
  `rclone obscure -` on stdin) with `RCLONE_CONFIG` pointing at an EMPTY file of ours, and the
  user's own `RCLONE_*` variables are dropped: nothing secret on a command line or in a file, and a
  user's rclone.conf is never read (tests/test_backup.py checks every rclone call through a
  stand-in). A backup folder may not be inside the notebook nor hold it. Cloud folders are guessed
  by `cloud_folders()` from each program's own settings (OneDrive's variables, Dropbox's
  info.json, a drive holding "My Drive", iCloudDrive, Box) and the suggestion is
  `<cloud>/FLEx Scratchpad backup/<notebook>`. STORAGE: `Notebook.storage()` by kind (notes,
  attached files, pasted pictures, FLEx snapshots, cached clips, trash, other), the backup's
  `usage()` (current + each version); cleanup = remove chosen versions, or "keep old versions N
  days" (`keepDays`, applied after each good backup; the current copy is never pruned), unused
  attachments → the TRASH (a file a trashed note uses still counts as used), Empty the trash (the
  one real deletion, asked first), clear cached audio clips. Snapshots are never offered for
  cleanup: they keep notes readable without FLEx. `--selftest` checks rclone and a Credential
  Manager round trip on Windows. Not verified on a real Windows / real bucket yet.
  PROGRESS (Seth, 2026-10-17: "a progress bar on the backup … percent/ETA … (or when they exit)",
  and it must say plainly that it FINISHED): `Backup.report` → `py:backup` events {phase
  scanning|copying|finishing|done, percent, done/total bytes, files/filesTotal, eta}; the folder
  mirror plans first (so the total is known) and copies in 1 MB pieces; rclone runs with
  `--use-json-log --stats 1s` (its stats + eta). Updates are throttled to 5/s but a new phase or
  the 100% is never dropped. `backup.js progressBar()` = an animated stripe until a percent is known,
  then % · files · size · time left; the dialog's bar has Cancel (`Api.backup_cancel`: between
  pieces, a `.part` is never left) and STAYS at the end — green "✓ Backed up at 10:42 — 3 files
  (2.1 MB) copied to …" (`_summary`), or red; the ☁ line fills while it runs. CLOSING: the window
  no longer closes first — `on_closing` returns False while `app.backup_then_close` backs up with
  the page's locked "Backing up before closing" screen (bar; Close without backing up / Close now,
  finish in the background → the old detached `--backup` process; after a failure Try again /
  Close anyway; ✕ again = background), then destroys the window. THE ANSWER IS ACTED ON AT ONCE
  (Seth, 2026-10-18: "Close and finish backup in background" appeared to do nothing): the run is on
  its own thread; a choice cancels it and waits `CLOSE_GRACE` (3 s) for it to stop cleanly, then
  closes anyway; `_mirror_folder`'s planning and clean-up walks (slow on a cloud-synced folder, and
  uncancellable before) now answer the cancel too; the quiet `--backup` process retries a busy lock
  for up to two minutes, since the window's run may still be letting go of it.
- Exporting a collection's examples as a `.flextext` (`flex/flextext_writer.py`, `Api.export_note_flextext`,
  Seth, 2026-10-16): one `<interlinear-text>` PER BASELINE WRITING SYSTEM (a FLEx text has one
  vernacular WS), and since 2026-10-17 each in its OWN FILE, `<name> (<ws>).flextext`, titled
  `<title> (<ws>)` (Seth: "handle different baseline writing systems gracefully … one different
  text for each"; the Audio Segmenter gives no recording to a file holding several texts —
  `importFile` in flextext-editor's app.js); `oneFile` puts them together again. One paragraph per
  example, one phrase per segment, every writing-system
  alternative as its own `<item lang>` (backends attach `*Alts` only when asked: `get_text(…,
  alts=True)` / `get_object(…, alts=True)`, see `model.fill_alts`). Text / paragraph / phrase
  GUIDs are NEW (an original GUID would make FLEx's import touch the source text); word GUIDs
  are kept so the import reuses the analyses. A Source note per line (title, FLEx number,
  GUIDs) and, optionally, a `flexscratchpad://note/<id>` link and the note's markdown as the
  text comment. Audio (`opts.audio`, the user's choice in the dialog; Seth, 2026-10-17:
  "default to concatenated"): `bundle` (default) = the text's ONE media file, a 16-bit mono WAV
  NAMED LIKE ITS .flextext and beside it (the Segmenter pairs a text and a recording by name,
  `satBase`), one piece PER EXAMPLE ("an example that's multiple lines long … treated as a unit.
  So per flex object, not per flex text line": cut once from its first timed line's begin to its
  last one's end, so its lines keep their own timing and pauses) with a generated CLICK between
  examples only (500 ms silence, 5 ms 2 kHz fading sine, 500 ms silence — the Visual Stimulus
  Kit's joiner, `videoannotationtool/vat/audio/joiner.py`; its peak is the quieter neighbour's,
  0.03–0.5), offsets rewritten (`audio.concat_clips`, `FlexService.bundle_audio`); `clips` = one
  small 16-bit mono WAV PER LINE (`audio.to_mono16`, `FlexService.clip_audio`) in
  `<name>-audio/`, each phrase pointing at its own `<media>` from 0 to its length. Either goes
  into a chosen folder instead — inside a LinkedFiles tree the locations are relative to it
  (`AudioVisual/x.wav`, as FLEx stores media); `original` keeps the source recordings and
  offsets; `none` drops timing. Checked against the Segmenter's own reader
  (`parseFlextext` + `segmentsFromOffsets`, run in node with its `test/lib/mini-xml-dom.mjs`):
  one text per file, ordered spans.
  ⚠ VALID BY THE SCHEMA IS NOT IMPORTABLE (Seth, 2026-10-16: an export stopped FLEx with "Object
  reference not set…" on one `<word/>` with no items, and the file passed the XSD). FLEx reads a
  .flextext with XmlSerializer and never validates it; `BIRDInterlinearImporter.cs` assumes more
  than `FlexInterlinear.xsd` says. So every export passes TWO checks: `tests/test_flextext_schema.py`
  validates every export shape against a verbatim copy of FieldWorks' XSD
  (`tests/fixtures/FlexInterlinear.xsd`; `lxml`, dev only), and `flex/flextext_check.import_problems`
  (stdlib, the importer's own assumptions with the source line behind each) runs in the export
  itself, which refuses to save a file FLEx would fail on. The writer never emits a word without a
  txt/punct, puts the baseline WS's item FIRST (the importer builds the baseline from the first),
  drops a morpheme line with a missing form, keeps morph types to the XSD's list and skips empty
  paragraphs. `RightToLeft` on `<language>` is not in the XSD but FLEx's own exporter writes it, so
  we do too. When FLEx changes, re-read those two files in sillsdev/FieldWorks before trusting either.
  Save dialogs (`Api._save_dialog`) make the suggested name Windows-safe (a "/" in a title lost the
  extension) and always end the path in the suggested extension.
- CLOSING THE APP (Seth, 2026-10-17: "Unhandled Exception: Python.Runtime.InternalPythonnetException:
  Failed to create Python type for System.ComponentModel.InvalidAsynchronousStateException" on
  close): a thread calling into .NET after the window's UI thread ended, while Python was already
  tearing pythonnet down. `app.shut_down` (after `webview.start` returns) stops `_emit`, the link
  poller and FLEx and waits ≤5 s for an Api call still writing; `__main__` then ends the GUI
  process with `app.exit_now` (`os._exit`), never through the interpreter's shutdown. Anything
  that must reach disk is written synchronously before that — never put it in an atexit handler.
- `flexscratchpad://note/<id>` (`links.py`): registered per user (HKCU) at start on Windows; a
  second instance hands the URL to the running one through `open-request.txt` in the local data
  folder (polled; no sockets) and exits; one instance is kept by a lock file. The second start
  also hands over its build (`#build <id>`); when it differs from the running window's, that
  window says to close and restart (`FS.otherBuild`), and the terminal says it was already
  running. `build_id()` (package `__init__`) fingerprints the installed files; Settings and
  `--version` show it. Updating from a branch needs `pip install --force-reinstall --no-deps`
  (the version stays 0.1.0, so `--upgrade` keeps the old copy). Off Windows the
  registration is a no-op and the link is plain text.
- Sharing check (`_sharing_status`): `shared` is True only when the open cache's
  `ProjectId.Type` says shared, else `null` (unknown) — Seth's shared project read as plain XML
  on 2026-10-16, so "not shared" is NEVER concluded from it; a real lock error is the signal.
  `flexHasItOpen` from `<project>.fwdata.lock` is a guess too; the UI says nothing on `null`.
  Progress messages (`py:progress`) show in the pill only while they last; an empty message or
  20 s of silence restores the state, and the LCM index sends an empty one when done.
- THE RAIL'S PARTS (Seth, 2026-10-18: "the left pane is now too crowded … the borders of each part
  can be vertically dragged and collapsed/expanded. We don't ever want something hidden beyond
  recovery in that pane"): `#rail-body` is a flex column of `.rail-section`s (Tabs, Folders, Tags,
  FLEx tags; `data-sec`) with a `.rail-divider` between each pair. A click on a heading folds its
  part (`.collapsed`: the body goes, the heading stays), a divider drag moves room between the two
  open parts it separates (both get fixed px; the last open part keeps `flex-grow` so no gap is
  left), double-click resets them, and a part can never be dragged below its heading's height.
  State in localStorage `fs:rail` = {collapsed, sizes} (`applyRail` / `setupRail` in app.js; a
  hidden FLEx-tags part hides its divider). Unsized Tabs and Folders size to their content (`.auto`).
- The note list (app.js `visibleNotes`): a folder or tab lists only its OWN notes; "Show notes in
  subfolders" (shown where there are subfolders, remembered per computer in localStorage) lists
  the whole tree with each note's subfolder; a folder with notes only below it offers them; a
  selected tag still looks through the whole tab (Seth, 2026-10-16: "VERY cluttery if every
  parent folder shows ALL daughter notes").
- PLAYBACK (Seth, 2026-10-17: "highlight the line that's playing … auto-scroll to it if the user is
  not manually grabbing the scroll bar or clicking something in the preview pane … make the play
  controls sticky … to the bottom of the current view window until the user scrolls to the bottom
  of the object"): `playRange` maps the playhead (file time; a cached clip's time + its begin) to the
  line whose span holds it and lights that `.segment[data-n]` with `.playing-line`;
  `FS.follow.to(row)` scrolls a newly lit line into view (`block: nearest`, `scroll-margin` clears
  the player) unless the user is busy — a wheel / touch scroll or a scrolling key (4 s), a press on a
  scroll bar (until released), a click inside an example or preview other than its ▶ / Play /
  player controls (4 s). The player (`.transport`) is `position: sticky; bottom` inside the
  example, so it rides the bottom of the view while the example runs on below and rests at the
  example's end once you scroll there. NOW PLAYING (Seth, 2026-10-17: "Any time something is playing, there should be a
  play control and the ability to stop it" — a collapsed example's preview closed and took its
  player along): `nowPlaying` (interlinear.js) shows a bar at the bottom of the window whenever
  `audio.current` exists and the example's own `.transport` is not on screen (closed preview,
  scrolled away, redrawn) — ❚❚/▶ (`audio.toggle`; the pause state lives on the playback, so both
  players agree), ■ Stop, the progress (click to seek), "<text title> · <FLEx line>" (a click
  scrolls to the example when it is still open). It is re-checked on the ticks (≤ every 150 ms)
  and every 300 ms while paused. Esc stops playback when no modal, popover or preview is open
  (Esc closes those first).
- Refreshing: what FieldWorks saved after the project was opened only shows after LCM's
  `RefreshFromDisk`. The ↻ on ONE example calls `Api.flex_reload` (RefreshFromDisk, indexes
  kept so the next paste stays fast) before re-fetching; "Refresh all" (the toolbar, and a
  collection's header) also drops the indexes and re-fetches every example (Seth, 2026-10-16:
  ↻ in a collection only re-read the in-memory copy).
- SNAPSHOT WRITES ARE SERIALISED (Seth's log, 2026-10-19: a note with twelve examples of one text
  fetched them on twelve pywebview threads at once; on Windows the second `os.replace` of the same
  snapshot hit "Access is denied" while the first still had the file open, and a good live read was
  shown as "the snapshot"): `SnapshotCache.put` holds one lock, writes a per-thread `.tmp` and
  retries the replace a few times; `merge_text` is one read-modify-write under that lock; and in
  `FlexService.get_object` every snapshot write goes through `keep()`, which logs a failure and
  never lets it fail the live fetch (`tests/test_flex.py::test_snapshot_writes_from_many_threads…`).
  The same evening config.json failed the same way on the backup-before-closing screen (the page
  was reading it while the finished backup recorded its result, so a GOOD backup was reported as
  failed): EVERY atomic write in the app now goes through `fsutil.replace_file` (os.replace with a
  few short retries on PermissionError, the temp file removed when they run out) — config.py (under
  `_SAVE_LOCK`, a per-thread temp name), notebook.py, secrets_store.py, tracking.py, backup.py's
  mirror and the snapshot cache; `Backup.run` records its result inside a try and logs a failure
  instead of returning it (`tests/test_backup.py::test_atomic_writes_ride_out_a_busy_target…`).
  THE PICKER'S TEXT PREVIEW PAGES (Seth, 2026-10-19: the preview "only return[s] the first few
  rows … I can't scroll to other rows"): the backends hand out 60 lines at a time, so `pickText`
  fetches and appends the next page as the preview nears its end (`loadMore`, `preview.onscroll`)
  until the text is whole; the chart preview always had the whole chart.
- `flex/lcm.py` has never met a real FieldWorks: it was written from flexicon 4.12's source and
  the LCM model. The first run on Windows will need adjustments — keep every access behind the
  `_t()` guard so one odd object degrades a rendering instead of failing it, and record what you
  learn in this file.
- The app icon (Seth, 2026-10-16): `ui/img/icon.svg` (40 px and up: a scratchpad page whose top
  row is IPA, ʃə ŋɔ ʔa, glossed beneath), `icon-small.svg` (32 px and the rail mark: a highlighted
  ŋ) and `icon-tiny.svg` (16–24 px: lines only) are the sources. The IPA is glyph OUTLINES from
  DejaVu Sans Bold (fontTools, once), never `<text>`, so no machine's fonts can change it; `tools/make_icons.py` renders the PNGs and
  the multi-size `flex-scratchpad.ico` (dev-only Playwright + Pillow) — re-run it and commit the
  outputs after editing either SVG. The .ico is the window/taskbar icon (`webview.start(icon=)`,
  which pywebview's WinForms backend honours despite its docs), the exe icon (the spec) and the
  `flexscratchpad://` link icon; the process sets its own AppUserModelID so the taskbar does not
  group it under Python. Link registration is keyed on the build, so updates reach the registry.
- The window starts maximized (Seth, 2026-10-16: the default size hung off his screen); the
  size it restores to is fitted to the screen (`_fit_to_screen`) and is not saved while maximized.
- RELEASES (Seth, 2026-10-16: "a pyinstaller version (portable and setup) … bundled ffmpeg OR an
  auto download … a pre-release, and then our site can point to the pre-release download"): push a
  tag `v0.1.0-beta.N` → `release.yml` → `windows-package.yml` (windows-latest) builds the onedir
  (`build/flex-scratchpad.spec`, entry `build/launcher.py` — NEVER `flex_scratchpad/__main__.py`,
  whose relative imports fail as a script and hang a windowed build on a message box), with
  flexicon + pythonnet bundled (flexicon still loads the INSTALLED FieldWorks) and ffmpeg BUNDLED
  beside the exe (`ffmpeg/ffmpeg.exe`, BtbN's LGPL build, `tools/fetch_ffmpeg.py`, checksum-verified;
  chosen over a first-use download: field laptops are offline, and a program that fetches and runs
  another executable is what anti-malware watches for). It self-tests a console copy and the real
  one (`--selftest`), makes the per-user NSIS Setup (`build/installer.nsi`) and the portable zip,
  installs / upgrades / uninstalls silently with checks, and only then publishes the PRE-release
  with `build/RELEASE-NOTES.md`. `ci.yml`'s manual dispatch runs the same packaging as an artifact.
  `build_id()` reads the `BUILD_ID` the spec stamps (a frozen build has no .py files to hash).
  Unsigned: SmartScreen says so. RUN BY HAND (2026-10-20): Actions › Release › Run workflow — `tag` makes and
  releases that tag at the chosen branch's head (`final` for a full release), `promote` marks an existing release
  final and latest; a cloud session can push its branch but neither a tag nor a release edit, nor main. EVERY
  RELEASE ALSO LANDS ON MAIN (Seth, 2026-10-20: "every time we push a release (or pre-release), we should also
  commit and push to main"): the workflow's `main` job fast-forwards main to the released commit (a bare manual
  run with neither input does only that) by fast-forward, else by a merge commit (Seth merges pull requests of this
  branch into main, so main carries merge commits the branch lacks); a conflict stops it and says to merge by hand.
- THE SITE is `docs/` (GitHub Pages from `/docs`), in LingTeX Tools' pattern (its tokens and
  components, `assets/media.js` verbatim): a BRIEF hero (Seth, 2026-10-20: "make the intro text a LOT briefer so that the
  scrolling carousel is immediately visible on page load" — the kicker, the title, ONE sentence and three buttons, no
  claim pills or link row; the carousel's top sits at ~440px on a 768px-tall screen), the carousel, three steps with
  stills, features, install, a pre-release band. `assets/release.js` moves every download link and the
  version to the newest RELEASE (not marked pre-release) that has BOTH files, and the `data-pre` buttons to the newest
  PRE-release published after it (`pre-exe` / `pre-zip` / `pre-version`; hidden when none is newer; Seth, 2026-10-20:
  "the buttons should offer both") (`tests/js/site-release.test.js`). The video
  and stills are filmed from the REAL UI by `tools/record_demo.py`; THE HERO IS A CAROUSEL (Seth, 2026-10-20: first
  "mouseover generated screenshots for each feature", then "what I'd rather have is just one scrolling carousel of
  screenshots and the video all where the video is now, auto scrolling and also easy for people to navigate … each
  feature … as a caption underneath that also changes"): `#hero-carousel` (`.car-view` > `.car-track` of
  `.car-slide`s, each a `.media-slot` with `data-caption`; the loop video first, `data-hold` 16 s, then one 16:9
  still per feature, 6 s each) with ‹ › buttons, dots, ← → Home End, a swipe, a `.car-caption` band under the
  picture and a `n / N` count; `assets/media.js` drops a still slide whose file is not on the manifest, pauses while
  the pointer or focus is on it or the tab is hidden, and never auto-advances under reduced motion; the video plays
  only on its own slide. `tools/shoot_claims.py` photographs the stills (`claim-*.webp`, 1280×720) from the demo
  through the e2e bridge: the chart in its three views, the styled example, the collection, the concordance
  dialog, the exports menu… (demo project — an invented
  language, never a community's data — through the e2e bridge, a drawn cursor and captions,
  Chromium's screencast, ffmpeg): re-run it after a UI change and look at the result.
  THE USER GUIDE (Seth, 2026-10-20: "thorough documentation with screenshots, generated screenshots, for everything
  you can do with this app and a clear sort of table of contents … in the user-facing website"): `docs/guide/index.html`
  (+ `assets/guide.css`), fifteen numbered sections (getting started, the notebook, writing, examples, styling and
  filters, audio, collections, charts, chart notes, chart search, exports, backup, settings and shortcuts, the files,
  troubleshooting) with a sticky contents list (a `<details>` on a phone; an IntersectionObserver marks the section in
  view and opens its sub-headings) and ~60 pictures in `docs/media/guide/*.webp`, plain `<img>`s (no manifest: they are
  committed with the page). `tools/shoot_guide.py` makes them from the demo through the e2e bridge — it builds a
  notebook (a chapter note with every block kind, a collection with groups and notes, a rule collection, a chart note
  with list / notes / rule columns, attachments), photographs each view (`shot(name, target)` crops the element with
  padding; popovers on their own, dialogs by `.modal`), renders the Word and Excel exports through LibreOffice and
  pdftoppm, and prints the names that failed; `python tools/shoot_guide.py name…` re-shoots some. Re-run it after a UI
  change and LOOK at the pictures. `tests/js/site-guide.test.js` fails when the page names a picture that is not there
  (or a picture nobody shows), when an in-page link has no target, when a section or sub-heading is missing from the
  contents, or when the home page stops linking to `guide/`. The README's how-to table and the guide say the same
  things: change both.
  IT DESCRIBES THE CURRENT RELEASE (Seth, 2026-10-20: "have the documentation match the most recent full release …
  you can have documentation for features on the pre-release, but have them flagged as such"): the guide names the
  release it describes (0.1.0-beta.2, the GitHub release NOT marked pre-release) in its head and legend; anything only
  in the pre-release wears `<span class="rel rel-pre">beta.3</span>`, anything finished but in no download yet
  `<span class="rel rel-next">next</span>` (on a heading when the whole part is new, on the sentence or table row
  otherwise, and in both contents lists for a whole section); the test checks the legend, the flag classes and that
  sections 8–10 are flagged in the body and the contents. WHEN A RELEASE IS PROMOTED OR CUT: move the flags — a
  promoted beta.3 drops every `beta.3` flag and renames the legend; a new pre-release turns `next` into its number.
  What was in beta.2 was settled by `git show 0d84fd2:<file>` (no tagstyles.js / chart.js / log.py / xlsx, pptx,
  pdf writers; no Ctrl+K, nested lists, gap bar, sticky headings, promote/demote, rule collections, flexcopy).
- GitHub Actions: public repo, standard runners only, Windows build is `workflow_dispatch`. Never
  add a schedule, a larger runner, LFS or a release step without Seth's say-so.
- This is Seth's suite: see `flextext-editor/CLAUDE.md` for the house rules on writing about
  security (describe what is protected, never speculate about whom against) — they apply here too.
