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
    # plays from the cached clip when there is one (its time starts at 0), else from the file
    t = page.evaluate("FS.audio.current ? [FS.audio.current.el.currentTime, FS.audio.current.begin, FS.audio.current.end] : [-1, 0, 0]")
    assert t[1] <= t[0] <= t[2] + 0.1 and t[2] - t[1] > 1.0, t
    page.wait_for_timeout(2600)
    assert page.evaluate("!!FS.audio.current") is False       # stopped at `end`
    clips = [c for c in h.api._nb.cache_dir.rglob("*_1500-3200.*") if c.suffix in (".wav", ".flac")]
    assert clips, "the clip was cut into the notebook cache"
    # the clip keeps playing after the source media is gone
    import os
    src = h.api._flex.backend.texts[T_STORY]["media"][0]["path"]
    os.remove(src)
    h.api._flex.backend._resolve_media()
    info = h.api.audio_clip(T_STORY, None, 1500, 3200)
    assert info["found"] is False and re.search(r"_1500-3200\.(wav|flac)$", info["clipUrl"])


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


def test_example_settings_redraw_at_once(app):
    """Seth, 2026-10-13: a change in the ⋯ settings (the segment range above all) must redraw
    the example right there — in a note block, in a table cell, and in an overlay."""
    h, page, errors = app
    new_note(page, "Redraw")
    page.click(".blk-body")
    insert_text_segments(page, 0, 0)
    assert page.locator("#editor .text-obj .segment").count() == 1
    # block: widen the range to 1.1–2.1 from the menu → three segments, no refresh needed
    page.locator("#editor .text-obj .flex-head .lnk[title='Options']").click()
    page.wait_for_selector(".popover input[title*='FLEx number']")
    ins = page.locator(".popover input[title*='FLEx number']")
    ins.nth(1).fill("2.1")
    ins.nth(1).dispatch_event("change")
    page.wait_for_function("() => document.querySelectorAll('#editor .text-obj .segment').length === 3")
    # and a line toggle redraws too
    page.locator(".popover input[type=checkbox]").nth(0).click()        # Word line off
    page.wait_for_function("() => document.querySelectorAll('#editor .text-obj .word-cell:not(.punct-cell) .il-txt').length === 0")
    page.keyboard.press("Escape")
    # overlay: collapse, open, change the range in the overlay's menu → the overlay redraws
    page.locator("#editor .flex-obj .lnk[title='Collapse to a chip']").click()
    page.wait_for_selector("#editor .flex-collapsed")
    page.locator("#editor .flex-collapsed").click()
    page.wait_for_selector(".flex-overlay .segment")
    assert page.locator(".flex-overlay .segment").count() == 3
    page.locator(".flex-overlay .flex-head .lnk[title='Options']").click()
    page.wait_for_selector(".popover input[title*='FLEx number']")
    ins = page.locator(".popover input[title*='FLEx number']")
    ins.nth(1).fill("1.2")
    ins.nth(1).dispatch_event("change")
    page.wait_for_function("() => document.querySelectorAll('.flex-overlay .segment').length === 2")
    page.keyboard.press("Escape")
    page.keyboard.press("Escape")
    # a table cell with an expanded example
    page.locator("#editor .blk-body").last.click()
    page.keyboard.press("End")
    page.keyboard.press("Enter")
    paste(page, "| a |\n|---|\n| {{flex:text %s seg=1 expanded}} |" % T_STORY)
    page.wait_for_selector("table.md-table .text-obj .segment")
    assert page.locator("table.md-table .text-obj .segment").count() == 1
    page.locator("table.md-table .text-obj .flex-head .lnk[title='Options']").click()
    page.wait_for_selector(".popover input[title*='FLEx number']")
    ins = page.locator(".popover input[title*='FLEx number']")
    ins.nth(1).fill("2.2")
    ins.nth(1).dispatch_event("change")
    page.wait_for_function("() => document.querySelectorAll('table.md-table .text-obj .segment').length === 4")
    assert not errors


def test_interlinear_rows_stay_level_when_a_word_lacks_a_line(app):
    """Every word cell has the same rows; a missing gloss / category leaves an empty row rather
    than letting the row below move up (Seth, 2026-10-13)."""
    h, page, errors = app
    new_note(page, "Level")
    page.click(".blk-body")
    insert_text_segments(page, 0, 0)
    page.wait_for_selector("#editor .text-obj .word-cell")
    # strip the category and gloss from word 3 ("lo") in the rendered object model by editing
    # the mock's data is not possible here, so check the structural guarantee instead:
    # every non-punctuation cell has the same number of rows, in the same order
    rows = page.evaluate("""() => [...document.querySelectorAll('#editor .text-obj .segment .word-cell:not(.punct-cell)')].map((c) => [...c.querySelectorAll('.il-line')].map((l) => l.className.replace(/\\bil-line\\b|\\bil-empty\\b|\\s+/g, ' ').trim()).join(','))""")
    assert len(rows) >= 3 and len(set(rows)) == 1, rows
    assert not errors


def test_insert_into_cell_keeps_the_place(app):
    """After an insert into a table cell the same cell is open again, with the caret after the
    inserted text, and the pane has not scrolled (Seth, 2026-10-13)."""
    h, page, errors = app
    cell = page.locator("table.md-table td[data-r='2'][data-c='1'] .cell-view")
    cell.scroll_into_view_if_needed()
    cell.dispatch_event("mousedown")
    page.wait_for_selector(".cell-edit")
    page.keyboard.press("End")
    page.keyboard.press("Control+Shift+L")
    page.wait_for_selector(".pick-item .hw")
    page.locator(".pick-item").first.click()
    page.wait_for_selector(".picker-preview .entry-card")
    page.locator(".btn.primary", has_text="Insert rendered").click()
    page.wait_for_timeout(900)
    # the chip is shown in the same cell; the next insert and a click on the padding target it
    assert page.locator(".cell-edit").count() == 0
    assert page.locator("table.md-table td[data-r='2'][data-c='1'] .flex-collapsed").count() == 1
    page.keyboard.press("Control+Shift+L")
    page.wait_for_selector(".pick-item .hw")
    page.locator(".pick-item").nth(1).click()
    page.wait_for_selector(".picker-preview .entry-card")
    page.locator(".btn.primary", has_text="Insert rendered").click()
    page.wait_for_timeout(900)
    assert page.locator("table.md-table td[data-r='2'][data-c='1'] .flex-collapsed").count() == 2
    assert page.locator("table.md-table .flex-collapsed").count() == 2          # nowhere else
    page.locator("table.md-table td[data-r='2'][data-c='1']").dispatch_event("mousedown", {"button": 0, "bubbles": True})
    page.wait_for_selector(".cell-edit")
    page.keyboard.press("End")
    page.keyboard.type(" then")
    page.keyboard.press("Escape")
    page.wait_for_timeout(900)
    assert re.search(r"\{\{flex:entry [0-9a-f-]+\}\} \{\{flex:entry [0-9a-f-]+\}\} then \|", body_of(h)), body_of(h)
    # the Refresh all button reloads every example and keeps the note open
    page.locator("#btn-refresh-all").click()
    page.wait_for_function("() => document.getElementById('btn-refresh-all').textContent.includes('Refresh all')")
    page.wait_for_selector(".toast")
    assert "Refreshed" in page.locator(".toast").last.inner_text()
    assert page.locator("table.md-table").count() == 1
    assert not errors


