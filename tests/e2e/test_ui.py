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
from flex_scratchpad.notebook import without_flex_copies  # noqa: E402

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
    """The body of the note the test is working on: the most recently edited one — skipping the
    Welcome note when the test made another, since edit times tie within a second."""
    notes = h.api._nb.list_notes()
    own = [n for n in notes if n["title"] != "Welcome to FLEx Scratchpad"] or notes
    # what the user edited: the file also carries a plain-text copy after each FLEx object
    # (flexcopy.js), which test_flex_objects_get_a_readable_copy_in_the_file checks on its own
    return without_flex_copies(h.api.get_note(own[0]["id"])["body"])


def tool(page, text, nth=0):
    """Click a button in the bar under the nth table; the bar shows once the table was clicked into
    (not on mere hover — Seth, 2026-10-18), so press on it first."""
    page.locator("table.md-table").nth(nth).hover()
    page.locator("table.md-table").nth(nth).dispatch_event("mousedown")
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


def test_a_chart_plays_its_lines_and_lights_their_cells(app):
    """Seth, 2026-10-18: "audio playback in the chart, with play controls on the first row that
    starts an interlinear line. And highlighting (while playing) the cells that contain data
    from that line"."""
    h, page, errors = app
    new_note(page, "Chart audio")
    page.keyboard.type("{{flex:chart %s rows=1-3}}" % CHART)
    page.keyboard.press("Enter")
    page.wait_for_selector(".tchart .rlab .seg-play")
    # one ▶ per timed line, on the row where it starts (demo: rows 1, 2a, 2b start lines 1, 2, 3)
    assert page.locator(".tchart .rlab .chart-play").count() == 3
    assert page.locator(".tchart .th-lab .seg-play").count() == 1
    # ▶§ plays the whole sentence 2 (rows 2a–2b) from its first row (Seth: "a play button for 4, not just for 4a, 4b, 4c")
    assert page.locator(".tchart .rlab .chart-play-sent").count() == 1          # rows 1a–1b (2a is alone in this range)
    assert "rows 1a–1b" in page.locator(".tchart .rlab .chart-play-sent").get_attribute("title")
    assert page.locator(".tchart tr[data-label='1a'] .chart-play-sent").count() == 1
    page.locator(".tchart .rlab .chart-play").nth(1).click()
    page.wait_for_selector(".chart-obj .transport")
    page.wait_for_timeout(400)
    assert page.evaluate("!!FS.interlinear.audio.current")
    # the cells holding line 2's words are lit, nothing else
    lit = page.locator(".tchart td.playing-line")
    assert lit.count() >= 1
    assert all("2" in (lit.nth(i).get_attribute("data-segs") or "").split() for i in range(lit.count()))
    page.wait_for_timeout(2600)
    assert page.evaluate("!!FS.interlinear.audio.current") is False
    assert page.locator(".tchart td.playing-line").count() == 0


def test_html_export_embeds_the_recordings_as_players(app):
    """Seth, 2026-10-18: "pretty exports … including audio players and base64 embedded audio where
    audio files and segmentation data are available and match" — for examples and charts alike."""
    h, page, errors = app
    new_note(page, "Players")
    page.keyboard.type("{{flex:text %s seg=1-2}}" % T_STORY)
    page.keyboard.press("Enter")
    page.keyboard.type("{{flex:chart %s rows=1-2}}" % CHART)
    page.keyboard.press("Enter")
    page.keyboard.type("{{flex:text %s}}" % T_ARAB)        # no recording: no player, the page still exports
    page.keyboard.press("Enter")
    page.wait_for_selector("#editor .chart-obj tr.crow")
    page.wait_for_function("() => document.getElementById('save-state').textContent === 'Saved'", timeout=5000)
    html_path = str(h.tmp / "players.html")
    res = page.evaluate("""async (hp) => {
      const api = window.pywebview.api;
      const notes = await api.list_notes(); const note = (await Promise.all(notes.map((n) => api.get_note(n.id)))).find((n) => n.title === 'Players');
      const editor = new FS.Editor(document.createElement('div'), {}); editor.load(FS.flexcopy.strip(note.body));
      const doc = await FS.exporter.buildDoc(note, editor);
      const timed = FS.exporter.timedBlocks(doc).length;
      const stats = await FS.exporter.embedAudio(doc);
      await api.export_note_html(note.id, FS.exporter.toHtml(doc), hp);
      return { timed, stats, html: FS.exporter.toHtml(doc) };
    }""", html_path)
    assert res["timed"] == 2 and res["stats"]["count"] == 2 and res["stats"]["missing"] == 0, res["stats"]
    html = res["html"]
    assert html.count('<audio data-a=') == 2 and 'src="data:audio/' in html and '<div id="np"' in html
    assert '<button class="play" data-a="a1" data-segs="1"' in html and 'data-segs="1 2"' in html      # a line, the whole example
    assert 'class="tchart"' in html and '<td data-segs="1">' in html.split('class="tchart"')[1]      # the cells a line lights
    assert '@page { size: landscape' in html and 'header class="doc"' in html
    # the slideshow: a title slide, the two examples and the chart on slides of their own
    deck = page.evaluate("""async () => {
      const api = window.pywebview.api;
      const notes = await api.list_notes(); const note = (await Promise.all(notes.map((n) => api.get_note(n.id)))).find((n) => n.title === 'Players');
      const editor = new FS.Editor(document.createElement('div'), {}); editor.load(FS.flexcopy.strip(note.body));
      const doc = await FS.exporter.buildDoc(note, editor);
      const deck = FS.exporter.slidesOf(doc);
      await api.export_note_pptx(note.id, deck, %r);
      return { kinds: deck.slides.map((s) => s.kind + ':' + (s.blocks[0] ? s.blocks[0].type : '')), html: FS.exporter.toSlides(doc) };
    }""" % str(h.tmp / "deck.pptx"))
    assert deck["kinds"] == ["title:", "object:interlinear", "object:chart", "object:interlinear"], deck["kinds"]
    assert deck["html"].count('<section class="slide') == 4 and 'id="toc"' in deck["html"]
    import zipfile
    zp = zipfile.ZipFile(str(h.tmp / "deck.pptx"))
    assert zp.testzip() is None and "Kabir" in zp.read("ppt/slides/slide2.xml").decode("utf-8") and "<a:tbl>" in zp.read("ppt/slides/slide3.xml").decode("utf-8")
    slides_path = str(h.tmp / "slides.html")
    Path(slides_path).write_text(deck["html"], encoding="utf-8")
    pg = page.context.new_page()
    try:
        pg.goto(Path(slides_path).resolve().as_uri())
        pg.wait_for_selector(".slide.on")
        assert pg.locator(".slide.on").get_attribute("data-n") == "0"
        pg.keyboard.press("ArrowRight")
        assert pg.locator(".slide.on").get_attribute("data-n") == "1" and pg.locator(".slide.on .seg").count() == 2
        pg.keyboard.press("End")
        assert pg.locator(".slide.on").get_attribute("data-n") == "3"
        pg.keyboard.press("Home")
        assert pg.locator("#ctr").inner_text() == "1 / 4"
    finally:
        pg.close()
    # the written page plays on its own: open it in the browser and press a line's ▶
    pg = page.context.new_page()
    try:
        pg.goto(Path(html_path).resolve().as_uri())
        pg.wait_for_selector(".seg .play")
        pg.locator(".seg .play").first.click()
        pg.wait_for_selector(".seg.playing", timeout=5000)
        assert pg.locator("#np").is_visible()
        assert pg.evaluate("document.querySelector('.seg.playing').dataset.n") == "1"
        pg.locator(".tchart tbody th .play").first.click()
        pg.wait_for_selector(".tchart td.playing", timeout=5000)
        assert "1" in pg.locator(".tchart td.playing").first.get_attribute("data-segs").split()
        pg.locator("#np .st").click()
        assert pg.locator(".playing").count() == 0
    finally:
        pg.close()
    assert not errors


def test_chart_columns_resize_and_a_collapsed_example_exports_as_a_link(app):
    """Seth, 2026-10-18: "adjust column sizes (including off the right side, requiring rightward
    scroll)"; a collapsed example or chip exports as "a text abbreviation or title and line range
    that is a hyperlink to that text in FLEx"."""
    h, page, errors = app
    new_note(page, "Widths")
    page.keyboard.type("{{flex:chart %s rows=1-3}}" % CHART)
    page.keyboard.press("Enter")
    page.keyboard.type("{{flex:text %s seg=1-2 collapsed}}" % T_STORY)
    page.keyboard.press("Enter")
    page.wait_for_selector("#editor .chart-obj tr.crow")
    page.wait_for_function("() => document.getElementById('save-state').textContent === 'Saved'", timeout=5000)
    grip = page.locator("#editor .chart-obj [data-test=col-rs-4]")
    th = page.locator("#editor .chart-obj thead th.th-col[data-col='4']")
    before = th.bounding_box()["width"]
    pane_w = page.evaluate("document.querySelector('#editor .chart-obj .chart-scroll').clientWidth")
    box = grip.bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(box["x"] + 420, box["y"] + 2, steps=8)
    page.mouse.up()
    page.wait_for_function("() => document.getElementById('save-state').textContent === 'Saved'", timeout=5000)
    after = page.locator("#editor .chart-obj thead th.th-col[data-col='4']").bounding_box()["width"]
    assert after > before + 300, (before, after)
    body = body_of(h)
    assert re.search(r"cw=4:\d+", body), body
    # the table outgrew the pane and scrolls sideways
    assert page.evaluate("() => { const s = document.querySelector('#editor .chart-obj .chart-scroll'); return s.scrollWidth > s.clientWidth; }"), pane_w
    # the exports: the widths on the page's table, the collapsed example as a FLEx link
    html = page.evaluate("""async () => {
      const api = window.pywebview.api; const notes = await api.list_notes(); const note = (await Promise.all(notes.map((n) => api.get_note(n.id)))).find((n) => n.title === 'Widths');
      const editor = new FS.Editor(document.createElement('div'), {}); editor.load(FS.flexcopy.strip(note.body));
      const doc = await FS.exporter.buildDoc(note, editor); return FS.exporter.toHtml(doc);
    }""")
    assert re.search(r'<col style="width:\d+px">', html) and html.count('class="obj"') == 0 and '<a href="silfw://' in html and "1.1–1.2" in html, html[-800:]
    # ⋯ → Reset column widths
    page.locator("#editor .chart-obj [data-test=chart-menu]").click()
    page.locator("[data-test=chart-reset-widths]").click()
    page.wait_for_function("() => document.getElementById('save-state').textContent === 'Saved'", timeout=5000)
    assert "cw=" not in body_of(h)
    assert not errors


def test_chart_header_rows_stick_while_the_chart_scrolls(app):
    """Seth, 2026-10-18: "we want the chart header rows to be sticky"."""
    h, page, errors = app
    new_note(page, "Sticky chart")
    page.keyboard.type("{{flex:chart %s}}" % CHART)
    page.keyboard.press("Enter")
    for i in range(30):
        page.keyboard.type("Line %d after the chart." % i)
        page.keyboard.press("Enter")
    page.wait_for_selector("#editor .chart-obj tr.crow")
    page.wait_for_timeout(300)
    assert page.locator("[data-test=chart-sticky-head]").count() == 0 or not page.locator("[data-test=chart-sticky-head]").is_visible()
    # scroll so the header has passed the top but the last rows are still in view
    page.evaluate("""() => { const ed = document.getElementById('editor'); const t = document.querySelector('#editor .chart-obj table.tchart'); const r = t.getBoundingClientRect(), e = ed.getBoundingClientRect(); ed.scrollTop += (r.top - e.top) + 120; }""")
    page.wait_for_selector("[data-test=chart-sticky-head]", state="visible", timeout=3000)
    ghost = page.locator("[data-test=chart-sticky-head]")
    assert "NUCLEUS" in ghost.inner_text().upper() and "Subject" in ghost.inner_text()      # (the group row is uppercased by CSS)
    gb = ghost.bounding_box(); eb = page.locator("#editor").bounding_box()
    assert abs(gb["y"] - eb["y"]) < 4, (gb, eb)
    # the copy's columns sit over the table's
    live = page.locator("#editor .chart-obj table.tchart thead th.th-col[data-col='3']").bounding_box()
    copy = ghost.locator("th.th-col[data-col='3']").bounding_box()
    assert abs(live["x"] - copy["x"]) < 2 and abs(live["width"] - copy["width"]) < 2, (live, copy)
    # gone once the chart has scrolled away
    page.evaluate("document.getElementById('editor').scrollTop += 2000")
    page.wait_for_timeout(200)
    assert not ghost.is_visible()
    assert not errors


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
    # the note lives in Grammar / Verbs / Aspect: the tab lists its own notes and offers the rest
    page.locator("[data-test='show-below']").click()
    page.wait_for_selector(".note-card")
    page.locator(".note-card", has_text="Past tense").click()
    page.wait_for_selector("#editor .entry-card")
    page.wait_for_selector("#editor .text-obj .st-u")
    ctx.close()


def test_inside_the_app_the_page_waits_for_the_api_and_never_shows_the_demo(browser):
    """Seth, 2026-10-19: the newest wheel started on the page's in-browser demo notebook ("Kalu
    Demo", nothing else) — pywebview had not handed the page its api and after 15 s the page
    quietly used the mock. A WebView2 page is known from window.chrome.webview before pywebview
    injects anything: there the page waits, says so, and takes the api whenever it arrives."""
    ctx = browser.new_context()
    ctx.add_init_script("window.chrome = window.chrome || {}; window.chrome.webview = { postMessage() {} }; window.FS_BRIDGE_WAIT_MS = 400; window.FS_BRIDGE_RELOAD_MS = 1500;")
    page = ctx.new_page()
    from bridge import UI
    page.goto(UI.as_uri())
    page.wait_for_selector("[data-test='bridge-wait']", timeout=5000)
    assert "Waiting for the app" in page.inner_text("#bridge-wait")
    assert "flex-scratchpad -v" in page.inner_text("#bridge-wait")
    page.wait_for_timeout(800)
    assert page.evaluate("!!window.FS._mockActive") is False
    assert page.locator("#tabs .tab-item").count() == 0
    # the retry: the page reloads itself (pywebview injects on every navigation), at most twice
    page.wait_for_function("sessionStorage.getItem('fs:bridgeReloads') === '1' && document.querySelector('#bridge-wait')", timeout=8000)
    assert "Reloaded 1 time" in page.inner_text("#bridge-wait")
    assert page.evaluate("!!window.FS._mockActive") is False
    # the api arrives late (here: the mock standing in for it): the page goes on as usual
    page.evaluate("window.pywebview = { api: FS.mockApi() }")
    page.wait_for_selector("#tabs .tab-item", timeout=5000)
    page.wait_for_selector("[data-test='bridge-wait']", state="detached", timeout=5000)
    assert page.evaluate("sessionStorage.getItem('fs:bridgeReloads')") is None
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
    # the whole table in the middle of the view: at the bottom edge its sticky tool bar would sit over the header
    page.evaluate("(el) => el.closest('.widget').scrollIntoView({ block: 'center' })", th.element_handle())
    page.wait_for_timeout(200)
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
    page.locator("#editor .blk-body").last.click()
    page.keyboard.press("End")
    page.keyboard.press("Enter")
    page.keyboard.type("> A quotation, without its marker in the export")
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
    assert "<blockquote>A quotation, without its marker in the export</blockquote>" in html, html
    # the entry sits in a table cell as a CHIP, so it exports as a link into FLEx (Seth, 2026-10-18), not in full
    assert "The dog slept." in html and 'href="silfw://' in html and "kabir" in html and "a domestic dog" not in html
    assert (h.tmp / "note.html").read_text(encoding="utf-8").startswith("<!doctype html>")
    import zipfile
    xml = zipfile.ZipFile(docx_path).read("word/document.xml").decode("utf-8")
    assert "ka-nuwa-mo" in xml and "The dog slept." in xml and '<w:u w:val="single"/>' in xml
    assert '<w:tblStyle w:val="LingTeXInterlinear"/>' in xml and '<w:pStyle w:val="LingTeXFree"/>' in xml      # LingTeX-Word's shape
    assert "<w:hyperlink " in xml and ">kabir" in xml
    assert not errors


def test_paste_interlinear_lines_locates_the_segment(app):
    h, page, errors = app
    new_note(page, "Located")
    paste(page, "Word\tHaŋa\ttiket\tka-sila-mo\tpemu\nWord Gloss\tyesterday\tchild\tsaw\triver\nFree\tYesterday the child saw the river.")
    page.wait_for_selector(".modal")
    assert "The dog and the river" in page.locator(".modal-body").inner_text() and "segment 1.2" in page.locator(".modal-body").inner_text()   # FLEx's number
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
    # the heading's "# " is not displayed (the caret is elsewhere), the text is intact
    page.evaluate("() => { const b = document.querySelector('#editor .blk-p .blk-body'); FS.editor.setCaret(b, 0); b.focus(); }")
    page.wait_for_timeout(150)
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
    page.locator("table.md-table").first.evaluate("(e) => e.scrollIntoView({ block: 'center' })")   # the table's tool bar floats at the pane's foot
    page.wait_for_timeout(200)
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
    # nested items are lettered (a. b.), the level below in roman (i. ii.) — Seth, 2026-10-18: "display it prettily"
    assert shown == ["1. Symmetrical", "a. Examples:", "2. One-word", "a. Examples:", "3. Argument sharing", "a. All", "b. Shared subject"], shown
    # what is DRAWN: the computed number via ::before, the typed digits invisible
    drawn = page.evaluate("() => [...document.querySelectorAll('#editor .md-num[data-num]')].map((n) => [getComputedStyle(n, '::before').content, getComputedStyle(n).color])")
    assert [d[0] for d in drawn] == ['"1."', '"a."', '"2."', '"a."', '"3."', '"a."', '"b."'], drawn
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
    assert shown[-1] == "c."
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
    # concatenated audio is the default (Seth, 2026-10-17), per line the other choice
    sel = page.locator(".modal .form-row:has(label:text-is(\"Audio\")) select")
    assert sel.input_value() == "bundle" and "click" in sel.locator("option:checked").inner_text()
    assert page.locator(".modal .form-row", has_text="Audio into").is_visible()
    sel.select_option("none")
    assert page.locator(".modal .form-row", has_text="Audio into").is_hidden()
    sel.select_option("clips")
    assert page.locator(".modal .form-row", has_text="Audio into").is_visible()
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
    assert r["audio"] == str(h.tmp / "svcs.wav") and r["audioMatched"] == 3 and (h.tmp / "svcs.wav").exists()
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
    page.wait_for_timeout(1000)   # past the 600 ms autosave
    assert "5. fifth" in body_of(h), body_of(h)
    # the block menu sets the start of the second list
    page.once("dialog", lambda d: d.accept("7"))
    page.locator("#editor .blk-list").nth(1).hover()
    page.locator("#editor .blk-list").nth(1).locator(".blk-handle button").dispatch_event("mousedown")
    page.locator(".popover .menu-item", has_text="Start numbering at").click()
    page.wait_for_timeout(1000)
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
    # the Row ▾ menu's Delete takes the row SELECTED in the gutter, not the cell last edited, and
    # leaves a toast whose Undo brings it back (Seth, 2026-10-18: the bar's − buttons were "easy
    # to click on accident (with drastic consequences)")
    page.locator("table.md-table th.gutter.row[data-gr='3']").click()          # the "a2 | b2+zz" row
    page.locator("table.md-table").hover()
    assert page.locator(".tbl-tools").first.locator("button", has_text="− Row").count() == 0
    tool(page, "Row ▾")
    page.locator("[data-test=row-delete]").click()
    page.wait_for_selector(".toast:has-text('Row removed') [data-test=toast-action]")
    page.wait_for_timeout(900)
    b = body_of(h)
    assert "b2+zz" not in b and "| p | q |" in b, b
    page.locator(".toast [data-test=toast-action]").click()
    page.wait_for_timeout(900)
    assert "b2+zz" in body_of(h), body_of(h)
    page.locator("table.md-table th.gutter.row[data-gr='3']").click()
    tool(page, "Row ▾")
    page.locator("[data-test=row-delete]").click()
    page.wait_for_timeout(900)
    assert "b2+zz" not in body_of(h), body_of(h)
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


def test_new_menu_stays_visible_beside_a_long_folder_name(app):
    """Seth, 2026-10-16: with the folder "Morning- SVCs (Part I)" open, the ▾ beside "+ New"
    (where New example collection lives) was pushed out of the pane by the title."""
    h, page, errors = app
    page.evaluate("() => { document.getElementById('list-title').textContent = 'Morning- SVCs (Part I) and a much longer folder name still'; }")
    lst = page.locator("#list").bounding_box()
    for sel in ("#btn-new-note", "#btn-new-menu"):
        b = page.locator(sel).bounding_box()
        assert b["x"] + b["width"] <= lst["x"] + lst["width"] + 0.5, (sel, b, lst)
    page.locator("#btn-new-menu").click()
    page.locator("[data-test='new-collection']").click()
    page.wait_for_selector("#collection .coll-add")
    assert not errors


def test_a_running_window_says_when_another_build_is_installed(app):
    """A second start hands over to the running window; when the installed build differs, that
    window says to close and restart (Seth, 2026-10-16: the update "doesn't appear to have
    added the feature" — the old window was still the one running)."""
    h, page, errors = app
    page.evaluate("() => FS.otherBuild('f629ec1', '87496d6')")
    page.wait_for_selector(".modal.other-build")
    t = page.locator(".modal.other-build").inner_text()
    assert "87496d6" in t and "f629ec1" in t and "start it again" in t
    page.evaluate("() => FS.otherBuild('f629ec1', '87496d6')")             # never stacked
    assert page.locator(".modal.other-build").count() == 1
    page.locator(".modal.other-build .btn.primary").click()
    assert page.locator(".modal.other-build").count() == 0
    assert not errors


def test_collection_groups_and_example_notes(app):
    """Seth, 2026-10-16: "expandable/collapsible, labeled blocks of examples within the collection
    type. Those won't export in the flextext … Also the ability to add notes … to flex objects
    that WOULD get included in the flextext export." """
    h, page, errors = app
    page.locator("#btn-new-menu").click()
    page.locator("[data-test='new-collection']").click()
    page.wait_for_selector("#collection .coll-add")
    page.locator("#note-title").fill("SVC sorting")
    for seg in (1, 2, 4):
        page.locator("#collection .coll-add").click()
        paste(page, "{{flex:text %s seg=%d}}" % (T_STORY, seg))
    page.wait_for_function("document.querySelectorAll('#collection .coll-item').length === 3")
    def body():
        return h.api.get_note(h.api.list_collections()[0]["id"])["body"]
    # a group, added at the end, then the last example moved into it with ↓
    page.once("dialog", lambda d: d.accept("Shared subject"))
    page.locator("[data-test='coll-add-group']").click()
    page.wait_for_selector("#collection .coll-group")
    third = page.locator("#collection .coll-item").nth(2)
    third.hover()
    third.locator("button[title='Move down']").click()
    page.wait_for_timeout(900)
    assert body().split("## Shared subject")[1].count("{{flex:text") == 1 and "seg=4" in body().split("## Shared subject")[1], body()
    assert "1 example" in page.locator("#collection .coll-group").inner_text()
    # numbering runs straight through the groups
    assert page.locator("#collection .coll-num").all_inner_texts() == ["(1)", "(2)", "(3)"]
    # a note on the second example
    second = page.locator("#collection .coll-item").nth(1)
    second.hover()
    second.locator("[data-test='coll-note-btn']").click()
    page.keyboard.type("Both verbs share the subject.")
    page.wait_for_timeout(900)
    assert "seg=2" in body() and "> Both verbs share the subject." in body(), body()
    # collapse: its example is hidden and the file says so; the count stays
    page.locator("[data-test='coll-toggle']").click()
    page.wait_for_timeout(900)
    assert page.locator("#collection .coll-item").count() == 2 and "## Shared subject {collapsed}" in body()
    assert page.locator("[data-test='coll-count']").inner_text() == "3 examples"
    # drag the first example onto the collapsed group's heading: into the group
    head = page.locator("#collection .coll-group").bounding_box()
    page.evaluate("""([x, y]) => {
      const dt = new DataTransfer();
      const grip = document.querySelector('#collection .coll-item .coll-grip');
      grip.dispatchEvent(new DragEvent('dragstart', { bubbles: true, cancelable: true, dataTransfer: dt }));
      const t = document.elementFromPoint(x, y);
      t.dispatchEvent(new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer: dt, clientX: x, clientY: y }));
      t.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt, clientX: x, clientY: y }));
      grip.dispatchEvent(new DragEvent('dragend', { bubbles: true, dataTransfer: dt }));
    }""", [head["x"] + 200, head["y"] + head["height"] / 2])
    page.wait_for_timeout(900)
    tail = body().split("## Shared subject")[1]
    assert tail.count("{{flex:text") == 2 and tail.index("seg=4") < tail.index("seg=1"), body()   # appended to the group
    assert "2 examples" in page.locator("#collection .coll-group").inner_text()
    # expand, rename by double-click
    page.locator("[data-test='coll-toggle']").click()
    page.locator("#collection .coll-group-label").dblclick()
    page.keyboard.press("Control+a")
    page.keyboard.type("Same subject")
    page.keyboard.press("Enter")
    page.wait_for_timeout(900)
    assert "## Same subject\n" in body() and "{collapsed}" not in body(), body()
    # the export carries the note, on the example's first line; the group is not exported
    items = page.evaluate("() => window.__fsCollection.flextextItems()")
    assert [i["seg"] for i in items] == [[2, 2], [4, 4], [1, 1]] and items[0]["note"] == "Both verbs share the subject."
    out = str(h.tmp / "groups.flextext")
    page.evaluate("""async ([items, out]) => { const cols = await window.pywebview.api.list_collections();
      return await window.pywebview.api.export_note_flextext(cols[0].id, items, { title: 'SVC sorting', sourceNotes: false, audio: 'none' }, out); }""", [items, out])
    import xml.etree.ElementTree as ET
    root = ET.parse(out).getroot()
    assert "Same subject" not in ET.tostring(root, encoding="unicode")
    first = root.findall(".//phrase")[0]
    assert [i.text for i in first.findall("item[@type='note']")] == ["Both verbs share the subject."]
    # one button closes every group, then opens them again
    page.locator("[data-test='coll-all']", has_text="Collapse all").click()
    page.wait_for_timeout(900)
    assert "## Same subject {collapsed}" in body() and page.locator("#collection .coll-item").count() == 1
    page.locator("[data-test='coll-all']", has_text="Expand all").click()
    page.wait_for_timeout(900)
    assert "{collapsed}" not in body()
    # removing the group keeps its examples; Undo brings the heading back
    page.locator("#collection .coll-group").hover()
    page.locator("[data-test='coll-ungroup']").click()
    page.wait_for_timeout(900)
    assert "## Same subject" not in body() and body().count("{{flex:text") == 3
    page.locator("#collection .coll-undo button", has_text="Undo").click()
    page.wait_for_timeout(900)
    assert "## Same subject" in body()
    assert not errors


def test_drag_select_part_of_a_free_translation_and_highlight_it(app):
    """Seth, 2026-10-16: "I'd like to be able to drag select part of the free translation and
    highlight the selection" — in any colour, not only by typing into "match text"."""
    h, page, errors = app
    new_note(page, "Free")
    page.keyboard.type("{{flex:text %s seg=2}}" % T_STORY)
    page.keyboard.press("Enter")
    page.wait_for_selector("#editor .text-obj .seg-free")
    page.wait_for_timeout(600)
    # the screen positions of "the child" in "Yesterday the child saw the river."
    pts = page.evaluate("""() => {
      const d = document.querySelector('#editor .seg-free'); const node = d.firstChild;
      const t = node.textContent, a = t.indexOf('the child'), b = a + 'the child'.length;
      const r = document.createRange();
      r.setStart(node, a); r.setEnd(node, a + 1); const ra = r.getBoundingClientRect();
      r.setStart(node, b - 1); r.setEnd(node, b); const rb = r.getBoundingClientRect();
      return [ra.left + 1, ra.top + ra.height / 2, rb.right - 1, rb.top + rb.height / 2];
    }""")
    page.mouse.move(pts[0], pts[1])
    page.mouse.down()
    page.mouse.move((pts[0] + pts[2]) / 2, pts[1])
    page.mouse.move(pts[2], pts[3])
    page.mouse.up()
    page.wait_for_selector(".popover")
    assert "“the child”" in page.locator(".popover").inner_text()
    # a green highlight, not the default
    page.locator(".popover button.sw[title='#caffbf']").click()
    page.wait_for_timeout(900)
    assert re.search(r"hl\[#caffbf\]=ft:2:11-19", body_of(h)), body_of(h)
    span = page.locator("#editor .seg-free span.st-hl")
    assert span.inner_text() == "the child" and "202, 255, 191" in span.evaluate("(e) => getComputedStyle(e).backgroundColor")
    page.keyboard.press("Escape")
    # "match text" takes any colour too: type the match, then pick a swatch
    page.locator("#editor .seg-free").click()
    page.wait_for_selector(".popover")
    page.locator(".popover input[placeholder^='match text']").fill("river")
    page.locator(".popover button.sw[title='#bdb2ff']").click()
    page.wait_for_timeout(900)
    assert 'hl[#bdb2ff]=ft:"river"' in body_of(h), body_of(h)
    assert not errors


