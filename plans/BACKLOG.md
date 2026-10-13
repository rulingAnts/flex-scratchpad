# FLEx Scratchpad — backlog

Things Seth has asked for that are not built yet, in his words where possible, so the shape is
not lost between sessions. Tracked in git, never served.

## Copy an example as FLEx TSV or langsci-gb4e LaTeX (Seth, 2026-10-12)

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
running one through a file in the app data folder (no sockets). Deferred from the first plan.

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