def test_entry_fields_and_senses_menu(app):
    h, page, errors = app
    new_note(page, "Entry fields")
    page.keyboard.type("{{flex:entry %s}}" % "6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0001")
    page.keyboard.press("Enter")
    page.wait_for_selector("#editor .entry-card .sense")
    assert page.locator("#editor .entry-card .sense").count() == 3            # 1, 2, 2.1
    assert page.locator("#editor .entry-card .sense.level1").count() == 1
    page.locator("#editor .entry-card .flex-head .lnk", has_text="⋯").click()
    page.wait_for_selector(".popover")
    assert page.locator(".popover b", has_text="Senses fields").count() == 1
    assert page.locator(".popover", has_text="Lines to show").count() == 0
    # definitions off
    page.locator(".popover label", has_text="Definition").locator("input").click()
    page.wait_for_function("() => document.querySelectorAll('#editor .entry-card .def').length === 0")
    # only sense 2 (which brings 2.1)
    sens = page.locator(".popover input[title*='Which senses']")
    sens.fill("2")
    sens.dispatch_event("change")
    page.wait_for_function("() => document.querySelectorAll('#editor .entry-card .sense').length === 2")
    # sub-senses off → just sense 2
    page.locator(".popover label", has_text="Sub-senses").locator("input").click()
    page.wait_for_function("() => document.querySelectorAll('#editor .entry-card .sense').length === 1")
    page.wait_for_timeout(900)
    body = body_of(h)
    assert "fields=cf,mt,hn,sn,spos,gl,ex,tr senses=2" in body, body
    assert not errors


def test_overlay_scrolls_inside_and_duplicate_remove(app):
    h, page, errors = app
    new_note(page, "Overlay scroll")
    page.keyboard.type("{{flex:text %s seg=1-6 collapsed}}" % T_STORY)
    page.keyboard.press("Enter")
    page.wait_for_selector("#editor .flex-collapsed")
    page.set_viewport_size({"width": 1100, "height": 420})
    page.locator("#editor .flex-collapsed").click()
    page.wait_for_selector(".flex-overlay .segment")
    page.wait_for_timeout(300)
    box = page.evaluate("() => { const o = document.querySelector('.flex-overlay').getBoundingClientRect(); const i = document.querySelector('.flex-overlay-inner'); return { bottom: o.bottom, vh: window.innerHeight, scrollable: i.scrollHeight > i.clientHeight }; }")
    assert box["bottom"] <= box["vh"] and box["scrollable"], box
    # the overlay's own scrolling works and is not reset by the re-placement
    page.evaluate("() => { document.querySelector('.flex-overlay-inner').scrollTop = 150; }")
    page.wait_for_timeout(250)
    assert page.evaluate("() => document.querySelector('.flex-overlay-inner').scrollTop") >= 140
    page.mouse.wheel(0, 80)
    page.wait_for_timeout(250)
    assert page.evaluate("() => document.querySelector('.flex-overlay-inner').scrollTop") >= 140
    # duplicate from the overlay bar → two blocks; remove one after confirming
    page.locator(".flex-overlay .lnk", has_text="Duplicate").click()
    page.wait_for_function("() => document.querySelectorAll('#editor .flex-collapsed').length === 2")
    page.set_viewport_size({"width": 1100, "height": 860})
    page.locator("#editor .flex-collapsed").first.click()
    page.wait_for_selector(".flex-overlay .lnk")
    page.locator(".flex-overlay .lnk", has_text="Remove").click()
    page.wait_for_selector(".popover .btn.danger")
    page.locator(".popover .btn", has_text="Cancel").click()
    page.wait_for_timeout(300)
    assert page.locator("#editor .flex-collapsed").count() == 2
    page.locator(".flex-overlay .lnk", has_text="Remove").click()
    page.wait_for_selector(".popover .btn.danger")
    page.locator(".popover .btn.danger").click()
    page.wait_for_function("() => document.querySelectorAll('#editor .flex-collapsed').length === 1")
    page.wait_for_timeout(900)
    assert body_of(h).count("{{flex:text") == 1
    # in a cell: the ⋯ menu offers both
    page.locator("#editor .blk-body").last.click()
    paste(page, "| a |\n|---|\n| {{flex:entry 6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0001 expanded}} |")
    page.wait_for_selector("table.md-table .entry-card")
    page.locator("table.md-table .entry-card .flex-head .lnk[title='Duplicate this object']").click()
    page.wait_for_function("() => document.querySelectorAll('table.md-table .entry-card').length === 2")
    page.locator("table.md-table .entry-card .flex-head .lnk[title='Remove this object…']").first.click()
    page.wait_for_selector(".popover .btn.danger")
    page.locator(".popover .btn.danger").click()
    page.wait_for_function("() => document.querySelectorAll('table.md-table .entry-card').length === 1")
    assert not errors


def test_flex_pairing_prompt_banner_and_sharing_warning(app):
    h, page, errors = app
    # demo project: connected, no prompt, no banner
    assert page.locator("#flex-pill.on").count() == 1 and page.locator("#flex-banner").is_hidden()
    assert page.locator(".modal", has_text="Link a FieldWorks project").count() == 0
    # nothing linked → the first-run prompt and the banner appear
    page.evaluate("() => { sessionStorage.removeItem('fs:flexPromptShown'); FS.flexUi.setFlex({ open: false, configured: false, error: '', errorCode: '' }); FS.flexUi.flexPrompt(false); }")
    page.wait_for_selector(".modal", state="visible")
    assert "Link a FieldWorks project" in page.locator(".modal .modal-title").inner_text()
    assert page.locator(".modal .btn", has_text="Choose a project").count() == 1
    page.locator(".modal .btn", has_text="Not now").click()
    assert page.locator("#flex-banner").is_visible() and "No FieldWorks project is linked" in page.locator("#flex-banner .text").inner_text()
    assert page.locator("#flex-pill .warn-icon").is_visible()
    # a locked project → error state with the sharing fix in the pill's explanation
    page.evaluate("() => FS.flexUi.setFlex({ open: false, configured: true, project: 'fau-iya-flex', error: 'The project is locked by FieldWorks.', errorCode: 'locked' })")
    assert page.locator("#flex-pill.err").count() == 1
    page.locator("#flex-pill").click()
    page.wait_for_selector(".popover.flex-explain")
    assert "Share project contents" in page.locator(".popover.flex-explain").inner_text()
    page.keyboard.press("Escape")
    # connected but sharing off → warning, still usable
    page.evaluate("() => FS.flexUi.setFlex({ open: true, configured: true, backend: 'lcm', project: 'fau-iya-flex', shared: false, flexHasItOpen: false })")
    assert page.locator("#flex-pill.warn").count() == 1 and page.locator("#flex-banner").is_hidden()
    page.locator("#flex-pill").click()
    page.wait_for_selector(".popover.flex-explain")
    assert "sharing" in page.locator(".popover.flex-explain").inner_text().lower() and "Sharing tab" in page.locator(".popover.flex-explain").inner_text()
    page.keyboard.press("Escape")
    # connected and shared → plain
    page.evaluate("() => FS.flexUi.setFlex({ open: true, configured: true, backend: 'lcm', project: 'fau-iya-flex', shared: true })")
    assert page.locator("#flex-pill.on").count() == 1 and page.locator("#flex-pill .warn-icon").is_hidden()
    assert not errors


def test_row_selection_keeps_to_the_row_with_merged_cells(app):
    h, page, errors = app
    new_note(page, "Merged rows")
    page.locator("#editor .blk-body").first.click()
    paste(page, "| a | b | c |\n|---|---|---|\n| 1 | tall | 3 |\n| 4 |  | 6 |\n| 7 | 8 | 9 |\n{table: span 2.2: 2x1}")
    page.wait_for_selector("table.md-table td[rowspan='2']")
    page.locator("table.md-table").hover()
    # row 3 (0-based 2) is spanned by the merged cell anchored in row 2: selecting it selects
    # that row only, and the merged cell counts as part of it
    page.locator("table.md-table th.gutter.row").nth(2).dispatch_event("mousedown", {"button": 0, "bubbles": True})
    page.wait_for_timeout(100)
    sel = page.evaluate("() => [...document.querySelectorAll('table.md-table .sel')].map((c) => c.dataset.r + ',' + c.dataset.c)")
    assert sorted(sel) == ["1,1", "2,0", "2,2"], sel
    assert page.locator("table.md-table th.gutter.row.on").count() == 1
    # the column with the merged cell: that column only
    page.locator("table.md-table th.gutter.col").nth(1).dispatch_event("mousedown", {"button": 0, "bubbles": True})
    page.wait_for_timeout(100)
    sel = page.evaluate("() => [...document.querySelectorAll('table.md-table .sel')].map((c) => c.dataset.r + ',' + c.dataset.c)")
    assert sorted(sel) == ["0,1", "1,1", "3,1"], sel
    assert page.locator("table.md-table th.gutter.col.on").count() == 1
    assert not errors


