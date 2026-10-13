import re
"""End-to-end through the real UI and the real Api, with no server: Chromium opens index.html
as a file:// page and `window.pywebview.api` is bridged to Python (see bridge.py).

Skipped when Playwright or its Chromium is not available."""
import os
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from bridge import Harness  # noqa: E402
from flex_scratchpad.flex.demo import T_ARAB, T_STORY  # noqa: E402

pw = pytest.importorskip("playwright.sync_api")


def chromium_path():
    env = os.environ.get("FS_CHROMIUM")
    if env:
        return env
    root = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers"))
    for p in sorted(root.glob("chromium-*/chrome-linux/chrome"), reverse=True):
        return str(p)
    return None


@pytest.fixture(scope="module")
def browser():
    with pw.sync_playwright() as p:
        kw = {"args": ["--autoplay-policy=no-user-gesture-required"]}
        exe = chromium_path()
        if exe:
            kw["executable_path"] = exe
        try:
            b = p.chromium.launch(**kw)
        except Exception as e:  # noqa: BLE001
            pytest.skip(f"Chromium not available: {e}")
        yield b
        b.close()


@pytest.fixture()
def app(browser):
    h = Harness()
    ctx = browser.new_context(viewport={"width": 1360, "height": 860})
    errors = []
    ctx.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page = h.open(ctx)
    page.wait_for_timeout(500)
    yield h, page, errors
    ctx.close()
    shutil.rmtree(h.tmp, ignore_errors=True)


def body_of(h):
    notes = h.api._nb.list_notes()
    return h.api.get_note(notes[0]["id"])["body"]


def tool(page, text, nth=0):
    """Click a button in the bar under the nth table; the bar shows while the table is hovered."""
    page.locator("table.md-table").nth(nth).hover()
    page.locator(".tbl-tools").nth(nth).locator("button", has_text=text).click()


def new_note(page, title):
    """Ctrl+N, then wait until the new (untitled) note is actually open before typing."""
    before = page.locator(".note-card").count()
    page.keyboard.press("Control+n")
    page.wait_for_function("(n) => document.querySelectorAll('.note-card').length > n && document.getElementById('note-title').value === ''", arg=before)
    page.fill("#note-title", title)
    page.keyboard.press("Enter")
    page.wait_for_timeout(100)


def test_welcome_note_and_markers(app):
    h, page, errors = app
    assert page.locator(".note-card").count() == 1
    assert page.locator(".blk").count() >= 6
    assert page.locator("table.md-table").count() == 1
    # markers are present as faint spans, text intact
    assert page.locator(".md-marker").first.is_visible()
    assert page.locator(".blk-h .blk-body").first.inner_text() == "# Welcome to FLEx Scratchpad"
    assert not errors


def test_insert_entry_and_segments_then_style(app):
    h, page, errors = app
    page.keyboard.press("Control+Shift+L")
    page.fill(".picker input[type=text]", "kab")
    page.wait_for_selector(".pick-item .hw")
    page.locator(".pick-item").first.click()
    page.wait_for_selector(".picker-preview .entry-card")
    page.locator(".btn.primary", has_text="Insert rendered").click()
    page.wait_for_selector("#editor .entry-card")
    page.keyboard.press("Control+Shift+L")
    page.locator(".picker-tabs button", has_text="Texts").click()
    page.wait_for_selector(".pick-item .hw")
    page.locator(".pick-item").first.click()
    page.wait_for_selector(".picker-preview .segment")
    segs = page.locator(".picker-preview .segment")
    segs.nth(0).click()
    segs.nth(1).click()
    page.locator(".btn.primary", has_text="Insert segments").click()
    page.wait_for_selector("#editor .text-obj")
    assert page.locator("#editor .text-obj .segment").count() == 2
    # click a word → highlight it from the popover
    page.locator("#editor .text-obj .word-cell").nth(1).locator(".il-txt").click()
    page.wait_for_selector(".popover")
    page.locator(".popover .sw").nth(1).click()
    page.wait_for_selector("#editor .text-obj .st-hl")
    page.wait_for_timeout(900)
    body = body_of(h)
    assert "{{flex:entry 6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0001}}" in body
    assert re.search(r"\{\{flex:text %s seg=1-2( at=[0-9a-f-]+)? hl\[#ffd6a5\]=1\.2\}\}" % T_STORY, body), body
    assert not errors


def test_paste_flex_link(app):
    h, page, errors = app
    new_note(page, "Pasted")
    url = "silfw://localhost/link?app=flex&server=&database=Kalu%20Demo&tool=lexiconEdit&guid=6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0002&tag="
    page.evaluate("""(url) => {
      const dt = new DataTransfer(); dt.setData('text/plain', url);
      document.activeElement.dispatchEvent(new InputEvent('beforeinput', { inputType: 'insertFromPaste', dataTransfer: dt, bubbles: true, cancelable: true }));
    }""", url)
    page.wait_for_selector(".modal", timeout=5000)
    assert "tiket" in page.locator(".modal-body").inner_text()
    page.locator(".modal .btn.primary", has_text="Insert rendered").click()
    page.wait_for_selector("#editor .entry-card")
    page.wait_for_timeout(900)
    assert "{{flex:entry 6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0002}}" in body_of(h)


def test_typing_lists_headings_undo(app):
    h, page, errors = app
    new_note(page, "Typing")
    page.keyboard.type("first")
    page.keyboard.press("Shift+Enter")
    page.keyboard.type("second")
    page.keyboard.press("Enter")
    page.keyboard.type("- item one")
    page.keyboard.press("Enter")
    page.keyboard.type("item two")
    page.keyboard.press("Enter")
    page.keyboard.press("Enter")
    page.keyboard.type("## Head")
    page.wait_for_timeout(900)
    assert body_of(h) == "first\nsecond\n\n- item one\n- item two\n\n## Head"
    assert page.locator(".blk-h").count() == 1 and page.locator(".blk-list").count() == 1
    page.keyboard.press("Control+z")
    page.wait_for_timeout(900)
    assert not body_of(h).endswith("## Head")
    assert not errors


def test_table_cell_edit_and_embed_in_cell(app):
    h, page, errors = app
    cell = page.locator("table.md-table td .cell-view").nth(1)
    cell.scroll_into_view_if_needed()
    cell.dispatch_event("mousedown")
    page.wait_for_selector(".cell-edit")
    page.keyboard.press("End")
    page.keyboard.type(" {{flex:text %s seg=1}}" % T_STORY)
    page.keyboard.press("Shift+Enter")
    page.keyboard.type("line two")
    page.keyboard.press("Escape")
    page.wait_for_selector("table.md-table .flex-inline .flex-collapsed")
    page.wait_for_timeout(900)
    body = body_of(h)
    assert re.search(r"\{\{flex:text %s seg=1( at=[0-9a-f-]+)?\}\}<br>line two \|" % T_STORY, body), body
    # column style popover
    tool(page, "Table")
    page.locator(".popover .tog", has_text="Compact").click()
    page.wait_for_timeout(900)
    assert "{table: striped; compact; col 1: bold}" in body_of(h)