def test_collect_examples_from_a_highlighted_part_or_the_whole_note(app):
    """Seth, 2026-10-16: "Collect examples into a new collection…" on "a highlighted PART of a note
    (for all FLEx objects within that highlight) OR a whole document (if nothing … selected)"."""
    h, page, errors = app
    new_note(page, "Mixed")
    page.locator("#editor .blk-body").first.click()
    paste(page, "Intro with {{flex:entry 6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0001}} and {{flex:text %s seg=1}} inline.\n\n"
                "{{flex:text %s seg=2}}\n\n{{flex:text %s seg=4}}\n\nOutro." % (T_STORY, T_STORY, T_STORY))
    page.wait_for_function("document.querySelectorAll('#editor .blk-flex .text-obj').length === 2")
    page.wait_for_timeout(900)
    def collect(expect_label):
        page.locator("#btn-note-menu").click()
        item = page.locator(".popover .menu-item", has_text="Collect the")
        assert expect_label in item.inner_text(), item.inner_text()
        item.click()
        page.wait_for_selector("#collection .coll-item")
        page.wait_for_timeout(900)
        cols = h.api.list_collections()
        body = h.api.get_note(cols[0]["id"])["body"]
        page.locator(".note-card").filter(has=page.locator(".t", has_text=re.compile(r"^Mixed$"))).click()
        page.wait_for_selector("#editor .blk-flex .text-obj")
        page.wait_for_timeout(500)
        return sorted(int(m) for m in re.findall(r"seg=(\d+)", body))
    # a selection inside the first paragraph: its inline example only (the entry is not one)
    page.evaluate("""() => { const body = document.querySelector('#editor .blk-body'); const r = document.createRange();
      r.selectNodeContents(body); const s = window.getSelection(); s.removeAllRanges(); s.addRange(r); }""")
    assert collect("1 selected example") == [1]
    # a selection across blocks: from the end of the first paragraph to the second block example
    page.locator("#editor .blk-body").first.click()
    page.keyboard.press("End")
    page.locator("#editor .blk-flex").nth(1).click(modifiers=["Shift"])
    page.wait_for_function("!!window.__fsEditor.msel")
    assert collect("2 selected examples") == [2, 4]
    # nothing highlighted: the whole note, entry left out
    page.locator("#editor .blk-body", has_text="Outro").click()
    assert collect("Collect the examples into a new collection") == [1, 2, 4]
    assert not errors


def test_a_pasted_line_lands_on_its_own_segment_even_when_numbering_differs(app):
    """Seth, 2026-10-16: "The Paste TSV dialog box … shows the correct line number. But then the
    flex object that's created selects the wrong number(s)" — two lines above. The locator's
    index and the rendered text can number segments differently, so the embed now carries the
    located segments' own GUIDs (at=), which win over the number when the example is drawn."""
    h, page, errors = app
    be = h.api._flex.backend
    real = be.all_baselines
    # an index whose running numbers are two behind the text (as if it had skipped two segments)
    def shifted():
        out = {}
        for g, t in real().items():
            rows = t["segments"]
            out[g] = dict(t, segments=[(r[0] - 2,) + tuple(r[1:]) for r in rows[2:]] if g == T_STORY else rows)
        return out
    be.all_baselines = shifted
    try:
        new_note(page, "Numbering")
        paste(page, "2.2\tWord\tKabir\tpemu\tka-nuwa\tlo\nFree\tThe dog sleeps by the river.")
        page.wait_for_selector(".modal")
        assert "segment 2.2" in page.locator("[data-test='locate-where']").inner_text()   # FLEx's number
        page.locator(".modal .btn.primary", has_text="Insert rendered").click()
        page.wait_for_selector("#editor .text-obj .segment")
        page.wait_for_timeout(1200)
        shown = page.locator("#editor .text-obj .segment").evaluate_all("(els) => els.map((e) => e.dataset.n)")
        assert shown == ["4"], shown
        body = body_of(h)
        assert re.search(r"seg=4 at=0e1f2a3b1004\b", body), body                         # number healed, GUID kept
    finally:
        be.all_baselines = real
    assert not errors


def test_insert_a_new_block_from_the_context_menu(app):
    """Seth, 2026-10-16: "the ability to insert a new block in a note (like list, text, heading …).
    This is especially useful after examples or tables … I think the context menu is a good place"."""
    h, page, errors = app
    new_note(page, "Blocks")
    page.locator("#editor .blk-body").first.click()
    paste(page, "Intro.\n\n{{flex:text %s seg=1}}\n\n| A | B |\n|---|---|\n| a | b |\n\nEnd." % T_STORY)
    page.wait_for_selector("#editor .blk-flex .text-obj")
    page.wait_for_selector("table.md-table")
    # right-click the example: a heading below it, the caret in it
    page.locator("#editor .blk-flex .seg-free").first.click(button="right")
    page.locator(".popover [data-ins-kind='h'][data-ins-where='after']").click()
    page.keyboard.type("Analysis")
    page.wait_for_timeout(900)
    b = body_of(h)
    assert re.search(r"seg=1[^}]*\}\}\n\n## Analysis\n\n\| A \| B \|", b), b
    # the table's own cell menu ends with the same section: a paragraph below the table
    page.locator("table.md-table td[data-r='1'][data-c='0']").click(button="right")
    page.locator(".popover [data-ins-kind='p'][data-ins-where='after']").click()
    page.keyboard.type("After the table.")
    page.wait_for_timeout(900)
    b = body_of(h)
    assert re.search(r"\| a \| b \|\n\nAfter the table\.\n\nEnd\.", b), b
    # the ⋮ block menu: a numbered list above the closing paragraph
    page.locator("#editor .blk", has_text="End.").hover()
    page.locator("#editor .blk", has_text="End.").locator(".blk-handle button[data-test=blk-grip]").dispatch_event("mousedown")
    page.locator(".popover [data-ins-kind='ol'][data-ins-where='before']").click()
    page.keyboard.type("first")
    page.wait_for_timeout(900)
    assert "1. first\n\nEnd." in body_of(h), body_of(h)
    # right-click inside running text keeps the browser's menu (spelling, copy, paste)
    page.locator("#editor .blk-body", has_text="Intro.").click(button="right")
    assert page.locator(".popover [data-ins-kind]").count() == 0
    # "FLEx example" opens the picker for the new spot
    page.locator("#editor .blk-flex .seg-free").first.click(button="right")
    page.locator(".popover [data-ins-kind='flex'][data-ins-where='before']").click()
    page.wait_for_selector(".modal", timeout=5000)
    assert "Insert from FieldWorks" in page.locator(".modal").inner_text()
    page.keyboard.press("Escape")
    assert not errors


def test_refresh_in_a_collection_takes_in_changes_saved_in_flex(app):
    """Seth, 2026-10-16: "I fixed a source and then tried reloading it with the refresh button in
    an example in a collections note and it doesn't appear to be registering the refresh". The
    ↻ re-read the backend's in-memory copy; FieldWorks only shows what it saved after a
    RefreshFromDisk — which "Refresh all" did, and a collection had no Refresh all."""
    h, page, errors = app
    be = h.api._flex.backend
    seg1 = be.texts[T_STORY]["segments"][0]
    original = seg1["free"]
    pending, calls = {}, []

    def refresh(indexes=True):          # like LCM: a change saved in FLEx shows only after this
        calls.append(indexes)
        if "free" in pending:
            seg1["free"] = pending.pop("free")
    be.refresh = refresh
    try:
        page.locator("#btn-new-menu").click()
        page.locator("[data-test='new-collection']").click()
        page.wait_for_selector("#collection .coll-add")
        page.locator("#collection .coll-add").click()
        paste(page, "{{flex:text %s seg=1}}" % T_STORY)
        page.wait_for_selector("#collection .seg-free")
        # "fixed in FLEx": the ↻ on the example shows it
        pending["free"] = "The dog slept soundly."
        page.locator("#collection .flex-head button[title='Reload from FLEx']").first.click()
        page.wait_for_function("document.querySelector('#collection .seg-free') && document.querySelector('#collection .seg-free').textContent.includes('soundly')")
        assert calls == [False]                       # the indexes are kept for one example
        # and the collection's own Refresh all
        pending["free"] = "The dog slept very soundly."
        page.locator("[data-test='coll-refresh']").click()
        page.wait_for_function("document.querySelector('#collection .seg-free') && document.querySelector('#collection .seg-free').textContent.includes('very soundly')")
        assert calls[-1] is True
    finally:
        seg1["free"] = original
        del be.refresh
    assert not errors


def test_a_folder_lists_its_own_notes_unless_subfolders_are_shown(app):
    """Seth, 2026-10-16: "it's VERY cluttery if every parent folder shows ALL daughter notes. If a
    note is in a sub-folder, I'd like it to not show up in the parent folder, or maybe give me a
    checkbox to show or hide the whole tree"."""
    h, page, errors = app
    tab = h.api.init()["config"]["tabs"][0]["dir"]
    h.api.create_folder(tab, "Week One")
    h.api.create_folder(tab, "Week One/Tuesday")
    h.api.create_folder(tab, "Empty parent")
    h.api.create_folder(tab, "Empty parent/Child")
    h.api.create_note(tab, "Week One", "Overview", "plan #week")
    h.api.create_note(tab, "Week One/Tuesday", "Morning SVCs", "svc #week")
    h.api.create_note(tab, "Empty parent/Child", "Deep note", "deep")
    page.reload()
    page.wait_for_selector(".folder-item")
    titles = lambda: page.locator("#notes .note-card .t").all_inner_texts()   # noqa: E731
    # the tab itself: only its top-level notes (the Welcome note), no daughter notes
    assert not any("Overview" in t or "Morning SVCs" in t for t in titles()), titles()
    page.locator(".folder-item[data-path='Week One']").click()
    page.wait_for_timeout(300)
    assert [t.strip() for t in titles()] == ["Overview"], titles()
    # the checkbox shows the whole tree, with where each daughter note lives
    page.locator("#chk-subfolders").check()
    assert sorted(t.strip() for t in titles()) == ["Morning SVCs", "Overview"], titles()
    assert "Tuesday" in page.locator("#notes .note-card", has_text="Morning SVCs").locator(".sub-loc").inner_text()
    # remembered on this computer
    page.reload()
    page.wait_for_selector(".folder-item")
    page.locator(".folder-item[data-path='Week One']").click()
    page.wait_for_timeout(300)
    assert page.locator("#chk-subfolders").is_checked() and len(titles()) == 2
    page.locator("#chk-subfolders").uncheck()
    # a folder with notes only below it says so, and offers them
    page.locator(".folder-item[data-path='Empty parent']").click()
    page.wait_for_selector("[data-test='show-below']")
    assert "1 note" in page.locator("[data-test='show-below']").inner_text()
    page.locator("[data-test='show-below']").click()
    assert [t.strip() for t in titles()] == ["Deep note"]
    page.locator("#chk-subfolders").uncheck()
    # a folder without subfolders has no checkbox
    page.locator(".folder-item[data-path='Week One'] .chev").click()
    page.locator(".folder-item[data-path='Week One/Tuesday']").click()
    page.wait_for_timeout(300)
    assert page.locator("#list-subfolders").is_hidden()
    assert not errors


def test_headings_have_levels_and_fold_their_sections(app):
    """Seth, 2026-10-16: "multiple levels of headings, and for those headings to be collapsible
    (with material between that heading and the NEXT heading of the same or higher level)"."""
    h, page, errors = app
    new_note(page, "Folding")
    page.locator("#editor .blk-body").first.click()
    paste(page, "# Chapter\n\nintro\n\n## Part A\n\na text\n\n### Deep\n\ndeep text\n\n## Part B\n\nb text\n\n# Next\n\nlast")
    page.wait_for_timeout(300)
    blk = lambda t: page.locator("#editor .blk", has=page.locator(".blk-body", has_text=t)).first   # noqa: E731
    visible = lambda t: blk(t).is_visible()                                                        # noqa: E731
    # close "## Part A": it hides "a text", "### Deep" and "deep text" — "## Part B" ends it
    blk("Part A").hover()
    blk("Part A").locator(".fold-tog").dispatch_event("mousedown")
    page.wait_for_timeout(100)
    assert not visible("a text") and not visible("deep text") and not visible("Deep")
    assert visible("Part B") and visible("b text") and visible("intro")
    assert blk("Part A").locator(".fold-more").inner_text() == "⋯ 3 blocks"
    page.wait_for_timeout(900)
    body = body_of(h)
    assert "## Part A {collapsed}\n\na text" in body, body
    # the marker is never text in the editor
    assert blk("Part A").locator(".blk-body").inner_text() == "## Part A"
    # Enter at the end of the closed heading starts the next heading of its level after the section
    blk("Part A").locator(".blk-body").click()
    page.keyboard.press("End")
    page.keyboard.press("Enter")
    page.keyboard.type("Part A2")
    page.wait_for_timeout(900)
    assert "deep text\n\n## Part A2\n\n## Part B" in body_of(h), body_of(h)
    # ArrowUp from it steps onto the closed heading, not into its hidden blocks
    page.keyboard.press("Home")
    page.keyboard.press("ArrowUp")
    assert page.evaluate("() => document.activeElement.textContent") == "## Part A"
    # closing the chapter hides everything up to "# Next"
    blk("Chapter").hover()
    blk("Chapter").locator(".fold-tog").dispatch_event("mousedown")
    page.wait_for_timeout(100)
    assert not visible("intro") and not visible("Part B") and not visible("b text") and visible("Next") and visible("last")
    # reopened, the folds are still there
    page.reload()
    page.wait_for_selector(".note-card")
    page.locator(".note-card", has_text="Folding").click()
    page.wait_for_selector("#editor .blk-h")
    assert not visible("intro") and visible("Next")
    # the toolbar's H menu: expand all, then change a level (Ctrl+Alt+N does the same)
    page.locator("[data-test=tb-heading]").dispatch_event("mousedown")
    page.locator("[data-test=unfold-all]").dispatch_event("mousedown")
    page.wait_for_timeout(100)
    assert visible("intro") and visible("deep text")
    blk("b text").locator(".blk-body").click()
    page.locator("[data-test=tb-heading]").dispatch_event("mousedown")
    page.locator("[data-test=heading-3]").dispatch_event("mousedown")
    page.wait_for_timeout(100)
    blk("intro").locator(".blk-body").click()
    page.keyboard.press("Control+Alt+4")
    page.wait_for_timeout(900)
    body = body_of(h)
    assert "### b text" in body and "#### intro" in body and "{collapsed}" not in body, body
    # the block menu of a heading offers its levels and the folds
    blk("Part B").hover()
    blk("Part B").locator(".blk-handle button").dispatch_event("mousedown")
    page.locator("[data-test=heading-levels] .tog", has_text="H1").click()
    page.wait_for_timeout(900)
    assert "\n# Part B\n" in body_of(h), body_of(h)
    # the excerpt never shows a fold marker
    blk("Next").hover()
    blk("Next").locator(".fold-tog").dispatch_event("mousedown")
    page.wait_for_timeout(900)
    assert "# Next {collapsed}" in body_of(h)
    assert "collapsed" not in page.locator(".note-card", has_text="Folding").inner_text()
    assert not errors


def test_sticky_headings_follow_the_view_and_fold_in_place(app):
    """Seth, 2026-10-17: "make whatever headings apply to the current viewport be sticky (optionally,
    give the user the ability to turn this feature on and off)"; "they can collapse the sticky heading
    even if they're not scrolled up to the top, in place"; "When they do collapse a sticky heading,
    scroll to that heading, instead of skipping ahead or going to the start or end of the note"."""
    h, page, errors = app
    new_note(page, "Sticky")
    page.locator("#editor .blk-body").first.click()
    filler = lambda tag, n: "\n\n".join("%s paragraph %d, long enough to take a line of its own." % (tag, k) for k in range(n))   # noqa: E731
    paste(page, "# Chapter\n\nintro\n\n## Part A\n\n" + filler("A", 14) + "\n\n### Deep\n\n" + filler("deep", 14) + "\n\n## Part B\n\n" + filler("B", 14) + "\n\n# Next\n\nlast")
    page.wait_for_timeout(300)
    blk = lambda t: page.locator("#editor .blk", has=page.locator(".blk-body", has_text=t)).first   # noqa: E731
    strip = page.locator("#sticky-heads")
    rows = lambda: page.evaluate("() => [...document.querySelectorAll('#sticky-heads .sh-title')].map((x) => x.textContent.trim())")   # noqa: E731
    top_of = lambda t: page.evaluate("(t) => { const b = [...document.querySelectorAll('#editor .blk-body')].find((x) => x.textContent.includes(t)); return b.getBoundingClientRect().top - document.getElementById('editor').getBoundingClientRect().top; }", t)   # noqa: E731
    # at the top nothing is stuck; scrolled into "### Deep", the chain Chapter › Part A › Deep is
    page.evaluate("() => { document.getElementById('editor').scrollTop = 0; }")
    page.wait_for_timeout(200)
    assert strip.is_hidden()
    page.evaluate("() => { const t = [...document.querySelectorAll('#editor .blk-body')].find((x) => x.textContent === 'deep paragraph 6, long enough to take a line of its own.'); t.scrollIntoView({ block: 'start' }); }")
    page.wait_for_timeout(200)
    assert rows() == ["Chapter", "Part A", "Deep"], rows()
    # the strip never covers a block it names: the first block under it is a "deep" paragraph
    assert page.evaluate("() => { const s = document.getElementById('sticky-heads').getBoundingClientRect(); const e = document.getElementById('editor').getBoundingClientRect(); return s.top === e.top && s.width === e.width; }")
    # fold "Part A" from the strip: its section closes in place and the view moves to that heading,
    # under the "Chapter" row (not to the start or the end of the note)
    strip.locator(".sh-fold").nth(1).dispatch_event("mousedown")
    page.wait_for_timeout(250)
    assert not blk("deep paragraph 6").is_visible() and not blk("Deep").is_visible()
    assert blk("Part A").locator(".fold-more").inner_text() == "⋯ 29 blocks"
    assert rows() == ["Chapter"], rows()
    strip_h = strip.bounding_box()["height"]
    assert abs(top_of("## Part A") - strip_h) < 6, (top_of("## Part A"), strip_h)
    page.wait_for_timeout(900)
    assert "## Part A {collapsed}\n\nA paragraph 0" in body_of(h)
    # a click on a sticky title goes to that heading
    page.evaluate("() => { const t = [...document.querySelectorAll('#editor .blk-body')].find((x) => x.textContent === 'B paragraph 9, long enough to take a line of its own.'); t.scrollIntoView({ block: 'start' }); }")
    page.wait_for_timeout(200)
    assert rows() == ["Chapter", "Part B"], rows()
    strip.locator(".sh-title").first.dispatch_event("mousedown")
    page.wait_for_timeout(250)
    assert strip.is_hidden() and page.evaluate("() => document.getElementById('editor').scrollTop") == 0   # the first block: the top of the note
    # off in the H ▾ menu: no strip, remembered in the settings; on again from Settings
    page.evaluate("() => { const t = [...document.querySelectorAll('#editor .blk-body')].find((x) => x.textContent === 'B paragraph 9, long enough to take a line of its own.'); t.scrollIntoView({ block: 'start' }); }")
    page.wait_for_timeout(200)
    assert rows() == ["Chapter", "Part B"]
    page.locator("[data-test=tb-heading]").dispatch_event("mousedown")
    page.locator("[data-test=sticky-toggle]").dispatch_event("mousedown")
    page.wait_for_timeout(200)
    assert strip.is_hidden()
    assert h.api._nb.config["settings"]["stickyHeadings"] is False
    page.click("#btn-settings")
    page.locator("[data-test=setting-sticky]").check()
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    assert rows() == ["Chapter", "Part B"], rows()
    assert not errors


def test_collection_groups_nest_by_level_and_fold(app):
    """Seth, 2026-10-16: collapsible headings of several levels in a collection too; they
    organise the view and are never exported."""
    h, page, errors = app
    page.locator("#btn-new-menu").click()
    page.locator("[data-test='new-collection']").click()
    page.wait_for_selector("#collection .coll-add")
    page.locator("#note-title").fill("Chaining")
    for seg in (1, 2, 4):
        page.locator("#collection .coll-add").click()
        paste(page, "{{flex:text %s seg=%d}}" % (T_STORY, seg))
    page.wait_for_function("document.querySelectorAll('#collection .coll-item').length === 3")
    cid = h.api.list_collections()[0]["id"]
    body = lambda: h.api.get_note(cid)["body"]   # noqa: E731
    # "Chaining" before the first example, "Same subject" before the second, then make it a sub-group
    for label, at in (("Chaining", 0), ("Same subject", 1)):
        page.once("dialog", lambda d, label=label: d.accept(label))
        page.locator("[data-test='coll-add-group']").click()
        page.wait_for_timeout(200)
    page.wait_for_timeout(900)
    # added at the end; move them into place with the API-backed view to keep the test short
    page.evaluate("""() => { const c = window.__fsCollection; const it = c.items;
        const g1 = it.findIndex((x) => x.label === 'Chaining'); const a = it.splice(g1, 1)[0]; it.splice(0, 0, a);
        const g2 = it.findIndex((x) => x.label === 'Same subject'); const b = it.splice(g2, 1)[0]; it.splice(2, 0, b);
        c.changed(); c.render(); }""")
    page.wait_for_timeout(200)
    group = lambda t: page.locator("#collection .coll-group", has_text=t)   # noqa: E731
    group("Same subject").hover()
    group("Same subject").locator("[data-test='coll-indent']").click()     # ## → ###, inside "Chaining"
    page.wait_for_timeout(900)
    assert body().startswith("## Chaining\n\n{{flex:text") and "\n### Same subject\n" in body(), body()
    assert "2 examples" in group("Same subject").inner_text() and "3 examples" in group("Chaining").inner_text()
    # closing the sub-group hides its two examples, closing the parent hides the sub-group too
    group("Same subject").locator("[data-test='coll-toggle']").click()
    assert page.locator("#collection .coll-item").count() == 1
    group("Chaining").locator("[data-test='coll-toggle']").click()
    assert page.locator("#collection .coll-item").count() == 0 and group("Same subject").count() == 0
    page.wait_for_timeout(900)
    assert "## Chaining {collapsed}" in body() and "### Same subject {collapsed}" in body(), body()
    # numbering still runs straight through, and the export has every example and no headings
    out = h.tmp / "chaining.flextext"
    r = h.api.export_note_flextext(cid, page.evaluate("() => window.__fsCollection.flextextItems()"), {"title": "Chaining", "audio": "none"}, str(out))
    assert r["examples"] == 3
    xml = out.read_text(encoding="utf-8")
    assert "Same subject" not in xml and "Chaining" in xml        # the title only
    assert not errors


def test_move_copy_and_drag_several_blocks_in_a_note(app):
    """Seth, 2026-10-16: "select and move/copy/cut/etc multiple blocks at a time (including FLEx
    objects) both within a note and within an example collection"."""
    h, page, errors = app
    new_note(page, "Blocks")
    page.locator("#editor .blk-body").first.click()
    paste(page, "Alpha\n\nBravo\n\n{{flex:text %s seg=1}}\n\nCharlie\n\nDelta" % T_STORY)
    page.wait_for_selector("#editor .blk-flex .text-obj")
    page.wait_for_timeout(300)
    order = lambda: [x.split(" seg=")[0][:12] if x.startswith("{{") else x for x in body_of(h).strip().split("\n\n")]   # noqa: E731
    # select Alpha … the example (Shift+click), then Alt+Shift+Down moves all three below Charlie
    page.locator("#editor .blk-body", has_text="Alpha").click()
    page.keyboard.press("Home")
    page.locator("#editor .blk-flex").click(modifiers=["Shift"], position={"x": 30, "y": 8})
    page.wait_for_function("!!window.__fsEditor.msel")
    page.keyboard.press("Alt+Shift+ArrowDown")
    page.wait_for_timeout(900)
    assert order() == ["Charlie", "Alpha", "Bravo", "{{flex:text ", "Delta"], order()
    assert page.locator("#editor .msel-block").count() >= 2                        # still selected: move again
    page.keyboard.press("Alt+Shift+ArrowUp")
    page.wait_for_timeout(900)
    assert order() == ["Alpha", "Bravo", "{{flex:text ", "Charlie", "Delta"], order()
    # the ⋮ menu of a selected block acts on all of them
    page.locator("#editor .blk-p", has_text="Bravo").hover()
    page.locator("#editor .blk-p", has_text="Bravo").locator(".blk-handle button").dispatch_event("mousedown")
    assert page.locator("[data-test=blocks-label]").inner_text() == "3 blocks selected"
    page.locator(".popover .menu-item", has_text="Duplicate").click()
    page.wait_for_timeout(900)
    assert order() == ["Alpha", "Bravo", "{{flex:text ", "Alpha", "Bravo", "{{flex:text ", "Charlie", "Delta"], order()
    page.keyboard.press("Escape")
    page.locator("#editor .blk-p", has_text="Delta").hover()
    page.locator("#editor .blk-p", has_text="Delta").locator(".blk-handle button").dispatch_event("mousedown")
    page.locator(".popover .menu-item", has_text="Delete block").click()
    page.wait_for_timeout(900)
    # dragging a block by ⋮: Charlie onto the top half of the first Alpha
    n = page.locator("#editor > .blk").count()
    charlie = [i for i in range(n) if page.locator("#editor > .blk").nth(i).inner_text().strip().endswith("Charlie")][0]
    box = page.locator("#editor .blk-p", has_text="Alpha").first.bounding_box()
    dnd(page, "#editor > .blk:nth-child(%d) .blk-handle button" % (charlie + 1), box["x"] + 40, box["y"] + 3)
    assert order()[0] == "Charlie", order()
    # with a selection, the drag takes every selected block (the example too); Ctrl copies
    page.locator("#editor .blk-body", has_text="Bravo").first.click()
    page.keyboard.press("Home")
    page.locator("#editor .blk-flex").first.click(modifiers=["Shift"], position={"x": 30, "y": 8})
    page.wait_for_function("!!window.__fsEditor.msel")
    last = page.locator("#editor > .blk").last.bounding_box()
    dnd(page, "#editor .blk-flex .blk-handle button", last["x"] + 40, last["y"] + last["height"] - 3)
    assert order() == ["Charlie", "Alpha", "Alpha", "Bravo", "{{flex:text ", "Bravo", "{{flex:text "], order()
    assert not errors


def test_select_and_move_several_items_in_a_collection(app):
    h, page, errors = app
    page.locator("#btn-new-menu").click()
    page.locator("[data-test='new-collection']").click()
    page.wait_for_selector("#collection .coll-add")
    page.locator("#note-title").fill("Sorting")
    for seg in (1, 2, 4):
        page.locator("#collection .coll-add").click()
        paste(page, "{{flex:text %s seg=%d}}" % (T_STORY, seg))
    page.once("dialog", lambda d: d.accept("Later"))
    page.locator("[data-test='coll-add-group']").click()
    page.wait_for_function("document.querySelectorAll('#collection .coll-item').length === 3 && document.querySelector('#collection .coll-group')")
    cid = h.api.list_collections()[0]["id"]

    def order():
        page.wait_for_timeout(900)
        out = []
        for line in h.api.get_note(cid)["body"].split("\n"):
            m = re.search(r"seg=(\d+)", line)
            if m:
                out.append(int(m.group(1)))
            elif line.startswith("#"):
                out.append(line.lstrip("# "))
        return out
    items = page.locator("#collection .coll-item")
    items.nth(0).hover()
    items.nth(0).locator("[data-test=coll-check]").click()
    items.nth(1).hover()
    items.nth(1).locator("[data-test=coll-check]").click(modifiers=["Shift"])
    assert "2 items selected" in page.locator("[data-test=coll-selbar]").inner_text()
    page.keyboard.press("Alt+Shift+ArrowDown")
    assert order() == [4, 1, 2, "Later"], order()
    # into the group, then copy and paste after the selection
    page.locator("[data-test=coll-into]").select_option(label="Later")
    assert order() == [4, "Later", 1, 2], order()
    page.locator("[data-test=coll-sel-copy]").click()
    page.locator("[data-test=coll-sel-paste]").click()
    assert order() == [4, "Later", 1, 2, 1, 2], order()
    # the pasted copies are the selection now; Delete removes them, Undo brings them back
    page.keyboard.press("Delete")
    assert order() == [4, "Later", 1, 2], order()
    page.locator(".coll-undo button", has_text="Undo").click()
    assert order() == [4, "Later", 1, 2, 1, 2], order()
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)
    # Ctrl+A selects everything; dragging a selected card moves them all (here: nowhere new)
    page.locator("#collection .coll-head").click(position={"x": 5, "y": 5})
    page.keyboard.press("Control+a")
    assert "items selected" in page.locator("[data-test=coll-selbar]").inner_text()
    page.keyboard.press("Escape")
    # select the last two, drag them by a grip to the top
    items = page.locator("#collection .coll-item")
    for k in (3, 4):
        items.nth(k).hover()
        items.nth(k).locator("[data-test=coll-check]").click(modifiers=["Shift"] if k == 4 else [])
    items.nth(0).scroll_into_view_if_needed()
    top = items.nth(0).bounding_box()
    page.evaluate("""([x, y]) => {
      const dt = new DataTransfer();
      const s = document.querySelectorAll('#collection .coll-item')[3].querySelector('.coll-grip');
      s.dispatchEvent(new DragEvent('dragstart', { bubbles: true, cancelable: true, dataTransfer: dt }));
      const t = document.elementFromPoint(x, y);
      t.dispatchEvent(new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer: dt, clientX: x, clientY: y }));
      t.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt, clientX: x, clientY: y }));
      s.dispatchEvent(new DragEvent('dragend', { bubbles: true, dataTransfer: dt }));
    }""", [top["x"] + 60, top["y"] + 4])
    assert order() == [1, 2, 4, "Later", 1, 2], order()
    assert not errors


def window_last(info):
    return info[2][-1].split(":", 1)[1]