def test_table_frame_grip_and_scroll_chaining(app):
    h, page, errors = app
    new_note(page, "Frame")
    page.locator("#editor .blk-body").first.click()
    paste(page, "\n\n".join(f"intro {i}" for i in range(14)) + "\n\n" + "| a | b |\n|---|---|\n" + "\n".join(f"| r{i} | x{i} |" for i in range(40)) + "\n\n" + "\n\n".join(f"para {i}" for i in range(60)))
    page.wait_for_selector("table.md-table")
    # drag the grip up: the frame gets a height and scrolls inside
    grip = page.locator(".tbl-grip")
    grip.scroll_into_view_if_needed()
    page.locator("table.md-table").hover()
    box = grip.bounding_box()
    page.mouse.move(box["x"] + 7, box["y"] + 7)
    page.mouse.down()
    page.mouse.move(box["x"] + 7, box["y"] - 900, steps=8)
    page.mouse.up()
    page.wait_for_timeout(900)
    body = body_of(h)
    assert re.search(r"max-height \d+px", body), body.split("\n")[-62:-58]
    wrap = page.locator(".tbl-wrap.framed")
    assert wrap.count() == 1
    assert page.evaluate("() => { const w = document.querySelector('.tbl-wrap.framed'); return w.scrollHeight > w.clientHeight; }")
    # a gesture under way when the pointer reaches the frame stays with the document
    page.evaluate("() => { document.getElementById('editor').scrollTop = 0; }")
    wrap.scroll_into_view_if_needed()
    page.evaluate("() => { const ed = document.getElementById('editor'); const w = document.querySelector('.tbl-wrap.framed'); ed.scrollTop += w.getBoundingClientRect().top - ed.getBoundingClientRect().top - 160; }")
    page.wait_for_timeout(300)
    b2 = wrap.bounding_box()
    page.mouse.move(b2["x"] + 60, b2["y"] - 80)                          # above the frame, in the note
    assert page.evaluate("([x, y]) => !!document.elementFromPoint(x, y).closest('#editor')", [b2["x"] + 60, b2["y"] - 80])
    page.wait_for_timeout(300)
    before = page.evaluate("() => [document.getElementById('editor').scrollTop, document.querySelector('.tbl-wrap.framed').scrollTop]")
    page.mouse.wheel(0, 60)                                               # gesture starts in the note…
    page.mouse.move(b2["x"] + 60, b2["y"] + b2["height"] - 60)            # …pointer now over the frame…
    page.mouse.wheel(0, 60)                                               # …same gesture (no gap): the note keeps moving
    page.mouse.wheel(0, 60)
    page.wait_for_timeout(400)
    after = page.evaluate("() => [document.getElementById('editor').scrollTop, document.querySelector('.tbl-wrap.framed').scrollTop]")
    assert after[0] >= before[0] + 150 and after[1] == before[1], (before, after)
    # after a pause over the frame, a new gesture scrolls the frame
    page.wait_for_timeout(600)
    b3 = wrap.bounding_box()
    page.mouse.move(b3["x"] + 60, b3["y"] + b3["height"] - 60)
    page.wait_for_timeout(400)
    before = page.evaluate("() => [document.getElementById('editor').scrollTop, document.querySelector('.tbl-wrap.framed').scrollTop]")
    page.mouse.wheel(0, 120)
    page.wait_for_timeout(200)
    after = page.evaluate("() => [document.getElementById('editor').scrollTop, document.querySelector('.tbl-wrap.framed').scrollTop]")
    assert after[1] > before[1] and after[0] == before[0], (before, after)
    # at the frame's end: the rest of the gesture is absorbed…
    page.evaluate("() => { const w = document.querySelector('.tbl-wrap.framed'); w.scrollTop = w.scrollHeight - w.clientHeight - 30; }")
    page.wait_for_timeout(600)
    before = page.evaluate("() => document.getElementById('editor').scrollTop")
    page.mouse.wheel(0, 40)                  # carries the frame to its end
    page.mouse.wheel(0, 30)                  # straight on (a decaying tail): absorbed
    page.wait_for_timeout(60)
    page.mouse.wheel(0, 20)
    page.wait_for_timeout(150)
    assert page.evaluate("() => document.getElementById('editor').scrollTop") == before
    assert page.evaluate("() => { const w = document.querySelector('.tbl-wrap.framed'); return w.scrollTop + w.clientHeight >= w.scrollHeight - 1; }")
    # a fresh push (a clear jump in delta) releases to the document at once, no pause needed
    page.mouse.wheel(0, 120)
    page.wait_for_timeout(400)
    assert page.evaluate("() => document.getElementById('editor').scrollTop") > before
    page.wait_for_timeout(300)
    page.evaluate("() => { const w = document.querySelector('.tbl-wrap.framed'); w.scrollTop = w.scrollHeight; }")
    before = page.evaluate("() => document.getElementById('editor').scrollTop")
    # …and a new gesture after half a second moves the document, and keeps moving it
    page.wait_for_timeout(600)
    page.mouse.wheel(0, 120)
    page.wait_for_timeout(50)
    page.mouse.wheel(0, 120)
    page.wait_for_timeout(400)
    mid = page.evaluate("() => document.getElementById('editor').scrollTop")
    assert mid >= before + 200, (before, mid)
    page.mouse.wheel(0, 120)
    page.wait_for_timeout(400)
    assert page.evaluate("() => document.getElementById('editor').scrollTop") > mid
    assert page.evaluate("() => { const w = document.querySelector('.tbl-wrap.framed'); return w.scrollTop + w.clientHeight >= w.scrollHeight - 1; }")
    # double-click the grip resets the frame
    grip = page.locator(".tbl-grip")
    grip.scroll_into_view_if_needed()
    page.locator("table.md-table").hover()
    page.wait_for_timeout(100)
    grip.dblclick()
    page.wait_for_timeout(900)
    assert "max-height" not in body_of(h)
    assert not errors


def test_outline_numbering_and_enter(app):
    h, page, errors = app
    new_note(page, "Outline")
    page.locator("#editor .blk-body").first.click()
    paste(page, "1. Symmetrical\n  2. Examples:\n\n2. One-word\n  3. Examples:\n\n3. Argument sharing\n  4. All\n  5. Shared subject")
    page.wait_for_timeout(400)
    shown = page.evaluate("() => [...document.querySelectorAll('#editor .md-line[data-num]')].map((l) => l.dataset.num + ' ' + l.textContent.trim().replace(/^\\d+\\.\\s*/, ''))")
    assert shown == ["1. Symmetrical", "1. Examples:", "2. One-word", "1. Examples:", "3. Argument sharing", "1. All", "2. Shared subject"], shown
    # what is DRAWN: the computed number via ::before, the typed digits invisible
    drawn = page.evaluate("() => [...document.querySelectorAll('#editor .md-num[data-num]')].map((n) => [getComputedStyle(n, '::before').content, getComputedStyle(n).color])")
    assert [d[0] for d in drawn] == ['"1."', '"1."', '"2."', '"1."', '"3."', '"1."', '"2."'], drawn
    assert all(d[1] == "rgba(0, 0, 0, 0)" for d in drawn), drawn
    # Enter after the last sub-item continues ITS level with the shown number + 1
    last = page.locator("#editor .blk-list .blk-body").last
    last.click()
    page.keyboard.press("Control+End")
    page.keyboard.press("Enter")
    page.keyboard.type("Shared object")
    page.wait_for_timeout(600)
    assert "  3. Shared object" in body_of(h)
    shown = page.evaluate("() => [...document.querySelectorAll('#editor .md-line[data-num]')].map((l) => l.dataset.num)")
    assert shown[-1] == "3."
    # inserting an item at the top renumbers the blocks below
    first = page.locator("#editor .blk-list .blk-body").first
    first.click()
    page.keyboard.press("Control+Home")
    page.keyboard.type("1. New first")
    page.keyboard.press("Enter")
    page.wait_for_timeout(600)
    shown = page.evaluate("() => [...document.querySelectorAll('#editor .md-line[data-num]')].map((l) => l.dataset.num)")
    assert shown[0] == "1." and "4." in shown, shown
    assert not errors


