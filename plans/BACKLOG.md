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