def test_the_view_stays_put_on_a_click_beside_a_table_and_on_table_tools(app):
    """Seth, 2026-10-16: "if I click outside the table, it scrolls to the same position, but
    deselects the cell/table … I don't want the scroll jumping to the end of the document after
    edits or de-select/focus change" — "When I add rows or columns … it jumps to the bottom"."""
    h, page, errors = app
    new_note(page, "Tall")
    page.locator("#editor .blk-body").first.click()
    paras = "\n\n".join(f"Paragraph {i} with some words in it." for i in range(30))
    paste(page, paras + "\n\n| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n\n" + paras.replace("Paragraph", "After"))
    page.wait_for_selector("table.md-table")
    page.wait_for_timeout(900)
    st = lambda: page.evaluate("() => document.getElementById('editor').scrollTop")   # noqa: E731
    page.evaluate("() => document.querySelector('table.md-table').scrollIntoView({block: 'center'})")
    page.wait_for_timeout(200)
    s0 = st()
    # a cell open, then a click on the background beside the table: the cell closes, the view stays
    page.locator("table.md-table td").first.click()
    page.keyboard.type("x")
    tb = page.locator("table.md-table").bounding_box()
    ed = page.locator("#editor").bounding_box()
    page.mouse.click(ed["x"] + ed["width"] - 14, tb["y"] + tb["height"] / 2)
    page.wait_for_timeout(300)
    assert abs(st() - s0) <= 2, (s0, st())
    assert page.locator("table.md-table .cell-edit").count() == 0                     # deselected
    page.wait_for_timeout(700)
    assert "| 1x |" in body_of(h) or "| x1 |" in body_of(h), body_of(h)
    # a press on a tool whose release lands on the background (the table redrew under it) is
    # not a background click
    page.locator("table.md-table").hover()
    page.locator("table.md-table").dispatch_event("mousedown")
    btn = page.locator(".tbl-tools").first.locator("button", has_text="+ Row")
    b = btn.bounding_box()
    page.mouse.move(b["x"] + 5, b["y"] + 5)
    page.mouse.down()
    page.mouse.move(ed["x"] + ed["width"] - 14, b["y"] + 5)
    page.mouse.up()
    page.wait_for_timeout(300)
    assert abs(st() - s0) <= 2, (s0, st())
    for label in ("+ Row", "+ Column"):
        page.locator("table.md-table").hover()
        page.locator("table.md-table").dispatch_event("mousedown")
        page.locator(".tbl-tools").first.locator("button", has_text=label).click()
        page.wait_for_timeout(300)
        assert abs(st() - s0) <= 2, (label, s0, st())
    # below the last block a click still means "type at the end"
    page.evaluate("() => { const e = document.getElementById('editor'); e.scrollTop = e.scrollHeight; }")
    last = page.locator("#editor > .blk").last.bounding_box()
    page.mouse.click(last["x"] + 40, last["y"] + last["height"] + 40)
    info = page.evaluate("() => [document.activeElement.className, document.activeElement.textContent, window.__fsEditor.blocks.slice(-2).map((b) => b.type + ':' + b.src)]")
    assert info[0] == "blk-body" and info[1] == window_last(info), info
    assert not errors


def test_the_export_dialog_shows_no_stray_null(app):
    """The demo video showed "null" under the title field: Element.append writes a null child
    as text, and the Baseline row is null when every example shares one baseline."""
    h, page, errors = app
    page.locator("#btn-new-menu").click()
    page.locator("[data-test='new-collection']").click()
    page.wait_for_selector("#collection .coll-add")
    page.locator("#collection .coll-add").click()
    paste(page, "{{flex:text %s seg=1}}" % T_STORY)
    page.wait_for_selector("#collection .coll-item")
    page.locator("[data-test='coll-export']").click()
    page.wait_for_selector(".modal")
    assert "null" not in page.locator(".modal").inner_text()
    assert not errors


def test_texts_used_in_a_note_a_selection_a_folder_and_a_collection(app):
    h, page, errors = app
    tab = h.api.init()["config"]["tabs"][0]["dir"]
    h.api.create_folder(tab, "Grammar")
    h.api.create_note(tab, "Grammar", "Chapter", "Intro.\n\n{{flex:text %s seg=1}}\n\n{{flex:text %s seg=2}}\n\nMore.\n\n{{flex:text %s seg=1}}" % (T_STORY, T_STORY, T_ARAB))
    page.reload()
    page.wait_for_selector(".folder-item")
    page.locator(".folder-item[data-path='Grammar']").click()
    page.locator(".note-card", has_text="Chapter").click()
    page.wait_for_selector("#editor .blk-flex .text-obj")
    page.wait_for_timeout(300)
    # the note: two texts, one row each, with FLEx links
    page.locator("#btn-note-menu").click()
    page.locator(".popover .menu-item", has_text="Texts used in this note").click()
    page.wait_for_selector("[data-test=texts-used]")
    titles = page.locator("[data-test=texts-used-title]").all_inner_texts()
    assert titles == ["The dog and the river", "الكلب والنهر"], titles
    assert "2 examples" in page.locator(".texts-used-row").first.inner_text()
    assert page.locator("[data-test=texts-used-title]").first.get_attribute("href").startswith("silfw://")
    page.locator(".modal .btn.primary", has_text="Close").click()
    # a selection that holds only the first example
    page.locator("#editor .blk-body", has_text="Intro.").click()
    page.keyboard.press("Home")
    page.locator("#editor .blk-flex").first.click(modifiers=["Shift"], position={"x": 30, "y": 8})
    page.wait_for_function("!!window.__fsEditor.msel")
    page.locator("#btn-note-menu").dispatch_event("mousedown")
    page.locator("#btn-note-menu").click()
    page.locator(".popover .menu-item", has_text="Texts used in the selection").click()
    page.wait_for_selector("[data-test=texts-used]")
    assert page.locator("[data-test=texts-used-title]").all_inner_texts() == ["The dog and the river"]
    page.locator(".modal .btn.primary", has_text="Close").click()
    # the folder (its subfolders too)
    page.locator(".folder-item[data-path='Grammar']").click(button="right")
    page.locator(".popover .menu-item", has_text="Texts used in this folder").click()
    page.wait_for_selector("[data-test=texts-used]")
    assert len(page.locator("[data-test=texts-used-title]").all_inner_texts()) == 2
    page.locator(".modal .btn.primary", has_text="Close").click()
    # a collection's ticked cards
    page.locator("#btn-new-menu").click()
    page.locator("[data-test='new-collection']").click()
    page.wait_for_selector("#collection .coll-add")
    for src in ("{{flex:text %s seg=1}}" % T_STORY, "{{flex:text %s seg=1}}" % T_ARAB):
        page.locator("#collection .coll-add").click()
        paste(page, src)
    page.wait_for_function("document.querySelectorAll('#collection .coll-item').length === 2")
    page.locator("#collection .coll-item").nth(1).hover()
    page.locator("#collection .coll-item").nth(1).locator("[data-test=coll-check]").click()
    page.locator("[data-test=coll-sel-texts]").click()
    page.wait_for_selector("[data-test=texts-used]")
    assert page.locator("[data-test=texts-used-title]").all_inner_texts() == ["الكلب والنهر"]
    assert not errors


