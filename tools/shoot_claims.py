"""Photograph the website's "what you can do" rows from the REAL program (dev-only).

    python tools/shoot_claims.py            → docs/media/claim-*.webp, docs/media/available.json updated

Seth, 2026-10-20: "mouseover generated screenshots for each feature with a checkbox in the what you
can do (especially working with charts in three different views, for example)". Each still is the
actual UI (flex_scratchpad/ui) against the built-in demo project — an invented language, so no
community's data appears on the site — through the same no-server bridge the end-to-end tests and
tools/record_demo.py use. The page's compare table names a row's stills in `data-stills`; the
site's assets/media.js shows them in a hover card only when they are on the manifest, so a still
that is not made yet simply leaves its row without one.

Needs: Playwright's Chromium and Pillow. Re-run after a UI change and look at the result.
"""
from __future__ import annotations

import json
import sys
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "e2e"))
from bridge import INIT_SCRIPT, Harness  # noqa: E402
from flex_scratchpad.flex.demo import T_STORY  # noqa: E402

OUT = ROOT / "docs" / "media"
UI = ROOT / "flex_scratchpad" / "ui"
W, H, SCALE = 1280, 800, 1.5
CHART = "d15c0000-0000-4000-8000-00000000c001"
NOTE = f"""# 3 Verbs

## 3.1 Past tense

The past tense suffix *-mo* follows the verb stem, as in (1).

{{{{flex:text {T_STORY} seg=1-2 ex hl=1.2 b=morph:"-mo" u=2.3 "past tense"}}}}

| Construction | Example | Note |
|---|---|---|
| Intransitive | {{{{flex:text {T_STORY} seg=1 expanded}}}} | the suffix on *nuwa* |
| Transitive | {{{{flex:text {T_STORY} seg=2 expanded}}}} | object before the verb |

- [x] check the suffix on stative verbs
- [ ] ask about *-mo* with negation

## 3.2 Questions

Questions end in the particle *ba*.
"""
CONCORDANCE = (
    "Ref,Occurrence\n"
    "DOG 1.2,Kabir ka-nuwa-mo lo.§ Haŋa tiket ka-sila-mo pemu.\n"
    "The dog and the river 2.1,\"“Ɲamú!” ka-sila lo.§ Kabir pemu ka-nuwa lo.\"\n"
    "DOG 3,Tiket ka-nuwa-mo.\n"
    "DOG 3,Tiket ka-nuwa-mo.\n"
    "DOG 4.1,Kabir ka-nuwa-mo.\n"
)


def chromium_path():
    import os
    p = os.environ.get("PLAYWRIGHT_CHROMIUM") or "/opt/pw-browsers/chromium"
    return p if Path(p).exists() else None


def crop(png: bytes, box: dict, ratio: float = 1.6, width: int = 1200) -> "Image":
    from PIL import Image
    im = Image.open(BytesIO(png)).convert("RGB")
    k = SCALE
    x0, y0, w, h = box["x"], box["y"], box["width"], box["height"]
    hh = min(h, w / ratio)
    cy = box.get("cy", y0 + hh / 2)
    yy = max(y0, min(cy - hh / 2, y0 + h - hh))
    im = im.crop((int(x0 * k), int(yy * k), int((x0 + w) * k), int((yy + hh) * k)))
    return im.resize((width, int(width * im.size[1] / im.size[0])), Image.LANCZOS)