def test_copy_example_as_flex_tsv(app):
    h, page, errors = app
    new_note(page, "TSV")
    page.keyboard.type("{{flex:text %s seg=1-2 lines=txt,morph,mgls,gls,pos,ft}}" % T_STORY)
    page.keyboard.press("Enter")
    page.wait_for_selector("#editor .text-obj .segment")
    tsv = page.evaluate("() => FS.interlinear.flexTsv(FS.flexref.parse('{{flex:text %s seg=1-2 lines=txt,morph,mgls,gls,pos,ft}}'), document.querySelector('#editor .blk-flex .widget-host')._obj)" % T_STORY)
    blocks = tsv.strip().split("\n\n")
    assert len(blocks) == 2
    rows = blocks[0].split("\n")
    assert rows[0] == "Word\tKabir\tka-nuwa-mo\tlo\t.", rows
    assert rows[1] == "Morphemes\tkabir\tka- nuwa -mo\tlo\t", rows
    assert rows[2] == "Lex. Gloss\tdog\t3SG- sleep -PST\tDECL\t", rows
    assert any(r.startswith("Word Gloss\t") for r in rows) and any(r.startswith("Word Cat.\t") for r in rows)
    assert rows[-1] == "Free\tThe dog slept."
    # the pasted rows find their way back: locate() resolves them to the same segments
    hits = h.api.flex_locate(tsv)
    assert hits and hits[0]["seg"] == 1 and hits[0]["segTo"] == 2, hits
    # the menu and the header offer it
    assert page.locator("#editor .text-obj .flex-head .lnk[title^='Copy as FLEx TSV']").count() == 1
    page.locator("#editor .text-obj .flex-head .lnk[title='Options']").click()
    page.wait_for_selector(".popover .menu-item")
    assert page.locator(".popover .menu-item", has_text="Copy as FLEx TSV").count() == 1
    page.keyboard.press("Escape")
    assert not errors


def test_inline_chip_in_body_text(app):
    """Seth, 2026-10-13: "put chips inline with text". An entry inserted mid-sentence is a chip
    whose span text is still the embed code; Backspace removes it whole; the overlay opens on
    click and can expand it into a block of its own."""
    h, page, errors = app
    new_note(page, "Inline")
    page.locator("#editor .blk-body").first.click()
    page.keyboard.type("Compare the word  with")
    page.keyboard.press("ArrowLeft")
    for _ in range(4): page.keyboard.press("ArrowLeft")
    page.keyboard.press("Control+Shift+L")
    page.fill(".picker input[type=text]", "kab")
    page.wait_for_selector(".pick-item .hw")
    page.locator(".pick-item").first.click()
    page.wait_for_selector(".picker-preview .entry-card")
    page.locator(".btn.primary", has_text="Insert rendered").click()
    page.wait_for_selector("#editor .md-embed")
    page.wait_for_function("() => /kabir/.test(document.querySelector('#editor .md-embed').dataset.title)")
    page.wait_for_timeout(900)
    body = body_of(h)
    assert "Compare the word {{flex:entry 6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0001}} with" in body, body
    assert page.locator("#editor .blk-p").count() == 1 and page.locator("#editor .entry-card").count() == 0
    span = page.locator("#editor .md-embed")
    assert span.get_attribute("contenteditable") == "false"
    assert page.evaluate("() => getComputedStyle(document.querySelector('#editor .md-embed'), '::before').content").find("kabir") >= 0
    # click → pinned overlay with the entry; "Expand in note" makes it a block between the two halves
    span.click()
    page.wait_for_selector(".flex-overlay.pinned .entry-card")
    page.locator(".flex-overlay button", has_text="Expand in note").click()
    page.wait_for_selector("#editor .blk-flex .entry-card")
    page.wait_for_timeout(900)
    assert body_of(h) == "Compare the word\n\n{{flex:entry 6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0001}}\n\nwith", body_of(h)
    # typing an embed code into text makes a chip too; Backspace after it removes the whole chip
    page.locator("#editor .blk-body").last.click()
    page.keyboard.press("Control+End")
    page.keyboard.type(" {{flex:entry 6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0001}} end")
    page.wait_for_selector("#editor .blk-body .md-embed")
    page.keyboard.press("Control+End")
    for _ in range(4): page.keyboard.press("Backspace")
    page.wait_for_timeout(300)
    assert page.locator("#editor .blk-body").last.text_content() == "with {{flex:entry 6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0001}}"
    page.keyboard.press("Backspace")                          # one Backspace removes the whole chip
    page.wait_for_timeout(900)
    assert page.locator("#editor .blk-body").last.text_content() == "with "
    assert body_of(h).endswith("with"), body_of(h)
    assert page.locator("#editor .blk-body .md-embed").count() == 0
    assert not errors


def test_numbered_indented_examples(app):
    """`ex` numbers examples (1), (2)… through the note; `indent=N` steps a block in; the ⋯
    menu and Tab / Shift+Tab on the block drive both."""
    h, page, errors = app
    new_note(page, "Examples")
    page.locator("#editor .blk-body").first.click()
    paste(page, "Intro\n\n{{flex:text %s seg=1 ex}}\n\n{{flex:text %s seg=2 ex indent=1}}\n\n{{flex:entry 6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0001}}" % (T_STORY, T_STORY))
    page.wait_for_selector("#editor .entry-card")
    nums = page.locator("#editor .blk-flex > .ex-num")
    assert nums.all_inner_texts() == ["(1)", "(2)"]
    assert page.locator("#editor .blk-flex.blk-indent1").count() == 1
    # Tab on the first example block indents it; the number stays
    page.locator("#editor .blk-flex").first.focus()
    page.keyboard.press("Tab")
    page.keyboard.press("Tab")
    page.wait_for_timeout(900)
    assert re.search(r"\{\{flex:text %s seg=1( at=[0-9a-f-]+)? ex indent=2\}\}" % T_STORY, body_of(h)), body_of(h)
    assert page.locator("#editor .blk-flex.blk-indent2 > .ex-num").inner_text() == "(1)"
    page.keyboard.press("Shift+Tab")
    page.wait_for_timeout(900)
    assert "indent=1}}" in body_of(h).split("\n")[2]
    # the ⋯ menu numbers the entry as (3)
    page.locator("#editor .entry-card .flex-head button[title='Options']").click()
    page.wait_for_selector(".popover")
    page.locator(".popover label", has_text="Number as example").locator("input").check()
    page.wait_for_selector("#editor .blk-flex:nth-of-type(4) > .ex-num")
    assert page.locator("#editor .blk-flex > .ex-num").all_inner_texts() == ["(1)", "(2)", "(3)"]
    page.keyboard.press("Escape")
    # deleting the first example renumbers the rest
    page.locator("#editor .blk-flex").first.focus()
    page.keyboard.press("Delete")
    page.wait_for_timeout(300)
    assert page.locator("#editor .blk-flex > .ex-num").all_inner_texts() == ["(1)", "(2)"]
    assert not errors