def test_attached_files_open_preview_drop_and_never_start_a_program(app):
    """Seth, 2026-10-17: attachments in notes, as chips that open the file in its own program,
    a web page in a preview (sandboxed: its scripts run, this window is out of its reach) with
    Open in browser; copied into attachments/ by default, linked on request."""
    h, page, errors = app
    opened, shown = [], []
    h.api._open_url = lambda u: opened.append(u) or True
    h.api._reveal = lambda p: shown.append(str(p)) or True
    src = h.tmp / "from-elsewhere"
    src.mkdir()
    (src / "preview ŋa.html").write_text(
        "<!doctype html><meta charset=utf-8><body><p id=a>page</p><script>"
        "document.getElementById('a').textContent='scripts ran';"
        "var r='isolated';try{r=parent.document.title?'REACHED THE APP':'isolated';}catch(e){}"
        "try{if(parent.pywebview)r='REACHED THE API';}catch(e){}"
        "document.body.insertAdjacentHTML('beforeend','<p id=b>'+r+'</p>');</script>", encoding="utf-8")
    (src / "notes.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    (src / "tool.bat").write_text("echo hi", encoding="utf-8")
    html = h.api.attach_paths([str(src / "preview ŋa.html")])[0]
    pdf = h.api.attach_paths([str(src / "notes.pdf")])[0]
    bat = h.api.attach_paths([str(src / "tool.bat")], True)[0]
    assert html["ref"] == "attachments/preview ŋa.html" and bat["linked"]
    tab = h.api.init()["config"]["tabs"][0]["dir"]
    body = "See the {{file attachments/preview%20ŋa.html}} page and {{file " + bat["ref"].replace(" ", "%20") + " \"the tool\"}}.\n\n{{file attachments/notes.pdf}}\n\nEnd."
    h.api.create_note(tab, "", "Field trip", body)
    page.reload()
    page.wait_for_selector(".note-card")
    page.locator(".note-card", has_text="Field trip").click()
    chip = page.locator("#editor .md-embed[data-kind=file]").first
    chip.wait_for()
    assert chip.get_attribute("data-icon") == "🌐" and chip.get_attribute("data-title") == "preview ŋa.html"
    # a web page: the preview, its scripts running, the app out of its reach
    chip.click()
    page.wait_for_selector("[data-test=file-preview] iframe[sandbox]")
    frame = page.frame_locator("[data-test=file-preview] iframe")
    assert frame.locator("#a").inner_text() == "scripts ran"
    assert frame.locator("#b").inner_text() == "isolated"
    page.locator("[data-test=file-open]").click()                # Open in browser = Windows' choice for .html
    page.wait_for_timeout(200)
    assert opened and opened[-1].endswith("preview ŋa.html"), opened
    page.keyboard.press("Escape")
    # a program is never started: the click shows it in its folder
    page.locator("#editor .md-embed[data-kind=file]").nth(1).click()
    page.wait_for_timeout(300)
    assert len(opened) == 1 and shown and shown[-1].endswith("tool.bat"), (opened, shown)
    # the PDF on a line of its own is a card; Open hands it to its program
    card = page.locator("[data-test=file-card]")
    card.wait_for()
    assert "notes.pdf" in card.inner_text()
    card.locator("[data-test=file-open-btn]").click()
    page.wait_for_timeout(200)
    assert opened[-1].endswith("notes.pdf")
    # a web page can be shown IN the note too: the ⋯ menu, saved as `preview`
    page.locator("#editor .blk-body", has_text="End.").click()
    page.keyboard.press("End")
    page.keyboard.press("Enter")
    page.keyboard.type("x ")
    # drop a file from the desktop into that line: copied into attachments/, a chip where it fell
    target = page.locator("#editor .blk-body", has_text="x").last
    box = target.bounding_box()
    page.evaluate("""([x, y]) => {
        const dt = new DataTransfer();
        dt.items.add(new File(['dropped bytes'], 'dropped notes.txt', { type: 'text/plain' }));
        const at = document.elementFromPoint(x, y);
        for (const type of ['dragenter', 'dragover', 'drop']) at.dispatchEvent(new DragEvent(type, { bubbles: true, cancelable: true, clientX: x, clientY: y, dataTransfer: dt }));
    }""", [box["x"] + box["width"] - 4, box["y"] + box["height"] / 2])
    page.wait_for_function("() => [...document.querySelectorAll('#editor .md-embed[data-kind=file]')].some((x) => x.dataset.title === 'dropped notes.txt')", timeout=8000)
    assert (h.api._nb.root / "attachments" / "dropped notes.txt").read_text() == "dropped bytes"
    page.wait_for_timeout(1200)
    assert "{{file attachments/dropped%20notes.txt}}" in body_of(h)
    # a picture dropped below the last block is shown in the note (Seth: "images and videos
    # would also work"), the file copied like any other
    png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    ed = page.locator("#editor").bounding_box()
    page.evaluate("""([b64, x, y]) => {
        const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
        const dt = new DataTransfer();
        dt.items.add(new File([bytes], 'photo 1.png', { type: 'image/png' }));
        const at = document.getElementById('editor');
        for (const type of ['dragover', 'drop']) at.dispatchEvent(new DragEvent(type, { bubbles: true, cancelable: true, clientX: x, clientY: y, dataTransfer: dt }));
    }""", [png, ed["x"] + 40, ed["y"] + ed["height"] - 10])
    page.wait_for_selector("[data-test=file-inline] img.file-img", timeout=8000)
    assert (h.api._nb.root / "attachments" / "photo 1.png").exists()
    page.wait_for_timeout(1200)
    assert "{{file attachments/photo%201.png preview}}" in body_of(h)
    # the HTML page shown inside the note, via the menu of a card
    nid = next(n["id"] for n in h.api.list_notes() if n["title"] == "Field trip")
    h.api.save_note(nid, {"body": "{{file attachments/preview%20ŋa.html}}\n"})
    page.reload()
    page.wait_for_selector(".note-card")
    page.locator(".note-card", has_text="Field trip").click()
    page.locator("[data-test=file-more]").click()
    page.locator("[data-test=file-menu-inline]").click()
    page.wait_for_selector("[data-test=file-inline] iframe[sandbox]")
    assert page.frame_locator("[data-test=file-inline] iframe").locator("#a").inner_text() == "scripts ran"
    page.wait_for_timeout(1200)
    assert "{{file attachments/preview%20ŋa.html preview}}" in body_of(h)
    assert not [e for e in errors if "Failed to load resource" not in e], errors


def test_backup_to_a_sync_folder_and_storage_management(app):
    """Seth, 2026-10-17: back up to a OneDrive / Google Drive / Dropbox folder (or S3 storage), and
    show how much the notebook and its backup take, with cleanup."""
    import base64
    h, page, errors = app
    h.api._secrets = __import__("flex_scratchpad.secrets_store", fromlist=["MemoryStore"]).MemoryStore()
    h.api._backup_obj = None
    h.api._backup.lock_dir = h.tmp / "local"
    h.api.attach_data("orphan.wav", base64.b64encode(b"o" * 2048).decode())
    tab = h.api.init()["config"]["tabs"][0]["dir"]
    n = h.api.create_note(tab, "", "To back up", "Some text.")
    dest = h.tmp / "OneDrive" / "FLEx Scratchpad backup" / "notebook"
    page.reload()
    page.wait_for_selector(".note-card")
    assert page.locator("[data-test=backup-pill]").is_hidden()
    page.locator("#btn-settings, [title='Settings']").first.click()
    page.locator("[data-test=open-backup]").click()
    page.wait_for_selector("[data-test=backup-dialog]")
    assert page.locator("[data-test=bk-kind-folder]").is_checked()
    page.fill("[data-test=bk-folder]", str(dest))
    page.locator("[data-test=bk-now]").click()
    page.wait_for_selector("[data-test=bk-progress].ok", timeout=10000)
    assert (dest / "current" / "notebook.json").exists()
    assert h.api.backup_status()["settings"]["kind"] == "folder"
    assert "Backed up" in page.locator("[data-test=backup-pill]").inner_text()
    # storage: the notebook by kind, and an unused attachment to clear away
    page.wait_for_selector("[data-test=st-unused]")
    assert "This notebook:" in page.locator("[data-test=storage]").inner_text()
    page.locator("[data-test=st-unused]").click()
    page.locator(".popover .btn.danger").click()
    page.wait_for_selector("[data-test=st-trash]")
    assert not (h.api._nb.root / "attachments" / "orphan.wav").exists()
    page.locator("[data-test=st-trash]").click()
    page.locator(".popover .btn.danger").click()
    page.wait_for_function("() => !document.querySelector('[data-test=st-trash]')")
    assert not h.api._nb.trash_dir.exists()
    # a second backup after a change keeps a dated version; it shows with its size and can go
    import time
    time.sleep(1.1)
    h.api.save_note(n["id"], {"body": "Changed text."})
    page.locator("[data-test=bk-now]").click()
    page.wait_for_selector("[data-test=bk-version]", timeout=10000)
    assert page.locator("[data-test=bk-version]").count() >= 1
    page.locator("[data-test=bk-version-check]").first.check()
    page.locator("[data-test=bk-prune]").click()
    page.locator(".popover .btn.danger").click()
    page.wait_for_function("() => !document.querySelector('[data-test=bk-version]')", timeout=10000)
    assert not any((dest / "versions").iterdir())
    assert not [e for e in errors if "Failed to load resource" not in e], errors


def test_an_example_and_its_highlights_follow_their_lines_when_flex_changes_the_text(app):
    """Seth, 2026-10-17: lines added, deleted, merged or split in FLEx must not shift what an
    example shows, nor what its highlights mark."""
    import copy
    h, page, errors = app
    tab = h.api.init()["config"]["tabs"][0]["dir"]
    h.api.create_note(tab, "", "Follows", "{{flex:text %s seg=3-4 hl=3.1 b=4.2}}" % T_STORY)
    page.reload()
    page.wait_for_selector(".note-card")
    page.locator(".note-card", has_text="Follows").click()
    page.wait_for_selector("#editor .blk-flex .text-obj")
    page.wait_for_function("(g) => !!window.__fsEditor && /at=/.test(window.__fsEditor.getMarkdown())", arg=T_STORY)
    page.wait_for_timeout(1200)
    assert " at=" in body_of(h)
    # FLEx: a line added at the top, and the example's last line split in two
    text = h.api._flex.backend.texts[T_STORY]
    segs = text["segments"]
    top = copy.deepcopy(segs[0])
    top.update(guid="9b1c2d3e-4f50-4a6b-8c7d-0e1f2a3b9101", baseline="Ere ka-sila.", words=[{"txt": "Ere"}, {"txt": "ka-sila"}])
    segs.insert(0, top)
    last = next(s for s in segs if s["baseline"] == "Kabir pemu ka-nuwa lo.")
    tail = copy.deepcopy(last)
    last.update(baseline="Kabir pemu.", words=[w for w in last["words"] if w.get("txt") in ("Kabir", "pemu")] + [{"txt": ".", "punct": True}])
    tail.update(guid="9b1c2d3e-4f50-4a6b-8c7d-0e1f2a3b9102", baseline="Ka-nuwa lo.", words=[w for w in tail["words"] if w.get("txt") not in ("Kabir", "pemu")])
    segs.insert(segs.index(last) + 1, tail)
    for n, s in enumerate(segs, 1):
        s["n"] = n
    page.locator("#editor .text-obj button[title='Reload from FLEx']").first.click()
    page.wait_for_function("() => /seg=4-6/.test(window.__fsEditor.getMarkdown())", timeout=8000)
    page.wait_for_timeout(1200)
    body = body_of(h)
    assert "seg=4-6" in body and "hl=4.1" in body and "b=5.2" in body, body
    # and the marks are drawn on the same words as before
    marked = page.locator("#editor .text-obj .st-hl").first.inner_text()
    bold = page.locator("#editor .text-obj .st-b").first.inner_text()
    assert "Ɲamú" in marked and bold == "pemu", (marked, bold)
    assert "ka-nuwa" in page.locator("#editor .text-obj").inner_text()          # the split-off piece is in the example
    assert not [e for e in errors if "Failed to load resource" not in e], errors


def test_backup_progress_bar_finish_and_the_closing_screen(app):
    """Seth, 2026-10-17: a progress bar (percent, time left) when backing up — and when the app
    closes — and a clear word that it has finished."""
    h, page, errors = app
    h.api._secrets = __import__("flex_scratchpad.secrets_store", fromlist=["MemoryStore"]).MemoryStore()
    h.api._backup_obj = None
    h.api._backup.lock_dir = h.tmp / "local"
    h.api.backup_save({"kind": "folder", "folder": str(h.tmp / "OneDrive" / "bk")})
    page.reload()
    page.wait_for_selector("[data-test=backup-pill]:not([hidden])")
    page.locator("[data-test=backup-pill]").click()
    page.wait_for_selector("[data-test=backup-dialog]")
    page.locator("[data-test=bk-now]").click()
    # the finish stays on screen: a full, green bar that says what was done
    page.wait_for_selector("[data-test=bk-progress].ok", timeout=10000)
    done = page.locator("[data-test=bk-progress].ok").inner_text()
    assert "✓ Backed up at" in done and "copied to" in done, done
    # while it runs: the bar follows Python's reports — a stripe until the size is known, then %
    page.evaluate("() => { window.__bar = FS.backup.progressBar(); document.body.appendChild(window.__bar.node); }")
    page.evaluate("() => FS.onEvent({event: 'backup', phase: 'scanning', percent: null})")
    assert "indeterminate" in page.locator("body > [data-test=bk-progress] .bk-track").get_attribute("class")
    page.evaluate("() => FS.onEvent({event: 'backup', phase: 'copying', percent: 42, done: 4404019, total: 10485760, files: 3, filesTotal: 7, eta: 95})")
    label = page.locator("body > [data-test=bk-progress] .bk-progress-label").inner_text()
    assert "42%" in label and "3 of 7 files" in label and "4.2 MB of 10 MB" in label and "about 2 minutes left" in label, label
    assert page.locator("body > [data-test=bk-progress] .bk-track").get_attribute("aria-valuenow") == "42"
    assert "Backing up 42%" in page.locator("[data-test=backup-pill]").inner_text()
    page.evaluate("() => FS.onEvent({event: 'backup', phase: 'done'})")
    page.locator(".modal .modal-head .icon-btn").first.click()
    # closing with a backup due: the window stays, the bar shows, Esc does not dismiss it
    page.evaluate("() => FS.onEvent({event: 'backupClosing', state: 'running'})")
    page.wait_for_selector("[data-test=backup-closing]")
    page.keyboard.press("Escape")
    assert page.locator("[data-test=backup-closing]").is_visible()
    assert page.locator("[data-test=backup-closing] [data-test=bk-progress]").is_visible()
    page.locator("[data-test=close-background]").click()
    page.wait_for_timeout(300)
    assert h.api._close_choice == "background"
    # a failed one says so and asks
    page.evaluate("() => FS.onEvent({event: 'backupClosing', state: 'failed', message: 'offline'})")
    assert "offline" in page.locator("[data-test=backup-closing]").inner_text()
    assert page.locator("[data-test=close-retry]").is_visible() and page.locator("[data-test=close-anyway]").is_visible()
    page.locator("[data-test=close-retry]").click()
    page.wait_for_timeout(300)
    assert h.api._close_choice == "retry"
    assert not [e for e in errors if "Failed to load resource" not in e], errors


def test_playback_lights_the_playing_line_follows_it_and_keeps_its_controls_in_view(app):
    """Seth, 2026-10-17: highlight the line that's playing, scroll to it unless the user is
    scrolling or clicking, and keep the play controls at the bottom of the view."""
    h, page, errors = app
    page.set_viewport_size({"width": 1360, "height": 520})
    tab = h.api.init()["config"]["tabs"][0]["dir"]
    h.api.create_note(tab, "", "Listen", "Intro.\n\n{{flex:text %s seg=1-6}}\n\nAfter." % T_STORY)
    page.reload()
    page.wait_for_selector(".note-card")
    page.locator(".note-card", has_text="Listen").click()
    page.wait_for_selector("#editor .text-obj .play-range")
    page.evaluate("FS.follow._reset()")
    seen = "(n) => { const r = document.querySelector('#editor .segment[data-n=\"' + n + '\"]').getBoundingClientRect(), e = document.getElementById('editor').getBoundingClientRect(); return r.top >= e.top - 1 && r.bottom <= e.bottom + 1; }"
    page.locator("#editor .text-obj .play-range").click()
    page.wait_for_function("() => !!document.querySelector('#editor .segment.playing-line[data-n=\"1\"]')", timeout=4000)
    # the player stays at the bottom of the view while the example runs on below it
    tr = page.evaluate("() => { const t = document.querySelector('#editor .text-obj .transport'), e = document.getElementById('editor').getBoundingClientRect(), r = t.getBoundingClientRect(); return [getComputedStyle(t).position, r.bottom <= e.bottom + 1, r.top >= e.top]; }")
    assert tr == ["sticky", True, True], tr
    # the view moved away (not by the user): the next line is brought back into view
    page.evaluate("() => { document.getElementById('editor').scrollTop = 0; }")
    page.wait_for_function("() => !!document.querySelector('#editor .segment.playing-line[data-n=\"2\"]')", timeout=4000)
    page.wait_for_timeout(700)
    assert page.evaluate(seen, 2), "the playing line was scrolled into view"
    # the user scrolls with the wheel: the view is left alone
    page.mouse.move(700, 300)
    page.mouse.wheel(0, -600)
    page.wait_for_timeout(200)
    assert page.evaluate("FS.follow._state().quiet")
    page.evaluate("() => { document.getElementById('editor').scrollTop = 0; }")
    top = page.evaluate("document.getElementById('editor').scrollTop")
    page.wait_for_function("() => !!document.querySelector('#editor .segment.playing-line[data-n=\"3\"]')", timeout=4000)
    page.wait_for_timeout(500)
    assert page.evaluate("document.getElementById('editor').scrollTop") == top
    page.wait_for_function("() => !document.querySelector('#editor .segment.playing-line')", timeout=8000)   # off when it ends
    assert not [e for e in errors if "Failed to load resource" not in e], errors


def test_examples_in_a_collection_collapse_to_chips(app):
    """Seth, 2026-10-17: "we DO want flex objects in example collection notes to be collapsible"."""
    h, page, errors = app
    tab = h.api.init()["config"]["tabs"][0]["dir"]
    n = h.api.create_note(tab, "", "Switch reference", "## Same subject\n\n{{flex:text %s seg=1}}\n\n{{flex:text %s seg=3-4}}\n" % (T_STORY, T_STORY), "examples")
    page.reload()
    page.wait_for_selector(".note-card")
    page.locator(".note-card", has_text="Switch reference").click()
    page.wait_for_selector("#collection .coll-item .text-obj")
    assert page.locator("#collection .coll-item .text-obj").count() == 2
    # one example, by its ⤡
    page.locator("#collection .coll-item").first.locator("[data-test=collapse-obj]").click()
    page.wait_for_selector("#collection .coll-item .flex-collapsed")
    assert page.locator("#collection .coll-item .text-obj").count() == 1
    page.wait_for_timeout(1200)
    body = h.api.get_note(n["id"])["body"]
    assert body.count(" collapsed") == 1 and "## Same subject" in body, body
    # all of them, from the header; it stays so after a reload
    page.locator("[data-test=coll-ex-all]").click()
    page.wait_for_function("() => document.querySelectorAll('#collection .coll-item .flex-collapsed').length === 2")
    page.wait_for_timeout(1200)
    page.reload()
    page.wait_for_selector(".note-card")
    page.locator(".note-card", has_text="Switch reference").click()
    page.wait_for_function("() => document.querySelectorAll('#collection .coll-item .flex-collapsed').length === 2")
    assert "Examples in full" in page.locator("[data-test=coll-ex-all]").inner_text()
    # a chip opens its preview on a click, and ⤢ Expand puts the example back in full
    page.locator("#collection .coll-item .flex-collapsed").first.click()
    page.wait_for_selector(".flex-overlay .text-obj")
    page.locator(".flex-overlay .lnk", has_text="⤢ Expand").click()
    page.wait_for_function("() => document.querySelectorAll('#collection .coll-item .text-obj').length === 1")
    # the export takes every example, open or not
    items = page.evaluate("() => window.__fsCollection.flextextItems()")
    assert len(items) == 2, items
    page.wait_for_timeout(1200)
    assert h.api.get_note(n["id"])["body"].count(" collapsed") == 1
    assert not [e for e in errors if "Failed to load resource" not in e], errors


def test_blank_flex_lines_are_left_out_and_flex_numbers_kept(app):
    """Seth, 2026-10-17: a Shift+Enter in FLEx leaves an empty line 1.2 that FLEx numbers but never
    shows; the example must not show it either."""
    import copy
    h, page, errors = app
    text = h.api._flex.backend.texts[T_STORY]
    segs = text["segments"]
    blank = copy.deepcopy(segs[0])
    blank.update(guid="9b1c2d3e-4f50-4a6b-8c7d-0e1f2a3b9301", baseline=" ", words=[], free="", lit="", notes=[], begin=None, end=None)
    segs.insert(1, blank)
    for n, s in enumerate(segs, 1):
        s["n"] = n
    segs[0]["label"], segs[1]["label"], segs[2]["label"] = "1.1", "1.2", "1.3"
    tab = h.api.init()["config"]["tabs"][0]["dir"]
    h.api.create_note(tab, "", "Blank", "{{flex:text %s seg=1-3}}\n\n{{flex:text %s seg=2}}" % (T_STORY, T_STORY))
    page.reload()
    page.wait_for_selector(".note-card")
    page.locator(".note-card", has_text="Blank").click()
    page.wait_for_selector("#editor .text-obj .segment")
    ex = page.locator("#editor .text-obj").first
    assert ex.locator(".segment").count() == 2
    body = ex.inner_text()
    assert "1.1" in body and "1.3" in body and "segments 1.1–1.3" in body, body
    # an example that IS the blank line says so instead of showing nothing
    assert "This line is empty in FLEx." in page.locator("#editor .text-obj").nth(1).inner_text()
    # the copy for FLEx (TSV) leaves it out too
    tsv = page.evaluate("""(g) => FS.interlinear.flexTsv(FS.flexref.parse('{{flex:text ' + g + ' seg=1-2 lines=txt}}'),
        { segments: [{ n: 1, label: '1.1', baseline: 'Kabir', words: [{ txt: 'Kabir' }] }, { n: 2, label: '1.2', baseline: '\u2028', words: [] }] })""", T_STORY)
    assert tsv.count("Word") == 1 and "Kabir" in tsv, tsv
    assert not [e for e in errors if "Failed to load resource" not in e], errors


def test_something_playing_always_has_a_way_to_pause_and_stop_it(app):
    """Seth, 2026-10-17: a collapsed example played from its preview kept playing after the preview
    closed, with no player left to stop it."""
    h, page, errors = app
    tab = h.api.init()["config"]["tabs"][0]["dir"]
    h.api.create_note(tab, "", "Chip audio", "Intro.\n\n{{flex:text %s seg=1-3 collapsed}}\n\nAfter." % T_STORY)
    page.reload()
    page.wait_for_selector(".note-card")
    page.locator(".note-card", has_text="Chip audio").click()
    page.wait_for_selector("#editor .flex-collapsed")
    # the example's own player is on screen: no second one
    page.locator("#editor .flex-collapsed").click()
    page.wait_for_selector(".flex-overlay .text-obj .play-range")
    page.locator(".flex-overlay .play-range").click()
    page.wait_for_selector(".flex-overlay .transport")
    page.wait_for_timeout(400)
    assert page.locator("[data-test=now-playing]").is_hidden()
    # the preview closes (Esc closes it first, without stopping the sound): the bar takes over
    page.keyboard.press("Escape")
    page.wait_for_selector(".flex-overlay", state="detached")
    page.wait_for_selector("[data-test=now-playing]:not([hidden])")
    assert page.evaluate("!!FS.audio.current")
    assert "The dog and the river" in page.locator("[data-test=np-title]").inner_text()
    page.locator("[data-test=np-play]").click()
    assert page.evaluate("FS.audio.current && FS.audio.current.paused") is True
    t0 = page.evaluate("FS.audio.current.el.currentTime")
    page.wait_for_timeout(400)
    assert page.evaluate("FS.audio.current.el.currentTime") == t0
    page.locator("[data-test=np-play]").click()
    page.wait_for_timeout(300)
    assert page.evaluate("FS.audio.current && !FS.audio.current.paused") is True
    page.locator("[data-test=np-stop]").click()
    assert page.evaluate("FS.audio.current") is None
    page.wait_for_selector("[data-test=now-playing]", state="hidden")
    # reopened and played again, then Esc twice: the preview closes, then the sound stops
    page.locator("#editor .flex-collapsed").click()
    page.wait_for_selector(".flex-overlay .text-obj .play-range")
    page.locator(".flex-overlay .play-range").click()
    page.wait_for_timeout(300)
    page.keyboard.press("Escape")
    page.wait_for_selector(".flex-overlay", state="detached")
    assert page.evaluate("!!FS.audio.current")
    page.keyboard.press("Escape")
    assert page.evaluate("FS.audio.current") is None
    assert not [e for e in errors if "Failed to load resource" not in e], errors


def test_styling_inside_a_preview_keeps_the_preview_where_it_was(app):
    """Seth, 2026-10-17: styling a word inside a collapsed example's preview made the preview
    jump back up to the top of the example."""
    h, page, errors = app
    page.set_viewport_size({"width": 1360, "height": 560})
    tab = h.api.init()["config"]["tabs"][0]["dir"]
    n = h.api.create_note(tab, "", "Styled chip", "Intro.\n\n{{flex:text %s seg=1-6 collapsed}}\n\nAfter." % T_STORY)
    page.reload()
    page.wait_for_selector(".note-card")
    page.locator(".note-card", has_text="Styled chip").click()
    page.wait_for_selector("#editor .flex-collapsed")
    page.locator("#editor .flex-collapsed").click()
    page.wait_for_selector(".flex-overlay .text-obj .segment")
    page.wait_for_timeout(400)
    inner = ".flex-overlay .flex-overlay-inner"
    assert page.evaluate("(s) => { const e = document.querySelector(s); return e.scrollHeight > e.clientHeight + 100; }", inner), "the preview scrolls"
    # down to a later line, then highlight one of its words
    page.evaluate("(s) => { const e = document.querySelector(s); e.querySelector('.segment[data-n=\"5\"]').scrollIntoView({ block: 'center' }); }", inner)
    page.wait_for_timeout(200)
    before = page.evaluate("(s) => document.querySelector(s).scrollTop", inner)
    assert before > 100
    page.locator(".flex-overlay .segment[data-n='5'] .word-cell").first.locator(".il-txt").click()
    page.wait_for_selector(".popover .sw")
    page.locator(".popover .sw").nth(1).click()
    page.wait_for_selector(".flex-overlay .segment[data-n='5'] .st-hl")
    page.wait_for_timeout(300)
    after = page.evaluate("(s) => document.querySelector(s).scrollTop", inner)
    assert abs(after - before) < 4, (before, after)
    page.wait_for_timeout(900)
    assert "hl[#ffd6a5]=5.1" in h.api.get_note(n["id"])["body"]
    assert not [e for e in errors if "Failed to load resource" not in e], errors


def test_one_backspace_or_delete_removes_a_whole_br(app):
    """Seth, 2026-10-17: "Deleting <br> with one backspace just deletes part and leaves the text
    behind (should delete the line break altogether)"."""
    h, page, errors = app
    tab = h.api.init()["config"]["tabs"][0]["dir"]
    n = h.api.create_note(tab, "", "Breaks", "one<br>two\n\n| a | b |\n|---|---|\n| x<br>y | z |\n")
    page.reload()
    page.wait_for_selector(".note-card")
    page.locator(".note-card", has_text="Breaks").click()
    page.wait_for_selector("#editor .blk-body")
    body = page.locator("#editor .blk-body").first
    body.click()
    # Backspace just after the break, in a paragraph
    page.evaluate("() => { const b = document.querySelector('#editor .blk-body'); b.focus(); FS.editor.setCaret(b, 'one<br>'.length); }")
    page.keyboard.press("Backspace")
    page.wait_for_function("() => document.querySelector('#editor .blk-body').textContent === 'onetwo'", timeout=3000)
    page.keyboard.type("<br>")
    # Delete just before it
    page.evaluate("() => { const b = document.querySelector('#editor .blk-body'); FS.editor.setCaret(b, 'one'.length); }")
    page.keyboard.press("Delete")
    page.wait_for_function("() => document.querySelector('#editor .blk-body').textContent === 'onetwo'", timeout=3000)
    # inside a table cell, the caret inside the token
    page.locator("table.md-table td .cell-view").first.click()
    page.wait_for_selector(".cell-edit")
    page.evaluate("() => { const c = document.querySelector('.cell-edit'); FS.editor.setCaret(c, 'x<b'.length); }")
    page.keyboard.press("Backspace")
    page.wait_for_function("() => document.querySelector('.cell-edit') && document.querySelector('.cell-edit').textContent === 'xy'", timeout=3000)
    page.keyboard.press("Escape")
    page.wait_for_timeout(1200)
    saved = h.api.get_note(n["id"])["body"]
    assert "onetwo" in saved and "| xy |" in saved and "<b" not in saved and "br>" not in saved, saved
    assert not [e for e in errors if "Failed to load resource" not in e], errors


def test_flex_objects_get_a_readable_copy_in_the_file(app):
    """Seth, 2026-10-17: the note's file carries a plain-text copy of each FLEx object ("so that a
    markdown file IS actually readable elsewhere"), never shown in the app; a block after an object
    on its own line, one link in a table cell, switching when the object moves; written when the
    example changes, never just because a note was opened."""
    import time
    h, page, errors = app
    tab = h.api.init()["config"]["tabs"][0]["dir"]
    E1 = "6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0001"
    n = h.api.create_note(tab, "", "Readable", "Intro\n\n{{flex:text %s seg=1-2 at=0e1f2a3b1001-0e1f2a3b1002}}\n\n| a | b |\n|---|---|\n| x | {{flex:entry %s}} |\n" % (T_STORY, E1))
    path = Path(h.api._nb.get_note(n["id"]).path)
    page.reload()
    page.wait_for_selector(".note-card")
    page.locator(".note-card", has_text="Readable").click()
    page.wait_for_selector("#editor .text-obj .segment")
    page.wait_for_selector("table.md-table td .flex-collapsed, table.md-table td .entry-card")
    before = path.read_text(encoding="utf-8")
    page.wait_for_timeout(1500)
    assert path.read_text(encoding="utf-8") == before and "flex-copy" not in before   # opening never rewrites
    # an edit saves the note, and the file gets its copies
    page.locator("#editor .blk-body").first.click()
    page.keyboard.press("End")
    page.keyboard.type(" here")
    page.wait_for_function("() => document.getElementById('save-state').textContent === 'Saved'", timeout=5000)
    body = path.read_text(encoding="utf-8")
    block = body.split("{{flex:text %s seg=1-2" % T_STORY)[1].split("\n```\n")[0] + "\n```"
    assert '\n[The dog and the river 1.1–1.2](silfw://localhost/link?' in block and '"flex-copy")\n```flex-copy\n1.1  Kabir' in block, block
    assert "‘The dog slept.’" in block and block.rstrip().endswith("```"), block
    row = next(l for l in body.split("\n") if l.startswith("| x |"))
    assert re.search(r"\{\{flex:entry %s\}\}\[kabir.*\]\(silfw://[^ )]+ \"flex-copy\"\) \|$" % E1, row), row
    # none of it is shown: the editor has the same blocks, and no copy text anywhere
    shown = page.locator("#editor").inner_text()
    assert "flex-copy" not in shown and "silfw://" not in shown
    srcs = page.evaluate("() => window.__fsEditor.blocks.map((b) => b.src)")
    assert not any("flex-copy" in s for s in srcs) and len(srcs) == 3, srcs
    # reopened, still hidden, and the file untouched by the opening
    saved = path.read_text(encoding="utf-8")
    page.reload()
    page.wait_for_selector(".note-card")
    page.locator(".note-card", has_text="Readable").click()
    page.wait_for_selector("#editor .text-obj .segment")
    page.wait_for_timeout(1500)
    assert path.read_text(encoding="utf-8") == saved
    assert "flex-copy" not in page.locator("#editor").inner_text()
    # the example changes in FLEx: ↻ redraws it, and the copy follows without an edit
    h.api._flex.backend.texts[T_STORY]["segments"][0]["free"] = "The dog fell asleep."
    page.locator("#editor .text-obj .flex-head .lnk[title='Reload from FLEx']").first.click()
    deadline = time.time() + 6
    while time.time() < deadline and "‘The dog fell asleep.’" not in path.read_text(encoding="utf-8"):
        page.wait_for_timeout(200)
    assert "‘The dog fell asleep.’" in path.read_text(encoding="utf-8")
    # dragged out of its cell to below the table: the entry gets the block form, the cell none
    tb = page.locator("#editor .blk-table").bounding_box()
    dnd(page, "table.md-table td .flex-collapsed, table.md-table td .entry-card .drag-handle", tb["x"] + tb["width"] / 2, tb["y"] + tb["height"] - 3)
    deadline = time.time() + 6
    while time.time() < deadline and "| x | |" not in path.read_text(encoding="utf-8").replace("| x |  |", "| x | |"):
        page.wait_for_timeout(200)
    body = path.read_text(encoding="utf-8")
    assert re.search(r"\n\{\{flex:entry %s\}\}\n\[kabir[^\n]*\]\(silfw://[^ )]+ \"flex-copy\"\)\n```flex-copy\n1\. " % E1, body), body
    assert "flex-copy" not in next(l for l in body.split("\n") if l.startswith("| x |"))
    assert not errors


def test_flex_text_markup_tags_render_and_are_styled_by_scope(app):
    """Seth, 2026-10-17: FLEx's TextMarkup tags drawn in examples, styled per project / tab /
    folder / example (the most specific wins), each switchable on and off where it applies, and
    searchable: the picker's "FLEx tags" finds every place a tag is used."""
    h, page, errors = app
    tab = h.api.init()["config"]["tabs"][0]["dir"]
    n = h.api.create_note(tab, "", "Markup", "{{flex:text %s seg=1-2}}\n\n{{flex:text %s seg=4-6}}\n" % (T_STORY, T_STORY))
    page.reload()
    page.wait_for_selector(".note-card")
    page.locator(".note-card", has_text="Markup").first.click()
    page.wait_for_selector("#editor .text-obj .tagbar")
    first = page.locator("#editor .text-obj").first
    # the tags under the words, with FLEx's own colour on Subject and the palette on Verb
    assert first.locator(".segment").first.locator(".tagbar").all_inner_texts() == ["S", "V"]
    assert first.locator(".segment").nth(1).locator(".tagbar").all_inner_texts() == ["Foc", "S", "V", "O"]
    subj = first.locator(".segment").first.locator(".tagbar").first
    assert subj.evaluate("(e) => getComputedStyle(e).backgroundColor") == "rgb(219, 234, 254)"
    # a tag over two segments: the second half says it continues
    second = page.locator("#editor .text-obj").nth(1)
    assert second.locator(".segment").nth(0).locator(".tagbar").all_inner_texts() == ["Top", " "]
    assert second.locator(".segment").nth(2).locator(".tagbar.cont").first.inner_text() == "…Top"
    assert first.locator("[data-test=tag-btn]").inner_text() == "⚑ 4"
    # the ⚑ popover: where each tag's look comes from, and a toggle that writes the example's own rule
    first.locator("[data-test=tag-btn]").click()
    page.wait_for_selector("[data-test=tag-popover]")
    rows = page.locator("[data-test=tag-popover] .tagrow")
    # in FLEx's own hierarchy: Syntax › Arguments › Subject, Object; Syntax › Verb; Discourse › Focus
    assert page.evaluate("() => [...document.querySelectorAll('[data-test=tag-popover] [data-test=tag-tree-group]')].map((h) => h.dataset.group + ':' + h.querySelector('.tag-tree-n').textContent)") == ["Syntax:3", "Arguments:2", "Discourse:1"]
    assert [r.strip() for r in rows.locator(".tag-name > span:first-child").all_inner_texts()] == ["Subject (S) ×2", "Object (O)", "Verb (V) ×2", "Focus (Foc)"]
    assert rows.locator("[data-test=tag-via]").all_inner_texts() == ["styled by FLEx’s own colours", "styled by FLEx’s own colours", "styled by the standard palette", "styled by the standard palette"]
    page.locator("[data-test=tag-popover] [data-test=tag-tree-group][data-group=Arguments]").click()        # fold a group: its tags go, remembered
    assert rows.count() == 2
    page.locator("[data-test=tag-popover] [data-test=tag-tree-group][data-group=Arguments]").click()
    assert rows.count() == 4
    rows.nth(0).locator("[data-test=tag-toggle]").click()
    page.wait_for_function("() => !document.querySelector('#editor .text-obj .segment .tagbar') || document.querySelector('#editor .text-obj .segment').querySelectorAll('.tagbar').length === 1")
    page.wait_for_timeout(900)
    body = body_of(h)
    assert re.search(r"seg=1-2( at=[0-9a-f-]+)? tags=Subject:off\}\}", body), body
    assert page.locator("[data-test=tag-popover] [data-test=tag-via]").first.inner_text() == "hidden by this example"
    page.keyboard.press("Escape")
    # a TAB rule: Verb in a colour of the tab's, from the tab's menu; the examples redraw with it
    page.locator(".tab-item", has_text="Notes").click(button="right")
    page.locator(".popover .menu-item", has_text="FLEx tag styles for this tab").click()
    page.wait_for_selector("[data-test=tag-dialog]")
    # the dialog starts EMPTY: tags are added one at a time from the list (Seth, 2026-10-18)
    assert page.locator("[data-test=tag-dialog-empty]").count() == 1
    page.locator("[data-test=tag-add]").click()
    page.locator("[data-test=tag-pick][data-tag='Verb']").click()
    verb = page.locator("[data-test=tag-dialog] .tagrow[data-tag='Verb']")
    assert verb.count() == 1 and page.locator("[data-test=tag-dialog] .tagrow").count() == 1
    verb.locator("[data-test=tag-bg]").nth(3).click()                 # the 4th palette colour, #bdb2ff
    page.wait_for_function("() => document.querySelector('[data-test=tag-dialog] .tagrow[data-tag=\"Verb\"] [data-test=tag-via]').textContent === 'styled by the tab'")
    assert verb.locator("[data-test=tag-rule-on]").is_checked()
    page.locator(".modal .btn.primary", has_text="Done").click()
    page.wait_for_function("() => { const b = [...document.querySelectorAll('#editor .text-obj .segment')][0].querySelector('.tagbar'); return b && getComputedStyle(b).backgroundColor === 'rgb(189, 178, 255)'; }")
    assert h.api.init()["config"]["tagStyles"]["tab"][tab] == [{"tag": "Verb", "enabled": True, "bg": "#bdb2ff"}]
    # the example's own style wins over the tab's
    first.locator("[data-test=tag-btn]").click()
    page.wait_for_selector("[data-test=tag-popover]")
    page.locator("[data-test=tag-popover] .tagrow[data-tag='Verb'] [data-test=tag-style]").click()
    page.locator("[data-test=tag-popover] .tag-style-box [data-test=tag-bg]").nth(0).click()        # #ffd6a5
    page.wait_for_function("() => { const b = [...document.querySelectorAll('#editor .text-obj .segment')][0].querySelector('.tagbar'); return b && getComputedStyle(b).backgroundColor === 'rgb(255, 214, 165)'; }")
    assert page.locator("[data-test=tag-popover] .tagrow[data-tag='Verb'] [data-test=tag-via]").inner_text() == "styled by this example"
    # the same popover can aim its changes at another scope: the TEXT, wherever its examples appear
    # (Seth, 2026-10-18: "specific texts anywhere they appear") — Object off for the text
    sel = page.locator("[data-test=tag-scope-pick]")
    labels = sel.locator("option").all_inner_texts()
    assert labels[0] == "this example" and "this note" in labels and "this tab" in labels and "the whole notebook" in labels and any(l.startswith("the text “The dog") for l in labels), labels
    sel.select_option(label=[l for l in labels if l.startswith("the text")][0])
    page.locator("[data-test=tag-popover] .tagrow[data-tag='Object'] [data-test=tag-toggle]").click()
    page.wait_for_function("() => document.querySelector('[data-test=tag-popover] .tagrow[data-tag=\"Object\"] [data-test=tag-via]').textContent.startsWith('hidden by the text')")
    assert h.api.init()["config"]["tagStyles"]["text"][T_STORY] == [{"tag": "Object", "enabled": True, "hide": True}]
    page.keyboard.press("Escape")
    page.wait_for_timeout(900)
    assert "tags=Subject:off,Verb:bg#ffd6a5" in body_of(h), body_of(h)
    assert "Object" not in body_of(h)                                         # a text rule lives in notebook.json, not in the embed
    assert page.locator("#editor .text-obj .tagbar", has_text=re.compile(r"^O$")).count() == 0           # in every example of that text
    # the picker's FLEx tags: Topic is used in two places; both inserted as examples
    page.locator("#toolbar button", has_text="FLEx object").click()      # nothing focused: new blocks go after the last
    page.locator(".picker-tabs button", has_text="FLEx tags").click()
    page.wait_for_selector("[data-test=pick-tag]")
    assert page.locator("[data-test=pick-tag] .hw").all_inner_texts() == ["Subject", "Object", "Verb", "Topic", "Focus"]
    page.locator("[data-test=pick-tag]", has_text="Topic").click()
    page.wait_for_selector("[data-test=pick-occurrence]")
    occ = page.locator("[data-test=pick-occurrence]")
    assert occ.count() == 2 and occ.nth(1).locator(".pos").inner_text() == "3.1–3.2" and occ.nth(0).locator(".gl").inner_text() == "Kabir pemu"
    occ.nth(1).click()
    page.wait_for_selector(".picker-preview .segment.in-range")
    assert page.locator(".picker-preview .segment.in-range").count() == 2
    page.locator("[data-test=insert-all-tagged]").click()
    page.wait_for_timeout(1200)
    body = body_of(h)
    assert body.count("{{flex:text") == 4 and "seg=5-6 at=" in body and "seg=4 at=" in body, body
    assert not errors


def test_tag_styles_for_a_selection_of_examples(app):
    """Seth, 2026-10-17: example-scoped tag styles "applyable to a group of examples by highlight" —
    here the selected cards of a collection; the rule is written into each embed."""
    h, page, errors = app
    tab = h.api.init()["config"]["tabs"][0]["dir"]
    c = h.api.create_note(tab, "", "Tagged set", "{{flex:text %s seg=1}}\n\n{{flex:text %s seg=2}}\n\n{{flex:text %s seg=4}}\n" % (T_STORY, T_STORY, T_STORY), "examples")
    page.reload()
    page.wait_for_selector(".note-card")
    page.locator(".note-card", has_text="Tagged set").first.click()
    page.wait_for_selector("#collection .coll-item .tagbar")
    checks = page.locator("[data-test=coll-check]")
    checks.nth(0).click()
    checks.nth(1).click()
    page.locator("[data-test=coll-sel-tags]").click()
    page.wait_for_selector("[data-test=tag-dialog]")
    assert "2 selected examples" in page.locator(".modal .modal-title, .modal h2, .modal header").first.inner_text()
    for name in ("Subject", "Verb"):
        page.locator("[data-test=tag-add]").click()
        page.locator("[data-test=tag-pick-search]").fill(name[:3])
        page.locator("[data-test=tag-pick][data-tag='%s']" % name).click()
    page.locator("[data-test=tag-dialog] .tagrow[data-tag='Subject'] [data-test=tag-show]").select_option("hide")
    page.locator("[data-test=tag-dialog] .tagrow[data-tag='Verb'] [data-test=tag-b]").click()
    page.wait_for_function("() => document.querySelector('[data-test=tag-dialog] .tagrow[data-tag=\"Subject\"] [data-test=tag-via]').textContent === 'hidden by this example'")
    page.locator(".modal .btn.primary", has_text="Done").click()
    page.wait_for_timeout(1000)
    body = without_flex_copies(h.api.get_note(c["id"])["body"])
    assert body.count("tags=Subject:off,Verb:b") == 2 and "seg=4 " in body and "seg=4" in body.split("\n")[-2], body
    assert "seg=4 at=" in body or "seg=4}}" in body
    assert body.split("\n\n")[2].count("tags=") == 0            # the unselected example is untouched
    # drawn accordingly: no S bar on the first two cards, bold words where Verb is
    assert page.locator("#collection .coll-item").nth(0).locator(".tagbar", has_text="S").count() == 0
    assert page.locator("#collection .coll-item").nth(0).locator(".il-txt.tag-b").count() == 1
    assert page.locator("#collection .coll-item").nth(2).locator(".tagbar", has_text="Top").count() == 1
    assert not errors


def test_tags_style_the_text_and_visual_filters_and_the_rail_filters_by_tag(app):
    """Seth, 2026-10-18: "the option to style the TEXT, not the tags … brackets around words …
    highlight/background/border/tile", visual filters "like you can do with visual filters in
    Logos", and "the ability also to search or filter notes and specific flex objects in notes by
    text markup tags"."""
    h, page, errors = app
    tab = h.api.init()["config"]["tabs"][0]["dir"]
    # the third example is a collapsed chip, the fourth a chip in a line of text: both count
    h.api.create_note(tab, "", "Markup", "Intro.\n\n{{flex:text %s seg=1-2}}\n\n{{flex:text %s seg=4-6}}\n\n{{flex:text %s seg=5 collapsed}}\n\nSee {{flex:text %s seg=1}} here.\n" % (T_STORY, T_STORY, T_STORY, T_STORY))
    h.api.create_note(tab, "", "Plain", "No examples here.")
    h.api.set_tag_styles("tab", tab, [{"tag": "Subject", "br": "sq", "hl": True}, {"tag": "Verb", "box": True, "bs": "dashed", "bw": 3}, {"tag": "Topic", "tile": True, "bar": True, "tc": "#fde68a"}, {"tag": "Object", "c": "#b45309", "b": True}])
    h.api.set_tag_filters([{"id": "f1", "name": "Discourse", "enabled": True, "rules": [{"tag": "group:Discourse", "br": "an"}]}])
    page.reload()
    page.wait_for_selector(".note-card")
    page.locator(".note-card", has_text="Markup").first.click()
    page.wait_for_selector("#editor .text-obj .tag-ov-box")
    first = page.locator("#editor .text-obj").first
    seg1 = first.locator(".segment").first
    # Subject: brackets round the word with the abbreviation on the closing one, a marker behind it, NO bar
    assert seg1.locator(".br-cell.br-open").inner_text() == "[" and seg1.locator(".br-cell.br-close").inner_text() == "]S"
    assert seg1.locator(".tag-ov-hl").count() == 1 and seg1.locator(".tagbar", has_text="S").count() == 0
    # Verb: a border round the word's column, drawn over its cells; Object: the word coloured and bold
    box = seg1.locator(".tag-ov-box")
    assert box.count() == 1
    geo = page.evaluate("() => { const b = document.querySelector('#editor .text-obj .segment .tag-ov-box').getBoundingClientRect(); const c = document.querySelector('#editor .text-obj .segment .word-cell[data-w=\"2\"]').getBoundingClientRect(); return [b.left <= c.left, b.right >= c.right, b.top <= c.top, b.bottom >= c.bottom]; }")
    assert geo == [True, True, True, True], geo
    # the border's line style and thickness, the tile's own colour (Seth, 2026-10-18)
    assert box.evaluate("(e) => [getComputedStyle(e).borderTopStyle, getComputedStyle(e).borderTopWidth]") == ["dashed", "3px"]
    seg2 = first.locator(".segment").nth(1)
    assert seg2.locator(".word-cell[data-w='4'] .il-txt").evaluate("(e) => [getComputedStyle(e).color, getComputedStyle(e).fontWeight]") == ["rgb(180, 83, 9)", "700"]
    # the visual filter puts angle brackets round the Focus tag (by its FLEx group); Topic keeps its bar beside its tile
    assert seg2.locator(".br-cell.br-open").all_inner_texts() == ["⟨", "["]
    second = page.locator("#editor .text-obj").nth(1)
    assert second.locator(".segment").first.locator(".tag-ov-tile").count() == 1 and second.locator(".segment").first.locator(".tagbar", has_text="Top").count() == 1
    assert second.locator(".segment").first.locator(".tag-ov-tile").evaluate("(e) => getComputedStyle(e).backgroundColor") == "rgba(253, 230, 138, 0.55)"
    # the controls: with "border" on, its line style and thickness; with "tile" on, its colour (aimed at the tab, where the rules are)
    first.locator("[data-test=tag-btn]").click()
    page.wait_for_selector("[data-test=tag-popover]")
    page.locator("[data-test=tag-scope-pick]").select_option(label="this tab")
    page.locator("[data-test=tag-popover] .tagrow[data-tag='Verb'] [data-test=tag-style]").click()
    sb = page.locator("[data-test=tag-popover] .tag-style-box")
    assert sb.locator("[data-test=tag-box]").first.evaluate("(e) => e.classList.contains('on')")
    assert sb.locator("[data-test=tag-bs]").input_value() == "dashed" and sb.locator("[data-test=tag-bw]").input_value() == "3"
    sb.locator("[data-test=tag-bw]").select_option("6")
    page.wait_for_function("() => getComputedStyle(document.querySelector('#editor .text-obj .segment .tag-ov-box')).borderTopWidth === '6px'")
    # …and the border's own colour (Seth, 2026-10-19: "I should be able to specify a border color")
    sb.locator("[data-test=tag-bc]").evaluate("(e) => { e.value = '#1d4ed8'; e.dispatchEvent(new Event('change', {bubbles: true})); }")
    page.wait_for_function("() => getComputedStyle(document.querySelector('#editor .text-obj .segment .tag-ov-box')).borderTopColor === 'rgb(29, 78, 216)'")
    page.keyboard.press("Escape")
    second.locator("[data-test=tag-btn]").click()                       # Topic is on the second example's lines
    page.wait_for_selector("[data-test=tag-popover] .tagrow[data-tag='Topic']")
    page.locator("[data-test=tag-scope-pick]").select_option(label="this tab")
    page.locator("[data-test=tag-popover] .tagrow[data-tag='Topic'] [data-test=tag-style]").click()
    assert page.locator("[data-test=tag-popover] .tag-style-box [data-test=tag-tc]").input_value() == "#fde68a"
    page.locator("[data-test=tag-popover] .tag-style-box [data-test=tag-tc-auto]").click()
    page.wait_for_function("() => getComputedStyle(document.querySelector('#editor .text-obj:nth-of-type(2) .segment .tag-ov-tile, #editor .text-obj .tag-ov-tile')).backgroundColor !== 'rgba(253, 230, 138, 0.55)'")
    page.keyboard.press("Escape")
    assert h.api.init()["config"]["tagStyles"]["tab"][tab][1] == {"tag": "Verb", "enabled": True, "box": True, "bs": "dashed", "bw": 6, "bc": "#1d4ed8"}
    assert h.api.init()["config"]["tagStyles"]["tab"][tab][2] == {"tag": "Topic", "enabled": True, "tile": True, "bar": True}
    # the toolbar's ⚑ Filters is a VIEW setting (Seth: "for the whole app or for notebook pages"):
    # off for THIS NOTE first — the angle brackets go here, the filter stays on by default…
    page.locator("#btn-filters").click()
    page.wait_for_selector("[data-test=filters-mode]")
    assert page.locator("[data-test=filters-mode] .seg-btn.on").inner_text() == "This note"
    angles = "() => [...document.querySelectorAll('#editor .text-obj .br-cell.br-open')].filter((b) => b.textContent === '⟨').length"
    assert page.evaluate(angles) > 0
    page.locator("[data-test=filter-on][data-filter=f1]").click()
    page.wait_for_function("(() => { const f = " + angles + "; return f() === 0; })()")
    cfg = h.api.init()["config"]["tagStyles"]
    assert cfg["note"][[n for n in h.api.list_notes() if n["title"] == "Markup"][0]["id"]] == [{"tag": "filter:f1", "enabled": True, "hide": True}] and cfg["filters"][0]["enabled"] is True
    page.locator("[data-test=filter-reset]").click()                                # back to the default: on again
    page.wait_for_function("(() => { const f = " + angles + "; return f() > 0; })()")
    # …then off EVERYWHERE
    page.locator("[data-test=filters-mode] .seg-btn[data-mode=all]").click()
    page.locator("[data-test=filter-on][data-filter=f1]").click()
    page.wait_for_function("(() => { const f = " + angles + "; return f() === 0; })()")
    assert h.api.init()["config"]["tagStyles"]["filters"][0]["enabled"] is False
    page.keyboard.press("Escape")
    # the rail lists the FLEx tags the notes use; one click filters the list and dims the other examples
    page.wait_for_selector("[data-test=ftag][data-tag='Topic']")
    assert page.locator("[data-test=ftag]").count() == 5
    page.locator("[data-test=ftag][data-tag='Topic']").click()
    page.wait_for_selector("#tagfocus:not([hidden])")
    page.wait_for_function("() => document.querySelectorAll('.note-card').length === 1")
    assert "1 match with ⚑ Topic" in page.locator("#list-sub").inner_text()
    page.wait_for_function("() => document.querySelector('[data-test=tagfocus-count]').textContent === '2 of 4 examples in this note'")
    assert "tag-miss" in first.get_attribute("class") and "tag-hit" in second.get_attribute("class")
    assert "tag-hit" in page.locator("#editor .flex-collapsed").first.get_attribute("class")      # the chip for 3.1 carries Topic
    assert "tag-miss" in page.locator("#editor .md-embed").first.get_attribute("class")
    page.locator("[data-test=tagfocus-clear]").click()
    page.wait_for_function("() => document.querySelectorAll('.note-card').length === 3 && document.getElementById('tagfocus').hidden")
    assert "tag-miss" not in first.get_attribute("class")
    assert not errors


def test_rail_parts_fold_and_resize_and_are_never_lost(app):
    """Seth, 2026-10-18: "the left pane is now too crowded … the borders of each part can be
    vertically dragged and collapsed/expanded. We don't ever want something hidden beyond recovery
    in that pane"."""
    h, page, errors = app
    tab = h.api.init()["config"]["tabs"][0]["dir"]
    for i in range(8):
        h.api.create_folder(tab, "Folder %d" % i)
    page.reload()
    page.wait_for_selector(".folder-item")
    height = lambda sel: page.evaluate("(s) => document.querySelector(s).getBoundingClientRect().height", sel)   # noqa: E731
    visible_top = lambda sel: page.evaluate("(s) => { const r = document.querySelector(s).getBoundingClientRect(); const p = document.getElementById('rail').getBoundingClientRect(); return r.top >= p.top && r.bottom <= p.bottom; }", sel)   # noqa: E731
    # every header is in the pane, and the FLEx tags part is hidden until the project is open or notes use tags
    for sec in ("tabs", "folders", "tags"):
        assert visible_top("#%s-section h4" % sec)
    # fold Tags with its header: the body goes, the header stays, the state is remembered
    page.locator("#tags-section h4").click()
    assert page.locator("#tags-section.collapsed").count() == 1 and not page.locator("#tags").is_visible()
    assert visible_top("#tags-section h4")
    page.reload()
    page.wait_for_selector(".folder-item")
    assert page.locator("#tags-section.collapsed").count() == 1
    page.locator("#tags-section h4").click()
    assert page.locator("#tags-section.collapsed").count() == 0 and page.locator("#tags").is_visible()
    # drag the divider under Folders down: Folders gains what Tags loses; double-click resets both
    before_f, before_t = height("#folders-section"), height("#tags-section")
    d = page.locator("[data-test=rail-divider]").nth(1).bounding_box()
    page.mouse.move(d["x"] + 40, d["y"] + 3)
    page.mouse.down()
    page.mouse.move(d["x"] + 40, d["y"] + 43, steps=5)
    page.mouse.up()
    assert abs(height("#folders-section") - (before_f + 40)) < 3, (before_f, height("#folders-section"))
    assert abs(height("#tags-section") - (before_t - 40)) < 3
    st = page.evaluate("JSON.parse(localStorage.getItem('fs:rail'))")
    assert set(st["sizes"]) == {"folders", "tags"}
    # a part can never be dragged smaller than its header
    page.mouse.move(d["x"] + 40, d["y"] + 43)
    page.mouse.down()
    page.mouse.move(d["x"] + 40, d["y"] + 900, steps=5)
    page.mouse.up()
    assert visible_top("#tags-section h4") and height("#tags-section") >= height("#tags-section h4")
    page.locator("[data-test=rail-divider]").nth(1).dblclick()
    assert "sizes" not in page.evaluate("JSON.parse(localStorage.getItem('fs:rail'))") or not page.evaluate("JSON.parse(localStorage.getItem('fs:rail')).sizes")
    assert not errors


def test_hidden_markers_type_to_the_right_of_a_prefix(app):
    """Seth, 2026-10-18: with markup hidden, "add a heading or make a blank block into a heading
    and then start typing, the cursor goes to the left of the ### and makes the ### appear. … text
    should automatically start typing to the RIGHT of a heading or list markup tag"."""
    h, page, errors = app
    page.locator("#btn-markers").click()
    page.wait_for_function("() => document.body.classList.contains('md-hide')")
    new_note(page, "Hidden")
    page.click(".blk-body")
    # an empty block made a heading: its prefix shows faintly, the caret sits after it, typing follows it
    page.locator("[data-test=tb-heading]").dispatch_event("mousedown")
    page.locator("[data-test=heading-2]").dispatch_event("mousedown")
    page.wait_for_selector("#editor .blk-h .md-line-empty")
    assert page.locator("#editor .blk-h .md-line-empty .md-marker").first.is_visible()
    page.keyboard.type("Title")
    page.wait_for_timeout(900)
    assert body_of(h).strip() == "## Title", body_of(h)
    # the heading's own markup stays visible while the caret is on its line (Seth, 2026-10-18:
    # "whatever … style markup applies to the current cursor position should be visible")
    assert page.locator("#editor .blk-h .md-marker.reveal").first.is_visible()
    # Home then typing: still after the prefix; a click at the far left of the line too
    page.keyboard.press("Home")
    page.keyboard.type("A ")
    page.wait_for_timeout(900)
    assert body_of(h).strip() == "## A Title", body_of(h)
    box = page.locator("#editor .blk-h .blk-body").bounding_box()
    page.mouse.click(box["x"] + 1, box["y"] + box["height"] / 2)
    page.keyboard.type("B")
    page.wait_for_timeout(900)
    assert body_of(h).strip() == "## BA Title", body_of(h)
    # Enter makes a paragraph under it; a list item started there keeps typing after its bullet
    page.keyboard.press("End")
    page.keyboard.press("Enter")
    page.keyboard.type("- first")
    page.keyboard.press("Enter")
    page.keyboard.press("Home")
    page.keyboard.type("second")
    page.wait_for_timeout(900)
    assert body_of(h).strip() == "## BA Title\n\n- first\n- second", body_of(h)
    # the caret has left the heading: its ## is hidden again; the bullets stay glyphs, never text
    assert not page.locator("#editor .blk-h .md-marker").first.is_visible()
    assert page.locator("#editor .blk-list .md-marker.reveal").count() == 0
    page.locator("#btn-markers").click()
    page.wait_for_function("() => !document.body.classList.contains('md-hide')")
    assert not errors


def test_hidden_markers_reveal_only_the_markup_at_the_caret(app):
    """Seth, 2026-10-18: "whatever character or style markup applies to the current cursor
    position should be visible, but none of the rest of it. I think this is roughly how WhatsApp
    works": the enclosing runs' markers (nested ones too) and the line's heading mark, nothing else."""
    h, page, errors = app
    page.locator("#btn-markers").click()
    page.wait_for_function("() => document.body.classList.contains('md-hide')")
    new_note(page, "Reveal")
    page.click(".blk-body")
    paste(page, "### Head **bold** and *it* here\n\nPlain **one *two* three** and `code` [a link](http://x.y) end")
    page.wait_for_timeout(400)
    revealed = lambda: page.evaluate("() => [...document.querySelectorAll('#editor .md-marker.reveal')].map((m) => m.textContent)")   # noqa: E731
    put = lambda sel, text, off: page.evaluate("([sel, text, off]) => { const b = document.querySelector(sel); FS.editor.setCaret(b, b.textContent.indexOf(text) + off); b.focus(); }", [sel, text, off])   # noqa: E731
    # on the heading line, in the plain word "and": the ### shows, the bold and italic marks do not
    put("#editor .blk-h .blk-body", "and", 1)
    page.wait_for_timeout(150)
    assert revealed() == ["### "], revealed()
    # inside "bold": the ### and that word's ** **, not the italic's
    put("#editor .blk-h .blk-body", "bold", 2)
    page.wait_for_timeout(150)
    assert revealed() == ["### ", "**", "**"], revealed()
    # in the paragraph, inside "two": the outer bold AND the inner italic; inside "three": the bold only
    put("#editor .blk-p .blk-body", "two", 1)
    page.wait_for_timeout(150)
    assert revealed() == ["**", "*", "*", "**"], revealed()
    put("#editor .blk-p .blk-body", "three", 2)
    page.wait_for_timeout(150)
    assert revealed() == ["**", "**"], revealed()
    # right after the closing ** (touching) still shows it; in "and" nothing; in the code its ticks; in the link its brackets
    put("#editor .blk-p .blk-body", "three**", len("three**"))
    page.wait_for_timeout(150)
    assert revealed() == ["**", "**"], revealed()
    put("#editor .blk-p .blk-body", "and `", 1)
    page.wait_for_timeout(150)
    assert revealed() == [], revealed()
    put("#editor .blk-p .blk-body", "code", 2)
    page.wait_for_timeout(150)
    assert revealed() == ["`", "`"], revealed()
    put("#editor .blk-p .blk-body", "link", 2)
    page.wait_for_timeout(150)
    assert revealed() == ["[", "](http://x.y)"], revealed()
    assert page.locator("#editor .md-marker.reveal").first.is_visible()
    page.locator("#btn-markers").click()
    page.wait_for_function("() => !document.body.classList.contains('md-hide')")
    assert not errors


def test_list_items_indent_and_outdent_and_nest_prettily(app):
    """Seth, 2026-10-18: lists "need to include the ability to increase and decrease the indent
    (and display it prettily)": Tab / Shift+Tab, Ctrl+] / Ctrl+[, the toolbar's ⇥ ⇤ and the block
    menu step the selected items in and out; each level gets its own bullet, nested numbers are
    lettered, then roman."""
    h, page, errors = app
    new_note(page, "Nested")
    page.click(".blk-body")
    paste(page, "- one\n- two\n- three\n- four")
    page.wait_for_timeout(300)
    bullet = lambda i: page.evaluate("(i) => getComputedStyle(document.querySelectorAll('#editor .md-bullet')[i], '::before').content", i)   # noqa: E731
    # Tab on "two", then on "three" twice: levels 1 and 2 with their own bullets
    body = page.locator("#editor .blk-list .blk-body")
    page.evaluate("() => { const b = document.querySelector('#editor .blk-list .blk-body'); FS.editor.setCaret(b, '- one\\n- t'.length); b.focus(); }")
    page.keyboard.press("Tab")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Tab")
    page.keyboard.press("Control+]")
    page.wait_for_timeout(700)
    assert body_of(h).strip() == "- one\n  - two\n    - three\n- four", body_of(h)
    assert [bullet(i) for i in range(4)] == ['"•"', '"◦"', '"▪"', '"•"']
    # the items are single-spaced: four lines take four line heights, not eight (Seth, 2026-10-18:
    # "we don't really want double-line spacing in our list items within a single block")
    h_body, lh = page.evaluate("() => { const b = document.querySelector('#editor .blk-list .blk-body'); return [b.getBoundingClientRect().height, parseFloat(getComputedStyle(b).lineHeight)]; }")
    assert 3.5 * lh < h_body < 5 * lh, (h_body, lh)
    # Shift+Tab brings "three" back one; the toolbar's ⇤ once more; ⇥ in again
    page.keyboard.press("Shift+Tab")
    page.locator("[data-test=tb-outdent]").dispatch_event("mousedown")
    page.locator("[data-test=tb-indent]").dispatch_event("mousedown")
    page.wait_for_timeout(700)
    assert body_of(h).strip() == "- one\n  - two\n  - three\n- four", body_of(h)
    # a selection over several items moves them together, and stays on the same text
    page.evaluate("() => { const b = document.querySelector('#editor .blk-list .blk-body'); FS.editor.setCaret(b, '- one\\n  - t'.length, '- one\\n  - two\\n  - th'.length); b.focus(); }")
    page.keyboard.press("Control+[")
    page.wait_for_timeout(700)
    assert body_of(h).strip() == "- one\n- two\n- three\n- four", body_of(h)
    assert page.evaluate("() => getSelection().toString()") == "wo\n- th"
    # numbered items: a. b. one level in, i. ii. two levels in, shown over the typed digits
    page.keyboard.press("Control+End")
    page.keyboard.press("Enter")
    page.keyboard.press("Enter")
    paste(page, "1. first\n  1. sub a\n  2. sub b\n    1. deep\n    2. deeper\n2. second")
    page.wait_for_timeout(500)
    shown = page.evaluate("() => [...document.querySelectorAll('#editor .md-line[data-num]')].map((l) => l.dataset.num)")
    assert shown == ["1.", "a.", "b.", "i.", "ii.", "2."], shown
    # the block menu has the indent row for a list
    grip = page.locator("#editor .blk-list").last.locator("[data-test=blk-grip]")
    page.locator("#editor .blk-list").last.hover()
    grip.dispatch_event("mousedown")
    page.wait_for_selector("[data-test=list-indent]")
    page.keyboard.press("Escape")
    assert not errors


def test_gap_bar_between_blocks_adds_and_removes(app):
    """Seth, 2026-10-18: the empty line between blocks is "a convenient place for an add/remove
    block bar similar to the bar at the end of our table": hovering the gap shows + Paragraph /
    + Example / + Table / + More and − Above / − Below."""
    h, page, errors = app
    new_note(page, "Gaps")
    page.click(".blk-body")
    paste(page, "first\n\nsecond")
    page.wait_for_timeout(300)
    page.keyboard.press("Backspace")          # the empty paragraph the paste leaves after itself
    page.wait_for_timeout(300)
    assert page.locator("#editor .blk").count() == 2
    bar = page.locator("[data-test=blk-gap]")
    assert bar.is_hidden()
    gap_y = page.evaluate("() => { const [a, b] = document.querySelectorAll('#editor .blk'); return (a.getBoundingClientRect().bottom + b.getBoundingClientRect().top) / 2; }")
    x = page.evaluate("() => { const r = document.querySelector('#editor').getBoundingClientRect(); return r.left + r.width / 2; }")
    page.mouse.move(x, gap_y - 30)
    page.mouse.move(x, gap_y)
    page.wait_for_timeout(120)
    assert bar.is_hidden()                     # passing through shows nothing: the pointer has to REST in the gap
    page.wait_for_selector("[data-test=blk-gap]:not([hidden])")
    # the bar sits on the gap
    top, bottom = page.evaluate("() => { const r = document.querySelector('#blk-gap').getBoundingClientRect(); return [r.top, r.bottom]; }")
    assert top < gap_y < bottom
    # + Paragraph puts a new block between the two, focused
    bar.locator("[data-gap=p]").click()
    page.wait_for_timeout(300)
    assert bar.is_hidden()
    assert page.locator("#editor .blk").count() == 3
    assert page.evaluate("() => [...document.querySelectorAll('#editor .blk')].indexOf(document.activeElement.closest('.blk'))") == 1
    page.keyboard.type("middle")
    page.wait_for_timeout(700)
    assert body_of(h).strip() == "first\n\nmiddle\n\nsecond", body_of(h)
    # − Below from the gap under "first" removes "middle"; hovering the button marks it first
    gap_y = page.evaluate("() => { const [a, b] = document.querySelectorAll('#editor .blk'); return (a.getBoundingClientRect().bottom + b.getBoundingClientRect().top) / 2; }")
    page.mouse.move(x, gap_y + 40)
    page.mouse.move(x, gap_y)
    page.wait_for_selector("[data-test=blk-gap]:not([hidden])")
    bar.locator("[data-gap=rm-below]").hover()
    assert page.evaluate("() => document.querySelectorAll('#editor .blk')[1].classList.contains('del-hint')")
    # one click only ARMS the button ("Remove?"); it disarms by itself; two clicks remove
    bar.locator("[data-gap=rm-below]").click()
    assert bar.locator("[data-gap=rm-below]").inner_text() == "Remove?" and page.locator("#editor .blk").count() == 3
    page.wait_for_timeout(2300)
    assert bar.locator("[data-gap=rm-below]").inner_text() == "− Below"
    bar.locator("[data-gap=rm-below]").click()
    bar.locator("[data-gap=rm-below]").click()
    page.wait_for_timeout(700)
    assert body_of(h).strip() == "first\n\nsecond", body_of(h)
    assert page.locator("#editor .blk").count() == 2
    assert page.locator("#editor .del-hint").count() == 0
    # the toast's Undo brings the paragraph back
    page.wait_for_selector(".toast:has-text('Paragraph removed') [data-test=toast-action]")
    page.locator(".toast [data-test=toast-action]").click()
    page.wait_for_timeout(700)
    assert page.locator("#editor .blk").count() == 3 and body_of(h).strip() == "first\n\nmiddle\n\nsecond", body_of(h)
    gap_y = page.evaluate("() => { const [a, b] = document.querySelectorAll('#editor .blk'); return (a.getBoundingClientRect().bottom + b.getBoundingClientRect().top) / 2; }")
    page.mouse.move(x, gap_y + 40)
    page.mouse.move(x, gap_y)
    page.wait_for_selector("[data-test=blk-gap]:not([hidden])")
    bar.locator("[data-gap=rm-below]").click()
    bar.locator("[data-gap=rm-below]").click()
    page.wait_for_timeout(700)
    assert page.locator("#editor .blk").count() == 2
    # below the last block: no "− Below"; + More ▾ lists every kind, each inserting here
    last_bottom = page.evaluate("() => document.querySelector('#editor .blk:last-child').getBoundingClientRect().bottom")
    page.mouse.move(x, last_bottom + 6)
    page.wait_for_selector("[data-test=blk-gap]:not([hidden])")
    assert bar.locator("[data-gap=rm-below]").count() == 0 and bar.locator("[data-gap=rm-above]").count() == 1
    bar.locator("[data-gap=more]").click()
    page.wait_for_selector(".popover .ins-grid")
    assert page.locator(".popover .ins-grid [data-ins-where=before]").count() == 0
    page.locator(".popover .ins-grid [data-ins-kind=hr]").click()
    page.wait_for_timeout(700)
    assert body_of(h).strip().endswith("second\n\n---"), body_of(h)
    # the bar goes away when the pointer leaves the gap
    page.mouse.move(x, 5)
    page.wait_for_timeout(300)
    assert bar.is_hidden()
    # a table's bar shows once the table was clicked into, not on hover
    page.locator("#editor .blk-body").first.click()
    page.keyboard.press("Control+End")
    page.locator("[data-ins=table]").dispatch_event("mousedown")
    page.wait_for_selector("#editor table.md-table")
    page.locator("#editor table.md-table").hover()
    page.wait_for_timeout(200)
    assert not page.locator("#editor .tbl-tools").is_visible()
    page.locator("#editor table.md-table").dispatch_event("mousedown")
    page.wait_for_selector("#editor .tbl-tools:visible")
    page.locator("#editor .blk-body").first.click()
    page.wait_for_timeout(200)
    assert not page.locator("#editor .tbl-tools").is_visible()
    # Settings can switch the bar between blocks off
    page.locator("#btn-settings").click()
    page.locator("[data-test=setting-gapbar]").uncheck()
    page.keyboard.press("Escape")
    gap_y = page.evaluate("() => { const [a, b] = document.querySelectorAll('#editor .blk'); return (a.getBoundingClientRect().bottom + b.getBoundingClientRect().top) / 2; }")
    page.mouse.move(x, gap_y - 30)
    page.mouse.move(x, gap_y)
    page.wait_for_timeout(700)
    assert bar.is_hidden()
    assert h.api.init()["config"]["settings"]["gapBar"] is False
    page.locator("#btn-settings").click()
    page.locator("[data-test=setting-gapbar]").check()
    page.keyboard.press("Escape")
    assert not errors


def test_collection_from_a_rule_and_find_new_lines(app):
    """Seth, 2026-10-18: "create a collection with ALL lines that match a specific rule. And to be
    able to have that collection add new matches found in the database that aren't already in
    that collection"."""
    h, page, errors = app
    page.locator("#btn-new-menu").click()
    page.locator("[data-test=new-rule-collection]").click()
    page.wait_for_selector(".rule-dlg [data-test=rule-tags] [data-test=rule-tag]")
    dlg = page.locator(".rule-dlg")
    assert dlg.locator("[data-test=rule-count]").inner_text() == "Choose one or more tags."
    # the tags come as FLEx's tree; a group's box stands for every tag under it
    assert dlg.locator("[data-test=tag-tree-group][data-group=Arguments]").count() == 1
    dlg.locator("[data-test=rule-tag][data-tag=Topic]").check()
    page.wait_for_function("() => /^2 lines match/.test(document.querySelector('[data-test=rule-count]').textContent)")
    assert dlg.locator("[data-test=rule-preview] div").count() == 2
    dlg.locator("[data-test=rule-group][data-tag='group:Arguments']").check()
    page.wait_for_function("() => /^4 lines match/.test(document.querySelector('[data-test=rule-count]').textContent)")
    assert dlg.locator("[data-test=rule-tag][data-tag=Subject]").is_disabled()        # covered by its group
    assert dlg.locator("[data-test=rule-title]").get_attribute("placeholder") == "Lines tagged Topic, Arguments"
    dlg.locator("[data-test=rule-title]").fill("Topics and arguments")
    dlg.locator("[data-test=rule-ok]").click()
    page.wait_for_selector("#collection [data-test=coll-rule]")
    page.wait_for_function("document.querySelectorAll('#collection .coll-item').length === 4")
    assert page.locator("#note-title").input_value() == "Topics and arguments"
    assert page.locator("[data-test=coll-rule]").inner_text().startswith("⚑ Topic, all of Arguments")
    nid = h.api.list_collections()[0]["id"]
    note = h.api.get_note(nid)
    assert note["rule"] == {"tags": ["Topic", "group:Arguments"]} and note["body"].count("{{flex:text") == 4
    assert "seg=5-6 at=" in note["body"]                                                   # the spanning Topic is one line
    # nothing new yet
    page.locator("[data-test=coll-rule-update]").click()
    page.wait_for_selector(".toast:has-text('Nothing new')")
    # remove two lines by hand, then "Find new lines" brings them back, at the end and selected
    first = page.locator("#collection .coll-item").first
    first.locator("[data-test=coll-check]").check()
    page.locator("#collection .coll-item").nth(1).locator("[data-test=coll-check]").check()
    page.locator("[data-test=coll-sel-delete]").click()
    page.wait_for_function("document.querySelectorAll('#collection .coll-item').length === 2")
    page.wait_for_timeout(900)
    page.locator("[data-test=coll-rule-update]").click()
    page.wait_for_selector(".toast:has-text('2 new lines added')")
    page.wait_for_function("document.querySelectorAll('#collection .coll-item').length === 4")
    assert page.locator("#collection .coll-item.selected").count() == 2
    assert [c.inner_text() for c in page.locator("#collection .coll-num").all()] == ["(1)", "(2)", "(3)", "(4)"]
    body = without_flex_copies(h.api.get_note(nid)["body"])
    assert body.count("{{flex:text") == 4 and body.rstrip().endswith("}}")
    # the rule is edited in place: the header follows, the file too
    page.locator("[data-test=coll-rule-edit]").click()
    page.wait_for_selector(".rule-dlg [data-test=rule-tag]")
    assert page.locator(".rule-dlg [data-test=rule-title]").is_disabled()
    page.locator(".rule-dlg [data-test=rule-group][data-tag='group:Arguments']").uncheck()
    page.locator(".rule-dlg [data-test=rule-ok]").click()
    page.wait_for_function("() => document.querySelector('[data-test=coll-rule] .coll-rule-tags').textContent.trim() === '⚑ Topic'")
    assert h.api.get_note(nid)["rule"] == {"tags": ["Topic"]}
    # the picker's tag view offers the same, pre-ticked
    page.locator("#btn-new-menu").click()
    page.locator("[data-test=new-collection]").click()
    page.wait_for_selector("#collection .coll-add")
    page.locator("#collection button", has_text="Add from FLEx").click()
    page.wait_for_selector(".picker-tabs")
    page.locator(".picker-tabs button", has_text="FLEx tags").click()
    page.locator("[data-test=pick-tag]", has_text="Verb").click()
    page.wait_for_selector("[data-test=collect-tagged]")
    page.locator("[data-test=collect-tagged]").click()
    page.wait_for_selector(".rule-dlg [data-test=rule-tag]")
    assert page.locator(".rule-dlg [data-test=rule-tag][data-tag=Verb]").is_checked()
    page.keyboard.press("Escape")
    assert not errors


def test_promote_and_demote_all_headings_in_the_note_or_a_selection(app):
    """Seth, 2026-10-18: "the easy ability to promote and demote all headers in a note or within a
    selected range"."""
    h, page, errors = app
    new_note(page, "Outline")
    page.locator("#editor .blk-body").first.click()
    paste(page, "# A\n\nx\n\n## B\n\ny\n\n### C\n\nz")
    page.wait_for_timeout(300)
    heads = lambda: page.evaluate("() => __fsEditor.blocks.filter((b) => b.type === 'h').map((b) => b.src)")   # noqa: E731
    # the H menu: demote every heading in the note; Ctrl+Alt+[ promotes them again
    page.locator("[data-test=tb-heading]").dispatch_event("mousedown")
    assert page.locator("[data-test=demote-all]").inner_text().startswith("⇥ Demote all headings in the note")
    page.locator("[data-test=demote-all]").dispatch_event("mousedown")
    page.wait_for_function("() => __fsEditor.blocks[0].src === '## A'")
    assert heads() == ["## A", "### B", "#### C"]
    page.locator("#editor .blk-body").first.click()
    page.keyboard.press("Control+Alt+[")
    page.wait_for_function("() => __fsEditor.blocks[0].src === '# A'")
    assert heads() == ["# A", "## B", "### C"]
    # at the top already: promoting would merge two levels, so nothing moves
    page.keyboard.press("Control+Alt+[")
    page.wait_for_selector(".toast:has-text('already at level 1')")
    assert heads() == ["# A", "## B", "### C"]
    # a cross-block selection (B's block to C's block): only the headings in it move, and it stays selected
    blk = lambda t: page.locator("#editor .blk", has=page.locator(".blk-body", has_text=t)).first   # noqa: E731
    blk("B").locator(".blk-body").click()
    blk("C").locator(".blk-body").click(modifiers=["Shift"])
    page.wait_for_function("() => !!__fsEditor.msel")
    page.locator("[data-test=tb-heading]").dispatch_event("mousedown")
    assert page.locator("[data-test=demote-all]").inner_text().startswith("⇥ Demote all headings in the selection")
    page.locator("[data-test=demote-all]").dispatch_event("mousedown")
    page.wait_for_function("() => __fsEditor.blocks[2].src === '### B'")
    assert heads() == ["# A", "### B", "#### C"]
    assert page.evaluate("() => !!__fsEditor.msel")
    page.keyboard.press("Control+Alt+[")
    page.wait_for_function("() => __fsEditor.blocks[2].src === '## B'")
    assert heads() == ["# A", "## B", "### C"]
    # the ⋮ menu of a selected block has the same two rows
    blk("B").hover()
    blk("B").locator(".blk-handle button").dispatch_event("mousedown")
    page.locator(".popover .menu-item", has_text="Demote the headings here").click()
    page.wait_for_function("() => __fsEditor.blocks[2].src === '### B'")
    assert heads() == ["# A", "### B", "#### C"]
    page.wait_for_timeout(900)
    assert body_of(h).startswith("# A\n\nx\n\n### B\n\ny\n\n#### C"), body_of(h)
    # undo takes the whole step back
    page.keyboard.press("Escape")
    page.locator("#editor .blk-body").first.click()
    page.keyboard.press("Control+z")
    page.wait_for_function("() => __fsEditor.blocks[2].src === '## B'")
    assert not errors


def test_links_dialog_and_the_common_keyboard_shortcuts(app):
    """Seth, 2026-10-18: "a hyperlink feature to our app (button and keyboard shortcut … what
    common keyboard shortcuts we should add … Ctrl+Z, Ctrl+Y, Ctrl+K (hyperlink), Ctrl+I …)"."""
    h, page, errors = app
    new_note(page, "Links")
    page.locator("#editor .blk-body").first.click()
    page.keyboard.type("see docs here")
    page.wait_for_timeout(200)
    # Ctrl+K with "docs" selected: the selection is the text, the address gets https:// when it has no scheme
    page.evaluate("() => { const b = document.querySelector('#editor .blk-body'); FS.editor.setCaret(b, 4, 8); b.focus(); }")
    page.keyboard.press("Control+k")
    page.wait_for_selector(".link-dlg")
    assert page.locator("[data-test=link-text]").input_value() == "docs"
    page.locator("[data-test=link-url]").fill("example.org/x")
    page.locator("[data-test=link-ok]").click()
    page.wait_for_timeout(900)
    assert body_of(h) == "see [docs](https://example.org/x) here", body_of(h)
    # the caret inside the link shows the pill under it: the address, Open · Edit · Copy · Unlink
    # (Seth: "make it easy to click to follow or edit links")
    page.evaluate("() => { const b = document.querySelector('#editor .blk-body'); FS.editor.setCaret(b, 7); b.focus(); }")
    page.wait_for_selector("[data-test=link-pill]:not([hidden])")
    assert page.locator("#link-pill .lp-href").inner_text() == "https://example.org/x"
    # without clipboard permission (CI's Chromium) the copy falls back to a selected textarea: the
    # caret must come back to the link afterwards, or Edit finds no link under it (CI, 2026-10-20)
    page.evaluate("() => { navigator.clipboard.writeText = () => Promise.reject(new Error('no permission')); }")
    page.locator("[data-test=lp-copy]").click()
    page.wait_for_selector(".toast:has-text('Link copied')")
    assert page.evaluate("() => document.activeElement.classList.contains('blk-body')")       # the caret stayed in the note
    page.locator("[data-test=lp-edit]").click()
    page.wait_for_selector(".link-dlg")
    assert page.locator(".link-dlg .modal-title").inner_text() == "Edit link"
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)
    # the caret inside the link: Ctrl+K edits it; Update rewrites it in place
    page.evaluate("() => { const b = document.querySelector('#editor .blk-body'); FS.editor.setCaret(b, 7); b.focus(); }")
    page.keyboard.press("Control+k")
    page.wait_for_selector(".link-dlg")
    assert page.locator(".link-dlg .modal-title").inner_text() == "Edit link"
    assert page.locator("[data-test=link-url]").input_value() == "https://example.org/x" and page.locator("[data-test=link-text]").input_value() == "docs"
    page.locator("[data-test=link-text]").fill("the docs")
    page.locator("[data-test=link-ok]").click()
    page.wait_for_timeout(900)
    assert body_of(h) == "see [the docs](https://example.org/x) here", body_of(h)
    # Remove link keeps the text; the toolbar button opens the same dialog; a note link is a wikilink
    page.evaluate("() => { const b = document.querySelector('#editor .blk-body'); FS.editor.setCaret(b, 6); b.focus(); }")
    page.locator("[data-test=tb-link]").dispatch_event("mousedown")
    page.wait_for_selector("[data-test=link-remove]")
    page.locator("[data-test=link-remove]").click()
    page.wait_for_timeout(900)
    assert body_of(h) == "see the docs here", body_of(h)
    page.keyboard.press("End")
    page.keyboard.type(" and ")
    page.keyboard.press("Control+k")
    page.wait_for_selector(".link-dlg")
    page.locator("[data-test=link-kind]").select_option("note")
    page.locator("[data-test=link-note]").fill("Welcome to FLEx Scratchpad")
    page.locator("[data-test=link-ok]").click()
    page.wait_for_timeout(900)
    assert body_of(h) == "see the docs here and [[Welcome to FLEx Scratchpad]]", body_of(h)
    # a note link's pill opens the note; back in the note, Unlink keeps the title as text
    page.evaluate("() => { const b = document.querySelector('#editor .blk-body'); FS.editor.setCaret(b, b.textContent.length - 4); b.focus(); }")
    page.wait_for_selector("[data-test=link-pill]:not([hidden])")
    assert page.locator("[data-test=lp-open]").inner_text() == "Open note"
    page.locator("[data-test=lp-open]").click()
    page.wait_for_function("() => document.getElementById('note-title').value === 'Welcome to FLEx Scratchpad'")
    assert page.locator("[data-test=link-pill]").is_hidden()
    page.locator(".note-card", has_text="Links").first.click()
    page.wait_for_function("() => document.getElementById('note-title').value === 'Links'")
    page.evaluate("() => { const b = document.querySelector('#editor .blk-body'); FS.editor.setCaret(b, b.textContent.length - 4); b.focus(); }")
    page.wait_for_selector("[data-test=link-pill]:not([hidden])")
    page.locator("[data-test=lp-unlink]").click()
    page.wait_for_timeout(900)
    assert body_of(h) == "see the docs here and Welcome to FLEx Scratchpad", body_of(h)
    assert page.locator("[data-test=link-pill]").is_hidden()
    # the other common keys: Ctrl+E code, Ctrl+Shift+X strike, the lists, plain text, a paragraph above, duplicate
    page.keyboard.press("Control+Enter")
    page.keyboard.type("code strike")
    page.evaluate("() => { const b = document.querySelectorAll('#editor .blk-body')[1]; FS.editor.setCaret(b, 0, 4); b.focus(); }")
    page.keyboard.press("Control+e")
    page.evaluate("() => { const b = document.querySelectorAll('#editor .blk-body')[1]; FS.editor.setCaret(b, 7, 13); b.focus(); }")
    page.keyboard.press("Control+Shift+x")
    page.wait_for_timeout(900)
    assert body_of(h).endswith("`code` ~~strike~~"), body_of(h)
    page.keyboard.press("Control+Shift+Digit8")
    page.wait_for_timeout(300)
    assert page.evaluate("() => __fsEditor.blocks[1].src") == "- `code` ~~strike~~"
    page.keyboard.press("Control+Shift+Digit7")
    page.wait_for_timeout(300)
    assert page.evaluate("() => __fsEditor.blocks[1].src") == "1. `code` ~~strike~~"
    page.keyboard.press("Control+Shift+Digit9")
    page.wait_for_timeout(300)
    assert page.evaluate("() => __fsEditor.blocks[1].src") == "- [ ] `code` ~~strike~~"
    page.keyboard.press("Control+Alt+Digit0")
    page.wait_for_timeout(300)
    assert page.evaluate("() => __fsEditor.blocks[1].src") == "`code` ~~strike~~"
    page.keyboard.press("Control+Shift+Enter")
    page.keyboard.type("above")
    page.wait_for_timeout(300)
    assert page.evaluate("() => __fsEditor.blocks.map((b) => b.src)")[1:3] == ["above", "`code` ~~strike~~"]
    page.keyboard.press("Control+d")
    page.wait_for_timeout(300)
    assert page.evaluate("() => __fsEditor.blocks.map((b) => b.src)")[1:3] == ["above", "above"]
    # undo / redo still take the keys; Ctrl+/ lists everything; F2 goes to the title
    page.keyboard.press("Control+z")
    page.wait_for_timeout(200)
    assert page.evaluate("() => __fsEditor.blocks.map((b) => b.src)")[1:3] == ["above", "`code` ~~strike~~"]
    page.keyboard.press("Control+y")
    page.wait_for_timeout(200)
    assert page.evaluate("() => __fsEditor.blocks.map((b) => b.src)")[1:3] == ["above", "above"]
    page.keyboard.press("Control+Slash")
    page.wait_for_selector(".shortcuts-dlg")
    assert page.locator(".shortcuts-dlg kbd", has_text="Ctrl+K").count() == 1
    page.keyboard.press("Escape")
    page.keyboard.press("F2")
    assert page.evaluate("() => document.activeElement.id") == "note-title"
    # a link in a table cell
    page.locator("#editor .blk-body").first.click()
    page.keyboard.press("Control+End")
    page.locator("[data-ins=table]").dispatch_event("mousedown")
    page.wait_for_selector("#editor table.md-table")
    page.locator("#editor table.md-table td .cell-view").first.dispatch_event("mousedown")
    page.wait_for_selector("#editor .cell-edit")
    page.keyboard.press("Control+k")
    page.wait_for_selector(".link-dlg")
    page.locator("[data-test=link-text]").fill("site")
    page.locator("[data-test=link-url]").fill("https://a.b")
    page.locator("[data-test=link-ok]").click()
    page.wait_for_timeout(900)
    assert "| [site](https://a.b) |" in body_of(h) or "[site](https://a.b)" in body_of(h), body_of(h)
    # the hidden readable copy of a FLEx object (Seth: "needs to not accidentally expose our hidden md flex
    # hyperlinks, the ones that end with flex-copy") is never the link under the caret, and survives a link next to it
    tab = h.api.init()["config"]["tabs"][0]["dir"]
    n = h.api.create_note(tab, "", "Copies", "See {{flex:text %s seg=1}}[DOG 1.1: \u2018x\u2019](silfw://localhost/link?app=flex&guid=%s \"flex-copy\") after." % (T_STORY, T_STORY))
    page.reload()
    page.wait_for_selector(".note-card")
    page.locator(".note-card", has_text="Copies").first.click()
    page.wait_for_selector("#editor .md-embed")
    page.evaluate("() => { const b = document.querySelector('#editor .blk-body'); FS.editor.setCaret(b, b.textContent.indexOf(' after')); b.focus(); }")
    page.keyboard.press("Control+k")
    page.wait_for_selector(".link-dlg")
    assert page.locator(".link-dlg .modal-title").inner_text() == "Insert link"          # not "Edit link" on the hidden copy
    page.locator("[data-test=link-text]").fill("ref")
    page.locator("[data-test=link-url]").fill("https://x.y")
    page.locator("[data-test=link-ok]").click()
    page.wait_for_timeout(1200)
    assert body_of(h) == "See {{flex:text %s seg=1}}[ref](https://x.y) after." % T_STORY, body_of(h)
    raw = h.api.get_note(n["id"])["body"]
    assert raw.count('"flex-copy")') == 1 and "[ref](https://x.y)" in raw, raw
    assert not errors