def main() -> int:
    from playwright.sync_api import sync_playwright
    h = Harness()
    api = h.api
    tab = api.init()["tabs"][0]["dir"] if api.init().get("tabs") else "Notes"
    api.create_note(tab, "", "Field trip, 12 October", "Recorded two stories at the river.\n")
    note = api.create_note(tab, "", "Chapter 3 — Verbs", NOTE)
    coll = api.create_rule_collection(tab, "", "Lines tagged Topic", {"tags": ["*"]})
    chart_note = api.create_chart_note(tab, "", "", CHART)
    stills: dict[str, "Image"] = {}
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
        page.goto((UI / "index.html").as_uri())
        page.locator("#tabs .tab-item").first.wait_for()

        def still(name, focus=None, pane="#editor-pane", ratio=1.6):
            page.mouse.move(2, 2)
            page.wait_for_timeout(250)
            box = page.locator(pane).bounding_box()
            if focus is not None:
                fb = focus.bounding_box()
                if fb:
                    box = dict(box, cy=fb["y"] + fb["height"] / 2)
            stills[name] = crop(page.screenshot(type="png"), box, ratio)

        # the note: prose, a styled example, a table with examples in its cells, a checklist
        page.locator(".note-card", has_text="Chapter 3").click()
        page.locator("#editor .text-obj .segment").first.wait_for()
        page.locator("#editor table.md-table .text-obj .segment").first.wait_for()
        page.wait_for_timeout(600)
        still("claim-notes", page.locator("#editor table.md-table"))
        still("claim-example", page.locator("#editor .text-obj").first)
        # the word popover: highlight / bold / underline / brackets
        page.locator("#editor .text-obj").first.locator(".word-cell").nth(1).locator(".il-txt").click()
        page.locator(".popover").wait_for()
        page.wait_for_timeout(300)
        still("claim-style", page.locator("#editor .text-obj").first)
        page.keyboard.press("Escape")
        # audio: the ▶ and the player
        page.locator("#editor .text-obj").first.locator(".seg-play").first.click()
        page.wait_for_timeout(700)
        still("claim-audio", page.locator("#editor .text-obj").first)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        # the export menu
        page.locator("#btn-note-menu").click()
        page.locator(".popover .menu-item", has_text="Word").wait_for()
        page.wait_for_timeout(250)
        still("claim-export", page.locator(".popover"))
        page.keyboard.press("Escape")
        # a collection made by rule
        page.locator(".note-card", has_text="Lines tagged").click()
        page.locator("#collection .coll-item .text-obj .segment").first.wait_for()
        page.wait_for_timeout(600)
        still("claim-collect", page.locator("#collection .coll-item").first, pane="#editor-pane")
        # the chart note in its three views
        page.locator(".note-card", has_text="Story chart").click()
        page.locator("#chartnote .tchart tr.crow").first.wait_for()
        page.wait_for_timeout(600)
        still("claim-chart-columns", page.locator("#chartnote .tchart"), pane="#chartnote", ratio=1.5)
        page.locator("#chartnote [data-test=chart-view]").click()
        page.wait_for_timeout(700)
        still("claim-chart-flat", page.locator("#chartnote .tchart"), pane="#chartnote", ratio=1.5)
        page.locator("#chartnote [data-test=chart-view-groups]").click()
        page.wait_for_timeout(700)
        still("claim-chart-groups", page.locator("#chartnote .tchart"), pane="#chartnote", ratio=1.5)
        # the chart search
        page.locator("#btn-chart-search").click()
        page.locator(".modal input[type=text]").first.wait_for()
        page.locator(".modal input[type=text]").first.fill("col:Subject lex:kabir")
        page.wait_for_timeout(900)
        still("claim-chart-search", page.locator(".modal"), pane=".modal", ratio=1.5)
        page.keyboard.press("Escape")
        # the concordance import
        page.locator("#btn-new-menu").click()
        page.locator("[data-test=new-concordance]").click()
        page.locator("[data-test=conc-text]").fill(CONCORDANCE)
        page.wait_for_function("() => /placed/.test(document.querySelector('[data-test=conc-count]').textContent)")
        page.wait_for_timeout(300)
        still("claim-concordance", page.locator(".modal"), pane=".modal", ratio=1.5)
        page.keyboard.press("Escape")
        browser.close()
    files = []
    for name, im in stills.items():
        out = OUT / f"{name}.webp"
        im.save(out, "WEBP", quality=86, method=6)
        files.append(out)
        print(f"{out.relative_to(ROOT)}  {out.stat().st_size // 1024} KB  {im.size[0]}x{im.size[1]}")
    avail = OUT / "available.json"
    data = json.loads(avail.read_text(encoding="utf-8")) if avail.exists() else {"files": []}
    data.setdefault("_about", "Files in this folder that the site's pages may show (docs/assets/media.js). Made by tools/record_demo.py and tools/shoot_claims.py.")
    data["files"] = sorted(set(data.get("files", [])) | {p.name for p in files})
    avail.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