def test_resize_any_cell_edge_including_under_a_merged_header(app):
    """Seth, 2026-10-13: columns whose headers are merged cells must still resize one by one —
    any cell's right edge resizes the column it ends in, any bottom edge sets the row height."""
    h, page, errors = app
    new_note(page, "Edges")
    page.locator("#editor .blk-body").first.click()
    paste(page, "| A | B | C |\n|---|---|---|\n| 1 | 2 | 3 |\n| 4 | 5 | 6 |\n{table: span 1.1: 1x2}")
    page.wait_for_selector("table.md-table th.merged")

    def drag(sel, dx, dy):
        cell = page.locator(sel)
        cell.scroll_into_view_if_needed()
        handle = cell.locator(".col-resizer" if dx else ".row-resizer")
        box = handle.bounding_box()
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.mouse.down()
        page.mouse.move(box["x"] + box["width"] / 2 + dx, box["y"] + box["height"] / 2 + dy, steps=6)
        page.mouse.up()
        page.wait_for_timeout(900)

    # the body cell in column 2 (under the merged header) → col 2 only
    drag("table.md-table td[data-r='1'][data-c='1']", 90, 0)
    m = re.search(r"col 2: width (\d+)px", body_of(h))
    assert m and int(m.group(1)) >= 120, body_of(h).split("\n")[-1]
    assert "col 1:" not in body_of(h)
    # the merged header's right edge → the last column it covers (2), from that column's own width
    before = int(m.group(1))
    drag("table.md-table th.merged[data-c='0']", 40, 0)
    m = re.search(r"col 2: width (\d+)px", body_of(h))
    assert m and before + 25 <= int(m.group(1)) <= before + 55, (before, body_of(h).split("\n")[-1])
    # a bottom edge → the row's height
    drag("table.md-table td[data-r='2'][data-c='2']", 0, 30)
    m = re.search(r"row 3: height (\d+)px", body_of(h))
    assert m and int(m.group(1)) >= 50, body_of(h).split("\n")[-1]
    assert page.evaluate("() => document.querySelector(\"table.md-table td[data-r='2'][data-c='0']\").getBoundingClientRect().height") >= 50
    assert not errors


def test_view_example_in_context(app):
    """Seth, 2026-10-13: the whole text in an overlay, scrolled to the example's range, the
    range set off from the rest."""
    h, page, errors = app
    new_note(page, "Context")
    page.keyboard.type("{{flex:text %s seg=4-5 hl=4.1}}" % T_STORY)
    page.keyboard.press("Enter")
    page.wait_for_selector("#editor .text-obj .segment")
    assert page.locator("#editor .text-obj .segment").count() == 2
    page.locator("#editor .text-obj .flex-head button", has_text="Context").click()
    page.wait_for_selector(".modal.context .context-text .segment")
    segs = page.locator(".modal.context .context-text .segment")
    assert segs.count() == 6                                        # the whole demo text
    focus = page.locator(".modal.context .segment.in-focus")
    assert [focus.nth(i).get_attribute("data-n") for i in range(focus.count())] == ["4", "5"]
    assert "segments 2.2–3.1 of 6" in page.locator(".context-bar").inner_text()
    assert page.locator(".modal.context .segment[data-n='4'] .st-hl").count() == 1   # the example's own styling shows
    # scrolled to the range: the first focused row sits inside the modal body's viewport
    page.wait_for_timeout(300)
    inside = page.evaluate("""() => { const b = document.querySelector('.modal.context .modal-body').getBoundingClientRect();
      const r = document.querySelector('.modal.context .segment.in-focus').getBoundingClientRect(); return r.top >= b.top && r.bottom <= b.bottom; }""")
    assert inside
    # scroll away, "Back to the example" returns
    page.evaluate("() => { document.querySelector('.modal.context .modal-body').scrollTop = 0; }")
    page.locator(".context-bar button", has_text="Back to the example").click()
    page.wait_for_timeout(700)
    assert page.evaluate("""() => { const b = document.querySelector('.modal.context .modal-body').getBoundingClientRect();
      const r = document.querySelector('.modal.context .segment.in-focus').getBoundingClientRect(); return r.top >= b.top && r.bottom <= b.bottom; }""")
    page.keyboard.press("Escape")
    page.wait_for_selector(".modal.context", state="detached")
    # also from a chip's overlay
    page.locator("#editor .text-obj .flex-head button[title='Collapse to a chip']").click()
    page.wait_for_selector("#editor .flex-collapsed")
    page.locator("#editor .flex-collapsed").click()
    page.wait_for_selector(".flex-overlay.pinned .text-obj")
    page.locator(".flex-overlay-bar button", has_text="Context").click()
    page.wait_for_selector(".modal.context .segment.in-focus")
    page.keyboard.press("Escape")
    assert not errors


def test_paste_of_flex_rows_that_match_nothing_explains_the_word_line(app):
    h, page, errors = app
    new_note(page, "Nomatch")
    page.locator("#editor .blk-body").first.click()
    paste(page, "3.1\tMorphemes\tzzz\t-qq\n\tLex. Gloss\tnone\tat.all\n\u200eFree \u200e\u200enothing here.\n")
    page.wait_for_selector(".toast", state="attached")
    assert "Word line showing" in page.locator(".toast").last.inner_text()
    page.wait_for_timeout(900)
    assert "Morphemes" in body_of(h)                                       # and the rows still landed, as text
    assert not errors


def test_export_examples_as_flextext(app):
    """Seth, 2026-10-16: a note's examples as one FLEx text — and only an EXAMPLE COLLECTION
    exports (\"have just that special note type be the one that can export\"). An ordinary note
    collects its examples into a new collection, whose Export button opens the dialog."""
    h, page, errors = app
    new_note(page, "SVCs")
    page.keyboard.type("Serial verbs, in order.")
    page.keyboard.press("Enter")
    page.keyboard.type("{{flex:text %s seg=1-2 ex \"first\"}}" % T_STORY)
    page.keyboard.press("Enter")
    page.keyboard.type("Compare {{flex:entry 6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0001}} and {{flex:text %s seg=4}} inline." % T_STORY)
    page.wait_for_selector("#editor .text-obj")
    page.wait_for_selector("#editor .md-embed")
    page.wait_for_timeout(900)
    # an ordinary note offers no FLEx text export, only collecting its examples
    page.locator("#btn-note-menu").click()
    assert page.locator(".popover .menu-item", has_text=".flextext").count() == 0
    page.locator(".popover .menu-item", has_text="Collect the examples into a new collection").click()
    page.wait_for_selector("#collection .coll-item .text-obj")
    assert page.locator("#note-title").input_value() == "SVCs \u2014 examples"
    assert page.locator("#collection .coll-item").count() == 2            # the entry is not an example
    assert page.locator("#editor-pane.is-collection #toolbar").is_hidden()
    # the collection's own Export button → the dialog
    page.locator("[data-test='coll-export']").click()
    page.wait_for_selector(".modal", timeout=15000)
    assert "2 examples" in page.locator(".modal p").first.inner_text()
    assert page.locator(".modal input[type=text]").first.input_value() == "SVCs \u2014 examples"
    page.keyboard.press("Escape")
    page.wait_for_timeout(700)
    # the export through the API (the dialog's Export… goes through the save dialog)
    out = str(h.tmp / "svcs.flextext")
    r = page.evaluate("""async (out) => {
      const api = window.pywebview.api;
      const cols = await api.list_collections();
      const items = FS.exporter.flextextItems(window.__fsCollection.asEditor());
      return await api.export_note_flextext(cols[0].id, items, { title: 'SVCs', includeLink: true, includeMarkdown: true }, out);
    }""", out)
    assert r["examples"] == 2 and r["skipped"] == 0 and r["texts"] == [{"ws": "kal", "examples": 2}]
    assert r["audio"].endswith("svcs-audio") and r["audioMatched"] == 3 and (h.tmp / "svcs-audio" / "SVCs-1.1.wav").exists()
    import xml.etree.ElementTree as ET
    root = ET.parse(out).getroot()
    phrases = root.findall(".//phrase")
    assert len(phrases) == 3 and [ph.find("item[@type='segnum']").text for ph in phrases] == ["1.1", "1.2", "2.1"]
    assert any("label: first" in (i.text or "") for i in phrases[0].findall("item[@type='note']"))
    # the ordinary note itself is refused by the API too
    plain = page.evaluate("""async () => { const api = window.pywebview.api; const ns = await api.list_notes();
      const n = ns.find((x) => x.title === 'SVCs'); try { await api.export_note_flextext(n.id, [], {}, 'x'); return 'exported'; } catch (e) { return e.message; } }""")
    assert "example collection" in plain, plain
    assert not errors