def test_chart_block(app):
    h, page, errors = app
    new_note(page, "Chart")
    page.locator("#toolbar [data-ins=chart]").dispatch_event("mousedown")
    page.wait_for_selector(".chart-box canvas")
    page.wait_for_timeout(900)
    assert "```chart\ntype: bar" in body_of(h)
    assert not errors


def test_rtl_text_and_style_targets(app):
    h, page, errors = app
    new_note(page, "RTL")
    page.keyboard.type("{{flex:text %s}}" % T_ARAB)
    page.keyboard.press("Enter")
    page.wait_for_selector(".word-row[dir=rtl]")
    assert page.locator(".word-row[dir=rtl]").count() == 2
    page.keyboard.type('{{flex:text %s seg=2-3 u=morph:"-mo" hl=ft:2 b=2.1:1-2}}' % T_STORY)
    page.keyboard.press("Enter")
    page.wait_for_selector(".text-obj .st-u")
    assert page.locator(".st-u").inner_text() == "-mo"
    assert page.locator(".seg-free .st-hl").inner_text() == "Yesterday the child saw the river."
    assert page.locator(".il-txt .st-b").inner_text() == "Ha"


def test_audio_segment_plays_and_clip_is_cached(app):
    h, page, errors = app
    new_note(page, "Audio")
    page.keyboard.type("{{flex:text %s seg=2-2}}" % T_STORY)
    page.keyboard.press("Enter")
    page.wait_for_selector(".seg-play")
    page.locator(".seg-play").first.click()
    page.wait_for_selector(".transport")
    page.wait_for_timeout(400)
    t = page.evaluate("FS.audio.current ? FS.audio.current.el.currentTime : -1")
    assert 1.4 <= t <= 3.3
    page.wait_for_timeout(2600)
    assert page.evaluate("!!FS.audio.current") is False       # stopped at `end`
    clips = list(h.api._nb.cache_dir.rglob("*_1500-3200.wav"))
    assert clips, "the clip was cut into the notebook cache"
    # the clip keeps playing after the source media is gone
    import os
    src = h.api._flex.backend.texts[T_STORY]["media"][0]["path"]
    os.remove(src)
    h.api._flex.backend._resolve_media()
    info = h.api.audio_clip(T_STORY, None, 1500, 3200)
    assert info["found"] is False and info["clipUrl"].endswith("_1500-3200.wav")


def test_search_tags_and_folders(app):
    h, page, errors = app
    new_note(page, "Harmony")
    page.keyboard.type("vowel harmony in verbs #phonology")
    page.wait_for_timeout(900)
    page.fill("#search", "harmony")
    page.wait_for_selector(".note-card mark")
    assert page.locator(".note-card").count() == 1
    page.fill("#search", "")
    page.wait_for_timeout(300)
    page.locator(".tag-item", has_text="#phonology").click()
    page.wait_for_timeout(300)
    assert page.locator(".note-card").count() == 1
    page.locator(".tag-item", has_text="#phonology").click()
    # find in note
    page.keyboard.press("Control+f")
    page.fill("#find-input", "verbs")
    page.wait_for_selector(".find-hit")
    assert "1 found" in page.locator("#find-count").inner_text()


def test_mock_mode_without_python(browser):
    """The page also runs with no bridge at all (plain browser): the JS mock serves demo data."""
    ctx = browser.new_context()
    page = ctx.new_page()
    from bridge import UI
    page.goto(UI.as_uri() + "?mock=1")
    page.wait_for_selector("#tabs .tab-item", timeout=10000)
    page.wait_for_timeout(600)
    page.locator(".tab-item", has_text="Grammar").click()
    page.wait_for_selector(".note-card")
    page.locator(".note-card", has_text="Past tense").click()
    page.wait_for_selector("#editor .entry-card")
    page.wait_for_selector("#editor .text-obj .st-u")
    ctx.close()


def paste(page, plain, html=None):
    page.evaluate("""([plain, html]) => {
      const dt = new DataTransfer(); dt.setData('text/plain', plain); if (html) dt.setData('text/html', html);
      document.activeElement.dispatchEvent(new InputEvent('beforeinput', { inputType: 'insertFromPaste', dataTransfer: dt, bubbles: true, cancelable: true }));
    }""", [plain, html])


def test_paste_table_from_excel_and_html(app):
    h, page, errors = app
    new_note(page, "Pasted tables")
    # Excel / Word / browser: tab-separated text plus an HTML table on the clipboard
    html = ('<html><body><table><tr><td style="font-weight:700">Form</td><th>Gloss</th></tr>'
            '<tr><td>kabir</td><td>dog<br>canid</td></tr><tr><td><b>ka-</b></td><td>3SG &amp; co</td></tr></table></body></html>')
    paste(page, "Form\tGloss\r\nkabir\tdog\r\nka-\t3SG", html)
    page.wait_for_selector("table.md-table")
    page.wait_for_timeout(900)
    body = body_of(h)
    assert "| **Form** | Gloss |" in body and "| kabir | dog<br>canid |" in body and "| **ka-** | 3SG & co |" in body
    # plain tab-separated text alone (no HTML) also becomes a table
    page.locator(".blk").last.locator(".blk-body").click()
    paste(page, "a\tb\n1\t2\n")
    page.wait_for_timeout(900)
    assert "| a | b |\n|---|---|\n| 1 | 2 |" in body_of(h)
    assert page.locator("table.md-table").count() == 2
    assert not errors