# ---------------------------------------------------------------------------------- text charts
CHART = "d15c0000-0000-4000-8000-00000000c001"
TEXT = "9b1c2d3e-4f50-4a6b-8c7d-0e1f2a3b0001"   # the demo story, the chart's text


def test_text_chart_rows_from_the_picker_with_headings_markers_and_translations(app):
    """Seth, 2026-10-18: a text chart, a range of its rows (the column headings always included),
    FLEx's markers drawn, the free translations spliced in."""
    h, page, errors = app
    new_note(page, "Charted")
    page.click(".blk-body")
    page.keyboard.press("Control+Shift+L")
    page.locator(".picker-tabs button", has_text="Text charts").click()
    page.wait_for_selector("[data-test=pick-chart]")
    page.locator("[data-test=pick-chart]").first.click()
    page.wait_for_selector(".picker-preview tr.crow")
    rows = page.locator(".picker-preview tr.crow")
    rows.nth(1).click()
    rows.nth(3).click()
    page.locator("[data-test=insert-chart-rows]").click()
    page.wait_for_selector("#editor .chart-obj tr.crow")
    saved = lambda: page.wait_for_function("() => document.getElementById('save-state').textContent === 'Saved'", timeout=5000)  # noqa: E731
    saved()
    body = body_of(h)
    assert "{{flex:chart %s rows=2-4 at=" % CHART in body, body
    obj = page.locator("#editor .chart-obj")
    assert obj.locator("thead th.th-group").evaluate_all("els => els.map((e) => e.textContent)") == ["Prenuclear", "Nucleus", "Postnuclear"]
    assert "Subject" in obj.locator("thead th.th-col").all_inner_texts()
    assert obj.locator("tbody tr.crow th.rlab").evaluate_all("els => els.map((e) => [...e.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join(''))") == ["1b", "2a", "2b"]   # the ▶ buttons aside
    assert "rows 1b–2b of 7" in obj.locator("[data-test=chart-range]").inner_text()
    assert obj.locator(".cmoved").inner_text() == "‹‹" and obj.locator(".cclause").inner_text() == "[2a]"
    # the free translations: one row after each segment's rows, naming them (2a and 2b share a segment)
    frees = obj.locator("tr.cfree-row")
    assert frees.count() == 2
    assert "Yesterday the child saw the river." in frees.nth(0).inner_text() and frees.nth(0).locator(".cfree-rows").inner_text() == "1b"
    assert frees.nth(1).locator(".cfree-rows").inner_text() == "2a–2b"
    assert obj.locator("tr.cl-speech th.rlab").inner_text().strip().lstrip("▶§¶") == "2a"
    # a word styled from its popover; a column from its heading
    obj.locator("tr.crow[data-label='1b'] td[data-col='3'] .cw").first.click()
    page.locator(".popover button.tog", has_text="Bold").click()
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    saved()
    assert "b=r2c3.1" in body_of(h), body_of(h)
    page.locator("#editor .chart-obj thead th.th-col", has_text="Verb").click()
    page.locator(".popover .sw").nth(1).click()
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    saved()
    assert "hl[#ffd6a5]=c4" in body_of(h), body_of(h)
    assert page.locator("#editor .chart-obj td[data-col='4'].st-hl").count() == 3
    # the ⋯ menu: the free translations as a column spanning the rows of one segment
    page.locator("#editor .chart-obj [data-test=chart-menu]").click()
    page.locator(".popover select").first.select_option("col")
    page.wait_for_selector("#editor .chart-obj td.cfree")
    assert page.locator("#editor .chart-obj td.cfree").nth(1).get_attribute("rowspan") == "2"
    saved()
    assert "free=col" in body_of(h)
    # collapsed: a chip naming the chart and its rows
    page.locator("#editor .chart-obj [data-test=collapse-obj]").click()
    page.wait_for_selector("#editor .flex-collapsed.kind-chart")
    chip = page.locator("#editor .flex-collapsed.kind-chart")
    page.wait_for_function("() => document.querySelector('#editor .flex-collapsed.kind-chart .cttl').textContent.includes('Story chart')")
    assert chip.locator(".crange").inner_text() == "rows 1b–2b"
    assert not errors