def test_example_collection_add_reorder_remove_and_undo(app):
    """Seth, 2026-10-16: "a special notes type that is JUST IGT examples concatenated/expanded"."""
    h, page, errors = app
    # an ordinary note with an example to send over
    new_note(page, "Reading notes")
    page.keyboard.type("{{flex:text %s seg=4}}" % T_STORY)
    page.keyboard.press("Enter")
    page.wait_for_selector("#editor .text-obj")
    # a new collection from the New menu, filled by pasting FLEx rows into its paste box
    page.locator("#btn-new-menu").click()
    page.locator("[data-test='new-collection']").click()
    page.wait_for_selector("#collection .coll-add")
    page.locator("#note-title").fill("Serial verbs")
    page.locator("#note-title").press("Enter")
    page.locator("#collection .coll-add").click()
    paste(page, "Word\tHa\u014ba\ttiket\tka-sila-mo\tpemu\nWord Gloss\tyesterday\tchild\tsaw\triver\nFree\tYesterday the child saw the river.")
    page.wait_for_selector(".modal")
    page.locator(".modal .btn.primary", has_text="Insert rendered").click()
    page.wait_for_selector("#collection .coll-item .text-obj")
    # an embed line pasted there keeps its styling but not its layout keys
    page.locator("#collection .coll-add").click()
    paste(page, "{{flex:text %s seg=1 hl=1.1 ex indent=2 collapsed}}" % T_STORY)
    page.wait_for_function("document.querySelectorAll('#collection .coll-item').length === 2")
    page.wait_for_timeout(900)
    def body():
        cols = h.api.list_collections()
        return h.api.get_note(cols[0]["id"])["body"]
    b = body()
    assert b.index("seg=2") < b.index("seg=1 ") and "hl=1.1" in b and " ex" not in b and "indent" not in b and "collapsed" not in b, b
    # reorder with the arrows
    page.locator("#collection .coll-item").nth(1).hover()
    page.locator("#collection .coll-item").nth(1).locator("button[title='Move up']").click()
    page.wait_for_timeout(900)
    assert body().index("seg=1 ") < body().index("seg=2"), body()
    assert page.locator("#collection .coll-num").all_inner_texts() == ["(1)", "(2)"]
    # remove, then undo
    page.locator("#collection .coll-item").first.hover()
    page.locator("#collection .coll-item").first.locator("[data-test='coll-remove']").click()
    page.wait_for_selector("#collection .coll-undo")
    page.wait_for_timeout(900)
    assert "seg=1 " not in body()
    page.locator("#collection .coll-undo button", has_text="Undo").click()
    page.wait_for_timeout(900)
    assert body().index("seg=1 ") < body().index("seg=2"), body()
    # drag the second card's grip above the first
    first = page.locator("#collection .coll-item").first.bounding_box()
    page.evaluate("""([x, y]) => {
      const dt = new DataTransfer();
      const grip = document.querySelectorAll('#collection .coll-grip')[1];
      grip.dispatchEvent(new DragEvent('dragstart', { bubbles: true, cancelable: true, dataTransfer: dt }));
      const t = document.elementFromPoint(x, y);
      t.dispatchEvent(new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer: dt, clientX: x, clientY: y }));
      t.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt, clientX: x, clientY: y }));
      grip.dispatchEvent(new DragEvent('dragend', { bubbles: true, dataTransfer: dt }));
    }""", [first["x"] + 60, first["y"] + 8])
    page.wait_for_timeout(900)
    assert body().index("seg=2") < body().index("seg=1 "), body()
    # back in the ordinary note: "Add to an example collection…" from the example's ⋯ menu
    page.locator(".note-card", has_text="Reading notes").click()
    page.wait_for_selector("#editor .text-obj")
    page.locator("#editor .text-obj .flex-head button[title='Options']").first.click()
    page.locator("[data-test='add-to-collection']").click()
    page.locator(".popover .menu-item", has_text="Serial verbs").click()
    page.wait_for_timeout(900)
    assert "seg=4" in body().rstrip().split("\n\n")[-1], body()
    # the list shows it as a collection with its count; reopening draws the three examples
    card = page.locator(".note-card", has_text="Serial verbs")
    assert "IGT" in card.inner_text() and "3 examples" in card.inner_text()
    card.click()
    page.wait_for_function("document.querySelectorAll('#collection .coll-item .text-obj').length === 3")
    assert page.locator("[data-test='coll-count']").inner_text() == "3 examples"
    assert not errors


def dnd(page, src_sel, x, y, ctrl=False):
    """Synthetic HTML5 drag from the element at src_sel to the point (x, y)."""
    page.evaluate("""([src, x, y, ctrl]) => {
      const dt = new DataTransfer();
      const s = document.querySelector(src);
      s.dispatchEvent(new DragEvent('dragstart', { bubbles: true, cancelable: true, dataTransfer: dt }));
      const t = document.elementFromPoint(x, y);
      t.dispatchEvent(new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer: dt, clientX: x, clientY: y, ctrlKey: ctrl }));
      t.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt, clientX: x, clientY: y, ctrlKey: ctrl }));
      s.dispatchEvent(new DragEvent('dragend', { bubbles: true, dataTransfer: dt }));
    }""", [src_sel, x, y, ctrl])
    page.wait_for_timeout(900)


def test_drag_objects_between_text_cells_and_blocks(app):
    """Seth, 2026-10-16: drag objects inline with text, between table cells, out of and into
    tables, or to re-order them."""
    h, page, errors = app
    new_note(page, "Drag")
    page.locator("#editor .blk-body").first.click()
    paste(page, "Compare the word here.\n\n{{flex:entry 6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0001}}\n\n| Form | Example |\n|---|---|\n| a | b |\n| c | d |\n\n{{flex:text %s seg=1}}\n\n{{flex:text %s seg=2}}" % (T_STORY, T_STORY))
    page.wait_for_selector("#editor .blk-flex .entry-card")
    page.wait_for_selector("#editor .text-obj")
    page.wait_for_timeout(600)
    body = page.locator("#editor .blk-p .blk-body").first
    # 1. a block object → the end of the first paragraph: it becomes an inline chip, the block is gone
    box = body.bounding_box()
    dnd(page, "#editor .blk-flex .entry-card .drag-handle", box["x"] + box["width"] - 6, box["y"] + box["height"] / 2)
    assert body_of(h).split("\n")[0] == "Compare the word here. {{flex:entry 6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0001}}", body_of(h)
    assert page.locator("#editor .md-embed").count() == 1 and page.locator("#editor .entry-card").count() == 0
    # 2. the inline chip → a table cell: the cell gets it, the paragraph loses it
    cell = page.locator("table.md-table td[data-r='1'][data-c='1']")
    cb = cell.bounding_box()
    dnd(page, "#editor .md-embed", cb["x"] + cb["width"] / 2, cb["y"] + cb["height"] / 2)
    assert body_of(h).split("\n")[0] == "Compare the word here.", body_of(h)
    assert "| a | b {{flex:entry 6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0001}} |" in body_of(h), body_of(h)
    page.wait_for_selector("table.md-table td[data-r='1'][data-c='1'] .flex-collapsed")
    # 3. the object in the cell → below the table (a block of its own); the cell keeps its text
    tbl = page.locator("#editor .blk-table")
    tb = tbl.bounding_box()
    dnd(page, "table.md-table td[data-r='1'][data-c='1'] .flex-collapsed", tb["x"] + tb["width"] / 2, tb["y"] + tb["height"] - 3)
    b = body_of(h)
    assert "| a | b |" in b and b.count("{{flex:entry") == 1, b
    i_tbl, i_ent, i_t1 = b.index("{table") if "{table" in b else b.index("| c | d |"), b.index("{{flex:entry"), b.index("{{flex:text %s seg=1" % T_STORY)
    assert i_tbl < i_ent < i_t1, b
    # 4. re-order: the second example's handle onto the top half of the first → it comes first
    first = page.locator("#editor .blk-flex .text-obj").first
    fb = first.bounding_box()
    handles = page.evaluate("() => { const hs = [...document.querySelectorAll('#editor .blk-flex .text-obj .drag-handle')]; hs.forEach((h, i) => h.setAttribute('data-test', 'h' + i)); return hs.length; }")
    assert handles == 2
    dnd(page, "#editor .drag-handle[data-test='h1']", fb["x"] + fb["width"] / 2, fb["y"] + 4)
    b = body_of(h)
    assert b.index("seg=2") < b.index("seg=1"), b
    # 5. Ctrl-drag copies: the first example into the paragraph, and it stays below too
    box = page.locator("#editor .blk-p .blk-body").first.bounding_box()
    page.evaluate("() => { [...document.querySelectorAll('#editor .blk-flex .text-obj .drag-handle')].forEach((h, i) => h.setAttribute('data-test', 'h' + i)); }")
    dnd(page, "#editor .drag-handle[data-test='h0']", box["x"] + box["width"] - 6, box["y"] + box["height"] / 2, ctrl=True)
    b = body_of(h)
    assert b.count("seg=2") == 2 and b.split("\n")[0].startswith("Compare the word here. {{flex:text"), b
    assert not errors


