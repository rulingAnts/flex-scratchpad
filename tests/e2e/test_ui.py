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
    page.locator("#editor .text-obj .word-cell").nth(1).click()
    page.wait_for_selector(".popover")
    page.locator(".popover .sw").nth(1).click()
    page.wait_for_selector("#editor .text-obj .st-hl")
    page.wait_for_timeout(900)
    body = body_of(h)
    assert "{{flex:entry 6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0001}}" in body
    assert "{{flex:text %s seg=1-2 hl[#ffd6a5]=1.2}}" % T_STORY in body
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
    assert "{{flex:text %s seg=1}}<br>line two |" % T_STORY in body
    # column style popover
    page.locator(".tbl-tools button", has_text="Table").click()
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
    assert "{{flex:text %s seg=1-2 collapsed}}" % T_STORY in body_of(h)
    assert page.locator("#editor .flex-collapsed .crange").inner_text() == "1–2"
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
    th = page.locator("table.md-table thead th").first
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
    th = page.locator("table.md-table thead th").first
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
    assert '{{flex:text %s seg=1 "causative ex. 3"}}' % T_STORY in body_of(h)
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
    page.locator("#editor .text-obj .word-cell").first.click()
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
