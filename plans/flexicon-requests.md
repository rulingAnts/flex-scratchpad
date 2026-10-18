# Requests for the flexicon project (drafts)

Drafted 2026-10-18 for Seth to post at https://github.com/MattGyverLee/flexicon/issues. Each
section below is one issue: title, then body. They are written against **pyflexicon 4.12.0** as
read from its installed source; the line numbers are from that release. FLEx Scratchpad reads a
FieldWorks project read-only through flexicon (`OpenProject(name, writeEnabled=False)`) on one
worker thread, and everything here is about READING. Where we had to go around flexicon we say
how, so a fix can be checked against a working path.

---

## 1. Bug: `BestStr()` raises `FP_ParameterError` for every real multistring (pythonnet types them by runtime class)

**What happens.** `FLExProject.BestStr(x)` → `WritingSystems.GetBestString(x)` validates its
argument with `isinstance(x, (IMultiUnicode, IMultiString))`. On a real project (FieldWorks 9,
pythonnet as installed by `pip install pyflexicon`), the object a property such as
`ICmPossibility.Name` hands to Python is typed by its **runtime** class — liblcm's internal
`MultiUnicodeAccessor` / `MultiStringAccessor` — and the Python type pythonnet builds for that
class does not list the interfaces among its bases. So the `isinstance` check is false for every
real multistring, and `BestStr` raises for exactly the objects it exists for. The properties
themselves work: `x.BestAnalysisVernacularAlternative.Text` reads fine on the same object.

**How we saw it.** Reading `LangProject.TextMarkupTagsOA` items: every tag's name came back as
`"?"` (our fallback) because `BestStr(item.Name)` raised. 2026-10-18, FieldWorks 9.x, Windows,
pyflexicon 4.12.0.

**What we do instead** (`flex_scratchpad/flex/lcm.py`, `_best()`): try
`BestAnalysisVernacularAlternative`, `BestAnalysisAlternative`, `BestVernacularAlternative` in
turn, accept the first non-empty text that is not `"***"`, else the first stored alternative.

**Suggested fix.** Validate by capability rather than by interface: accept any object that has
`BestAnalysisVernacularAlternative` (or `get_String` / `AvailableWritingSystemIds`), or test
`IMultiUnicode.IsInstanceOfType(x)` / `IMultiString.IsInstanceOfType(x)` from .NET, which does see
the interfaces. Either keeps the string-argument warning path as it is.

---

## 2. Feature: a read API for text markup tags (`TextMarkupTags` list, and a text's `TagsOC`)

FieldWorks' Text Tagging view stores tags that nothing in FLEx exports, and flexicon has the
class id (`TextTags.kClassId` in `BuildGotoURL`) but no operations for them. We read them
directly; a supported API would let other scripts do the same. What a reader needs:

1. **The list, with its hierarchy.** `LangProject.TextMarkupTagsOA.PossibilitiesOS`, recursing
   into `SubPossibilitiesOS`: for each item its GUID, `Name`, `Abbreviation`, `ForeColor` /
   `BackColor` (BGR ints; `kclrTransparent` and also **0 in both fields** mean "not coloured" —
   an item nobody coloured reads 0/0, black on black), and its ancestors' names top first. The
   list nests at least two levels (group → tag) and may nest deeper.
2. **A text's tags.** `IStText.TagsOC` → for each `ITextTag`: GUID, `TagRA` (the list item),
   `BeginSegmentRA` / `EndSegmentRA` (segments, possibly in different paragraphs) and
   `BeginAnalysisIndex` / `EndAnalysisIndex` — 0-based over the segment's `AnalysesRS`,
   punctuation forms included.