def test_table_indent(app):
    """Seth, 2026-10-16: a table's indent within the note — Tab / Shift+Tab on the focused
    table, the context menu, the Table style popover; saved as `indent N` in the style line."""
    h, page, errors = app
    new_note(page, "Indent table")
    page.locator("#editor .blk-body").first.click()
    paste(page, "| a | b |\n|---|---|\n| 1 | 2 |")
    page.wait_for_selector("table.md-table")
    page.locator("#editor .blk-table").focus()
    page.keyboard.press("Tab")
    page.keyboard.press("Tab")
    page.wait_for_timeout(900)
    assert "{table: indent 2}" in body_of(h), body_of(h)
    assert page.locator(".tbl-frame.tbl-indent2").count() == 1
    page.locator("#editor .blk-table").focus()
    page.keyboard.press("Shift+Tab")
    page.wait_for_timeout(900)
    assert "{table: indent 1}" in body_of(h), body_of(h)
    # the context menu outdents back to the margin, and the style line loses the key
    page.locator("table.md-table td[data-r='1'][data-c='0']").click(button="right")
    page.locator(".popover .menu-item", has_text="Outdent table").click()
    page.wait_for_timeout(900)
    assert "indent" not in body_of(h), body_of(h)
    assert page.locator(".tbl-frame[class*='tbl-indent']").count() == 0
    assert not errors


def test_list_start_number(app):
    h, page, errors = app
    new_note(page, "Start at")
    page.locator("#editor .blk-body").first.click()
    paste(page, "3. third\n4. fourth\n\n1. again\n2. more")
    page.wait_for_timeout(400)
    shown = page.evaluate("() => [...document.querySelectorAll('#editor .md-num[data-num]')].map((n) => n.dataset.num)")
    assert shown == ["3.", "4.", "1.", "2."], shown
    # Enter after "fourth" continues with 5
    page.locator("#editor .blk-list .blk-body").first.click()
    page.keyboard.press("Control+End")
    page.keyboard.press("Enter")
    page.keyboard.type("fifth")
    page.wait_for_timeout(600)
    assert "5. fifth" in body_of(h), body_of(h)
    # the block menu sets the start of the second list
    page.once("dialog", lambda d: d.accept("7"))
    page.locator("#editor .blk-list").nth(1).hover()
    page.locator("#editor .blk-list").nth(1).locator(".blk-handle button").dispatch_event("mousedown")
    page.locator(".popover .menu-item", has_text="Start numbering at").click()
    page.wait_for_timeout(600)
    assert "7. again\n2. more" in body_of(h), body_of(h)
    shown = page.evaluate("() => [...document.querySelectorAll('#editor .md-num[data-num]')].map((n) => n.dataset.num)")
    assert shown[-2:] == ["7.", "8."], shown
    assert not errors


def test_duplicate_note_from_the_menu(app):
    h, page, errors = app
    new_note(page, "Original")
    page.locator("#editor .blk-body").first.click()
    page.keyboard.type("Keep me")
    page.wait_for_timeout(900)
    before = page.locator(".note-card").count()
    page.locator(".note-card", has_text="Original").first.click(button="right")
    page.locator(".popover .menu-item", has_text="Duplicate").click()
    page.wait_for_function("(n) => document.querySelectorAll('.note-card').length === n + 1", arg=before)
    assert page.locator("#note-title").input_value() == "Original (copy)"
    assert "Keep me" in page.locator("#editor").inner_text()
    titles = sorted(x["title"] for x in h.api._nb.list_notes())
    assert "Original" in titles and "Original (copy)" in titles
    assert not errors


def test_progress_messages_do_not_stick_in_the_pill(app):
    """Seth, 2026-10-16: "Indexing texts…" stayed in the tile next to a warning icon and read as
    "indexing paused". A progress message is temporary; an empty one restores the state."""
    h, page, errors = app
    label = page.locator("#flex-pill .label")
    before = label.inner_text()
    page.evaluate("() => FS.emit('py:progress', { message: 'Indexing texts… 40/140' })")
    assert label.inner_text() == "Indexing texts… 40/140"
    assert page.evaluate("() => getComputedStyle(document.querySelector('#flex-pill .warn-icon')).display") == "none"
    page.evaluate("() => FS.emit('py:progress', { message: '' })")
    assert label.inner_text() == before
    assert not errors


def test_select_across_blocks_cut_copy_delete_type(app):
    """Seth, 2026-10-16: select, cut, copy, paste or delete multiple lines — text, tables, FLEx
    objects and lists — with partial blocks at the ends."""
    h, page, errors = app
    new_note(page, "Multi")
    page.locator("#editor .blk-body").first.click()
    paste(page, "First line of text\n\n{{flex:text %s seg=1}}\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n1. one\n2. two\n\nLast line here" % T_STORY)
    page.wait_for_selector("#editor .text-obj")
    page.wait_for_timeout(600)
    bodies = page.locator("#editor .blk-body")
    first, last = bodies.first.bounding_box(), page.locator("#editor .blk-body", has_text="Last line here").bounding_box()
    # drag from the end of the first paragraph to the start of the last one
    page.mouse.move(first["x"] + first["width"] - 2, first["y"] + first["height"] / 2)
    page.mouse.down()
    page.mouse.move(last["x"] + 2, last["y"] + last["height"] / 2, steps=10)
    page.mouse.up()
    page.wait_for_timeout(200)
    md = page.evaluate("() => window.__fsEditor.selectionMarkdown()")
    assert md.strip().startswith("{{flex:text") and "| a | b |" in md and "1. one" in md and "Last line" not in md, md
    assert page.locator("#editor .blk.msel-block").count() >= 3                       # the flex block, the table, the list
    # Ctrl+C copies the markdown of the selection
    page.evaluate("() => { window.__copied = null; FS.copyText = (t) => { window.__copied = t; return Promise.resolve(true); }; }")
    page.keyboard.press("Control+c")
    copied = page.evaluate("() => window.__copied")
    assert copied and "{{flex:text" in copied and "| 1 | 2 |" in copied and "2. two" in copied, copied
    # Delete joins what is left of the first and last paragraphs into one block
    page.keyboard.press("Delete")
    page.wait_for_timeout(900)
    assert body_of(h) == "First line of textLast line here", body_of(h)
    assert page.locator("#editor .blk").count() == 2                                  # the joined paragraph + the trailing empty one
    # undo brings it all back
    page.keyboard.press("Control+z")
    page.wait_for_timeout(900)
    assert "{{flex:text" in body_of(h) and "| a | b |" in body_of(h)
    # Shift+click selects from the caret to another block; typing replaces the selection
    page.locator("#editor .blk-body").first.click()
    page.keyboard.press("Home")
    for _ in range(5): page.keyboard.press("ArrowRight")                             # after "First"
    box = page.locator("table.md-table td[data-r='1'][data-c='1']").bounding_box()
    page.keyboard.down("Shift")
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.keyboard.up("Shift")
    page.wait_for_timeout(200)
    assert page.evaluate("() => !!window.__fsEditor.msel")
    page.keyboard.type("!")
    page.wait_for_timeout(900)
    b = body_of(h)
    assert b.startswith("First!") and "{{flex:text" not in b and "| a | b |" not in b and "1. one" in b, b
    # Ctrl+A twice takes the whole note; Backspace empties it
    page.keyboard.press("Control+a")
    page.keyboard.press("Control+a")
    page.wait_for_timeout(100)
    assert page.evaluate("() => !!window.__fsEditor.msel")
    page.keyboard.press("Backspace")
    page.wait_for_timeout(900)
    assert body_of(h).strip() == "", body_of(h)
    assert not errors