def test_a_chart_gets_a_readable_copy_and_exports(app):
    h, page, errors = app
    new_note(page, "Chart export")
    page.keyboard.type("Intro")
    page.keyboard.press("Enter")
    page.keyboard.type("{{flex:chart %s rows=1-2}}" % CHART)
    page.keyboard.press("Enter")
    page.wait_for_selector("#editor .chart-obj tr.crow")
    page.wait_for_function("() => document.getElementById('save-state').textContent === 'Saved'", timeout=5000)
    page.locator("#editor .blk-body").first.click()
    page.keyboard.press("End")
    page.keyboard.type(" more")
    page.wait_for_function("() => document.getElementById('save-state').textContent === 'Saved'", timeout=5000)
    page.wait_for_timeout(600)
    notes = [n for n in h.api._nb.list_notes() if n["title"] == "Chart export"]
    raw = h.api.get_note(notes[0]["id"])["body"]
    assert '[Story chart — The dog and the river, rows 1a–1b](silfw://' in raw and '"flex-copy")' in raw, raw
    fence = raw.split("```flex-copy\n")[1].split("\n```")[0]
    assert fence.splitlines()[0].strip().startswith("Prenuclear") and "1b  Haŋa/yesterday" in fence and "‹‹1b" in fence, fence
    html_path, docx_path = str(h.tmp / "chart.html"), str(h.tmp / "chart.docx")
    html = page.evaluate("""async ([hp, dp]) => {
      const api = window.pywebview.api;
      const notes = await api.list_notes(); const note = (await Promise.all(notes.map((n) => api.get_note(n.id)))).find((n) => n.title === 'Chart export');
      const editor = new FS.Editor(document.createElement('div'), {}); editor.load(FS.flexcopy.strip(note.body));
      const doc = await FS.exporter.buildDoc(note, editor);
      await api.export_note_html(note.id, FS.exporter.toHtml(doc), hp);
      await api.export_note_docx(note.id, doc, dp);
      return FS.exporter.toHtml(doc);
    }""", [html_path, docx_path])
    assert 'class="tchart"' in html and "Prenuclear" in html and "Haŋa" in html and "The dog slept." in html and "‹‹1b" in html, html[:400]
    import zipfile
    xml = zipfile.ZipFile(docx_path).read("word/document.xml").decode("utf-8")
    assert "Prenuclear" in xml and "Haŋa" in xml and "The dog slept." in xml and '<w:gridSpan w:val="3"/>' in xml
    # FLEx's own chart XML, from the object's menu
    out = h.api.export_chart(CHART, "xml", [1, 2], path=str(h.tmp / "c.xml"))
    assert '<row type="normal" id="1a"' in Path(out).read_text(encoding="utf-8")
    assert not errors


def test_a_chart_note_with_custom_columns(app):
    """Seth, 2026-10-18: a chart note — one text chart with the user's own columns (a choice list
    shared by the notebook, notes, a rule from the markers and columns) and styles, all saved in the
    note's file as tables and found by search."""
    h, page, errors = app
    page.locator("#btn-new-menu").click()
    page.locator("[data-test=new-chart-note]").click()
    page.wait_for_selector("[data-test=pick-chart-note]")
    page.locator("[data-test=pick-chart-note]").first.click()
    page.wait_for_selector("#chartnote .tchart tr.crow")
    assert page.locator("#chartnote tr.crow").count() == 7
    # the view scrolls (Seth, 2026-10-18: "I can't scroll down" — a 65-row chart ran off the pane)
    assert page.evaluate("getComputedStyle(document.getElementById('chartnote')).overflowY") == "auto"
    assert page.evaluate("() => { const e = document.getElementById('chartnote'); return e.clientHeight > 0 && e.clientHeight <= document.getElementById('editor-pane').clientHeight; }")
    assert page.input_value("#note-title") == "Story chart — The dog and the river"
    saved = lambda: page.wait_for_function("() => document.getElementById('save-state').textContent === 'Saved'", timeout=5000)  # noqa: E731
    # a notes column, typed into
    page.locator("[data-test=cn-add-col]").click()
    page.fill("[data-test=cn-col-name]", "Comment")
    page.select_option("[data-test=cn-col-kind]", "notes")
    page.locator("[data-test=cn-col-save]").click()
    page.wait_for_selector("#chartnote th.th-x")
    page.locator("#chartnote tr.crow[data-label='1b'] td.xcell .xval").click()
    page.wait_for_selector("[data-test=xedit]")
    page.keyboard.type("Subject fronted")
    page.keyboard.press("Enter")
    page.wait_for_selector("#chartnote tr.crow[data-label='1b'] td.xcell .xval")
    saved()
    # a choice-list column with a new project-wide list
    page.locator("[data-test=cn-add-col]").click()
    page.fill("[data-test=cn-col-name]", "Status")
    page.select_option("[data-test=cn-col-kind]", "list")
    page.wait_for_selector("[data-test=cn-list-name]")
    page.fill("[data-test=cn-list-name]", "Information status")
    page.fill("[data-test=cn-list-opts]", "new\ngiven\ncontrast")
    page.locator("[data-test=cn-col-save]").click()
    page.wait_for_function("() => document.querySelectorAll('#chartnote th.th-x').length === 2")
    page.locator("#chartnote tr.crow[data-label='1a'] td.xcell-list .xval").click()
    page.wait_for_selector("#chartnote select.xsel")
    page.select_option("#chartnote select.xsel", "given")
    page.wait_for_function("() => document.querySelector(\"#chartnote tr.crow[data-label='1a'] td.xcell-list .xval\").textContent === 'given'")
    saved()
    assert h.api.chart_lists() == {"Information status": {"options": ["new", "given", "contrast"], "open": True}}
    # a rule column: text per row, a row style from a marker, a list column's value as a term
    page.locator("[data-test=cn-add-col]").click()
    page.fill("[data-test=cn-col-name]", "Role")
    page.select_option("[data-test=cn-col-kind]", "rule")
    page.wait_for_selector("[data-test=cn-builder]")
    # THE BUILDER (Seth, 2026-10-19: "a UI for building formulas rather than just a query language"): a new
    # rule opens in it; conditions are picked from the chart's markers and columns and it writes the text
    assert page.locator("[data-test=cn-rule-mode] .seg-btn.on").inner_text() == "Builder"
    page.locator("[data-test=rb-add-cond]").click()
    page.select_option("[data-test=rb-cond] [data-test=rb-what]", "marker")
    page.select_option("[data-test=rb-cond] [data-test=rb-val]", "New")
    page.fill("[data-test=rb-out]", "N")
    page.select_option("[data-test=rb-scope]", "row")
    page.locator("[data-test=rb-hl]").check()
    page.wait_for_function("() => document.querySelector('[data-test=cn-rule]').value === 'marker:New → N [row hl]'")
    # a second case: the words of ONE column against a pattern, in a chosen writing system when the chart has one
    page.locator("[data-test=rb-add-case]").click()
    page.locator("[data-test=rb-case]").nth(1).locator("[data-test=rb-add-cond]").click()
    cond2 = page.locator("[data-test=rb-case]").nth(1).locator("[data-test=rb-cond]")
    cond2.locator("[data-test=rb-what]").select_option("txt")
    cond2.locator("[data-test=rb-how]").select_option("regex")
    cond2.locator("[data-test=rb-val]").fill("^kabir$")
    cond2.locator("[data-test=rb-incol]").select_option("Subject")
    page.locator("[data-test=rb-case]").nth(1).locator("[data-test=rb-out]").fill("K")
    page.wait_for_function("() => document.querySelector('[data-test=cn-rule]').value === 'marker:New → N [row hl]; col:Subject[txt:/^kabir$/] → K'")
    page.wait_for_function("() => (document.querySelector('.cn-preview') || {}).textContent.includes('“K”: 2 rows')")
    # the text tab shows the same rule; typing there is read back into the builder
    page.locator("[data-test=cn-rule-text]").click()
    assert page.locator("[data-test=cn-rule]").input_value() == "marker:New → N [row hl]; col:Subject[txt:/^kabir$/] → K"
    page.fill("[data-test=cn-rule]", "marker:new → N [row hl#fde68a]; Status:given → G; col:Subject → S")
    page.locator("[data-test=cn-rule-builder]").click()
    page.wait_for_function("() => document.querySelectorAll('[data-test=rb-case]').length === 3")
    assert page.locator("[data-test=rb-case]").nth(1).locator("[data-test=rb-what]").input_value() == "list"
    assert page.locator("[data-test=cn-rule]").input_value() == "marker:new → N [row hl#fde68a]; Status:given → G; col:Subject → S"
    page.wait_for_function("() => (document.querySelector('.cn-preview') || {}).textContent.includes('row')")
    page.locator("[data-test=cn-col-save]").click()
    page.wait_for_function("() => document.querySelectorAll('#chartnote th.th-x').length === 3")
    roles = page.locator("#chartnote tr.crow td.xcell-rule").all_inner_texts()
    assert roles == ["N", "S", "", "", "S", "S", "S"], roles          # 1a: the marker case comes first; 2a / 2b have no Subject
    # MARKER CHIPS AND A JOINED ROW (Seth, 2026-10-19): a column that shows the row's markers as chips, and a
    # `join` case that takes the line away between the row and the one above (a ^ShdArg-style continuation)
    page.locator("[data-test=cn-add-col]").click()
    page.fill("[data-test=cn-col-name]", "Shared")
    page.select_option("[data-test=cn-col-kind]", "rule")
    page.wait_for_selector("[data-test=cn-builder]")
    page.locator("[data-test=cn-rule-text]").click()
    page.fill("[data-test=cn-rule]", "marker:/^(New|Given)$/ → @markers [join row hl#fde68a]")
    page.wait_for_function("() => (document.querySelector('.cn-preview') || {}).textContent.includes('2 rows')")
    page.locator("[data-test=cn-col-save]").click()
    page.wait_for_function("() => document.querySelectorAll('#chartnote th.th-x').length === 4")
    chips = page.locator("#chartnote tr.crow td.xcell-rule .ctag.xmark")
    assert chips.all_inner_texts() == ["new", "giv"], chips.all_inner_texts()
    assert page.locator("#chartnote tr.crow[data-label='2c']").evaluate("(e) => e.classList.contains('join-up')")
    assert page.locator("#chartnote tr.crow[data-label='2b']").evaluate("(e) => e.classList.contains('join-down')")
    assert page.locator("#chartnote tr.crow[data-label='2c'] td.ccell").first.evaluate("(e) => getComputedStyle(e).borderTopColor") == "rgba(0, 0, 0, 0)"
    assert page.locator("#chartnote tr.crow[data-label='2b']").evaluate("(e) => e.style.background") != ""   # the row style covers both rows
    assert page.locator("#chartnote tr.crow[data-label='1a']").evaluate("(e) => e.classList.contains('join-up')") is False   # the first row has nothing above
    saved()
    body = page.evaluate("() => window.__fsChartNote.markdown()")
    assert "## Custom columns" in body and "| Status | list | Information status |" in body and "| Role | rule | marker:new" in body
    assert "| 1b #" in body and "| Subject fronted |" in body and "| 1a #" in body and "| given |" in body, body
    # the exports carry the custom columns and the rule's row style (Seth, 2026-10-18: "pretty exports for chart-type notes")
    html_path, docx_path = str(h.tmp / "cn.html"), str(h.tmp / "cn.docx")
    html = page.evaluate("""async ([hp, dp]) => {
      const api = window.pywebview.api; const id = document.querySelector('.note-card.active').dataset.id; const note = await api.get_note(id);
      const doc = await FS.exporter.buildDoc(note, window.__fsChartNote.asEditor());
      await api.export_note_html(id, FS.exporter.toHtml(doc), hp); await api.export_note_docx(id, doc, dp); await api.export_note_xlsx(id, doc, dp.replace('.docx', '.xlsx')); return FS.exporter.toHtml(doc);
    }""", [html_path, docx_path])
    try:
        import openpyxl
        wb = openpyxl.load_workbook(str(h.tmp / "cn.xlsx"))
        assert wb.sheetnames == ["Note", "Chart", "Chart rows"], wb.sheetnames
        ws = wb["Chart rows"]; head = [c.value for c in ws[1]]
        rows = [{k: v for k, v in zip(head, [c.value for c in r])} for r in ws.iter_rows(min_row=2)]
        assert [r["Role"] for r in rows] == ["N", "S", None, None, "S", "S", "S"] and rows[1]["Comment"] == "Subject fronted" and rows[0]["Status"] == "given", rows
        assert rows[0]["Nucleus/Subject"] == "Kabir" and rows[0]["Markers"] == "New"
    except ImportError:
        pass
    assert '<th class="xh" rowspan="2">Role</th>' in html and "Subject fronted" in html and "background:#fde68a" in html and ">given<" in html, html[:600]
    import zipfile
    xml = zipfile.ZipFile(docx_path).read("word/document.xml").decode("utf-8")
    assert "Subject fronted" in xml and ">Role<" in xml and 'w:fill="FDE68A"' in xml.upper().replace('W:FILL', 'w:fill'), xml[:300]
    # found by search, and still there after a reload
    nid = page.evaluate("() => window.__fsChartNote && document.querySelector('.note-card.active').dataset.id")
    assert any(hit["id"] == nid for hit in h.api.search("fronted"))
    page.reload()
    page.wait_for_selector(".note-card")
    page.locator(".note-card", has_text="Story chart").click()
    page.wait_for_selector("#chartnote th.th-x")
    assert page.locator("#chartnote tr.crow[data-label='1b'] td.xcell .xval").first.inner_text() == "Subject fronted"
    # the row labels (with the ▶ buttons) are frozen on the left by default (Seth, 2026-10-18)
    assert page.locator("#chartnote .tchart tr.crow th.rlab[data-frz='l']").count() == 7
    assert page.evaluate("getComputedStyle(document.querySelector('#chartnote .tchart tr.crow th.rlab')).position") == "sticky"
    # a custom column moved to the LEFT of the chart and FROZEN (Seth: "freeze columns … for custom columns, on either or both sides")
    page.locator("#chartnote th.th-x", has_text="Comment").locator("button").click()
    page.locator(".popover .menu-item", has_text="Move to the left of the chart").click()
    page.wait_for_selector("#chartnote th.th-x-left")
    heads = [t.split("\n")[0] for t in page.locator("#chartnote .tchart thead tr").first.locator("th").all_inner_texts()]
    assert heads[:7] == ["▶#", "Comment", "PRENUCLEAR", "NUCLEUS", "POSTNUCLEAR", "Status", "Role"], heads
    page.locator("#chartnote th.th-x-left button").click()
    page.locator(".popover .menu-item", has_text="Freeze").click()
    page.wait_for_selector("#chartnote td.xcell-left[data-frz='l']")
    saved()
    body = page.evaluate("() => window.__fsChartNote.markdown()")
    assert "| Column | Kind | Settings | Place |" in body and "| Comment | notes | | left frozen |" in body, body
    assert page.evaluate("document.querySelector('#chartnote td.xcell-left').style.left") not in ("", "0px")   # placed after the label column
    # the dialog shows the place too
    page.locator("#chartnote th.th-x-left button").click()
    page.locator(".popover .menu-item", has_text="Rename / settings").click()
    assert page.input_value("[data-test=cn-col-side]") == "left" and page.is_checked("[data-test=cn-col-frozen]")
    page.keyboard.press("Escape")
    # the exports put a left-side column before the FLEx columns
    html = page.evaluate("async () => { const api = window.pywebview.api; const id = document.querySelector('.note-card.active').dataset.id; const note = await api.get_note(id); return FS.exporter.toHtml(await FS.exporter.buildDoc(note, window.__fsChartNote.asEditor())); }")
    assert html.index('<th class="xh" rowspan="2">Comment</th>') < html.index(">Prenuclear<") < html.index('<th class="xh" rowspan="2">Status</th>'), html[:800]
    # another chart in the same note (Seth: "change the text chart source for a text chart note"): the front matter and the view embed follow
    page.locator("#chartnote [data-test=chart-menu]").click()
    page.locator("[data-test=chart-change]").click()
    page.wait_for_selector("[data-test=pick-chart-change]")
    assert page.locator("[data-test=pick-chart-change]", has_text="this one").count() == 1
    page.locator("[data-test=pick-chart-change]", has_text="Topic-Comment").click()
    page.wait_for_function("() => document.querySelectorAll('#chartnote tr.crow').length === 2")
    saved()
    note = h.api.get_note(nid)
    assert note["chart"] == "d15c0000-0000-4000-8000-00000000c002" and note["body"].startswith("{{flex:chart d15c0000-0000-4000-8000-00000000c002"), note["body"][:120]
    assert "| Comment | notes | | left frozen |" in note["body"]        # the custom columns stay
    assert page.locator("#chartnote th.th-col").all_inner_texts() == ["Topic", "Comment", "Tail"]
    assert not errors