3. **Occurrences of one tag across the project** (every text's tags filtered by `TagRA`), with
   the segment numbers and baseline words, for search tools.

Proposed shape, in flexicon's style: `project.TextTags.GetList()` / `GetListTree()`,
`project.TextTags.GetAll(text)`, `project.TextTags.GetOccurrences(tag)`, plus the per-object
getters (`GetTag`, `GetBeginSegment`, `GetEndSegment`, `GetBeginIndex`, `GetEndIndex`). Our
working reader is `lcm._text_tags` / `list_text_tags` / `tag_occurrences` in
`flex_scratchpad/flex/lcm.py` if a reference helps.

Related: Seth's earlier custom-list import/export work also reads these lists through LCM; the
FLEx Export dialog never offers them, which is why a library path matters.

---

## 3. Feature: complete the constituent chart READ side

flexicon 4.12 already has `ConstCharts`, `ConstChartRows`, `ConstChartWordGroups`,
`ConstChartMovedText`, `ConstChartClauseMarkers`, `ConstChartMarkers`, `ConstChartCellTags` and
`Discourse.GetCells(row)` (which returns every cell part in order — thank you). To draw a chart as
FLEx does, a reader also needs these fields, none of which has a getter today:

| object | field | why |
|---|---|---|
| `IConstChartWordGroup` | `BeginAnalysisIndex`, `EndAnalysisIndex` | a cell is usually PART of a segment; `GetBeginSegment`/`GetEndSegment` alone cannot say which words |
| `IConstChartRow` | `ClauseType` (`ClauseTypes`: Normal, Dependent, Song, Speech), `EndParagraph`, `EndSentence`, `StartDependentClauseGroup`, `EndDependentClauseGroup` | row styling and the sentence / paragraph breaks FLEx draws |
| `IConstituentChartCellPart` | `ColumnRA` (for every part kind, not only word groups), `MergesAfter`, `MergesBefore` | which column a marker sits in; merged cells |
| `IConstChartMovedTextMarker` | `WordGroupRA`, `Preposed` | exists (`GetWordGroup`, `IsPreposed`) — listed for completeness |
| `IConstChartClauseMarker` | `DependentClausesRS` | exists (`GetDependentClauses`) |
| `IConstChartTag` | `TagRA` | exists (`GetMarker`); a `None` `TagRA` is FLEx's "missing marker" and should be reported, not skipped |
| `IDsConstChart` | `BasedOnRA` (the `IStText`), `TemplateRA` and the template's sub-possibility TREE (column groups → columns, with abbreviations), `Name` | `GetOwningText` and `GetTemplate` exist; the column tree does not |
| `IDsDiscourseData` | `ChartMarkersOA` list with hierarchy, `ConstChartTemplOA` list | the markers' groups and colours (same shape as the text markup tags list) |

Two smaller things:

- `Discourse.GetCells()` returns raw `IConstituentChartCellPart` objects; a typed result (`kind`
  = wordgroup / movedtext / clausemarker / tag, plus `column`) would save every caller the same
  `ClassName` switch.
- `GetChartType` exists; a `GetCharts(text)` that filters `ChartsOC` by `BasedOnRA == text.ContentsOA`
  would avoid walking every chart of the project per text (`Discourse.GetAllCharts(text)` does
  this, but through the text's `IStText`; documenting that `BasedOnRA` is the StText, not the
  `IText`, would help).

---

## 4. Feature: import a FieldWorks discourse-chart XML (and the matching export)

FieldWorks exports a chart (Texts & Words → Discourse Chart → Export: the "Discourse XML"
template, `DiscourseExporter.cs`) but has no importer, so a chart cannot move between projects
or survive a re-import of its text. flexicon has the WRITE operations a chart needs (`Create`
chart and rows, `ConstChartWordGroups.Create(row, beginSeg, endSeg)`, `SetColumn`, the marker
creators), so an importer belongs in flexicon rather than in a read-only tool like ours.

What it would read, matching FLEx's own export:

```xml
<document>
  <chart>
    <row type="title1"> <cell cols="2"><main><lit lang="en">Pre-nuclear</lit></main></cell> … </row>
    <row type="title2"> … column names … </row>
    <row type="normal|dependent|speech|song" id="1a" endSent="true" endPara="true">
      <cell cols="1" reversed="true?">
        <main><rownum lang="en">1a</rownum></main>
      </cell>
      <cell cols="1"><main><word lang="fau" moved="true?">…</word> <lit …>[</lit> <clauseMkr target="1b" lang="en">1b</clauseMkr>
                    <moveMkr lang="en" targetFirstOnLine="false?">Preposed</moveMkr> <listRef lang="en">Top</listRef></main>
        <glosses><gloss lang="en">…</gloss></glosses></cell>
      <cell …><main><note lang="en">…</note></main></cell>
    </row>
  </chart>
  <languages><language lang="fau" font="Charis SIL" vernacular="true" RightToLeft="true?"/></languages>
</document>
```

Words are matched back to the text by position (the export carries no GUIDs), so an importer
needs the target text and a tolerant matcher; an export that ADDS `guid` attributes on `row`,
`cell` and `word` (FLEx's XSLTs ignore unknown attributes) would make the round trip exact. FLEx
Scratchpad will write this XML shape with those extra attributes, plus a JSON with every GUID, so
there will be files to test an importer against.

---

## 5. Note: thread affinity and read-only use (documentation request)

Not a bug. Two things that cost us time and would fit a "using flexicon from a GUI" page:

- LCM is not thread-safe and WinForms-hosted libraries object to calls from other threads; a GUI
  that calls flexicon from UI callbacks (pywebview's `js_api` runs each call on its own thread)
  needs ONE dedicated thread that owns the project and runs every call. We use a queue + futures
  (`LcmWorker` in `flex_scratchpad/flex/lcm.py`); no .NET object may leave that thread.
- Closing: a call into .NET after the UI thread has ended, while Python is tearing pythonnet
  down, dies with `InternalPythonnetException: Failed to create Python type for
  System.ComponentModel.InvalidAsynchronousStateException`. Stop the worker, `CloseProject()`,
  then end the process with `os._exit` rather than through interpreter shutdown.
- `OpenProject(name, writeEnabled=False)` with FLEx open on the same project: a shared project
  opens fine; a non-shared one raises `FP_FileLockedError`. Worth stating that `ProjectId.Type`
  does not reliably say whether a project is shared (a shared project read as plain XML on
  2026-10-16), so the lock error is the only dependable signal.