def test_insert_flex_into_table_cell_and_overlay(app):
    h, page, errors = app
    # edit a cell, then insert through the toolbar button (which closes the cell editor first)
    cell = page.locator("table.md-table td .cell-view").nth(1)
    cell.scroll_into_view_if_needed()
    cell.dispatch_event("mousedown")
    page.wait_for_selector(".cell-edit")
    page.keyboard.press("End")
    page.locator("#btn-insert-flex").click()
    page.fill(".picker input[type=text]", "kab")
    page.wait_for_selector(".pick-item .hw")
    page.locator(".pick-item").first.click()
    page.wait_for_selector(".picker-preview .entry-card")
    page.locator(".btn.primary", has_text="Insert rendered").click()
    page.wait_for_selector("table.md-table .flex-collapsed")
    page.wait_for_timeout(900)
    assert "| Form | A vernacular form {{flex:entry 6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0001}} |" in body_of(h)
    # the chip shows the headword; clicking it opens the overlay with the full card, no layout change
    chip = page.locator("table.md-table .flex-collapsed")
    page.wait_for_function("document.querySelector('table.md-table .flex-collapsed .cttl').textContent.startsWith('kabir')")
    height_before = page.evaluate("document.querySelector('table.md-table').getBoundingClientRect().height")
    chip.click()
    page.wait_for_selector(".flex-overlay.pinned .entry-card")
    assert page.evaluate("document.querySelector('table.md-table').getBoundingClientRect().height") == height_before
    page.keyboard.press("Escape")
    page.wait_for_selector(".flex-overlay", state="detached")
    # ⤢ shows the full card in the cell; the compact header's ⤡ collapses it back to a chip
    page.locator("table.md-table .flex-collapsed .cexp").click()
    page.wait_for_selector("table.md-table .entry-card")
    page.wait_for_timeout(700)
    assert "{{flex:entry 6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0001 expanded}}" in body_of(h)
    page.locator("table.md-table .flex-head.compact button[title='Collapse to a chip']").click()
    page.wait_for_selector("table.md-table .flex-collapsed")
    page.wait_for_timeout(700)
    assert "expanded" not in body_of(h)
    # Ctrl+Shift+L from inside a cell reaches the app too
    cell2 = page.locator("table.md-table td .cell-view").nth(3)
    cell2.dispatch_event("mousedown")
    page.wait_for_selector(".cell-edit")
    page.keyboard.press("Control+Shift+L")
    page.wait_for_selector(".picker")
    page.keyboard.press("Escape")
    assert not errors


def test_collapse_expand_and_hover_overlay(app):
    h, page, errors = app
    new_note(page, "Collapse")
    page.keyboard.type("{{flex:text %s seg=1-2}}" % T_STORY)
    page.keyboard.press("Enter")
    page.wait_for_selector("#editor .text-obj")
    # collapse from the header → chip, flag saved in the note
    page.locator("#editor .text-obj .flex-head button[title='Collapse to a chip']").click()
    page.wait_for_selector("#editor .flex-collapsed")
    page.wait_for_timeout(900)
    assert re.search(r"\{\{flex:text %s seg=1-2( at=[0-9a-f-]+)? collapsed\}\}" % T_STORY, body_of(h)), body_of(h)
    assert page.locator("#editor .flex-collapsed .crange").inner_text() == "1.1–1.2"
    # hover → temporary overlay with the interlinear; moving away closes it
    page.hover("#editor .flex-collapsed")
    page.wait_for_selector(".flex-overlay .text-obj .segment")
    assert page.locator(".flex-overlay.pinned").count() == 0
    page.mouse.move(5, 5)
    page.wait_for_selector(".flex-overlay", state="detached")
    # ⤢ expands in place and removes the flag
    page.locator("#editor .flex-collapsed .cexp").click()
    page.wait_for_selector("#editor .text-obj .segment")
    page.wait_for_timeout(900)
    assert "collapsed" not in body_of(h)
    assert not errors


def test_panes_resize_and_collapse(app):
    h, page, errors = app
    rail_w = lambda: page.evaluate("document.getElementById('rail').getBoundingClientRect().width")
    assert 230 <= rail_w() <= 250
    sp = page.locator("#split-rail")
    box = sp.bounding_box()
    page.mouse.move(box["x"] + 2, box["y"] + 200)
    page.mouse.down()
    page.mouse.move(box["x"] + 102, box["y"] + 200, steps=5)
    page.mouse.up()
    assert 335 <= rail_w() <= 345
    assert page.evaluate("JSON.parse(localStorage.getItem('fs:panes')).railW") == 340
    # double-click collapses one pane; Ctrl+\ hides both; the handle brings them back
    sp.dblclick()
    assert page.locator("#app.rail-collapsed").count() == 1 and rail_w() == 0
    page.keyboard.press("Control+\\")
    assert page.locator("#app.rail-collapsed.list-collapsed").count() == 1
    assert page.locator("#btn-nav").is_visible()
    page.locator("#btn-nav").click()
    assert page.locator("#app.rail-collapsed").count() == 0 and rail_w() == 340
    assert not errors


def test_multiline_emphasis_wraps_per_line(app):
    h, page, errors = app
    new_note(page, "Emphasis")
    page.keyboard.type("first line")
    page.keyboard.press("Shift+Enter")
    page.keyboard.type("second line")
    page.keyboard.press("Control+a")
    page.keyboard.press("Control+i")
    page.wait_for_timeout(900)
    assert body_of(h) == "*first line*\n*second line*"
    assert page.locator("#editor .md-i").count() == 2
    page.keyboard.press("Control+a")
    page.keyboard.press("Control+i")
    page.wait_for_timeout(900)
    assert body_of(h) == "first line\nsecond line"