def test_chart_options_one_column_hide_empty_zoom_and_the_boundary_under_the_free_row(app):
    """Seth, 2026-10-18: ⚑ on every chart; "Hide this column" from its heading; "hide empty
    columns"; zoom; the one-column view with column labels and visual filters; the sentence /
    paragraph boundary drawn under the free translation row."""
    h, page, errors = app
    new_note(page, "Chart options")
    page.keyboard.type("{{flex:chart d15c0000-0000-4000-8000-00000000c002}}")
    page.keyboard.press("Enter")
    page.wait_for_selector("#editor .chart-obj tr.crow")
    obj = page.locator("#editor .chart-obj")
    src = lambda: page.evaluate("() => window.__fsEditor.getMarkdown()")  # noqa: E731
    # the ⚑ button is there although this chart has no markers (its text's tags and the visual filters are switched from it)
    assert obj.locator("[data-test=marker-btn]").count() == 1
    obj.locator("[data-test=marker-btn]").click()
    page.wait_for_selector(".popover [data-test=tag-scope-pick]")
    assert "What this chart draws" in page.locator(".popover").inner_text()
    page.keyboard.press("Escape")
    # the boundary: row 2 ends a paragraph; its free translation row follows it, so the double rule is under THAT row
    assert obj.locator("tr.crow[data-label='2'].end-para").count() == 0
    assert obj.locator("tr.cfree-row.end-para").count() == 1 and obj.locator("tr.cfree-row.end-sent").count() == 2
    # hide the EMPTY columns (nobody filled Tail): the menu's checkbox, `empty=off` in the note
    assert obj.locator("th.th-col").all_inner_texts() == ["Topic", "Comment", "Tail"]
    obj.locator("[data-test=chart-menu]").click()
    page.locator("[data-test=chart-hide-empty]").check()
    page.wait_for_function("() => document.querySelectorAll('#editor .chart-obj th.th-col').length === 2")
    assert "empty=off" in src()
    page.keyboard.press("Escape")
    obj.locator("[data-test=chart-menu]").click()
    page.locator("[data-test=chart-hide-empty]").uncheck()
    page.wait_for_function("() => document.querySelectorAll('#editor .chart-obj th.th-col').length === 3")
    assert "empty=off" not in src()
    page.keyboard.press("Escape")
    # hide a column from its heading (the "hide columns" feature, now one click away)
    obj.locator("th.th-col", has_text="Comment").click()
    page.locator(".popover [data-test=hide-col]").click()
    page.wait_for_function("() => document.querySelectorAll('#editor .chart-obj th.th-col').length === 2")
    assert "cols=c33,c35" in src(), src()
    assert obj.locator("th.th-col").all_inner_texts() == ["Topic", "Tail"]
    # zoom
    obj.locator("[data-test=chart-menu]").click()
    page.locator("[data-test=chart-zoom-in]").click()
    page.wait_for_function("() => document.querySelector('#editor .chart-obj').style.getPropertyValue('--cz') === '1.1'")
    assert "zoom=110" in src()
    assert page.locator("[data-test=chart-zoom]").inner_text() == "110%"
    page.keyboard.press("Escape")
    size = lambda: page.evaluate("parseFloat(getComputedStyle(document.querySelector('#editor .chart-obj .cw .il-txt')).fontSize)")  # noqa: E731
    assert abs(size() - 15.5 * 1.1) < 0.2, size()
    # every column back (the menu's column checkboxes), then the one-column view: one "Text" column,
    # each row in one cell, word groups labelled with their column
    obj.locator("[data-test=chart-menu]").click()
    page.locator(".popover label.chart-col", has_text="Comment").locator("input").check()
    page.wait_for_function("() => document.querySelectorAll('#editor .chart-obj th.th-col').length === 3")
    page.keyboard.press("Escape")
    obj.locator("[data-test=chart-view]").click()
    page.wait_for_selector("#editor .chart-obj.flat")
    assert "view=flat" in src()
    assert obj.locator("th.th-col").all_inner_texts() == ["Text"]
    r1 = obj.locator("tr.crow[data-label='1'] td.ccell")
    assert r1.count() == 1 and r1.locator(".cflat-g").count() == 2
    assert r1.locator(".cflat-lab").all_inner_texts() == ["Top", "Com"]
    assert r1.locator(".cflat-g").nth(0).get_attribute("title") == "Topic"
    # a column visual-filter rule styles the group (the same `column:` rules as on examples)
    page.evaluate("async () => { const c = await window.pywebview.api.set_tag_styles('project', FS.tagstyles.context().project, [{tag: 'column:Topic', br: 'sq', b: true}]); FS.tagstyles.setConfig(c); FS.emit('tagstyles'); }")
    page.wait_for_selector("#editor .chart-obj .cflat-br")
    assert r1.locator(".cflat-g").nth(0).locator(".cflat-br").all_inner_texts() == ["[", "]"]
    # and back
    obj.locator("[data-test=chart-view]").click()
    page.wait_for_function("() => !document.querySelector('#editor .chart-obj.flat')")
    assert "view=flat" not in src()
    # the parts of ONE chart cell share a box: in the story chart, row 1a's Post-I cell is a marker on its own,
    # and a cell holding words AND a marker keeps them together (Seth: "inside the same border as the cell")
    new_note(page, "Flat markers")
    page.keyboard.type("{{flex:chart %s rows=1 view=flat}}" % CHART)
    page.keyboard.press("Enter")
    page.wait_for_selector("#editor .chart-obj.flat tr.crow")
    g = page.locator("#editor .chart-obj.flat tr.crow[data-label='1a'] .cflat-g")
    assert g.evaluate_all("els => els.map((e) => e.title)") == ["Nucleus › Subject", "Nucleus › Verb", "Postnuclear › Inner"]
    assert g.nth(2).locator(".ctag").count() == 1 and g.nth(2).locator(".cflat-lab").inner_text() == "Post-I"
    # MARKERS IN CELLS WITH NO WORDS (Seth, 2026-10-19): the ⋯ switch hides them (`emptymarkers=off`), and a
    # one-column box whose every chip is hidden draws nothing — no tile, border or label
    flat = page.locator("#editor .chart-obj.flat")
    flat.locator("[data-test=chart-menu]").click()
    page.locator("[data-test=chart-empty-markers]").uncheck()
    page.wait_for_function("() => document.querySelectorAll('#editor .chart-obj.flat .ctag.hidden[data-empty]').length === 1")
    page.keyboard.press("Escape")
    assert "emptymarkers=off" in src(), src()
    assert flat.locator("tr.crow[data-label='1a'] .cflat-g.cflat-void").count() == 1
    assert flat.locator("tr.crow[data-label='1a'] .cflat-g.cflat-void").evaluate("(e) => getComputedStyle(e).display") == "none"
    assert flat.locator("tr.crow[data-label='1a'] .cflat-g:not(.cflat-void)").count() == 2
    # a marker's own rule overrides the chart's switch: New shown in an empty cell
    flat.locator("[data-test=marker-btn]").click()
    page.wait_for_selector("[data-test=tag-popover] .tagrow[data-tag='New']")
    page.locator("[data-test=tag-popover] .tagrow[data-tag='New'] [data-test=tag-style]").click()
    page.locator("[data-test=tag-popover] [data-test=tag-empty]").select_option("show")
    page.wait_for_function("() => document.querySelectorAll('#editor .chart-obj.flat .ctag:not(.hidden)').length === 1")
    page.keyboard.press("Escape")
    assert flat.locator("tr.crow[data-label='1a'] .cflat-g.cflat-void").count() == 0
    page.wait_for_function("() => window.__fsEditor.getMarkdown().includes('marker%3ANew:empty')")
    assert not errors


def test_a_column_is_styled_from_the_charts_flag_popover(app):
    """Seth, 2026-10-18: "apply specific styles to specific columns … and configure them myself":
    the ⚑ popover lists the chart's columns; a column's style tints its cells (and heading), its
    box hides the column; the same column: rules the one-column view and examples use."""
    h, page, errors = app
    new_note(page, "Column styles")
    page.keyboard.type("{{flex:chart d15c0000-0000-4000-8000-00000000c002}}")
    page.keyboard.press("Enter")
    page.wait_for_selector("#editor .chart-obj tr.crow")
    obj = page.locator("#editor .chart-obj")
    src = lambda: page.evaluate("() => window.__fsEditor.getMarkdown()")  # noqa: E731
    obj.locator("[data-test=marker-btn]").click()
    page.wait_for_selector(".popover .tagrow[data-tag='Comment']")
    names = page.locator(".popover .tagrow").evaluate_all("els => els.map((e) => e.dataset.tag)")
    assert all(c in names for c in ["Topic", "Comment", "Tail"]) and "Subject" in names, names   # the text's tags and the chart's columns
    # the look is written at the chosen scope: this chart by default (its embed)
    page.locator(".popover .tagrow[data-tag='Comment'] [data-test=tag-style]").click()
    page.locator(".popover [data-test=tag-tile]").click()
    page.wait_for_function("() => document.querySelector(\"#editor .chart-obj tr.crow[data-label='1'] td[data-col='34']\").classList.contains('col-styled')")
    assert "column" in src() and "tile" in src(), src()
    cell = obj.locator("tr.crow[data-label='1'] td[data-col='34']")
    assert cell.evaluate("e => e.style.background") != ""
    assert obj.locator("th.th-col", has_text="Comment").evaluate("e => e.classList.contains('col-styled')")
    assert obj.locator("tr.crow[data-label='1'] td[data-col='33']").evaluate("e => e.classList.contains('col-styled')") is False
    # bold too; then hidden: the column leaves the table
    page.locator(".popover [data-test=tag-b]").click()
    page.wait_for_function("() => document.querySelector(\"#editor .chart-obj tr.crow[data-label='1'] td[data-col='34']\").style.fontWeight === '700'")
    page.locator(".popover .tagrow[data-tag='Comment'] [data-test=tag-toggle]").click()
    page.wait_for_function("() => document.querySelectorAll('#editor .chart-obj th.th-col').length === 2")
    assert obj.locator("th.th-col").all_inner_texts() == ["Topic", "Tail"]
    page.locator(".popover .tagrow[data-tag='Comment'] [data-test=tag-toggle]").click()
    page.wait_for_function("() => document.querySelectorAll('#editor .chart-obj th.th-col').length === 3")
    page.keyboard.press("Escape")
    # the export model carries the tint and the bold
    doc = page.evaluate("async () => { const api = window.pywebview.api; const id = document.querySelector('.note-card.active').dataset.id; const note = await api.get_note(id); const d = await FS.exporter.buildDoc(note, window.__fsEditor); return d.blocks.find((b) => b.type === 'chart').rows[0].cells; }")
    c34 = [c for c in doc if c["col"] == 34][0]
    assert c34["hl"] and c34["b"] and not [c for c in doc if c["col"] == 33][0]["b"]
    assert not errors


def test_chart_markers_style_their_whole_row(app):
    """Seth, 2026-10-18: visual filters on chart markers, with row-level markers that style the
    whole row they are in — through the same scoped rules as the text tags."""
    h, page, errors = app
    new_note(page, "Marker rows")
    page.keyboard.type("{{flex:chart %s}}" % CHART)
    page.keyboard.press("Enter")
    page.wait_for_selector("#editor .chart-obj tr.crow")
    assert page.locator("#editor .chart-obj .ctag").count() == 2
    page.locator("#editor .chart-obj [data-test=marker-btn]").click()
    page.wait_for_selector("[data-test=tag-popover] .tagrow")
    row = page.locator("[data-test=tag-popover] .tagrow[data-tag='New']")
    row.locator("[data-test=tag-style]").click()
    page.locator("[data-test=tag-popover] [data-test=tag-bg]").first.click()
    page.locator("[data-test=tag-popover] [data-test=tag-row]").click()
    page.keyboard.press("Escape")
    page.wait_for_selector("#editor .chart-obj tr.crow.marker-row")
    tr = page.locator("#editor .chart-obj tr.crow.marker-row")
    assert tr.count() == 1 and tr.get_attribute("data-label") == "1a" and tr.get_attribute("data-marker-row") == "New"
    page.wait_for_function("() => document.getElementById('save-state').textContent === 'Saved'", timeout=5000)
    body = body_of(h)
    assert "tags=marker%3ANew:bg#ffd6a5+row" in body, body
    # hidden for the whole notebook from the popover's scope select: the chip goes, the row stays plain
    page.locator("#editor .chart-obj [data-test=marker-btn]").click()
    page.wait_for_selector("[data-test=tag-popover] .tagrow")
    page.select_option("[data-test=tag-scope-pick]", label="the whole notebook")
    page.wait_for_timeout(200)
    page.locator("[data-test=tag-popover] .tagrow[data-tag='Given'] [data-test=tag-toggle]").click()
    page.wait_for_function("() => document.querySelectorAll('#editor .chart-obj .ctag:not(.hidden)').length === 1")
    page.keyboard.press("Escape")
    rules = h.api._nb.config["tagStyles"]["project"]
    assert any(r.get("tag") == "marker:Given" and r.get("hide") for rs in rules.values() for r in rs), rules
    assert not errors


def test_chart_search_rows_profile_and_a_collection_of_rows(app):
    """Seth, 2026-10-18: search the charts — rows by words, column, marker, lexical item — insert
    the hits, see which columns an item sits in, and collect the rows into a collection that can
    take in new rows later."""
    h, page, errors = app
    new_note(page, "Chart search")
    page.click(".blk-body")
    page.keyboard.press("Control+Shift+L")
    page.locator(".picker-tabs button", has_text="Text charts").click()
    page.fill(".picker-left input[type=text]", "col:Subject lex:kabir")
    page.wait_for_selector("[data-test=pick-chart-row]")
    rows = page.locator("[data-test=pick-chart-row]")
    assert rows.count() == 3 and "1a" in rows.first.inner_text() and "Subject: Kabir" in rows.first.inner_text()
    # a hit opens the chart at that row; Insert rows writes an anchored one-row embed
    rows.nth(1).click()
    page.wait_for_selector(".picker-preview tr.crow.in-range")
    assert page.locator(".picker-preview tr.crow.in-range").get_attribute("data-label") == "2c"
    page.locator("[data-test=insert-chart-rows]").click()
    page.wait_for_selector("#editor .chart-obj tr.crow")
    page.wait_for_function("() => document.getElementById('save-state').textContent === 'Saved'", timeout=5000)
    assert "{{flex:chart %s rows=5 at=" % CHART in body_of(h)
    assert [x.lstrip("▶§¶") for x in page.locator("#editor .chart-obj tr.crow th.rlab").all_inner_texts()] == ["2c"]
    assert page.locator("#editor .chart-obj thead th.th-col").count() == 7            # the headings always come along
    # the column profile
    page.keyboard.press("Control+Shift+L")
    page.locator(".picker-tabs button", has_text="Text charts").click()
    page.fill(".picker-left input[type=text]", "lex:kabir")
    page.wait_for_selector("[data-test=chart-profile]")
    page.locator("[data-test=chart-profile]").click()
    page.wait_for_selector(".profile-table")
    assert page.locator(".profile-table").count() == 2        # one per template: Default, and the Topic-Comment chart
    assert "Subject" in page.locator(".profile-table").first.inner_text() and page.locator("[data-test=profile-count]").all_inner_texts() == ["3", "1", "1"]   # Subject 3, Verb 1 (3b's merged cell counts for both), Topic 1
    page.keyboard.press("Escape")
    # a collection of the rows a search matches, with a rule that finds new rows
    page.keyboard.press("Control+Shift+L")
    page.locator(".picker-tabs button", has_text="Text charts").click()
    page.fill(".picker-left input[type=text]", "marker:*")
    page.wait_for_selector("[data-test=collect-chart-rows]")
    page.locator("[data-test=collect-chart-rows]").click()
    page.wait_for_selector("[data-test=chart-rule-create]")
    page.wait_for_function("() => (document.querySelector('[data-test=chart-rule-count]') || {}).textContent.startsWith('2 rows')")
    page.fill("[data-test=chart-rule-title]", "Marked rows")
    page.locator("[data-test=chart-rule-create]").click()
    page.wait_for_selector("#collection .coll-item .chart-obj tr.crow")
    assert page.locator("#collection .coll-item").count() == 2
    bar = page.locator("[data-test=coll-rule]")
    assert "marker:*" in bar.inner_text() and "Find new rows" in bar.inner_text()
    page.locator("[data-test=coll-rule-update]").click()
    page.wait_for_selector(".toast", state="visible")
    assert "Nothing new" in page.locator(".toast").last.inner_text()
    notes = [n for n in h.api._nb.list_notes() if n["title"] == "Marked rows"]
    assert notes and h.api.get_note(notes[0]["id"])["rule"] == {"charts": "marker:*"}
    assert not errors


def test_chart_columns_on_an_example_text_tags_in_a_chart_pivot_and_entry_profile(app):
    """Seth, 2026-10-18 (phase 3): the text's chart columns drawn on an interlinear example like
    tags; the text's markup tags inside a chart's cells; a markers × columns pivot; where a lexical
    item sits in the charts, from its entry card."""
    h, page, errors = app
    new_note(page, "Columns as tags")
    page.keyboard.type("{{flex:text %s seg=1-2 lines=txt,gls,cols}}" % T_STORY)
    page.keyboard.press("Enter")
    page.wait_for_selector("#editor .text-obj .tagbar")
    bars = page.locator("#editor .text-obj .segment[data-n='1'] .tagbar.first")
    assert sorted(bars.all_inner_texts()) == ["Com", "S", "Top", "V"], bars.all_inner_texts()   # both charts on the story: Default (S, V) and Topic-Comment (Top, Com)
    assert page.locator("#editor .text-obj .il-tag[data-tag='Nucleus/Subject']").count() >= 1
    page.locator("#editor .text-obj [data-test=tag-btn]").click()
    page.wait_for_selector("[data-test=tag-popover] .tagrow[data-tag='Nucleus/Subject']")
    page.keyboard.press("Escape")
    # the text's FLEx tags inside a chart's cells, on request (typed in the paragraph after the example)
    page.locator("#editor .blk-body").last.click()
    page.keyboard.type("{{flex:chart %s rows=1-2 lines=txt,gls,tag}}" % CHART)
    page.keyboard.press("Enter")
    page.wait_for_selector("#editor .chart-obj .ctexttag")
    chips = page.locator("#editor .chart-obj tr.crow[data-label='1a'] .ctexttag").all_inner_texts()
    assert chips == ["S", "V"], chips
    # the pivot
    page.locator("#editor .chart-obj [data-test=chart-menu]").click()
    page.locator("[data-test=chart-pivot]").click()
    page.wait_for_selector(".pivot-table")
    txt = page.locator(".pivot-table").inner_text()
    assert "⚐ New" in txt and "moved text, preposed" in txt and "rows with words" in txt
    page.keyboard.press("Escape")
    # the entry card: where kabir sits in the charts
    page.locator("#editor .blk-body").last.click()
    page.keyboard.type("{{flex:entry 6a5f3a2e-1b1e-4c2a-9f10-0d2c1a7e0001}}")
    page.keyboard.press("Enter")
    page.wait_for_selector("#editor .entry-card [data-test=entry-chart-profile]")
    page.locator("#editor .entry-card [data-test=entry-chart-profile]").click()
    page.wait_for_selector(".profile-table")
    assert "Subject" in page.locator(".profile-table").first.inner_text()      # one table per template (Default first)
    assert not errors


def test_the_rule_list_keeps_its_place_when_a_rule_changes(app):
    """Seth, 2026-10-19: adding a border made "the current rule line I'm working on in visual filter
    jump to the top of the list". The list is its own scroller and every change redraws it whole,
    which let it fall back to the top; the place is kept now — and the border has a colour of its own."""
    h, page, _errors = app
    rules = [{"tag": "Topic", "bg": "#ffd6a5"}, {"tag": "Subject", "b": True}, {"tag": "Verb", "i": True}, {"tag": "Object", "b": True}]
    rules += [{"tag": "marker:M%d" % i, "bg": "#ffd6a5"} for i in range(60)]
    h.api.set_tag_filters([{"id": "f1", "name": "Probe", "enabled": True, "rules": rules}])
    page.reload()
    page.wait_for_selector(".note-card")
    page.evaluate("() => FS.tagstyles.dialog({kind: 'filter', key: 'f1', label: 'the filter'})")
    page.wait_for_selector("[data-test=tag-dialog]")
    order = lambda: page.evaluate("() => [...document.querySelectorAll('[data-test=tag-dialog] .tagrow')].map((r) => r.dataset.tag)")
    assert order()[:5] == ["Topic", "Subject", "Object", "Verb", "M0"]           # FLEx's own order within a group, then the markers
    page.evaluate("() => { document.querySelector('[data-test=tag-dialog]').scrollTop = 120; }")
    page.wait_for_timeout(100)
    page.locator("[data-test=tag-dialog] .tagrow[data-tag='Object'] [data-test=tag-box]").click()
    page.wait_for_selector("[data-test=tag-dialog] .tagrow[data-tag='Object'] [data-test=tag-bc]")
    page.wait_for_timeout(300)
    assert page.evaluate("() => document.querySelector('[data-test=tag-dialog]').scrollTop") == 120
    assert order()[:5] == ["Topic", "Subject", "Object", "Verb", "M0"]
    page.locator("[data-test=tag-dialog] .tagrow[data-tag='Object'] [data-test=tag-bc]").evaluate("(e) => { e.value = '#b91c1c'; e.dispatchEvent(new Event('change', {bubbles: true})); }")
    page.wait_for_selector("[data-test=tag-dialog] .tagrow[data-tag='Object'] [data-test=tag-bc-auto]")
    assert page.evaluate("() => document.querySelector('[data-test=tag-dialog]').scrollTop") == 120
    saved = h.api.init()["config"]["tagStyles"]["filters"][0]["rules"]
    assert {"tag": "Object", "enabled": True, "b": True, "box": True, "bc": "#b91c1c"} in saved, saved


def test_the_chart_search_is_a_button_and_a_builder(app):
    """Seth, 2026-10-19: the chart search "easy to find and also as GUI/visually creatable as possible
    without requiring the user to use a query language", with a regex help link naming the flavour."""
    h, page, errors = app
    new_note(page, "Chart search")
    page.locator("[data-test=btn-chart-search]").click()                       # the toolbar button opens the picker on Text charts
    page.wait_for_selector("[data-test=chart-search-build]:not([hidden])")
    assert page.locator(".picker-tabs button.on").inner_text() == "Text charts"
    page.locator("[data-test=chart-search-build]").click()
    page.wait_for_selector("[data-test=search-builder]")
    cond = page.locator("[data-test=sb-cond]").first
    assert cond.locator("[data-test=sb-what]").input_value() == "marker"      # a first condition to start from
    cond.locator("[data-test=sb-how]").select_option("is")
    cond.locator("[data-test=sb-val]").select_option("New")
    page.locator("[data-test=sb-add]").click()
    cond2 = page.locator("[data-test=sb-cond]").nth(1)
    cond2.locator("[data-test=sb-what]").select_option("gloss")
    cond2.locator("[data-test=sb-how]").select_option("regex")
    cond2.locator("[data-test=sb-val]").fill("sleep")
    page.fill("[data-test=sb-col]", "Verb")
    page.wait_for_function("() => document.querySelector('[data-test=search-q]').textContent === 'col:Verb marker:New gloss:/sleep/'")
    page.wait_for_function("() => document.querySelector('[data-test=search-count]').textContent === '1 row match'")
    assert page.locator("[data-test=search-builder] [data-test=regex-help]").get_attribute("data-flavour") == "py"
    page.locator("[data-test=sb-apply]").click()
    page.wait_for_selector("[data-test=pick-chart-row]")
    assert page.locator(".picker input[type=text]").first.input_value() == "col:Verb marker:New gloss:/sleep/"
    assert page.locator("[data-test=pick-chart-row]").count() == 1 and "1a" in page.locator("[data-test=pick-chart-row]").inner_text()
    # the query reads back into the builder
    page.locator("[data-test=chart-search-build]").click()
    page.wait_for_selector("[data-test=search-builder]")
    assert page.locator("[data-test=sb-col]").input_value() == "Verb"
    assert page.locator("[data-test=sb-cond]").count() == 2 and page.locator("[data-test=sb-cond]").nth(1).locator("[data-test=sb-how]").input_value() == "regex"
    page.keyboard.press("Escape")
    page.keyboard.press("Escape")
    # Ctrl+Shift+K from a chart note browses too (the rows go into a new note)
    page.evaluate("() => FS.newChartNote('%s')" % CHART)
    page.wait_for_selector("#chartnote tr.crow")
    page.keyboard.press("Control+Shift+K")
    page.wait_for_selector("[data-test=chart-search-build]:not([hidden])")
    page.keyboard.press("Escape")
    # the rule dialog's help names the JavaScript flavour
    page.locator("[data-test=cn-add-col]").click()
    page.select_option("[data-test=cn-col-kind]", "rule")
    page.wait_for_selector("[data-test=cn-builder] [data-test=regex-help]")
    assert page.locator("[data-test=cn-builder] [data-test=regex-help]").get_attribute("data-flavour") == "js"
    assert not errors


def chips_under_words(page, root="#editor .chart-obj"):
    """{n, ok}: every chip line that shares its box with words sits UNDER them, never beside them."""
    return page.evaluate("""(root) => { const out = { n: 0, ok: true }; for (const line of document.querySelectorAll(root + ' .chips-line:not(.void)')) {
        const words = line.parentElement.querySelector('.cwords'); if (!words) continue; out.n++;
        if (line.getBoundingClientRect().top < words.getBoundingClientRect().bottom - 1) out.ok = false; } return out; }""", root)


def test_marker_chips_on_their_own_line_in_the_groups_view(app):
    """Seth, 2026-10-20: in the one-column GROUPED view "on a line of their own" stacked the chips to
    the right of the words and "no longer than the words" did nothing visible — a flat box's body was
    an inline-flex ROW, so the chip line was just another item in it. The line now takes a row of its
    own under the words, in the groups view, the one-column view and the columns view alike."""
    h, page, errors = app
    new_note(page, "Chips under words")
    # the demo's two markers sit in cells without words; give row 1a's first word cell a marker too,
    # so a chip line shares a box with words (what the test measures)
    page.evaluate("""() => { const real = window.__flexBridge;
      window.__flexBridge = async (req) => { const q = JSON.parse(req); const r = await real(req);
        if (q.method !== 'flex_get' || q.args[0] !== 'chart') return r;
        const o = JSON.parse(r); const rows = o.result && o.result.rows; if (!rows) return r;
        const tag = rows.flatMap((x) => x.cells).find((c) => c.kind === 'tag'); const w = rows[0].cells.find((c) => c.kind === 'words');
        if (tag && w && !rows[0].cells.some((c) => c.kind === 'tag' && c.colN === w.colN)) rows[0].cells.push(Object.assign({}, tag, { col: w.col, colN: w.colN, guid: 'd15c0000-0000-4000-8000-0000000000e2' }));
        return JSON.stringify(o); }; }""")
    page.keyboard.type("{{flex:chart %s view=groups chips=line}}" % CHART)
    page.keyboard.press("Enter")
    page.wait_for_selector("#editor .chart-obj tr.crow .cflat-g")
    page.wait_for_selector("#editor .chart-obj .chips-line:not(.void)")
    u = chips_under_words(page)
    assert u["n"] >= 1 and u["ok"], u
    # the wrapped line is no wider than the words it belongs with
    page.locator("#editor .chart-obj [data-test=chart-menu]").click()
    page.select_option("[data-test=chart-chips-select]", "wrap")
    page.wait_for_function("() => { const ls = [...document.querySelectorAll('#editor .chart-obj .chips-line.wrap')]; return ls.length && ls.every((l) => /px$/.test(l.style.maxWidth)); }")
    page.keyboard.press("Escape")
    u = chips_under_words(page)
    assert u["n"] >= 1 and u["ok"], u
    assert page.evaluate("() => [...document.querySelectorAll('#editor .chart-obj .chips-line.wrap')].every((l) => { const w = l.parentElement.querySelector('.cwords'); return !w || l.getBoundingClientRect().width <= Math.max(48, w.getBoundingClientRect().width) + 1; })")   # 48px: the floor placeChipLines keeps
    # the columns view and the one-column view too (the head's button steps groups → columns → one column)
    page.locator("#editor .chart-obj [data-test=chart-view]").click()
    page.wait_for_function("() => !window.__fsEditor.getMarkdown().includes('view=')")
    page.wait_for_selector("#editor .chart-obj td.ccell .chips-line:not(.void)")
    u = chips_under_words(page)
    assert u["n"] >= 1 and u["ok"], u
    page.locator("#editor .chart-obj [data-test=chart-view]").click()
    page.wait_for_function("() => window.__fsEditor.getMarkdown().includes('view=flat')")
    page.wait_for_selector("#editor .chart-obj .cflat-g .chips-line:not(.void)")
    u = chips_under_words(page)
    assert u["n"] >= 1 and u["ok"], u


def test_the_flag_popover_keeps_its_place_and_the_chart_note_its_scroll(app):
    """Seth, 2026-10-20: the ⚑ popover "has the annoying behavior of skipping to the top … the moment
    something is changed within", and its close button should be clearly visible and sticky. A change
    at the chart's own scope and at the note's scope: the pane keeps its scroll, the popover keeps its
    place and its ✕, and the ✕ closes it."""
    h, page, errors = app
    page.locator("#btn-new-menu").click()
    page.locator("[data-test=new-chart-note]").click()
    page.wait_for_selector("[data-test=pick-chart-note]")
    page.locator("[data-test=pick-chart-note]").first.click()
    page.wait_for_selector("#chartnote .tchart tr.crow")
    # a short pane; the ⚑ popover open (a fixed box of its own), then the pane scrolled down into
    # the chart (Playwright's click would scroll the ⚑ button into view itself)
    page.evaluate("document.getElementById('editor-pane').style.height = '380px'")
    page.locator("#chartnote [data-test=marker-btn]").click()
    page.wait_for_selector(".popover [data-test=tag-scope-pick]")
    page.evaluate("document.getElementById('chartnote').scrollTop = 150")
    page.wait_for_timeout(100)
    pane_before = page.evaluate("document.getElementById('chartnote').scrollTop")
    assert pane_before > 100
    pop = page.locator(".popover")
    assert pop.locator(".pop-head [data-test=pop-close]").is_visible()
    # the popover is taller than the window here: scroll it down, then change something near the bottom
    page.evaluate("() => { const p = document.querySelector('.popover'); p.style.maxHeight = '260px'; p.scrollTop = p.scrollHeight; }")
    pop_before = page.evaluate("document.querySelector('.popover').scrollTop")
    assert pop_before > 50
    boxes = pop.locator("input[type=checkbox]")
    n = boxes.count()
    assert n > 2
    boxes.nth(n - 1).click()
    page.wait_for_timeout(500)
    assert page.locator(".popover").count() == 1
    assert abs(page.evaluate("document.querySelector('.popover').scrollTop") - pop_before) <= 2
    assert abs(page.evaluate("document.getElementById('chartnote').scrollTop") - pane_before) <= 2
    # the ✕ stays in view at the top of the scrolled popover, and closes it
    head = page.locator(".popover .pop-head")
    assert head.is_visible() and head.evaluate("e => e.getBoundingClientRect().top >= e.closest('.popover').getBoundingClientRect().top - 1")
    # a change at the note's scope: the whole note redraws, and nothing moves either
    page.select_option(".popover [data-test=tag-scope-pick]", index=1)
    page.wait_for_timeout(200)
    page.evaluate("() => { const p = document.querySelector('.popover'); p.scrollTop = p.scrollHeight; }")
    pop_before = page.evaluate("document.querySelector('.popover').scrollTop")
    boxes = page.locator(".popover input[type=checkbox]")
    boxes.nth(boxes.count() - 1).click()
    page.wait_for_timeout(700)
    assert page.locator(".popover").count() == 1
    assert abs(page.evaluate("document.querySelector('.popover').scrollTop") - pop_before) <= 2
    assert abs(page.evaluate("document.getElementById('chartnote').scrollTop") - pane_before) <= 2
    page.locator(".popover [data-test=pop-close]").click()
    page.wait_for_selector(".popover", state="detached")