def test_table_insert_above_while_editing_and_paste_rows_from_the_menu(app):
    """Seth, 2026-10-16: inserting rows above was unreliable (the open cell's text landed in
    its old row index after the shift) and the menu's Paste rows could not read the clipboard."""
    h, page, errors = app
    new_note(page, "Rows")
    page.locator("#editor .blk-body").first.click()
    paste(page, "| A | B |\n|---|---|\n| a1 | b1 |\n| a2 | b2 |")
    page.wait_for_selector("table.md-table")
    # type into a cell, then (still editing) insert a row above it from the menu
    cell = page.locator("table.md-table td[data-r='2'][data-c='1']")
    cell.click()
    page.wait_for_selector("table.md-table .cell-edit")
    page.keyboard.press("End")
    page.keyboard.type("+zz")
    cell = page.locator("table.md-table td[data-r='2'][data-c='1']")
    cell.click(button="right")
    page.locator(".popover .menu-item", has_text="Insert row above").click()
    page.wait_for_timeout(900)
    b = body_of(h)
    assert "| a1 | b1 |\n|  |  |\n| a2 | b2+zz |" in b, b
    # copy row 2 (gutter), then paste it below row 4 from the menu: the app's own copy serves
    page.locator("table.md-table th.gutter.row[data-gr='1']").click()
    page.keyboard.press("Control+c")
    assert page.evaluate("() => FS.tableClip && FS.tableClip.rows.map((r) => r.join('|')).join(';')") == "a1|b1"
    page.locator("table.md-table td[data-r='3'][data-c='0']").click(button="right")
    page.locator(".popover .menu-item", has_text="Paste rows below").click()
    page.wait_for_timeout(1500)     # the clipboard read gives up after 400 ms, then autosave's 600 ms
    b = body_of(h)
    assert b.count("| a1 | b1 |") == 2 and b.index("b2+zz") < b.rindex("| a1 | b1 |"), b
    # a 2x2 grid pasted while a cell is open fills the cells from that one
    page.locator("table.md-table td[data-r='1'][data-c='0']").click()
    page.wait_for_selector("table.md-table .cell-edit")
    paste(page, "p\tq\nr\ts")
    page.wait_for_timeout(900)
    b = body_of(h)
    assert "| p | q |\n| r | s |" in b, b
    # "− Row" deletes the row SELECTED in the gutter, not the cell last edited
    page.locator("table.md-table th.gutter.row[data-gr='3']").click()          # the "a2 | b2+zz" row
    page.locator("table.md-table").hover()
    tool(page, "− Row")
    page.wait_for_timeout(900)
    b = body_of(h)
    assert "b2+zz" not in b and "| p | q |" in b, b
    assert not errors


def test_pressing_or_dragging_a_chip_keeps_the_preview_out_of_the_way(app):
    """Seth, 2026-10-16: the overlay appeared the moment a tile was pressed and then sat in the
    way of the drag. A press cancels the hover preview; a drag closes any overlay."""
    h, page, errors = app
    new_note(page, "Press")
    page.locator("#editor .blk-body").first.click()
    paste(page, "Intro line.\n\n{{flex:text %s seg=1 collapsed}}\n\nInline {{flex:entry 6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0001}} here." % T_STORY)
    chip = page.locator("#editor .flex-collapsed").first
    chip.wait_for()
    # hovering previews it…
    chip.hover()
    page.wait_for_selector(".flex-overlay")
    # …pressing drops the preview, and holding still does not bring it back
    page.mouse.down()
    page.wait_for_timeout(700)
    assert page.locator(".flex-overlay").count() == 0
    page.mouse.up()                     # a click without a drag still pins it open
    page.wait_for_selector(".flex-overlay.pinned")
    # a drag that starts on the chip closes even the pinned overlay
    page.evaluate("""() => { const s = document.querySelector('#editor .flex-collapsed');
      s.dispatchEvent(new DragEvent('dragstart', { bubbles: true, cancelable: true, dataTransfer: new DataTransfer() })); }""")
    assert page.locator(".flex-overlay").count() == 0
    page.evaluate("() => document.querySelector('#editor .flex-collapsed').dispatchEvent(new DragEvent('dragend', { bubbles: true }))")
    # the inline chip behaves the same
    page.mouse.move(5, 5)
    page.wait_for_timeout(500)
    inline = page.locator("#editor .md-embed").first
    inline.hover()
    page.wait_for_selector(".flex-overlay")
    page.mouse.down()
    page.wait_for_timeout(700)
    assert page.locator(".flex-overlay").count() == 0
    page.mouse.up()
    assert not errors


def test_a_slow_paste_lookup_shows_a_spinner_and_can_be_skipped(app):
    """Seth, 2026-10-16: "when I paste a flex example and it takes awhile to process/find it,
    could we get a loading or 'searching...' spinner?" """
    h, page, errors = app
    new_note(page, "Slow")
    rows = "Word\tHaŋa\ttiket\tka-sila-mo\tpemu\nWord Gloss\tyesterday\tchild\tsaw\triver\nFree\tYesterday the child saw the river."
    # make the lookup slow (on the page side: a sleeping Python call would stall the test driver)
    page.evaluate("""() => { const real = window.__flexBridge; window.__locateDelay = 2500;
      window.__flexBridge = (req) => JSON.parse(req).method === 'flex_locate'
        ? new Promise((res) => setTimeout(() => res(real(req)), window.__locateDelay)) : real(req); }""")
    paste(page, rows)
    page.wait_for_selector(".busy-pill .spinner")
    assert "Searching the project" in page.locator(".busy-pill").inner_text()
    page.wait_for_selector(".modal", timeout=6000)          # the answer arrives: the pill goes
    assert page.locator(".busy-pill").count() == 0
    page.locator(".modal .btn", has_text="Paste as text").click()
    # skipping the wait pastes the lines as text, and the late answer is ignored
    page.locator("#editor .blk-body").last.click()
    page.keyboard.press("End")
    page.keyboard.press("Enter")
    paste(page, rows)
    page.wait_for_selector(".busy-pill")
    page.locator(".busy-pill button", has_text="Paste as text").click()
    assert page.locator(".busy-pill").count() == 0
    page.wait_for_timeout(3200)
    assert page.locator(".modal").count() == 0
    # a quick answer never flashes the pill
    page.evaluate("() => { window.__locateDelay = 0; }")
    page.locator("#editor .blk-body").last.click()
    page.keyboard.press("End")
    page.keyboard.press("Enter")
    seen = page.evaluate("""() => new Promise((res) => { let s = false;
      const mo = new MutationObserver(() => { if (document.querySelector('.busy-pill')) s = true; });
      mo.observe(document.body, { childList: true, subtree: true }); window.__seenPill = () => { mo.disconnect(); return s; }; res(true); })""")
    paste(page, rows)
    page.wait_for_selector(".modal")
    assert page.evaluate("() => window.__seenPill()") is False
    page.locator(".modal .btn", has_text="Paste as text").click()
    page.wait_for_timeout(900)
    assert body_of(h).count("Yesterday the child saw the river.") >= 2, body_of(h)
    assert not errors
