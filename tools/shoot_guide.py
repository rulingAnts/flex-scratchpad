"""Photograph the user guide's pictures from the REAL program (dev-only).

    python tools/shoot_guide.py            → docs/media/guide/*.webp (one per figure of docs/guide/index.html)
    python tools/shoot_guide.py settings chart-menu   → only those

Seth, 2026-10-20: "thorough documentation with screenshots, generated screenshots, for everything you
can do with this app and a clear sort of table of contents … in the user-facing website". Every
picture is the actual UI (flex_scratchpad/ui) against the built-in demo project — an invented
language, so no community's data appears on the site — through the same no-server bridge the
end-to-end tests use (tests/e2e/bridge.py). The guide page names each picture by file; a name
that fails here is printed at the end, so the page can be checked against what exists
(tests/js/site-guide.test.js does that).

Needs: Playwright's Chromium and Pillow; LibreOffice and pdftoppm for the pictures of the Word and
Excel exports (skipped when absent). Re-run after a UI change and look at the result.
"""
from __future__ import annotations

import base64
import json
import shutil
import subprocess
import sys
import traceback
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "e2e"))
from bridge import INIT_SCRIPT, Harness  # noqa: E402
from flex_scratchpad.flex.demo import E, T_ARAB, T_STORY  # noqa: E402

OUT = ROOT / "docs" / "media" / "guide"
UI = ROOT / "flex_scratchpad" / "ui"
W, H, SCALE = 1280, 900, 1.5
MAXW = 1200
CHART = "d15c0000-0000-4000-8000-00000000c001"
E_MO = E["mo"]
E_KABIR = E["kabir"]

CHAPTER = f"""# 3 Verbs

The verb carries a subject prefix and a tense suffix. This chapter looks at the past tense in (1) and at questions in §3.2; the field notes are in [[Field trip, 12 October]]. #todo

## 3.1 Past tense

The past tense suffix *-mo* follows the verb stem, as in (1). The **stem** is underlined in the second line.

{{{{flex:text {T_STORY} seg=1-2 ex hl=1.2 b=morph:"-mo" u=2.3 "past tense"}}}}

> In the second clause of a chain the suffix is dropped: compare (1) with the chained clauses below, and see the [FieldWorks notes](https://software.sil.org/fieldworks/) on the Morphemes line.

- The dog sleeps by the river in {{{{flex:text {T_STORY} seg=4}}}}, with no suffix.
- [x] check the suffix on stative verbs
- [ ] ask about *-mo* with negation

1. the stem
2. the subject prefix
  1. then the tense suffix

| Construction | Example | Note |
|---|---|---|
| Intransitive | {{{{flex:text {T_STORY} seg=1 expanded}}}} | the suffix on *nuwa* |
| Transitive | {{{{flex:text {T_STORY} seg=2 expanded}}}} | object before the verb |

{{{{flex:text {T_STORY} seg=5 collapsed "chained clause"}}}}

### 3.1.1 The suffix in the lexicon

{{{{flex:entry {E_MO}}}}}

## 3.2 Questions {{collapsed}}

Questions end in the particle *ba*.

## 3.3 Files

The wordlist from the trip: {{{{file attachments/wordlist.xlsx "Wordlist, October"}}}}

{{{{file attachments/river.png preview h=180 "The river at Kalu"}}}}
"""

FIELD_TRIP = """# Field trip, 12 October

Recorded two stories at the river with **Mama Ɲamú**; the second one still needs its free translations.

- [x] copy the recordings
- [ ] check the segment boundaries of story 2 #todo

#fieldwork
"""

CHART_IN_NOTE = f"""# The story's chart

Rows 1a–2c of the story chart, with the free translation after each line's rows.

{{{{flex:chart {CHART} rows=1-5 lines=txt,gls free=row "story chart"}}}}

The same rows as an interlinear example, for comparison:
"""

COLLECTION = f"""## Same subject

{{{{flex:text {T_STORY} seg=1}}}}
> The subject prefix on the verb, the suffix *-mo* after it.

{{{{flex:text {T_STORY} seg=2}}}}

## Different subject

{{{{flex:text {T_STORY} seg=4}}}}
> Compare (2): no tense suffix.

{{{{flex:chart {CHART} rows=2}}}}
"""

CONCORDANCE = (
    "Ref,Occurrence\n"
    "DOG 1.2,Kabir ka-nuwa-mo lo.§ Haŋa tiket ka-sila-mo pemu.\n"
    "Kabir pemu 2.1,\"“Ɲamú!” ka-sila lo.§ Kabir pemu ka-nuwa lo.\"\n"
    "DOG 3,Tiket ka-nuwa-mo.\n"
    "DOG 3,Tiket ka-nuwa-mo.\n"
    "DOG 4.1,Kabir ka-nuwa-mo.\n"
)


def chromium_path():
    import os
    p = os.environ.get("PLAYWRIGHT_CHROMIUM") or "/opt/pw-browsers/chromium"
    return p if Path(p).exists() else None