def test_column_resize_writes_width_and_wide(app):
    h, page, errors = app
    th = page.locator("table.md-table thead th[data-c]").first
    th.scroll_into_view_if_needed()
    handle = th.locator(".col-resizer")
    box = handle.bounding_box()
    page.mouse.move(box["x"] + 4, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(box["x"] + 124, box["y"] + box["height"] / 2, steps=6)
    page.mouse.up()
    page.wait_for_timeout(900)
    body = body_of(h)
    import re
    m = re.search(r"col 1: bold, width (\d+)px", body)
    assert m and 150 <= int(m.group(1)) <= 260, body.split("\n")[-1]
    # dragging far beyond the pane turns the wide flag on and the wrapper scrolls sideways
    th = page.locator("table.md-table thead th[data-c]").first
    handle = th.locator(".col-resizer")
    box = handle.bounding_box()
    page.mouse.move(box["x"] + 4, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(box["x"] + 900, box["y"] + box["height"] / 2, steps=8)
    page.mouse.up()
    page.wait_for_timeout(900)
    assert "{table: striped; wide; col 1: bold, width" in body_of(h)
    assert page.evaluate("(() => { const w = document.querySelector('.tbl-wrap'); return w.scrollWidth > w.clientWidth; })()")
    assert not errors


def test_label_and_title_ws_from_menu(app):
    h, page, errors = app
    new_note(page, "Label")
    page.keyboard.type("{{flex:text %s seg=1}}" % T_STORY)
    page.keyboard.press("Enter")
    page.wait_for_selector("#editor .text-obj")
    page.locator("#editor .text-obj .flex-head button[title='Options']").click()
    page.wait_for_selector(".popover input[type=text]")
    page.fill(".popover input[type=text]", "causative ex. 3")
    page.keyboard.press("Enter")
    page.wait_for_timeout(900)
    assert re.search(r'\{\{flex:text %s seg=1( at=[0-9a-f-]+)? "causative ex\. 3"\}\}' % T_STORY, body_of(h)), body_of(h)
    assert page.locator("#editor .text-obj .flex-head .badge", has_text="causative ex. 3").count() == 1
    # collapse: the chip shows the label
    page.locator("#editor .text-obj .flex-head button[title='Collapse to a chip']").click()
    page.wait_for_selector("#editor .flex-collapsed")
    assert page.locator("#editor .flex-collapsed .cttl").inner_text() == "causative ex. 3"
    assert not errors


def test_undo_redo_from_anywhere(app):
    h, page, errors = app
    new_note(page, "Undo")
    page.keyboard.type("{{flex:text %s seg=1}}" % T_STORY)
    page.keyboard.press("Enter")
    page.wait_for_selector("#editor .text-obj")
    # a styling change made through the popover (focus is not in a text block afterwards)
    page.locator("#editor .text-obj .word-cell").first.locator(".il-txt").click()
    page.wait_for_selector(".popover")
    page.locator(".popover .tog", has_text="Bold").click()
    page.wait_for_selector("#editor .text-obj .st-b")
    page.keyboard.press("Escape")
    page.wait_for_timeout(700)
    assert "b=1.1" in body_of(h)
    page.locator("#editor-pane").click(position={"x": 400, "y": 60})
    page.keyboard.press("Control+z")
    page.wait_for_timeout(700)
    assert "b=1.1" not in body_of(h)
    page.keyboard.press("Control+y")
    page.wait_for_timeout(700)
    assert "b=1.1" in body_of(h)
    page.locator("#btn-undo").dispatch_event("mousedown")
    page.wait_for_timeout(700)
    assert "b=1.1" not in body_of(h)
    assert not errors


def test_export_html_and_docx(app):
    h, page, errors = app
    new_note(page, "Export me")
    page.keyboard.type("Intro with **bold** and #tag")
    page.keyboard.press("Enter")
    page.keyboard.type('{{flex:text %s seg=1-2 u=morph:"-mo" hl=ft:1 "ex. A"}}' % T_STORY)
    page.keyboard.press("Enter")
    page.keyboard.type("| Form | Example |\n|---|---|\n| kabir | {{flex:entry 6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0001}} |")
    page.wait_for_selector("#editor .text-obj")
    page.wait_for_timeout(900)
    html_path = str(h.tmp / "note.html")
    docx_path = str(h.tmp / "note.docx")
    html = page.evaluate("""async ([hp, dp]) => {
      const ed = window.__fsEditor || null;
      const api = window.pywebview.api;
      const notes = await api.list_notes(); const note = await api.get_note(notes[0].id);
      const editor = new FS.Editor(document.createElement('div'), {}); editor.load(note.body);
      const doc = await FS.exporter.buildDoc(note, editor);
      await api.export_note_html(note.id, FS.exporter.toHtml(doc), hp);
      await api.export_note_docx(note.id, doc, dp);
      return FS.exporter.toHtml(doc);
    }""", [html_path, docx_path])
    assert "<b>bold</b>" in html and 'class="obj"' in html and "ka-nuwa-mo" in html and "<u>-mo</u>" in html
    assert "The dog slept." in html and "kabir" in html and "a domestic dog" in html
    assert (h.tmp / "note.html").read_text(encoding="utf-8").startswith("<!doctype html>")
    import zipfile
    xml = zipfile.ZipFile(docx_path).read("word/document.xml").decode("utf-8")
    assert "ka-nuwa-mo" in xml and "The dog slept." in xml and "a domestic dog" in xml and '<w:u w:val="single"/>' in xml
    assert not errors


def test_paste_interlinear_lines_locates_the_segment(app):
    h, page, errors = app
    new_note(page, "Located")
    paste(page, "Word\tHaŋa\ttiket\tka-sila-mo\tpemu\nWord Gloss\tyesterday\tchild\tsaw\triver\nFree\tYesterday the child saw the river.")
    page.wait_for_selector(".modal")
    assert "The dog and the river" in page.locator(".modal-body").inner_text() and "segment 2" in page.locator(".modal-body").inner_text()
    page.locator(".modal .btn.primary", has_text="Insert rendered").click()
    page.wait_for_selector("#editor .text-obj .segment[data-n='2']")
    page.wait_for_timeout(900)
    assert re.search(r"\{\{flex:text %s seg=2( at=[0-9a-f-]+)?\}\}" % T_STORY, body_of(h)), body_of(h)
    # ordinary prose pastes as text
    paste(page, "just some ordinary prose that is nowhere in the project")
    page.wait_for_timeout(600)
    assert page.locator(".modal").count() == 0
    page.wait_for_timeout(900)
    assert "ordinary prose" in body_of(h)
    assert not errors


def test_paste_flex_link_into_table_cell(app):
    h, page, errors = app
    cell = page.locator("table.md-table td .cell-view").nth(3)
    cell.scroll_into_view_if_needed()
    cell.dispatch_event("mousedown")
    page.wait_for_selector(".cell-edit")
    page.keyboard.press("End")
    url = "silfw://localhost/link?database%3dKalu%2520Demo%26tool%3dlexiconEdit%26guid%3d6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0002%26tag%3d"
    page.evaluate("""(url) => {
      const dt = new DataTransfer(); dt.setData('text/plain', url);
      document.activeElement.dispatchEvent(new InputEvent('beforeinput', { inputType: 'insertFromPaste', dataTransfer: dt, bubbles: true, cancelable: true }));
    }""", url)
    page.wait_for_selector(".modal")
    assert "tiket" in page.locator(".modal-body").inner_text()
    page.locator(".modal .btn.primary", has_text="Insert rendered").click()
    page.wait_for_selector("table.md-table .flex-collapsed")
    page.wait_for_timeout(900)
    assert "with Ctrl+Shift+L {{flex:entry 6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0002}} |" in body_of(h), body_of(h).split("\n")[-3:]
    # and "Paste as text" really pastes
    cell = page.locator("table.md-table td .cell-view").nth(1)
    cell.dispatch_event("mousedown")
    page.wait_for_selector(".cell-edit")
    page.keyboard.press("End")
    page.evaluate("""(url) => {
      const dt = new DataTransfer(); dt.setData('text/plain', url);
      document.activeElement.dispatchEvent(new InputEvent('beforeinput', { inputType: 'insertFromPaste', dataTransfer: dt, bubbles: true, cancelable: true }));
    }""", url)
    page.wait_for_selector(".modal")
    page.locator(".modal .btn", has_text="Paste as text").click()
    page.wait_for_timeout(900)
    assert "A vernacular form silfw://localhost/link?database%3dKalu" in body_of(h)
    assert not errors


def test_freeze_panes(app):
    h, page, errors = app
    tool(page, "Table")
    page.wait_for_selector(".popover input[type=number]")
    rows = page.locator(".popover input[type=number]").nth(0)
    rows.fill("1")
    rows.dispatch_event("change")
    page.wait_for_timeout(900)
    assert "freeze rows 1" in body_of(h)
    th = page.locator("table.md-table thead th[data-c]").first
    assert page.evaluate("(el) => getComputedStyle(el).position", th.element_handle()) == "sticky"
    assert page.locator(".tbl-wrap.frozen").count() == 1


def test_merge_cells_split_and_merge_tables(app):
    h, page, errors = app
    # merge the first body cell with the one to its right
    cell = page.locator("table.md-table td .cell-view").nth(0)
    cell.scroll_into_view_if_needed()
    cell.dispatch_event("mousedown")
    page.wait_for_selector(".cell-edit")
    tool(page, "Cells")
    page.locator(".popover .menu-item", has_text="to the right").click()
    page.wait_for_timeout(900)
    assert "span 2.1: 1x2" in body_of(h)
    assert page.locator("table.md-table td[colspan='2']").count() == 1
    # split the table above its last row
    last = page.locator("table.md-table tbody tr").last.locator(".cell-view").first
    last.dispatch_event("mousedown")
    page.wait_for_selector(".cell-edit")
    tool(page, "Table")
    page.locator(".popover button", has_text="Split above row").click()
    page.wait_for_timeout(900)
    assert page.locator("table.md-table").count() == 2
    body = body_of(h)
    assert body.count("{table:") == 2
    assert "span 2.1: 1x2" in body
    # and merge them back through the second table's Table menu
    page.locator("table.md-table").nth(1).locator("td .cell-view").first.dispatch_event("mousedown")
    page.wait_for_selector(".cell-edit")
    tool(page, "Table", 1)
    page.locator(".popover button", has_text="Merge with table above").click()
    page.wait_for_timeout(900)
    assert page.locator("table.md-table").count() == 1
    assert body_of(h).count("{table:") == 1
    assert not errors


def test_hide_markers_toggle(app):
    h, page, errors = app
    assert page.locator(".md-marker").first.is_visible()
    page.locator("#btn-markers").click()
    page.wait_for_function("() => document.body.classList.contains('md-hide')")
    # the heading's "# " is not displayed, the text is intact
    assert not page.locator(".blk-h .md-marker").first.is_visible()
    assert page.locator(".blk-h .blk-body").first.inner_text().strip() == "Welcome to FLEx Scratchpad"
    assert h.api._nb.config["settings"]["hideMarkers"] is True
    # putting the caret inside a bold run reveals its markers
    bold = page.locator(".blk-body .md-b").first
    bold.scroll_into_view_if_needed()
    page.evaluate("""(el) => { const r = document.createRange(); r.setStart(el.firstChild, 2); r.collapse(true); const s = getSelection(); s.removeAllRanges(); s.addRange(r); el.closest('.blk-body').focus(); }""", bold.element_handle())
    page.wait_for_timeout(200)
    assert page.locator(".md-marker.reveal").count() >= 2
    assert page.locator(".md-marker.reveal").first.is_visible()
    # Backspace right after a hidden list bullet removes the whole bullet
    new_note(page, "Bullets")
    page.click(".blk-body")
    page.keyboard.type("- item")
    page.wait_for_timeout(300)
    page.keyboard.press("Home")
    page.keyboard.press("Backspace")
    page.wait_for_timeout(900)
    assert body_of(h).strip() == "item" or "item" in page.locator(".blk-body").last.inner_text()
    assert "- item" not in page.locator(".blk-body").last.inner_text()
    page.locator("#btn-markers").click()
    page.wait_for_function("() => !document.body.classList.contains('md-hide')")
    assert not errors


def test_freeze_panes_menu(app):
    h, page, errors = app
    cell = page.locator("table.md-table td .cell-view").nth(1)
    cell.scroll_into_view_if_needed()
    cell.dispatch_event("mousedown")
    page.wait_for_selector(".cell-edit")
    tool(page, "Cells")
    page.locator(".popover .menu-item", has_text="Freeze panes here").click()
    page.wait_for_timeout(900)
    assert "freeze rows 1; freeze cols 1" in body_of(h)
    assert page.locator(".tbl-wrap.frozen").count() == 1
    page.locator("table.md-table td .cell-view").nth(0).dispatch_event("mousedown")
    page.wait_for_selector(".cell-edit")
    tool(page, "Table")
    page.locator(".popover button", has_text="Unfreeze").click()
    page.wait_for_timeout(900)
    assert "freeze" not in body_of(h)
    assert not errors


def test_table_rerender_saves_the_open_cell(app):
    """Typing in a cell and then resizing the column (or pressing + Row) must keep the text."""
    h, page, errors = app
    cell = page.locator("table.md-table td .cell-view").nth(1)
    cell.scroll_into_view_if_needed()
    cell.dispatch_event("mousedown")
    page.wait_for_selector(".cell-edit")
    page.keyboard.press("End")
    page.keyboard.type(" TYPED")
    page.wait_for_timeout(300)
    th = page.locator("table.md-table thead th[data-c]").nth(1)
    handle = th.locator(".col-resizer")
    box = handle.bounding_box()
    page.mouse.move(box["x"] + 4, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(box["x"] + 80, box["y"] + box["height"] / 2, steps=6)
    page.mouse.up()
    page.wait_for_timeout(900)
    assert "TYPED" in body_of(h)
    assert "col 2: width" in body_of(h)
    # the same through a tool button while a cell is open
    cell = page.locator("table.md-table td .cell-view").nth(0)
    cell.dispatch_event("mousedown")
    page.wait_for_selector(".cell-edit")
    page.keyboard.press("End")
    page.keyboard.type(" MORE")
    page.wait_for_timeout(200)
    tool(page, "+ Row")
    page.wait_for_timeout(900)
    body = body_of(h)
    assert "MORE" in body and "TYPED" in body
    # and both edits are on the undo stack
    page.keyboard.press("Escape")
    page.locator("#btn-undo").click()
    page.wait_for_timeout(900)
    assert body_of(h).count("|") < body.count("|")
    assert not errors


def test_cell_range_selection_and_context_menu(app):
    h, page, errors = app
    cells = page.locator("table.md-table td .cell-view")
    cells.nth(0).scroll_into_view_if_needed()
    cells.nth(0).dispatch_event("mousedown")
    page.wait_for_selector(".cell-edit")
    # Shift+click another cell selects the rectangle
    page.locator("table.md-table td[data-r='2'][data-c='1'] .cell-view").dispatch_event("mousedown", {"shiftKey": True, "bubbles": True})
    page.wait_for_timeout(200)
    assert page.locator("table.md-table td.sel").count() == 4
    assert page.locator(".cell-edit").count() == 0
    # right-click inside the selection → Merge cells
    page.locator("table.md-table td.sel").first.click(button="right")
    page.wait_for_selector(".popover.menu")
    assert page.locator(".popover.menu .menu-item", has_text="Freeze panes here").count() == 1
    assert page.locator(".popover.menu .menu-item", has_text="Split table above").count() == 1
    page.locator(".popover.menu .menu-item", has_text="Merge cells").click()
    page.wait_for_timeout(900)
    assert "span 2.1: 2x2" in body_of(h)
    assert page.locator("table.md-table td[colspan='2'][rowspan='2']").count() == 1
    # right-click the merged cell → Unmerge
    page.locator("table.md-table td.merged").click(button="right")
    page.wait_for_selector(".popover.menu")
    page.locator(".popover.menu .menu-item", has_text="Unmerge").click()
    page.wait_for_timeout(900)
    assert "span" not in body_of(h)
    # insert a row above the last row from the menu
    n = page.locator("table.md-table tbody tr").count()
    page.locator("table.md-table tbody tr").last.locator("td").first.click(button="right")
    page.wait_for_selector(".popover.menu")
    page.locator(".popover.menu .menu-item", has_text="Insert row above").click()
    page.wait_for_timeout(900)
    assert page.locator("table.md-table tbody tr").count() == n + 1
    assert not errors


def test_table_tools_stick_to_the_pane_bottom(app):
    h, page, errors = app
    # a tall table: 40 rows, then scroll so its top is visible and its bottom is not
    new_note(page, "Tall")
    page.click(".blk-body")
    paste(page, "| a | b |\n|---|---|\n" + "\n".join(f"| r{i} | x |" for i in range(40)))
    page.wait_for_selector("table.md-table")
    page.wait_for_timeout(600)
    page.evaluate("() => { const ed = document.getElementById('editor'); const t = document.querySelector('table.md-table'); ed.scrollTop = t.getBoundingClientRect().top - ed.getBoundingClientRect().top + ed.scrollTop - 40; }")
    page.wait_for_timeout(200)
    pos = page.evaluate("() => { const ed = document.getElementById('editor').getBoundingClientRect(); const t = document.querySelector('table.md-table').getBoundingClientRect(); const b = document.querySelector('.tbl-tools').getBoundingClientRect(); return { tableBottom: t.bottom, paneBottom: ed.bottom, barBottom: b.bottom, barTop: b.top }; }")
    assert pos["tableBottom"] > pos["paneBottom"], pos          # the table really is cut off
    assert pos["barBottom"] <= pos["paneBottom"] + 1, pos        # the bar is pinned inside the pane
    assert pos["barTop"] >= pos["paneBottom"] - 60, pos          # … at its bottom
    assert not errors


def test_pasted_html_table_keeps_merged_cells(app):
    h, page, errors = app
    new_note(page, "Merged paste")
    page.click(".blk-body")
    html = ("<table><tr><th colspan=2>Head</th><th>C</th></tr>"
            "<tr><td rowspan=2>tall</td><td>b1</td><td>c1</td></tr>"
            "<tr><td>b2</td><td>c2</td></tr></table>")
    paste(page, "Head\t\tC\ntall\tb1\tc1\n\tb2\tc2", html)
    page.wait_for_selector("table.md-table")
    page.wait_for_timeout(900)
    body = body_of(h)
    assert "| Head |  | C |" in body
    assert "| tall | b1 | c1 |" in body and "|  | b2 | c2 |" in body
    assert "span 1.1: 1x2" in body and "span 2.1: 2x1" in body
    assert page.locator("table.md-table th[colspan='2']").count() == 1
    assert page.locator("table.md-table td[rowspan='2']").count() == 1
    assert not errors


def test_row_column_and_table_selection_handles(app):
    h, page, errors = app
    table = page.locator("table.md-table")
    table.scroll_into_view_if_needed()
    table.hover()
    ncols = page.locator("table.md-table thead th[data-c]").count()
    nrows = page.locator("table.md-table tr:not(.gutter-row)").count()
    # a column handle selects the whole column
    page.locator("table.md-table th.gutter.col").nth(1).dispatch_event("mousedown", {"button": 0, "bubbles": True})
    page.wait_for_timeout(100)
    assert page.locator("table.md-table .sel").count() == nrows
    assert page.locator("table.md-table th.gutter.col.on").count() == 1
    # Shift-click the first column handle extends to both columns
    page.locator("table.md-table th.gutter.col").nth(0).dispatch_event("mousedown", {"button": 0, "shiftKey": True, "bubbles": True})
    page.wait_for_timeout(100)
    assert page.locator("table.md-table .sel").count() == nrows * 2
    # a row handle selects the row; the corner selects everything
    page.locator("table.md-table th.gutter.row").nth(2).dispatch_event("mousedown", {"button": 0, "bubbles": True})
    page.wait_for_timeout(100)
    assert page.locator("table.md-table .sel").count() == ncols
    assert page.locator("table.md-table th.gutter.row.on").count() == 1
    page.locator("table.md-table th.gutter.all").dispatch_event("mousedown", {"button": 0, "bubbles": True})
    page.wait_for_timeout(100)
    assert page.locator("table.md-table .sel").count() == nrows * ncols
    # right-click a row handle outside the selection: the menu acts on that row alone
    page.locator("table.md-table td .cell-view").first.dispatch_event("mousedown")
    page.keyboard.press("Escape")
    page.locator("table.md-table th.gutter.row").last.click(button="right")
    page.wait_for_selector(".popover.menu")
    page.locator(".popover.menu .menu-item", has_text="Delete row").click()
    page.wait_for_timeout(900)
    assert page.locator("table.md-table tr:not(.gutter-row)").count() == nrows - 1
    # the column handle still resizes and the grid still edits after all that
    page.locator("table.md-table td .cell-view").first.dispatch_event("mousedown")
    page.wait_for_selector(".cell-edit")
    assert not errors


def clip_event(page, kind, plain, html=None):
    """Fire a clipboard event on the document with the given data; returns the DataTransfer's text afterwards."""
    return page.evaluate("""([kind, plain, html]) => {
      const dt = new DataTransfer(); if (plain != null) dt.setData('text/plain', plain); if (html) dt.setData('text/html', html);
      const ev = new ClipboardEvent(kind, { clipboardData: dt, bubbles: true, cancelable: true });
      document.body.dispatchEvent(ev);
      return { prevented: ev.defaultPrevented, text: dt.getData('text/plain'), html: dt.getData('text/html') };
    }""", [kind, plain, html])


def test_copy_paste_rows_columns_and_cells(app):
    h, page, errors = app
    table = page.locator("table.md-table")
    table.scroll_into_view_if_needed()
    table.hover()
    nrows = page.locator("table.md-table tr:not(.gutter-row)").count()
    ncols = page.locator("table.md-table thead th[data-c]").count()
    # select row 2 (handle) and paste two TSV rows: they go in above it
    page.locator("table.md-table th.gutter.row").nth(1).dispatch_event("mousedown", {"button": 0, "bubbles": True})
    page.wait_for_timeout(100)
    r = clip_event(page, "paste", "new1\tx1\nnew2\tx2")
    assert r["prevented"]
    page.wait_for_timeout(900)
    body = body_of(h)
    assert page.locator("table.md-table tr:not(.gutter-row)").count() == nrows + 2
    assert "| new1 | x1 |" in body and "| new2 | x2 |" in body
    assert body.index("| new2 | x2 |") < body.index("| Example |")
    # select column 2 and paste an HTML column: inserted to the left, grid grows if taller
    page.locator("table.md-table th.gutter.col").nth(1).dispatch_event("mousedown", {"button": 0, "bubbles": True})
    page.wait_for_timeout(100)
    clip_event(page, "paste", "H\nv1\nv2", "<table><tr><td>H</td></tr><tr><td>v1</td></tr><tr><td>v2</td></tr></table>")
    page.wait_for_timeout(900)
    assert page.locator("table.md-table thead th[data-c]").count() == ncols + 1
    assert "| Column | H | What goes here |" in body_of(h) and "| new1 | v1 | x1 |" in body_of(h) and "| Form |  | A vernacular form |" in body_of(h)
    # a plain range: copy gives TSV of the source, Delete clears, paste overwrites from the corner
    page.locator("table.md-table td[data-r='1'][data-c='0'] .cell-view").dispatch_event("mousedown")
    page.wait_for_selector(".cell-edit")
    page.locator("table.md-table td[data-r='2'][data-c='1'] .cell-view").dispatch_event("mousedown", {"shiftKey": True, "bubbles": True})
    page.wait_for_timeout(100)
    r = clip_event(page, "copy", None)
    assert r["prevented"] and r["text"] == "new1\tv1\nnew2\tv2", r
    assert "<td>new1</td>" in r["html"]
    page.keyboard.press("Delete")
    page.wait_for_timeout(900)
    assert "| new1 |" not in body_of(h) and "|  |  | x1 |" in body_of(h)
    # paste over a range from its top-left corner, growing the table to fit
    page.locator("table.md-table td[data-r='4'][data-c='1'] .cell-view").dispatch_event("mousedown")
    page.wait_for_selector(".cell-edit")
    page.locator("table.md-table td[data-r='4'][data-c='2'] .cell-view").dispatch_event("mousedown", {"shiftKey": True, "bubbles": True})
    page.wait_for_timeout(100)
    clip_event(page, "paste", "a\tb\tc\nd\te\tf")
    page.wait_for_timeout(900)
    body = body_of(h)
    assert "| Example | a | b | c |" in body and "|  | d | e | f |" in body
    page.locator("table.md-table td[data-r='1'][data-c='0']").click(button="right")
    page.wait_for_selector(".popover.menu")
    assert page.locator(".popover.menu .menu-item", has_text="Paste rows above").count() == 1
    page.keyboard.press("Escape")
    assert not errors


def insert_text_segments(page, first, last):
    """Open the picker on the demo story and insert segments first..last (0-based clicks)."""
    page.keyboard.press("Control+Shift+L")
    page.locator(".picker-tabs button", has_text="Texts").click()
    page.wait_for_selector(".pick-item .hw")
    page.locator(".pick-item").first.click()
    page.wait_for_selector(".picker-preview .segment")
    segs = page.locator(".picker-preview .segment")
    segs.nth(first).click()
    segs.nth(last).click()
    page.locator(".btn.primary", has_text="Insert segments").click()
    page.wait_for_selector("#editor .text-obj .segment")


def test_flex_numbering_shown_and_accepted(app):
    h, page, errors = app
    new_note(page, "Numbering")
    page.click(".blk-body")
    insert_text_segments(page, 0, 2)
    # the gutters show FLEx's numbers (paragraph.segment); the badge shows both numberings
    nums = page.locator("#editor .text-obj .segnum").all_inner_texts()
    assert nums == ["1.1", "1.2", "2.1"], nums
    badge = page.locator("#editor .text-obj .flex-head .badge").first.inner_text()
    assert "segments 1.1–2.1" in badge and "(1–3 of" in badge, badge
    # glosses carry the morpheme break characters of their forms
    seg = page.locator("#editor .text-obj .segment").first.inner_text()
    assert "3SG-" in seg and "-PST" in seg, seg
    # the picker's range fields accept "2.1" and insert the running count
    page.keyboard.press("Control+Shift+L")
    page.locator(".picker-tabs button", has_text="Texts").click()
    page.wait_for_selector(".pick-item .hw")
    page.locator(".pick-item").first.click()
    page.wait_for_selector(".picker-preview .segment")
    inputs = page.locator(".modal input[title*='FLEx number']")
    inputs.nth(0).fill("2.1")
    inputs.nth(0).dispatch_event("change")
    inputs.nth(1).fill("2.2")
    inputs.nth(1).dispatch_event("change")
    page.wait_for_timeout(200)
    assert page.locator(".picker-preview .segment.in-range").count() == 2
    assert inputs.nth(0).input_value() == "2.1"
    page.locator(".btn.primary", has_text="Insert segments").click()
    page.wait_for_timeout(900)
    body = body_of(h)
    assert "seg=3-4 at=" in body, body            # anchored to the segments' GUIDs on insert
    # the ⋯ menu shows FLEx numbers for the range and accepts them
    page.locator("#editor .text-obj .flex-head .lnk[title='Options']").last.click()
    page.wait_for_selector(".popover input[title*='FLEx number']")
    ins = page.locator(".popover input[title*='FLEx number']")
    assert ins.nth(0).input_value() == "2.1" and ins.nth(1).input_value() == "2.2"
    ins.nth(1).fill("3.1")
    ins.nth(1).dispatch_event("change")
    page.wait_for_timeout(900)
    assert "seg=3-5 at=" in body_of(h)
    page.keyboard.press("Escape")                      # close the ⋯ popover
    page.wait_for_timeout(200)
    # the collapsed chip shows FLEx numbers too
    page.locator("#editor .flex-obj .lnk[title='Collapse to a chip']").last.click()
    page.wait_for_selector("#editor .flex-collapsed .crange")
    page.wait_for_timeout(400)
    assert page.locator("#editor .flex-collapsed .crange").last.inner_text() == "2.1–3.1"
    assert not errors


def test_overlay_stays_in_the_viewport(app):
    h, page, errors = app
    new_note(page, "Overlay")
    page.click(".blk-body")
    insert_text_segments(page, 0, 3)
    page.locator("#editor .flex-obj .lnk[title='Collapse to a chip']").first.click()
    page.wait_for_selector(".flex-collapsed")
    # put the chip near the bottom edge of the window, then open its overlay
    page.evaluate("() => { const ed = document.getElementById('editor'); const chip = document.querySelector('.flex-collapsed'); const r = chip.getBoundingClientRect(); ed.scrollTop += r.top - window.innerHeight + 60; }")
    page.wait_for_timeout(200)
    page.locator(".flex-collapsed").first.click()
    page.wait_for_selector(".flex-overlay .segment")
    page.wait_for_timeout(300)
    box = page.evaluate("() => { const r = document.querySelector('.flex-overlay').getBoundingClientRect(); return { top: r.top, bottom: r.bottom, left: r.left, right: r.right, vh: window.innerHeight, vw: window.innerWidth }; }")
    assert box["top"] >= 0 and box["bottom"] <= box["vh"] and box["left"] >= 0 and box["right"] <= box["vw"], box
    # scrolling the note keeps it inside too
    page.evaluate("() => { document.getElementById('editor').scrollTop -= 200; }")
    page.wait_for_timeout(200)
    box = page.evaluate("() => { const r = document.querySelector('.flex-overlay').getBoundingClientRect(); return { top: r.top, bottom: r.bottom, vh: window.innerHeight }; }")
    assert box["top"] >= 0 and box["bottom"] <= box["vh"], box
    assert not errors



def test_type_around_a_flex_chip_in_a_cell(app):
    h, page, errors = app
    # put an embed alone in a cell
    cell = page.locator("table.md-table td[data-r='1'][data-c='1'] .cell-view")
    cell.scroll_into_view_if_needed()
    cell.dispatch_event("mousedown")
    page.wait_for_selector(".cell-edit")
    page.keyboard.press("Control+a")
    page.keyboard.type("{{flex:text %s seg=1}}" % T_STORY)
    page.keyboard.press("Escape")
    page.wait_for_selector("table.md-table td[data-r='1'][data-c='1'] .flex-collapsed")
    page.wait_for_timeout(900)
    # a click on the cell's padding (the td itself) opens the source with the caret at the end
    td = page.locator("table.md-table td[data-r='1'][data-c='1']")
    td.dispatch_event("mousedown", {"button": 0, "bubbles": True})
    page.wait_for_selector(".cell-edit")
    page.keyboard.type(" after")
    page.keyboard.press("Escape")
    page.wait_for_timeout(900)
    assert re.search(r"\| Form \| \{\{flex:text %s seg=1( at=[0-9a-f-]+)?\}\} after \|" % T_STORY, body_of(h)), body_of(h)
    # the overlay's "Edit cell" does the same, with the caret right after the object
    page.locator("table.md-table td[data-r='1'][data-c='1'] .flex-collapsed").click()
    page.wait_for_selector(".flex-overlay .lnk", state="visible")
    page.locator(".flex-overlay .lnk", has_text="Edit cell").click()
    page.wait_for_selector(".cell-edit")
    page.keyboard.type(" and")
    page.keyboard.press("Escape")
    page.wait_for_timeout(900)
    assert re.search(r"seg=1( at=[0-9a-f-]+)?\}\} and after \|", body_of(h)), body_of(h)
    # a second object can be inserted into the same cell with the picker
    td.dispatch_event("mousedown", {"button": 0, "bubbles": True})
    page.wait_for_selector(".cell-edit")
    page.keyboard.press("End")
    page.keyboard.type(" ")
    page.keyboard.press("Control+Shift+L")
    page.wait_for_selector(".pick-item .hw")
    page.locator(".pick-item").first.click()
    page.wait_for_selector(".picker-preview .entry-card")
    page.locator(".btn.primary", has_text="Insert rendered").click()
    page.wait_for_timeout(900)
    assert page.locator("table.md-table td[data-r='1'][data-c='1'] .flex-collapsed").count() == 2
    assert not errors



def test_styles_update_in_cells_and_overlays(app):
    """Seth, 2026-10-13: highlights set from an overlay or an expanded in-cell example were
    saved but not drawn until the next open."""
    h, page, errors = app
    cell = page.locator("table.md-table td[data-r='1'][data-c='1'] .cell-view")
    cell.scroll_into_view_if_needed()
    cell.dispatch_event("mousedown")
    page.wait_for_selector(".cell-edit")
    page.keyboard.press("Control+a")
    page.keyboard.type("{{flex:text %s seg=1 expanded}}" % T_STORY)
    page.keyboard.press("Escape")
    page.wait_for_selector("table.md-table td[data-r='1'][data-c='1'] .text-obj .word-cell")
    page.wait_for_timeout(600)
    # expanded in the cell: highlight word 2, then underline its second morpheme
    page.locator("table.md-table td[data-r='1'][data-c='1'] .word-cell").nth(1).locator(".il-txt").click()
    page.wait_for_selector(".popover .sw")
    page.locator(".popover .sw").nth(1).click()
    page.wait_for_timeout(700)
    assert page.locator("table.md-table td[data-r='1'][data-c='1'] .il-txt .st-hl").count() == 1
    page.keyboard.press("Escape")
    # click the third morpheme (-mo) of word 2 on the Morphemes line: the popover opens on that
    # line with its characters preselected; Underline marks just that morpheme
    page.locator("table.md-table td[data-r='1'][data-c='1'] .word-cell").nth(1).locator(".il-morph > span").nth(2).click()
    page.wait_for_selector(".popover select")
    assert page.locator(".popover select").first.input_value() == "morph"
    page.locator(".popover .tog", has_text="Underline").click()
    page.wait_for_timeout(700)
    assert page.locator("table.md-table td[data-r='1'][data-c='1'] .il-morph .st-u").count() == 1
    assert page.locator("table.md-table td[data-r='1'][data-c='1'] .il-morph .st-u").inner_text() == "-mo"
    assert re.search(r"u=morph:1\.2:\d+-\d+", body_of(h)), body_of(h)
    # clicking it again turns it off (the drawing follows the file)
    page.locator(".popover .tog", has_text="Underline").click()
    page.wait_for_timeout(700)
    assert page.locator("table.md-table td[data-r='1'][data-c='1'] .st-u").count() == 0
    page.keyboard.press("Escape")
    # in the overlay of the collapsed chip: a new highlight is drawn at once, the overlay stays put
    page.locator("table.md-table td[data-r='1'][data-c='1'] .lnk[title='Collapse to a chip']").click()
    page.wait_for_selector("table.md-table td[data-r='1'][data-c='1'] .flex-collapsed")
    page.locator("table.md-table td[data-r='1'][data-c='1'] .flex-collapsed").click()
    page.wait_for_selector(".flex-overlay .word-cell")
    before = page.evaluate("() => document.querySelector('.flex-overlay').getBoundingClientRect().top")
    page.locator(".flex-overlay .word-cell").nth(0).locator(".il-txt").click()
    page.wait_for_selector(".popover .sw")
    page.locator(".popover .sw").nth(2).click()
    page.wait_for_timeout(900)
    assert page.locator(".flex-overlay .st-hl").count() == 2
    after = page.evaluate("() => { const o = document.querySelector('.flex-overlay'); return o ? o.getBoundingClientRect().top : -1; }")
    assert abs(after - before) < 4, (before, after)
    assert "hl[#caffbf]=1.1" in body_of(h)
    assert not errors