def test_the_groups_view_and_lining_up_on_a_column(app):
    """Seth, 2026-10-19: "a major-column view … just the 3 parent columns (and then style text from sub
    columns within each cell per visual filter rules)", and in the one-column view "align elements
    from one or more specific columns so that they do line up … center arrange/align"."""
    h, page, errors = app
    new_note(page, "Groups view")
    page.keyboard.type("{{flex:chart %s}}" % CHART)
    page.keyboard.press("Enter")
    page.wait_for_selector("#editor .chart-obj tr.crow")
    obj = page.locator("#editor .chart-obj")
    src = lambda: page.evaluate("() => window.__fsEditor.getMarkdown()")  # noqa: E731
    obj.locator("[data-test=chart-view-groups]").click()
    page.wait_for_function("() => document.querySelectorAll('#editor .chart-obj th.th-col').length === 3")
    assert "view=groups" in src()
    assert obj.locator("th.th-col").all_inner_texts() == ["Prenuclear", "Nucleus", "Postnuclear"]
    r1b = obj.locator("tr.crow[data-label='1b'] td.ccell")
    assert r1b.count() == 3
    assert r1b.nth(1).locator(".cflat-g").evaluate_all("els => els.map((e) => e.title)") == ["Nucleus › Subject", "Nucleus › Verb", "Nucleus › Object"]
    assert r1b.nth(1).locator(".cflat-lab").all_inner_texts() == ["S", "V", "O"]
    assert obj.locator("[data-test=chart-view-groups]").count() == 0           # already there
    # a sub-column's rule styles its words inside the group cell
    page.evaluate("async () => { const c = await window.pywebview.api.set_tag_styles('project', FS.tagstyles.context().project, [{tag: 'column:Nucleus/Verb', br: 'sq', b: true}]); FS.tagstyles.setConfig(c); FS.emit('tagstyles'); }")
    page.wait_for_selector("#editor .chart-obj tr.crow[data-label='1b'] td.ccell[data-col='1001'] .cflat-br")
    # LINE UP ON Verb in the one-column view: the Verb runs sit centred on one axis across the rows
    obj.locator("[data-test=chart-menu]").click()
    page.select_option("[data-test=chart-view-select]", "flat")
    page.wait_for_selector("#editor .chart-obj.flat")
    page.locator("#editor .chart-obj [data-test=chart-menu]").click()
    page.locator("[data-test=chart-align-col][data-col='4']").check()
    page.wait_for_function("() => document.querySelectorAll('#editor .chart-obj .al-grid').length > 2")
    page.keyboard.press("Escape")
    assert "align=c4" in src(), src()
    page.wait_for_function("() => /px$/.test(document.querySelector('#editor .chart-obj table.tchart').style.getPropertyValue('--al-a'))")
    centres = page.evaluate("() => [...document.querySelectorAll(\"#editor .chart-obj tr.crow .al-a\")].filter((a) => a.textContent.trim()).map((a) => { const r = a.getBoundingClientRect(); return [a.closest('tr').dataset.label, Math.round(r.left + r.width / 2)]; })")
    assert len(centres) >= 4, centres
    assert max(c[1] for c in centres) - min(c[1] for c in centres) <= 1, centres
    # the words before the Verb sit to its left (right-aligned to the axis), the rest to its right
    r1a = page.locator("#editor .chart-obj tr.crow[data-label='1a'] .al-grid")
    assert "Kabir" in r1a.locator(".al-l").inner_text() and "nuwa" in r1a.locator(".al-a").inner_text()
    # a row without the column flows as before
    assert page.locator("#editor .chart-obj tr.crow[data-label='2a'] .al-grid").count() == 0
    # the left edges instead of the centres (Seth, 2026-10-19: "left edge, right edge, or center")
    page.locator("#editor .chart-obj [data-test=chart-menu]").click()
    page.select_option("[data-test=chart-align-edge]", "left")
    page.wait_for_selector("#editor .chart-obj table.tchart.al-left")
    page.keyboard.press("Escape")
    assert "alignat=left" in src()
    page.wait_for_function("() => /px$/.test(document.querySelector('#editor .chart-obj table.tchart').style.getPropertyValue('--al-a'))")
    lefts = page.evaluate("() => [...document.querySelectorAll(\"#editor .chart-obj tr.crow .al-a\")].filter((a) => a.textContent.trim()).map((a) => Math.round(a.getBoundingClientRect().left))")
    assert len(lefts) >= 4 and max(lefts) - min(lefts) <= 1, lefts
    page.locator("#editor .chart-obj [data-test=chart-menu]").click()
    page.select_option("[data-test=chart-align-edge]", "center")
    page.wait_for_function("() => !window.__fsEditor.getMarkdown().includes('alignat=')")
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)
    # MARKER CHIPS on a line of their own, no wider than the words (Seth, 2026-10-19): row 1a's New marker shares the
    # Postnuclear › Inner box with nothing, 2c's Given sits in Postnuclear › Outer; in the columns view a cell that holds
    # words AND a marker keeps the chip under the words
    page.locator("#editor .chart-obj [data-test=chart-menu]").click()
    page.select_option("[data-test=chart-chips-select]", "wrap")
    page.wait_for_selector("#editor .chart-obj .chips-line.wrap")
    page.keyboard.press("Escape")
    assert "chips=wrap" in src()
    assert chips_under_words(page)["ok"]
    page.wait_for_function("() => [...document.querySelectorAll('#editor .chart-obj .chips-line.wrap')].every((l) => /px$/.test(l.style.maxWidth))")
    assert page.locator("#editor .chart-obj tr.crow[data-label='1a'] .chips-line .ctag").count() == 1
    page.locator("#editor .chart-obj [data-test=chart-menu]").click()
    page.select_option("[data-test=chart-chips-select]", "inline")
    page.wait_for_function("() => !window.__fsEditor.getMarkdown().includes('chips=')")
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)
    # a header GROUP lines up as one block: the group's box ticks its columns
    page.locator("#editor .chart-obj [data-test=chart-menu]").click()
    page.locator("[data-test=chart-align-group][data-group='Nucleus']").check()
    page.wait_for_function("() => window.__fsEditor.getMarkdown().includes('align=c3,c4,c5')")
    page.locator("[data-test=chart-align-group][data-group='Nucleus']").uncheck()
    page.wait_for_function("() => !window.__fsEditor.getMarkdown().includes('align=')")
    page.keyboard.press("Escape")                                                  # a redraw leaves the open menu behind
    page.wait_for_timeout(200)
    page.locator("#editor .chart-obj [data-test=chart-menu]").click()
    page.locator("[data-test=chart-align-col][data-col='4']").check()
    page.wait_for_function("() => window.__fsEditor.getMarkdown().includes('align=c4')")
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)
    # MERGED CELLS (Seth, 2026-10-19: "it could be either"): 3b's group is owned by Subject and merged into Verb, so
    # in the one-column view it is labelled S+V, wears Verb's brackets round Subject's box, and lines up on Verb
    w3b = page.locator("#editor .chart-obj tr.crow[data-label='3b'] .cflat-outer")
    assert w3b.count() == 1 and w3b.locator(".cflat-lab").inner_text() == "S+V" and w3b.locator(".cflat-br").all_inner_texts() == ["[", "]"]
    assert page.locator("#editor .chart-obj tr.crow[data-label='3b'] .al-a .cflat-outer").count() == 1
    # the chart's ⋯ menu offers the choice; owner only drops the second label and the outer look
    page.locator("#editor .chart-obj [data-test=chart-menu]").click()
    page.select_option("[data-test=chart-merge-select]", "owner")
    page.wait_for_function("() => document.querySelector(\"#editor .chart-obj tr.crow[data-label='3b'] .cflat-lab\").textContent === 'S'")
    page.keyboard.press("Escape")
    assert "merge=owner" in src() and page.locator("#editor .chart-obj tr.crow[data-label='3b'] .cflat-outer").count() == 0
    assert page.locator("#editor .chart-obj tr.crow[data-label='3b'] .al-grid").count() == 0        # Subject alone is not lined up
    # `labels` (Seth, 2026-10-20: "both labels … but not both borders"): S+V named, one box, still lined up on Verb
    page.locator("#editor .chart-obj [data-test=chart-menu]").click()
    page.select_option("[data-test=chart-merge-select]", "labels")
    page.wait_for_function("() => document.querySelector(\"#editor .chart-obj tr.crow[data-label='3b'] .cflat-lab\").textContent === 'S+V'")
    page.keyboard.press("Escape")
    assert "merge=labels" in src() and page.locator("#editor .chart-obj tr.crow[data-label='3b'] .cflat-outer").count() == 0
    assert page.locator("#editor .chart-obj tr.crow[data-label='3b'] .al-grid").count() == 1
    # back in the columns view the merged cell spans both and takes Verb's look as the outer layer
    page.locator("#editor .chart-obj [data-test=chart-menu]").click()
    page.select_option("[data-test=chart-merge-select]", "both")
    page.wait_for_function("() => !window.__fsEditor.getMarkdown().includes('merge=')")
    page.keyboard.press("Escape")                                                  # the menu stays open after a select
    page.wait_for_timeout(200)
    page.locator("#editor .chart-obj [data-test=chart-menu]").click()
    page.select_option("[data-test=chart-view-select]", "cols")
    page.wait_for_function("() => !document.querySelector('#editor .chart-obj.flat')")
    td = page.locator("#editor .chart-obj tr.crow[data-label='3b'] td.ccell[data-col='3']")
    assert td.get_attribute("colspan") == "2" and td.evaluate("(e) => e.classList.contains('cmerged')") and td.locator(".cmerge-in").count() == 1
    assert not errors


def test_chart_structure_and_header_groups_as_visual_filters(app):
    """Seth, 2026-10-19: visual filters for dependent / speech / song clauses and their markers, for
    moved (preposed / postposed) text with a choice of look and label, and for a header group's
    columns styled as ONE unit — in both chart layouts."""
    h, page, errors = app
    new_note(page, "Structure filters")
    page.keyboard.type("{{flex:chart %s}}" % CHART)
    page.keyboard.press("Enter")
    page.wait_for_selector("#editor .chart-obj tr.crow")
    obj = page.locator("#editor .chart-obj")
    # the ⚑ popover lists the chart's structure and its header groups
    obj.locator("[data-test=marker-btn]").click()
    page.wait_for_selector(".popover .tagrow[data-tag='moved:preposed']")
    names = page.locator(".popover .tagrow").evaluate_all("els => els.map((e) => e.dataset.tag)")
    assert "clause:speech" in names and "clauseref" in names and "moved:*" in names and "group:Nucleus" in names, names
    # merged cells are a target too (Seth, 2026-10-20): any, by side, and 3b's "Subject merged right"
    assert "merged:*" in names and "merged:right" in names and "merged:Nucleus/Subject:right" in names, names
    assert page.locator(".popover .tagrow[data-tag='merged:Nucleus/Subject:right']").inner_text().startswith("S merged right")
    # the popover's sticky head has a visible ✕ (Seth, 2026-10-20)
    assert page.locator(".popover .pop-head [data-test=pop-close]").is_visible()
    page.locator(".popover [data-test=pop-close]").click()
    page.wait_for_selector(".popover", state="detached")
    # rules at the project scope: a speech row tinted, the [2a] markers hidden, moved text boxed and
    # labelled with the column it came from, the Nucleus group tiled as one
    page.evaluate("""async () => {
      const c = await window.pywebview.api.set_tag_styles('project', FS.tagstyles.context().project, [
        {tag: 'clause:speech', bg: '#fde68a'}, {tag: 'clauseref', hide: true},
        {tag: 'moved:*', box: true, bg: '#c0392b'}, {tag: 'column:group:Nucleus', tile: true, bg: '#bdb2ff'},
        {tag: 'merged:Nucleus/Subject:right', box: true, bg: '#0f766e'}]);
      FS.tagstyles.setConfig(c); FS.emit('tagstyles');
    }""")
    page.wait_for_selector("#editor .chart-obj tr.clause-styled")
    # the merged cell of 3b (Subject, extended into Verb) wears the merged rule's box over the columns' looks; no other cell does
    assert obj.locator("tr.crow[data-label='3b'] td.merged-styled").count() == 1 and obj.locator("td.merged-styled").count() == 1
    assert obj.locator("tr.crow[data-label='2a']").evaluate("e => e.classList.contains('clause-styled') && e.style.background !== ''")
    assert obj.locator("tr.crow[data-label='2b'] .cclause.hidden").count() == 1 and obj.locator(".cclause:not(.hidden)").count() == 0
    moved = obj.locator(".cwords.moved-styled")
    assert moved.count() == 1 and moved.locator(".moved-lab").inner_text() == "‹‹ Post-O"     # row 1b: Haŋa, preposed from Postnuclear › Outer
    assert moved.evaluate("e => e.style.outline !== ''")
    # the Nucleus group: one box over Subject · Verb · Object in each row, the group heading styled, the leaf headings not
    r1a = obj.locator("tr.crow[data-label='1a']")
    assert r1a.locator("td.cgrp").count() == 3
    assert r1a.locator("td[data-col='3']").evaluate("e => e.classList.contains('cgrp-first') && !e.classList.contains('cgrp-last')")
    assert r1a.locator("td[data-col='5']").evaluate("e => e.classList.contains('cgrp-last')")
    assert obj.locator("th.th-group", has_text="Nucleus").evaluate("e => e.classList.contains('col-styled')")
    assert obj.locator("th.th-col", has_text="Verb").evaluate("e => e.classList.contains('col-styled')") is False
    # the label follows the choice: the column the words sit in
    page.evaluate("""async () => {
      const c = await window.pywebview.api.set_tag_styles('project', FS.tagstyles.context().project, [
        {tag: 'clause:speech', bg: '#fde68a'}, {tag: 'clauseref', hide: true},
        {tag: 'moved:*', box: true, bg: '#c0392b', ml: 'to'}, {tag: 'column:group:Nucleus', tile: true, bg: '#bdb2ff'}]);
      FS.tagstyles.setConfig(c); FS.emit('tagstyles');
    }""")
    page.wait_for_function("() => (document.querySelector('#editor .chart-obj .moved-lab') || {}).textContent === '‹‹ Pre-O'")
    # the one-column view: the Nucleus parts share one box labelled with the group, columns labelled inside
    obj.locator("[data-test=chart-view]").click()
    page.wait_for_selector("#editor .chart-obj.flat")
    g = page.locator("#editor .chart-obj.flat tr.crow[data-label='1a'] .cflat-g")
    assert g.evaluate_all("els => els.map((e) => e.dataset.group || e.dataset.col)") == ["Nucleus", "6"]
    assert g.first.locator(".cflat-lab").all_inner_texts() == ["S", "V", "Nucleus"]      # each column's label after its words, the group's last
    # the "null" that followed every row (a missing 🔍 appended as text) is gone, and a group heading's box
    # switches its tags off, back on, and back to a mix (Seth, 2026-10-19)
    obj.locator("[data-test=marker-btn]").click()
    page.wait_for_selector(".popover .tagrow")
    assert "null" not in page.locator(".popover [data-test=tag-popover]").inner_text()
    grp = page.locator(".popover .tag-tree-head[data-group='Arguments'] [data-test=tag-group-toggle]")
    assert grp.count() == 1 and grp.is_checked()
    page.locator(".popover .tagrow[data-tag='Subject'] [data-test=tag-toggle]").click()          # a mix: Subject off, Object on
    page.wait_for_function("() => document.querySelector(\".popover .tag-tree-head[data-group='Arguments'] [data-test=tag-group-toggle]\").indeterminate")
    page.locator(".popover .tag-tree-head[data-group='Arguments'] [data-test=tag-group-toggle]").click()   # mix → all on (mix remembered)
    page.wait_for_function("() => { const b = document.querySelector(\".popover .tag-tree-head[data-group='Arguments'] [data-test=tag-group-toggle]\"); return b.checked && !b.indeterminate; }")
    page.locator(".popover .tag-tree-head[data-group='Arguments'] [data-test=tag-group-toggle]").click()   # all on → all off
    page.wait_for_function("() => { const b = document.querySelector(\".popover .tag-tree-head[data-group='Arguments'] [data-test=tag-group-toggle]\"); return !b.checked && !b.indeterminate; }")
    page.locator(".popover .tag-tree-head[data-group='Arguments'] [data-test=tag-group-toggle]").click()   # all off → the mix again
    page.wait_for_function("() => document.querySelector(\".popover .tag-tree-head[data-group='Arguments'] [data-test=tag-group-toggle]\").indeterminate")
    assert page.locator(".popover .tagrow[data-tag='Subject'] [data-test=tag-toggle]").is_checked() is False
    assert page.locator(".popover .tagrow[data-tag='Object'] [data-test=tag-toggle]").is_checked()
    page.keyboard.press("Escape")
    assert page.locator("#editor .chart-obj.flat .moved-lab").inner_text() == "‹‹ Pre-O"
    # SENTENCE / PARAGRAPH BOUNDARIES (Seth, 2026-10-19): the lines FLEx's last-row boxes draw take a style of their own
    page.evaluate("async () => { const c = await window.pywebview.api.set_tag_styles('project', FS.tagstyles.context().project, [{tag: 'boundary:paragraph', bs: 'dashed', bw: 4, bc: '#1d4ed8'}, {tag: 'boundary:sentence', hide: true}]); FS.tagstyles.setConfig(c); FS.emit('tagstyles'); }")
    page.wait_for_selector("#editor .chart-obj tr.end-para.bnd-styled")
    para = page.locator("#editor .chart-obj tr.end-para").first.locator("td").first
    assert para.evaluate("(e) => [getComputedStyle(e).borderBottomStyle, getComputedStyle(e).borderBottomWidth, getComputedStyle(e).borderBottomColor]") == ["dashed", "4px", "rgb(29, 78, 216)"]
    sent = page.locator("#editor .chart-obj tr.end-sent:not(.end-para)").first
    assert sent.evaluate("(e) => e.classList.contains('bnd-off')") and sent.locator("td").first.evaluate("(e) => getComputedStyle(e).borderBottomWidth") == "1px"
    page.locator("#editor .chart-obj [data-test=marker-btn]").first.click()
    page.wait_for_selector("[data-test=tag-popover] .tagrow[data-tag='boundary:paragraph']")
    page.locator("[data-test=tag-popover] .tagrow[data-tag='boundary:paragraph'] [data-test=tag-style]").click()
    assert page.locator("[data-test=tag-popover] .tag-style-box [data-test=tag-bs]").count() == 1 and page.locator("[data-test=tag-popover] .tag-style-box [data-test=tag-bg]").count() == 0
    page.keyboard.press("Escape")
    assert not errors


CONCORDANCE_CSV = (
    "Ref,Occurrence\r\n"
    "DOG 1.2,Kabir ka-nuwa-mo lo.\u00a7 Ha\u014ba tiket ka-sila-mo pemu.\r\n"
    "The dog and the river 2.1,\"\u201c\u019dam\u00fa!\u201d ka-sila lo.\u00a7 Kabir pemu ka-nuwa lo.\"\r\n"
    "The dog 3,Tiket ka-nuwa-mo.\r\n"
    "DOG 1.2,Kabir ka-nuwa-mo lo.\u00a7 Ha\u014ba tiket ka-sila-mo pemu.\r\n"
    "DOG 9.9,Kabir pemu ka-nuwa lo.\r\n"
    "Nowhere 1.1,ba tuhwe de kudia te\r\n"
    "DOG 8.8,xyz nothing here\r\n"
)


def test_a_flex_concordance_export_becomes_a_collection(app):
    """Seth, 2026-10-20: "you can't actually 'paste' concordance search results, but you could open
    the CSV results and generate an example collection from that. THAT would be HUGELY useful." The
    file's contents pasted into the dialog (the file dialog cannot be driven here): the rows are placed
    in the project, the count says what was found, and the collection holds one example per line, the
    misses listed at its end."""
    h, page, errors = app
    page.locator("#btn-new-menu").click()
    page.locator("[data-test=new-concordance]").click()
    page.wait_for_selector("[data-test=conc-text]")
    page.locator("[data-test=conc-text]").fill(CONCORDANCE_CSV)
    page.wait_for_function("() => /placed/.test(document.querySelector('[data-test=conc-count]').textContent)")
    count = page.locator("[data-test=conc-count]").inner_text()
    assert "4 of 7 rows placed, 2 not found" in count and "1 text" in count, count
    assert page.locator("[data-test=conc-preview] .pick-item:not(.conc-miss)").count() == 4
    assert page.locator("[data-test=conc-preview] .conc-miss").count() == 2
    assert "found by its text" in page.locator("[data-test=conc-preview] .pick-item").nth(3).inner_text()
    page.locator("[data-test=conc-title]").fill("kudia te")
    page.locator("[data-test=conc-note]").check()
    page.locator("[data-test=conc-create]").click()
    page.wait_for_selector("#collection .coll-item .text-obj .segment")
    assert page.locator("#collection .coll-item .text-obj").count() == 4       # + the closing "Not found" paragraph
    assert page.locator("#collection .coll-note").first.input_value() == "DOG 1.2 (\u00d72)"
    md = page.locator("#collection").inner_text()
    assert "Not found in the project: Nowhere 1.1" in md and "DOG 8.8" in md


def test_a_chart_becomes_an_example_and_an_example_a_chart(app):
    """Seth, 2026-10-20: "convert a flex text-chart object to a regular interlinear example object
    (including the lines that chart rows touch) or vice versa … either direction should be inclusive".
    Rows 1b–2a hold lines 2 and 3 → an example of lines 2–3; that example → the rows holding words
    of lines 2–3, which are 1b, 2a AND 2b (rows 2–4): inclusive both ways, anchored, the view keys gone."""
    h, page, errors = app
    new_note(page, "Convert")
    page.keyboard.type("{{flex:chart %s rows=2-3 free=col zoom=120 \"My chart\"}}" % CHART)
    page.keyboard.press("Enter")
    page.wait_for_selector("#editor .chart-obj tr.crow")
    page.locator("#editor .chart-obj [data-test=chart-menu]").click()
    page.locator("[data-test=to-example]").click()
    page.wait_for_selector("#editor .text-obj .segment")
    md = page.evaluate("() => window.__fsEditor.getMarkdown()")
    assert "{{flex:text %s seg=2-3 at=0e1f2a3b1002-0e1f2a3b1003 \"My chart\"}}" % TEXT in md, md
    assert "zoom" not in md and "free=" not in md
    assert page.locator("#editor .text-obj .segment").count() == 2
    # and back: two charts of this text have rows, so the chooser asks which
    page.locator("#editor .text-obj .flex-head .lnk[title='Options']").click()
    page.locator("[data-test=to-chart]").click()
    page.wait_for_selector("[data-test=pick-chart-convert]")
    assert page.locator("[data-test=pick-chart-convert]").count() == 2
    page.locator("[data-test=pick-chart-convert]").first.click()
    page.wait_for_selector("#editor .chart-obj tr.crow")
    md = page.evaluate("() => window.__fsEditor.getMarkdown()")
    assert "{{flex:chart %s rows=2-4 at=000000000020-000000000040 \"My chart\"}}" % CHART in md, md
    assert page.locator("#editor .chart-obj tr.crow").count() == 3


def test_selected_lines_and_rows_copy_and_paste_as_a_new_example(app):
    """Seth, 2026-10-20: "copy TSV for individual or multiple selected rows in flex objects (either
    table or IGT) … paste them in a notes document elsewhere as a new example (and of course for FLEx
    text chart objects, headers always show)". Lines 1–2 of an example, selected by their numbers,
    copy as their reference plus FLEx's rows; pasted into the note they are a new example of those two
    lines. Chart rows 1b–2a, Ctrl+clicked, copy with the header rows and paste the same way."""
    h, page, errors = app
    new_note(page, "Rows")
    page.keyboard.type("{{flex:text %s seg=1-3}}" % TEXT)
    page.keyboard.press("Enter")
    page.wait_for_selector("#editor .text-obj .segment[data-n='3']")
    page.evaluate("() => { window.__copied = null; FS.copyText = (t) => { window.__copied = t; return Promise.resolve(true); }; }")
    page.locator("#editor .text-obj .segment[data-n='1'] [data-test=segnum]").click()
    page.locator("#editor .text-obj .segment[data-n='2'] [data-test=segnum]").click(modifiers=["Shift"])
    assert page.locator("#editor .text-obj .segment.line-sel").count() == 2
    assert page.locator("[data-test=sel-count]").inner_text() == "2 lines selected"
    page.locator("[data-test=sel-copy]").click()
    copied = page.evaluate("window.__copied")
    assert copied.startswith("{{flex:text %s seg=1-2 at=0e1f2a3b1001-0e1f2a3b1002}}\n" % TEXT), copied
    assert "Word\tKabir" in copied and "Ha\u014ba" in copied and "Tiket" not in copied
    # pasted at the end of the note: a new example of lines 1–2 (the rows under the reference are left out)
    page.locator("#editor .blk-body").last.click()
    page.keyboard.press("End")
    paste(page, copied)
    page.wait_for_function("() => document.querySelectorAll('#editor .text-obj').length === 2")
    md = page.evaluate("() => window.__fsEditor.getMarkdown()")
    assert "{{flex:text %s seg=1-2 at=0e1f2a3b1001-0e1f2a3b1002}}" % TEXT in md and "Word\t" not in md
    page.locator("#editor .text-obj").nth(1).locator(".segment[data-n='2']").wait_for()
    assert page.locator("#editor .text-obj").nth(1).locator(".segment").count() == 2
    # the note's redraw after the paste drew the first example afresh: no selection, no bar
    assert page.locator("[data-test=sel-bar]").count() == 0
    # Clear takes a selection and its bar away
    page.locator("#editor .text-obj").first.locator(".segment[data-n='3'] [data-test=segnum]").click()
    assert page.locator("[data-test=sel-count]").inner_text() == "1 line selected"
    page.locator("[data-test=sel-clear]").click()
    assert page.locator("[data-test=sel-bar]").count() == 0 and page.locator("#editor .segment.line-sel").count() == 0
    # chart rows: Ctrl+click two labels
    page.locator("#editor .blk-body").last.click()
    page.keyboard.press("End")
    page.keyboard.press("Enter")
    page.keyboard.type("{{flex:chart %s free=col}}" % CHART)
    page.keyboard.press("Enter")
    page.wait_for_selector("#editor .chart-obj tr.crow[data-row='3']")
    def rlab(n):   # the row's number sits at the right edge of its label cell, after the ▶ buttons
        th = page.locator("#editor .chart-obj tr.crow[data-row='%d'] th.rlab" % n)
        b = th.bounding_box()
        return th, {"x": b["width"] - 8, "y": b["height"] / 2}
    th, pos = rlab(2)
    th.click(modifiers=["Control"], position=pos)
    th, pos = rlab(3)
    th.click(modifiers=["Shift"], position=pos)
    assert page.locator("#editor .chart-obj tr.crow.row-sel").count() == 2
    assert page.locator("#editor .chart-obj [data-test=sel-count]").inner_text() == "2 rows selected"
    page.evaluate("() => { window.__copied = null; }")
    page.locator("#editor .chart-obj [data-test=sel-copy]").click()
    copied = page.evaluate("window.__copied")
    assert copied.startswith("{{flex:chart %s rows=2-3 at=000000000020-000000000030 free=col}}\n" % CHART), copied
    lines = copied.split("\n")
    assert "Subject" in lines[2] or "Subject" in lines[1]          # the header rows ride along
    assert any(l.startswith("1b\t") for l in lines) and any(l.startswith("2a\t") for l in lines) and not any(l.startswith("1a\t") for l in lines)
    # Ctrl+C from the page (the focus is on the chart's label, not in an editable)
    page.evaluate("() => { window.__copied = null; document.activeElement && document.activeElement.blur(); }")
    page.keyboard.press("Control+c")
    assert page.evaluate("window.__copied") == copied


def test_deleting_the_open_collection_leaves_nothing_under_the_placeholder(app):
    """Seth, 2026-10-20 (a screenshot): after deleting the open collection, "Select a note…" showed
    with the collection still drawn under it. A collection and a chart note hide with the editor."""
    h, page, errors = app
    page.locator("#btn-new-menu").click()
    page.locator("[data-test=new-collection]").click()
    page.wait_for_selector("#collection")
    assert page.locator("#collection").is_visible()
    page.wait_for_selector(".note-card.active")          # the new collection's own card, whatever the list order
    page.once("dialog", lambda d: d.accept())
    page.locator(".note-card.active").click(button="right")
    page.locator(".popover .menu-item", has_text="Delete (to trash)").click()
    page.wait_for_selector("#editor-pane.no-note")
    assert page.locator(".no-note-msg").is_visible()
    assert not page.locator("#collection").is_visible() and not page.locator("#chartnote").is_visible() and not page.locator("#editor").is_visible()