def river_png() -> bytes:
    """A small picture for the attachment card (drawn, not a photograph)."""
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (640, 360), "#dbeafe")
    d = ImageDraw.Draw(im)
    for y in range(0, 200):
        d.line([(0, y), (640, y)], fill=(219 - y // 3, 234 - y // 4, 254 - y // 8))
    d.polygon([(0, 200), (180, 120), (330, 190), (470, 110), (640, 180), (640, 230), (0, 230)], fill="#4d7c0f")
    d.polygon([(0, 230), (640, 230), (640, 360), (0, 360)], fill="#1d4ed8")
    for x in range(0, 640, 40):
        d.arc([x, 270, x + 60, 300], 0, 180, fill="#93c5fd", width=3)
    return _png_bytes(im)


def _png_bytes(im) -> bytes:
    b = BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def prepare(api) -> dict:
    """The notebook the pictures show: two tabs, folders, tags, notes of every kind."""
    tab = api.add_tab("Grammar", "#2563eb")["dir"]
    api.create_folder(tab, "Verbs")
    api.create_folder(tab, "Discourse")
    api.create_folder(tab, "Verbs/Tense")
    api.set_tags([{"name": "todo", "color": "#f59e0b"}, {"name": "fieldwork", "color": "#16a34a"}, {"name": "draft", "color": "#64748b"}])
    api.attach_data("wordlist.xlsx", base64.b64encode(b"PK\x03\x04" + b"\0" * 400).decode())
    api.attach_data("river.png", base64.b64encode(river_png()).decode())
    notes = {}
    notes["trip"] = api.create_note("Notes", "", "Field trip, 12 October", FIELD_TRIP)
    api.save_note(notes["trip"]["id"], {"tags": ["fieldwork", "todo"]})
    notes["chapter"] = api.create_note(tab, "Verbs", "Chapter 3 — Verbs", CHAPTER)
    api.save_note(notes["chapter"]["id"], {"tags": ["draft", "todo"]})
    api.create_note(tab, "Verbs/Tense", "Tense and aspect", "# Tense and aspect\n\nNotes to come.\n")
    notes["chartnote_in_note"] = api.create_note(tab, "Discourse", "Story chart in a note", CHART_IN_NOTE)
    notes["coll"] = api.create_note(tab, "Verbs", "Chained clauses — examples", COLLECTION, "examples")
    notes["rule"] = api.create_rule_collection(tab, "Discourse", "Lines tagged Topic", {"tags": ["Topic", "group:Arguments"]})
    notes["chartnote"] = api.create_chart_note(tab, "Discourse", "", CHART)
    rows = api.flex_get("chart", CHART)["rows"]
    anchor = {r["label"]: r["guid"][-12:] for r in rows}
    api.set_chart_list("Information status", ["new", "given", "contrast"], True)
    body = (
        f"{{{{flex:chart {CHART} lines=txt,gls free=row}}}}\n\n"
        "## Custom columns\n\n"
        "| Column | Kind | Settings |\n|---|---|---|\n"
        "| Status | list | Information status |\n"
        "| Comment | notes | |\n"
        "| Role | rule | marker:New → N [row hl#fde68a]; col:Subject[txt:/^kabir$/i] → K [b]; clause:dependent → dep [i] |\n\n"
        "## Values\n\n"
        "| Row | Status | Comment |\n|---|---|---|\n"
        f"| 1a #{anchor['1a']} | new | Subject fronted |\n"
        f"| 1b #{anchor['1b']} | given | |\n"
        f"| 2a #{anchor['2a']} | contrast | Direct speech |\n"
        f"| 2c #{anchor['2c']} | given | |\n"
    )
    api.save_note(notes["chartnote"]["id"], {"body": body})
    return notes


def crop_box(png: bytes, box: dict, pad: int = 0, maxw: int = MAXW):
    from PIL import Image
    im = Image.open(BytesIO(png)).convert("RGB")
    k = SCALE
    x0 = max(0, box["x"] - pad)
    y0 = max(0, box["y"] - pad)
    x1 = min(W, box["x"] + box["width"] + pad)
    y1 = min(H, box["y"] + box["height"] + pad)
    im = im.crop((int(x0 * k), int(y0 * k), int(x1 * k), int(y1 * k)))
    if im.size[0] > maxw:
        im = im.resize((maxw, int(maxw * im.size[1] / im.size[0])), Image.LANCZOS)
    return im


def main(argv: list[str]) -> int:
    from playwright.sync_api import sync_playwright
    only = set(argv)
    h = Harness()
    api = h.api
    notes = prepare(api)
    stills: dict[str, "Image"] = {}
    failed: list[str] = []
    with sync_playwright() as p:
        kw = {"args": ["--autoplay-policy=no-user-gesture-required", "--allow-file-access-from-files", "--font-render-hinting=none"]}
        exe = chromium_path()
        if exe:
            kw["executable_path"] = exe
        browser = p.chromium.launch(**kw)
        ctx = browser.new_context(viewport={"width": W, "height": H}, device_scale_factor=SCALE)
        ctx.expose_binding("__flexBridge", h.bridge)
        ctx.add_init_script(INIT_SCRIPT)
        page = ctx.new_page()
        page.set_default_timeout(8000)
        page.goto((UI / "index.html").as_uri())
        page.locator("#tabs .tab-item").first.wait_for()
        page.wait_for_timeout(400)

        def shot(name, target=None, pad=14, maxw=MAXW, box=None, settle=300):
            """A picture of `target` (a locator, a selector, a box dict, or the whole window)."""
            if only and name not in only:
                return
            page.wait_for_timeout(settle)
            if box is None:
                if target is None:
                    box = {"x": 0, "y": 0, "width": W, "height": H}
                else:
                    loc = page.locator(target) if isinstance(target, str) else target
                    if loc.count() > 1:
                        loc = loc.last
                    box = loc.bounding_box()
                    if box is None:
                        raise RuntimeError(f"{name}: target has no box")
            stills[name] = crop_box(page.screenshot(type="png"), box, pad, maxw)
            print("  ✓", name)

        def union(*targets, pad=14):
            boxes = [(page.locator(t) if isinstance(t, str) else t).bounding_box() for t in targets]
            boxes = [b for b in boxes if b]
            x0 = min(b["x"] for b in boxes); y0 = min(b["y"] for b in boxes)
            x1 = max(b["x"] + b["width"] for b in boxes); y1 = max(b["y"] + b["height"] for b in boxes)
            return {"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0}

        def step(name, fn):
            if only and name not in only and not name.startswith("*"):
                return
            try:
                fn()
            except Exception:  # noqa: BLE001
                failed.append(name)
                print("  ✗", name)
                traceback.print_exc(limit=3)
                try:
                    page.keyboard.press("Escape")
                    page.keyboard.press("Escape")
                except Exception:  # noqa: BLE001
                    pass

        def esc(n=1):
            for _ in range(n):
                page.keyboard.press("Escape")
                page.wait_for_timeout(150)

        WHERE = {"Chapter 3": ("Grammar", "Verbs"), "Chained clauses": ("Grammar", "Verbs"), "Field trip": ("Notes", ""),
                 "Story chart in a note": ("Grammar", "Discourse"), "Lines tagged Topic": ("Grammar", "Discourse"), "Story chart \u2014 The dog": ("Grammar", "Discourse")}

        def open_note(title, wait="#editor .blk"):
            """Tab, folder, card: a folder lists only its own notes."""
            tab, folder = WHERE[title]
            page.fill("#search", "")
            page.locator("#tabs .tab-item", has_text=tab).click()
            page.wait_for_timeout(250)
            if folder:
                page.locator("#folders .folder-item[data-path='" + folder + "']").click()
                page.wait_for_timeout(250)
            page.locator(".note-card", has_text=title).first.click()
            page.locator(wait).first.wait_for()
            page.wait_for_timeout(500)

        def popover():
            page.locator(".popover").last.wait_for()
            page.wait_for_timeout(250)
            return page.locator(".popover").last

        def modal():
            page.locator(".modal").last.wait_for()
            page.wait_for_timeout(300)
            return page.locator(".modal").last

        def scroll_to(sel, block="start"):
            page.locator(sel).first.evaluate("(e, b) => e.scrollIntoView({ block: b })", block)
            page.wait_for_timeout(300)

        # ---------------------------------------------------------------- getting started
        def s_window():
            page.locator("#tabs .tab-item", has_text="Grammar").click()
            page.wait_for_timeout(300)
            page.locator("#folders .folder-item, #folders [data-folder]", has_text="Verbs").first.click()
            page.wait_for_timeout(300)
            open_note("Chapter 3")
            page.locator("#editor .text-obj .segment").first.wait_for()
            page.locator("#editor table.md-table .text-obj .segment").first.wait_for()
            page.wait_for_timeout(700)
            shot("window", None, pad=0, maxw=1280)
        step("window", s_window)

        def s_settings():
            # This machine has no FieldWorks, so the project list would be empty and the source "demo"; the
            # picture has to show what a Windows user sees (Seth, 2026-10-20: "users need to see a screenshot
            # where FLEx projects are listed as a source"): three invented project names stand in.
            page.evaluate("""() => { window.__realBridge = window.__flexBridge;
              window.__flexBridge = (req) => JSON.parse(req).method === 'flex_projects'
                ? Promise.resolve(JSON.stringify({ result: ['Kalu', 'Kalu Texts 2024', 'Sandbox'] })) : window.__realBridge(req); }""")
            page.locator("#btn-settings").click()
            m = modal()
            block = m.locator(".setting-block", has_text="FieldWorks project")
            block.locator("select").first.select_option("lcm")
            block.locator("button", has_text="List").click()
            page.wait_for_function("() => [...document.querySelectorAll('.modal .setting-block select')].some((s) => [...s.options].some((o) => o.value === 'Kalu Texts 2024'))")
            block.locator("select").nth(1).select_option("Kalu")
            block.evaluate("(e) => e.scrollIntoView({ block: 'start' })")
            page.wait_for_timeout(300)
            shot("settings", m)
            esc()
            page.evaluate("() => { window.__flexBridge = window.__realBridge; }")
        step("settings", s_settings)

        def s_shortcuts():
            page.keyboard.press("Control+/")
            m = modal()
            shot("shortcuts", m)
            esc()
        step("shortcuts", s_shortcuts)

        # ---------------------------------------------------------------- the notebook
        def s_rail():
            shot("rail", "#rail", pad=4)
        step("rail", s_rail)

        def s_new_menu():
            page.locator("#btn-new-menu").click()
            pop = popover()
            shot("new-menu", box=union("#btn-new-menu", pop, pad=10), pad=10)
            esc()
        step("new-menu", s_new_menu)

        def s_search():
            page.fill("#search", "kabir")
            page.keyboard.press("Enter")
            page.wait_for_timeout(900)
            shot("search", box=union("#notes", "#rail"), pad=0)
            page.fill("#search", "")
            page.keyboard.press("Enter")
            page.wait_for_timeout(400)
        step("search", s_search)

        def s_tab_menu():
            page.locator("#tabs .tab-item", has_text="Grammar").click(button="right")
            pop = popover()
            shot("tab-menu", box=union("#tabs", pop, pad=10), pad=10)
            esc()
        step("tab-menu", s_tab_menu)

        # ---------------------------------------------------------------- writing
        def s_markdown():
            open_note("Chapter 3")
            scroll_to("#editor .blk")
            shot("markdown", box=union(page.locator("#editor .blk").nth(0), page.locator("#editor .blk-quote, #editor .blk").nth(4)), pad=10)
        step("markdown", s_markdown)

        def s_markers_hidden():
            open_note("Chapter 3")
            page.locator("#btn-markers").click()
            page.wait_for_timeout(400)
            shot("markers-hidden", box=union(page.locator("#editor .blk").nth(0), page.locator("#editor .blk").nth(4)), pad=10)
            page.locator("#btn-markers").click()
            page.wait_for_timeout(300)
        step("markers-hidden", s_markers_hidden)

        def s_heading_menu():
            open_note("Chapter 3")
            page.locator("#editor .blk-body").nth(1).click()
            page.locator("[data-test=tb-heading]").dispatch_event("mousedown")
            pop = popover()
            shot("heading-menu", box=union("[data-test=tb-heading]", pop, pad=10), pad=10)
            esc()
        step("heading-menu", s_heading_menu)

        def s_folding():
            open_note("Chapter 3")
            scroll_to("#editor .blk-h:has-text('3.2 Questions')", "center")
            fold = page.locator("#editor .blk-h", has_text="3.1 Past tense").locator("[data-test=fold]")
            fold.click()
            try:
                page.wait_for_timeout(500)
                scroll_to("#editor .blk-h:has-text('3.1 Past tense')", "center")
                shot("folding", box=union(page.locator("#editor .blk-h", has_text="3 Verbs"), page.locator("#editor .blk-h", has_text="3.3 Files")), pad=10)
            finally:
                fold.click()                       # never leave the section closed: every later picture needs it
                page.wait_for_timeout(400)
        step("folding", s_folding)

        def s_sticky():
            open_note("Chapter 3")
            scroll_to("#editor .blk-h:has-text('3.1.1')", "start")
            page.locator("#editor").evaluate("(e) => { e.scrollTop += 40; }")
            page.wait_for_timeout(500)
            shot("sticky-headings", box=union("#sticky-heads", page.locator("#editor .entry-card").first), pad=10)
        step("sticky-headings", s_sticky)

        def s_lists():
            open_note("Chapter 3")
            scroll_to("#editor .blk-list", "center")
            shot("lists", box=union(page.locator("#editor .blk-list").first, page.locator("#editor .blk-list").nth(1)), pad=12)
        step("lists", s_lists)

        def s_gap_bar():
            open_note("Chapter 3")
            blocks = page.locator("#editor .blk")
            a = page.locator("#editor .blk-quote").first
            a.evaluate("(e) => e.scrollIntoView({ block: 'center' })")
            page.wait_for_timeout(300)
            ab = a.bounding_box()
            x = ab["x"] + ab["width"] / 2
            y = ab["y"] + ab["height"] + 4
            page.mouse.move(x, y - 40)
            page.mouse.move(x, y)
            page.wait_for_selector("[data-test=blk-gap]:not([hidden])", timeout=3000)
            page.wait_for_timeout(300)
            shot("gap-bar", box=union(a, "#blk-gap", pad=12), pad=12)
            page.mouse.move(2, 2)
            page.wait_for_timeout(400)
        step("gap-bar", s_gap_bar)

        def s_block_menu():
            open_note("Chapter 3")
            q = page.locator("#editor .blk-quote").first
            q.evaluate("(e) => e.scrollIntoView({ block: 'center' })")
            q.hover()
            q.locator("[data-test=blk-grip]").dispatch_event("mousedown")
            pop = popover()
            shot("block-menu", box=union(q, pop, pad=10), pad=10)
            esc()
        step("block-menu", s_block_menu)

        def s_table():
            open_note("Chapter 3")
            t = page.locator("#editor table.md-table").first
            t.evaluate("(e) => e.scrollIntoView({ block: 'center' })")
            page.wait_for_timeout(300)
            t.locator("td").last.click()
            page.wait_for_timeout(400)
            shot("table", box=union(t, page.locator(".tbl-tools").first, pad=12), pad=12)
        step("table", s_table)

        def s_table_menu():
            open_note("Chapter 3")
            t = page.locator("#editor table.md-table").first
            t.locator("td").last.click()
            page.wait_for_timeout(300)
            t.locator("td").last.click(button="right")
            pop = popover()
            shot("table-cell-menu", box=union(t, pop, pad=10), pad=10)
            esc()
            page.keyboard.press("Escape")
        step("table-cell-menu", s_table_menu)

        def s_link_pill():
            open_note("Chapter 3")
            page.evaluate("() => { const b = [...document.querySelectorAll('#editor .blk-body')].find((x) => x.textContent.includes('FieldWorks notes')); b.scrollIntoView({ block: 'center' }); FS.editor.setCaret(b, b.textContent.indexOf('FieldWorks notes') + 3); b.focus(); }")
            page.wait_for_selector("[data-test=link-pill]:not([hidden])", timeout=3000)
            page.wait_for_timeout(300)
            shot("link-pill", box=union(page.locator("#editor .blk-quote").first, "#link-pill", pad=12), pad=12)
            page.keyboard.press("Control+k")
            m = page.locator(".link-dlg")
            m.wait_for()
            page.wait_for_timeout(300)
            shot("link-dialog", m)
            esc()
        step("link-pill", s_link_pill)


        def s_files():
            open_note("Chapter 3")
            scroll_to("[data-test=file-card]", "center")
            shot("attachments", box=union(page.locator("#editor .blk").filter(has=page.locator(".md-embed[data-icon]")).last, page.locator("[data-test=file-card]").first, pad=12), pad=12)
        step("attachments", s_files)

        # ---------------------------------------------------------------- examples from FLEx
        def s_picker():
            page.keyboard.press("Escape")
            page.keyboard.press("Control+Shift+L")
            page.locator(".picker-tabs button", has_text="Texts").click()
            page.wait_for_selector(".pick-item .hw")
            page.locator(".pick-item").first.click()
            page.wait_for_selector(".picker-preview .segment")
            segs = page.locator(".picker-preview .segment")
            segs.nth(0).click()
            segs.nth(2).click()
            page.wait_for_timeout(400)
            shot("picker-texts", ".picker")
            esc()
            page.keyboard.press("Control+Shift+L")
            page.locator(".picker-tabs button", has_text="Lexicon").click()
            page.fill(".picker-left input[type=text]", "kab")
            page.wait_for_selector(".pick-item .hw")
            page.locator(".pick-item").first.click()
            page.wait_for_selector(".picker-preview .entry-card")
            page.wait_for_timeout(300)
            shot("picker-lexicon", ".picker")
            esc()
            page.keyboard.press("Control+Shift+L")
            page.locator(".picker-tabs button", has_text="FLEx tags").click()
            page.wait_for_selector("[data-test=pick-tag]")
            page.locator("[data-test=pick-tag]").first.click()
            page.wait_for_timeout(600)
            shot("picker-tags", ".picker")
            esc()
        step("picker", s_picker)

        def s_example():
            open_note("Chapter 3")
            ex = page.locator("#editor .text-obj").first
            ex.evaluate("(e) => e.scrollIntoView({ block: 'center' })")
            page.wait_for_timeout(300)
            shot("example", ex, pad=10)
            ex.locator("button[title='Options']").click()
            pop = popover()
            shot("example-menu", box=union(ex, pop, pad=10), pad=10)
            esc()
        step("example", s_example)

        def s_chips():
            chip = page.locator("#editor .md-embed").first
            chip.evaluate("(e) => e.scrollIntoView({ block: 'center' })")
            page.wait_for_timeout(300)
            chip.hover()
            page.wait_for_timeout(900)
            if not page.locator(".flex-overlay").count():
                chip.click()
            page.locator(".flex-overlay").wait_for()
            page.wait_for_timeout(600)
            shot("chips", box=union(page.locator("#editor .blk-list").first, ".flex-overlay", pad=12), pad=12)
            esc()
            page.mouse.move(2, 2)
        step("chips", s_chips)

        def s_collapsed():
            c = page.locator("#editor .flex-collapsed").first
            c.evaluate("(e) => e.scrollIntoView({ block: 'center' })")
            page.wait_for_timeout(300)
            shot("collapsed-chip", box=union(page.locator("#editor table.md-table").first, c, pad=12), pad=12)
        step("collapsed-chip", s_collapsed)

        def s_entry():
            card = page.locator("#editor .entry-card").first
            card.evaluate("(e) => e.scrollIntoView({ block: 'center' })")
            page.wait_for_timeout(300)
            shot("entry-card", card, pad=10)
        step("entry-card", s_entry)

        def paste(plain):
            page.evaluate("""(plain) => {
              const dt = new DataTransfer(); dt.setData('text/plain', plain);
              document.activeElement.dispatchEvent(new InputEvent('beforeinput', { inputType: 'insertFromPaste', dataTransfer: dt, bubbles: true, cancelable: true }));
            }""", plain)

        def s_paste_locate():
            open_note("Field trip")
            page.locator("#editor .blk-body").last.click()
            page.keyboard.press("End")
            page.keyboard.press("Enter")
            paste("Word\tKabir\tpemu\tka-nuwa\tlo\nWord Gloss\tdog\triver\tsleeps\tDECL\nFree\tThe dog sleeps by the river.")
            m = modal()
            shot("paste-located", m)
            m.locator(".btn.primary", has_text="Insert rendered").click()
            page.locator("#editor .text-obj .segment").first.wait_for(timeout=8000)
            page.wait_for_timeout(600)
            shot("pasted-example", box=union(page.locator("#editor .blk").first, page.locator("#editor .text-obj").first, pad=12), pad=12)
            page.keyboard.press("Control+z")
            page.wait_for_timeout(300)
        step("pasted-example", s_paste_locate)

        def s_flex_link_paste():
            open_note("Field trip")
            page.locator("#editor .blk-body").last.click()
            page.keyboard.press("End")
            page.keyboard.press("Enter")
            paste("silfw://localhost/link?app=flex&server=&database=Kalu%20Demo&tool=lexiconEdit&guid=" + E_KABIR + "&tag=")
            m = modal()
            shot("paste-link", m)
            esc()
            page.keyboard.press("Control+z")
        step("paste-link", s_flex_link_paste)

        # ---------------------------------------------------------------- styling
        def s_word_popover():
            open_note("Chapter 3")
            ex = page.locator("#editor .text-obj").first
            ex.evaluate("(e) => e.scrollIntoView({ block: 'center' })")
            ex.locator(".word-cell").nth(1).locator(".il-txt").click()
            pop = popover()
            shot("word-popover", box=union(ex, pop, pad=10), pad=10)
            esc()
        step("word-popover", s_word_popover)

        def s_tag_popover():
            open_note("Chapter 3")
            ex = page.locator("#editor .text-obj").first
            ex.evaluate("(e) => e.scrollIntoView({ block: 'center' })")
            ex.locator("[data-test=tag-btn]").click()
            pop = page.locator("[data-test=tag-popover]")
            pop.wait_for()
            page.wait_for_timeout(400)
            shot("tag-popover", page.locator(".popover").last, pad=6)
            esc()
        step("tag-popover", s_tag_popover)

        def s_tag_styles():
            # a tab-wide look for the tags: brackets, a tile, a border; then the example again
            api.set_tag_styles("tab", "Grammar", [
                {"tag": "Subject", "enabled": True, "br": "sq", "bar": False},
                {"tag": "Object", "enabled": True, "br": "an", "bar": False},
                {"tag": "Verb", "enabled": True, "box": True, "bs": "dashed", "bw": 2, "bar": False},
                {"tag": "Topic", "enabled": True, "tile": True},
            ])
            page.reload()
            page.locator("#tabs .tab-item").first.wait_for()
            page.wait_for_timeout(400)
            open_note("Chapter 3")
            ex = page.locator("#editor .text-obj").first
            ex.evaluate("(e) => e.scrollIntoView({ block: 'center' })")
            page.wait_for_selector("#editor .text-obj .br-cell", timeout=5000)
            page.wait_for_timeout(500)
            shot("tag-styled", ex, pad=10)
            page.locator("#btn-settings").click()
            modal()
            page.locator("[data-test=open-tag-styles]").click()
            page.wait_for_selector("[data-test=tag-dialog]")
            page.wait_for_timeout(400)
            shot("tag-styles-dialog", modal())
            esc(2)
        step("tag-styles", s_tag_styles)

        def s_filters():
            api.set_tag_filters([
                {"id": "f1", "name": "Argument structure", "enabled": True, "rules": [{"tag": "Subject", "br": "sq"}, {"tag": "Object", "br": "an"}]},
                {"id": "f2", "name": "Discourse", "enabled": False, "rules": [{"tag": "Topic", "tile": True}, {"tag": "Focus", "hl": True}]},
            ])
            page.reload()
            page.locator("#tabs .tab-item").first.wait_for()
            page.wait_for_timeout(400)
            open_note("Chapter 3")
            page.locator("#btn-filters").click()
            pop = page.locator("[data-test=filters-mode]")
            pop.wait_for()
            page.wait_for_timeout(300)
            shot("filters-popover", box=union("#btn-filters", page.locator(".popover").last, pad=10), pad=10)
            page.locator("[data-test=filters-manage]").click()
            m = modal()
            shot("filters-dialog", m)
            esc(2)
        step("filters", s_filters)

        def s_ftags():
            page.locator("#tabs .tab-item", has_text="Grammar").click()
            page.wait_for_timeout(300)
            open_note("Chapter 3")
            page.locator("[data-test=ftag]").first.wait_for()
            page.locator("[data-test=ftag]", has_text="Subject").first.click()
            page.wait_for_selector("#tagfocus:not([hidden])", timeout=4000)
            page.wait_for_timeout(600)
            shot("tag-focus", None, pad=0, maxw=1280)
            page.locator("[data-test=tagfocus-clear]").click()
            page.wait_for_timeout(300)
        step("tag-focus", s_ftags)

        # ---------------------------------------------------------------- audio
        def s_audio():
            open_note("Chapter 3")
            ex = page.locator("#editor .text-obj").first
            ex.evaluate("(e) => e.scrollIntoView({ block: 'center' })")
            ex.locator(".seg-play").first.click()
            page.wait_for_timeout(700)
            shot("audio", ex, pad=10)
            page.locator("#editor").evaluate("(e) => { e.scrollTop = e.scrollHeight; }")
            page.wait_for_timeout(600)
            np = page.locator("[data-test=now-playing]")
            if np.count() and np.is_visible():
                shot("now-playing", np, pad=10)
            esc()
            page.wait_for_timeout(300)
        step("audio", s_audio)

        # ---------------------------------------------------------------- collections
        def s_collection():
            open_note("Chained clauses", "#collection .coll-item .text-obj .segment")
            page.wait_for_timeout(600)
            shot("collection", "#collection", pad=0)
            page.locator("#collection .coll-item [data-test=coll-check]").nth(0).check()
            page.locator("#collection .coll-item [data-test=coll-check]").nth(1).check()
            page.wait_for_selector("[data-test=coll-selbar]")
            page.wait_for_timeout(300)
            shot("collection-selection", box=union(page.locator("#collection .coll-head"), page.locator("#collection .coll-item").nth(1), pad=0), pad=0)
            page.keyboard.press("Escape")
            page.wait_for_timeout(200)
            page.locator("[data-test=coll-export]").click()
            m = page.locator(".modal")
            m.wait_for(timeout=15000)
            page.wait_for_timeout(500)
            shot("flextext-export", m)
            esc()
        step("collection", s_collection)

        def s_rule_collection():
            open_note("Lines tagged Topic", "#collection .coll-item .text-obj .segment")
            page.wait_for_timeout(500)
            shot("rule-collection", box=union(page.locator("#collection .coll-head"), page.locator("#collection .coll-item").nth(1), pad=0), pad=0)
            page.locator("#btn-new-menu").click()
            page.locator("[data-test=new-rule-collection]").click()
            page.wait_for_selector(".rule-dlg [data-test=rule-tag]")
            page.locator(".rule-dlg [data-test=rule-tag][data-tag=Topic]").check()
            page.wait_for_function("() => /lines match/.test(document.querySelector('[data-test=rule-count]').textContent)")
            page.wait_for_timeout(400)
            shot("rule-dialog", ".rule-dlg")
            esc()
        step("rule-collection", s_rule_collection)

        def s_concordance():
            page.locator("#btn-new-menu").click()
            page.locator("[data-test=new-concordance]").click()
            page.locator("[data-test=conc-text]").fill(CONCORDANCE)
            page.wait_for_function("() => /placed/.test(document.querySelector('[data-test=conc-count]').textContent)")
            page.wait_for_timeout(300)
            shot("concordance", ".modal")
            esc()
        step("concordance", s_concordance)

        def s_texts_used():
            open_note("Chapter 3")
            page.locator("#btn-note-menu").click()
            page.locator(".popover .menu-item", has_text="in this note").first.click()
            page.wait_for_selector("[data-test=texts-used]")
            page.wait_for_timeout(400)
            shot("texts-used", ".modal")
            esc()
        step("texts-used", s_texts_used)

        # ---------------------------------------------------------------- text charts
        def s_chart_in_note():
            open_note("Story chart in a note", "#editor .chart-obj tr.crow")
            page.wait_for_timeout(600)
            ch = page.locator("#editor .chart-obj").first
            ch.evaluate("(e) => e.scrollIntoView({ block: 'start' })")
            page.locator("#editor").evaluate("(e) => { e.scrollTop -= 56; }")
            page.wait_for_timeout(300)
            shot("chart", ch, pad=10)
            ch.locator("[data-test=chart-menu]").click()
            pop = popover()
            shot("chart-menu", box=union(ch, pop, pad=10), pad=10)
            esc()
            ch.locator("[data-test=marker-btn]").click()
            pop = page.locator("[data-test=tag-popover]")
            pop.wait_for()
            page.wait_for_timeout(400)
            shot("chart-flag", page.locator(".popover").last, pad=6)
            esc()
            ch.locator("tr.crow[data-label='1b'] .cw").first.click()
            pop = popover()
            shot("chart-style-popover", box=union(ch, pop, pad=10), pad=10)
            esc()
            # a row selected: the bar to copy rows
            lab = ch.locator("tr.crow[data-label='1a'] th.rlab")
            page.keyboard.down("Control")
            lb = lab.bounding_box()
            page.mouse.click(lb["x"] + lb["width"] - 6, lb["y"] + lb["height"] / 2)
            lab2 = ch.locator("tr.crow[data-label='1b'] th.rlab")
            lb = lab2.bounding_box()
            page.mouse.click(lb["x"] + lb["width"] - 6, lb["y"] + lb["height"] / 2)
            page.keyboard.up("Control")
            page.wait_for_selector("[data-test=sel-bar]")
            page.wait_for_timeout(300)
            shot("chart-rows-selected", ch, pad=10)
            page.locator("[data-test=sel-clear]").click()
            # pivot
            ch.locator("[data-test=chart-menu]").click()
            page.locator("[data-test=chart-pivot]").click()
            page.wait_for_selector(".pivot-table")
            page.wait_for_timeout(300)
            shot("pivot", ".modal")
            esc()
        step("chart", s_chart_in_note)

        def s_chart_chooser():
            page.evaluate("(t) => { FS.pickChart({ text: t, test: 'pick-chart-convert' }); }", T_STORY)
            m = modal()
            shot("chart-chooser", m)
            esc()
        step("chart-chooser", s_chart_chooser)

        def s_to_example():
            open_note("Story chart in a note", "#editor .chart-obj tr.crow")
            ch = page.locator("#editor .chart-obj").first
            ch.locator("[data-test=chart-menu]").click()
            page.locator("[data-test=to-example]").click()
            page.wait_for_selector("#editor .text-obj .segment", timeout=8000)
            page.wait_for_timeout(600)
            ex = page.locator("#editor .text-obj").first
            ex.locator("button[title='Options']").click()
            pop = popover()
            pop.locator("[data-test=to-chart]").wait_for()
            shot("chart-to-example", box=union(ex, pop, pad=10), pad=10)
            esc()
            page.keyboard.press("Control+z")
            page.wait_for_timeout(500)
        step("chart-to-example", s_to_example)

        # ---------------------------------------------------------------- chart notes
        def s_chartnote():
            open_note("Story chart \u2014 The dog", "#chartnote .tchart tr.crow")
            page.wait_for_timeout(700)
            shot("chartnote", "#chartnote", pad=0)
            page.locator("#chartnote [data-test=chart-view]").click()
            page.wait_for_timeout(700)
            shot("chart-flat", "#chartnote .tchart", pad=10)
            page.locator("#chartnote [data-test=chart-view-groups]").click()
            page.wait_for_timeout(700)
            shot("chart-groups", "#chartnote .tchart", pad=10)
            page.locator("#chartnote [data-test=chart-view-select]").select_option("cols") if page.locator("#chartnote [data-test=chart-view-select]").count() else None
            page.locator("#chartnote .chart-head button, #chartnote button", has_text="Columns").first.click()
            page.wait_for_timeout(500)
            # the list cell's select
            page.locator("#chartnote tr.crow[data-label='1b'] td.xcell-list .xval").click()
            page.wait_for_selector("#chartnote select.xsel")
            page.wait_for_timeout(300)
            shot("chartnote-list-cell", box=union(page.locator("#chartnote thead"), page.locator("#chartnote tr.crow[data-label='2a']"), pad=10), pad=10)
            esc()
            page.locator("[data-test=cn-add-col]").click()
            page.fill("[data-test=cn-col-name]", "Topic?")
            page.select_option("[data-test=cn-col-kind]", "rule")
            page.wait_for_selector("[data-test=cn-builder]")
            page.locator("[data-test=rb-add-cond]").click()
            page.select_option("[data-test=rb-cond] [data-test=rb-what]", "marker")
            page.select_option("[data-test=rb-cond] [data-test=rb-val]", "New")
            page.fill("[data-test=rb-out]", "new")
            page.select_option("[data-test=rb-scope]", "row")
            page.locator("[data-test=rb-hl]").check()
            page.wait_for_timeout(600)
            shot("column-dialog", ".modal")
            esc()
        step("chartnote", s_chartnote)

        # ---------------------------------------------------------------- chart search
        def s_chart_search():
            open_note("Chapter 3")
            page.keyboard.press("Control+Shift+K")
            page.locator(".picker input[type=text]").first.wait_for()
            page.fill(".picker-left input[type=text]", "col:Subject lex:kabir")
            page.wait_for_timeout(900)
            shot("chart-search", ".picker")
            page.locator("[data-test=chart-search-build]").click()
            page.wait_for_selector("[data-test=search-builder]")
            page.wait_for_timeout(500)
            shot("search-builder", modal())
            esc()
            page.wait_for_timeout(300)
            if not page.locator(".picker").count():
                page.keyboard.press("Control+Shift+K")
                page.fill(".picker-left input[type=text]", "col:Subject lex:kabir")
            page.locator("[data-test=chart-profile]").click()
            page.wait_for_selector(".profile-table")
            page.wait_for_timeout(300)
            shot("column-profile", modal())
            esc(2)
        step("chart-search", s_chart_search)

        # ---------------------------------------------------------------- exports
        def s_export_menu():
            open_note("Chapter 3")
            page.locator("#btn-note-menu").click()
            pop = popover()
            pop.locator(".menu-item", has_text="Word").wait_for()
            shot("export-menu", box=union("#btn-note-menu", pop, pad=10), pad=10)
            esc()
        step("export-menu", s_export_menu)

        def s_exports():
            open_note("Chapter 3")
            page.locator("#editor table.md-table .text-obj .segment").first.wait_for()
            res = page.evaluate("""async (title) => {
              const api = window.pywebview.api;
              const notes = await api.list_notes(); const note = (await Promise.all(notes.map((n) => api.get_note(n.id)))).find((n) => n.title === title);
              const editor = new FS.Editor(document.createElement('div'), {}); editor.load(FS.flexcopy.strip(note.body));
              const doc = await FS.exporter.buildDoc(note, editor);
              await FS.exporter.embedAudio(doc);
              return { id: note.id, doc, html: FS.exporter.toHtml(doc), slides: FS.exporter.toSlides(doc) };
            }""", "Chapter 3 — Verbs")
            tmp = h.tmp
            html_path = tmp / "chapter.html"
            html_path.write_text(res["html"], encoding="utf-8")
            slides_path = tmp / "slides.html"
            slides_path.write_text(res["slides"], encoding="utf-8")
            pg = ctx.new_page()
            try:
                pg.set_viewport_size({"width": 1100, "height": 760})
                pg.goto(html_path.as_uri())
                pg.wait_for_timeout(800)
                stills["export-web"] = crop_box(pg.screenshot(type="png"), {"x": 0, "y": 0, "width": 1100, "height": 760}, 0)
                print("  ✓ export-web")
                pg.set_viewport_size({"width": 1280, "height": 720})
                pg.goto(slides_path.as_uri())
                pg.wait_for_selector(".slide.on")
                pg.keyboard.press("ArrowRight")
                pg.keyboard.press("ArrowRight")
                pg.wait_for_timeout(600)
                stills["export-slides"] = crop_box(pg.screenshot(type="png"), {"x": 0, "y": 0, "width": 1280, "height": 720}, 0)
                print("  ✓ export-slides")
            finally:
                pg.close()
            # Word and Excel, rendered by LibreOffice when it is there
            soffice = shutil.which("soffice")
            pdftoppm = shutil.which("pdftoppm")
            if soffice and pdftoppm:
                for kind, fn in (("docx", api.export_note_docx), ("xlsx", api.export_note_xlsx)):
                    out = tmp / f"chapter.{kind}"
                    fn(res["id"], res["doc"], str(out))
                    subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", str(tmp), str(out)], check=True, capture_output=True, timeout=180)
                    subprocess.run([pdftoppm, "-png", "-r", "120", "-f", "1", "-l", "1", str(tmp / "chapter.pdf"), str(tmp / f"page-{kind}")], check=True, capture_output=True, timeout=120)
                    png = sorted(tmp.glob(f"page-{kind}*.png"))[0]
                    from PIL import Image
                    im = Image.open(png).convert("RGB")
                    w, hh = im.size
                    im = im.crop((0, 0, w, min(hh, int(w * (0.8 if kind == "docx" else 0.5)))))
                    if im.size[0] > MAXW:
                        im = im.resize((MAXW, int(MAXW * im.size[1] / im.size[0])), Image.LANCZOS)
                    stills[f"export-{'word' if kind == 'docx' else 'excel'}"] = im
                    print(f"  ✓ export-{'word' if kind == 'docx' else 'excel'}")
                    (tmp / "chapter.pdf").unlink(missing_ok=True)
        step("export-web", s_exports)

        # ---------------------------------------------------------------- backup & storage
        def s_backup():
            page.locator("#btn-settings").click()
            modal()
            page.locator("[data-test=open-backup]").click()
            page.wait_for_selector("[data-test=backup-dialog]")
            page.wait_for_timeout(500)
            shot("backup", modal())
            esc(2)
        step("backup", s_backup)

        browser.close()
    OUT.mkdir(parents=True, exist_ok=True)
    for name, im in stills.items():
        out = OUT / f"{name}.webp"
        im.save(out, "WEBP", quality=84, method=6)
        print(f"{out.relative_to(ROOT)}  {out.stat().st_size // 1024} KB  {im.size[0]}x{im.size[1]}")
    shutil.rmtree(h.tmp, ignore_errors=True)
    if failed:
        print("FAILED:", ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
