"""Record the website's loop video and its three stills from the REAL program (dev-only).

    python tools/record_demo.py                 → docs/media/scratchpad-loop.{mp4,webm,jpg}
                                                   docs/media/step-*.webp, docs/media/available.json

What is filmed is the actual UI (flex_scratchpad/ui) against the built-in demo project — an
invented language, so no community's data appears on the site — through the same no-server bridge
the end-to-end tests use (tests/e2e/bridge.py: file:// page, js_api into the real Python Api).
It is "artificial" only in that the pointer and the captions are drawn: the page sits in an
iframe inside a stage page dressed as a Windows window, a cursor glides to each target before the
real mouse event is sent there, and a caption names each step.

Frames come from Chromium's own screencast (CDP Page.startScreencast, JPEG at device scale 1.5),
each with its timestamp, so the cut keeps real timing; ffmpeg turns them into a 1280x720 H.264 MP4
and a VP9 WebM (silent, faststart), cross-fades the end into the first frame for a seamless loop,
and takes the poster from the first frame. Needs: Playwright's Chromium, ffmpeg with libx264 and
libvpx-vp9, Pillow (for the WebP stills).

The storyboard is SHOTS below. When the UI changes, re-run this and look at the result.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "e2e"))
from bridge import INIT_SCRIPT, Harness  # noqa: E402
from flex_scratchpad.flex.demo import T_STORY  # noqa: E402

OUT = ROOT / "docs" / "media"
W, H, SCALE = 1280, 720, 1.5
UI = ROOT / "flex_scratchpad" / "ui"

NOTE = f"""# 3 Verbs

## 3.1 Past tense

The past tense suffix *-mo* follows the verb stem, as in (1).

{{{{flex:text {T_STORY} seg=1 ex}}}}

The same suffix with a transitive verb:

## 3.2 Questions

Questions end in the particle *ba*.

Yes/no questions keep the order of a statement.
"""
# what FLEx's Gloss tab puts on the clipboard for segment 1.2 of the demo text
PASTE = "1.2\tWord\tHaŋa\ttiket\tka-sila-mo\tpemu\n\tWord Gloss\tyesterday\tchild\tsaw\triver\nFree\tYesterday the child saw the river."

STAGE = """<!doctype html><html><head><meta charset="utf-8"><style>
html, body { margin: 0; height: 100%; overflow: hidden; font-family: 'Segoe UI', system-ui, sans-serif; }
body { background: radial-gradient(60% 80% at 85% 0%, rgba(96,165,250,.45), transparent 70%), linear-gradient(160deg, #1e3a8a, #1d4ed8); }
.win { position: absolute; left: 28px; right: 28px; top: 22px; bottom: 0; background: #fff; border-radius: 9px 9px 0 0;
       box-shadow: 0 24px 60px rgba(2,6,23,.45); overflow: hidden; display: flex; flex-direction: column; }
.bar { height: 30px; flex: none; display: flex; align-items: center; gap: 8px; padding: 0 0 0 10px; background: #f3f3f3; border-bottom: 1px solid #e5e5e5; font-size: 12.5px; color: #1f1f1f; }
.bar img { width: 16px; height: 16px; }
.bar .t { flex: 1; }
.bar .c { display: flex; height: 100%; }
.bar .c i { width: 44px; height: 100%; display: grid; place-items: center; font-style: normal; color: #444; font-size: 12px; }
iframe { flex: 1; border: 0; width: 100%; display: block; }
#cur { position: absolute; left: 640px; top: 400px; width: 22px; z-index: 10; pointer-events: none; filter: drop-shadow(0 2px 3px rgba(0,0,0,.35)); transition-property: left, top; transition-timing-function: cubic-bezier(.45,.05,.3,1); }
#cur svg { display: block; width: 100%; margin: -2px 0 0 -4px; }
#ring { position: absolute; z-index: 9; width: 34px; height: 34px; margin: -17px 0 0 -17px; border-radius: 50%; background: rgba(0,120,215,.42); opacity: 0; transform: scale(.3); pointer-events: none; }
#ring.go { animation: ring .45s ease-out; }
@keyframes ring { 0% { opacity: 1; transform: scale(.3); } 100% { opacity: 0; transform: scale(1.5); } }
#cap { position: absolute; left: 50%; bottom: 26px; z-index: 11; transform: translate(-50%, 8px); opacity: 0; transition: opacity .35s, transform .35s;
       background: rgba(15,23,42,.86); color: #fff; font: 600 19px/1.2 'Segoe UI', system-ui, sans-serif; padding: 10px 20px; border-radius: 999px; white-space: nowrap;
       box-shadow: 0 10px 30px rgba(2,6,23,.35); }
#cap.on { opacity: 1; transform: translate(-50%, 0); }
</style></head><body>
<div class="win"><div class="bar"><img src="ICON"><span class="t">FLEx Scratchpad</span><span class="c"><i>&#x2013;</i><i>&#x25a1;</i><i>&#x2715;</i></span></div>
<iframe id="app" src="APP"></iframe></div>
<div id="ring"></div>
<div id="cur"><svg viewBox="0 0 24 24"><path d="M4 2 L4 20 L9 15.5 L12.5 23 L15.5 21.6 L12 14.3 L19 14.3 Z" fill="#fff" stroke="#000" stroke-width="1.4" stroke-linejoin="round"/></svg></div>
<div id="cap"></div>
</body></html>"""


class Director:
    def __init__(self, page, app):
        self.page, self.app = page, app
        self.x, self.y = 640.0, 400.0

    def at(self, loc, fx=0.5, fy=0.5):
        loc.wait_for(state="visible")
        bb = loc.bounding_box()
        frame = self.page.locator("#app").bounding_box()
        if bb["y"] < frame["y"] + 40 or bb["y"] + bb["height"] > frame["y"] + frame["height"] - 60:
            # out of view: scroll it to the middle the way a person would, smoothly
            loc.evaluate("(e) => e.scrollIntoView({ behavior: 'smooth', block: 'center' })")
            self.page.wait_for_timeout(750)
            bb = loc.bounding_box()
        return bb["x"] + bb["width"] * fx, bb["y"] + bb["height"] * fy

    def glide(self, x, y, pause=180):
        d = ((x - self.x) ** 2 + (y - self.y) ** 2) ** 0.5
        ms = int(max(260, min(900, d * 1.1)))
        self.page.evaluate("([x, y, ms]) => { const c = document.getElementById('cur'); c.style.transitionDuration = ms + 'ms'; c.style.left = x + 'px'; c.style.top = y + 'px'; }", [x, y, ms])
        # the real pointer follows in steps, so hover styles (a heading's ▾) appear as the cursor arrives
        self.page.mouse.move(x, y, steps=max(4, ms // 40))
        self.page.wait_for_timeout(max(0, ms - (ms // 40) * 4) + pause)
        self.x, self.y = x, y

    def click(self, loc, fx=0.5, fy=0.5, pause=260):
        x, y = self.at(loc, fx, fy)
        self.glide(x, y)
        self.page.evaluate("([x, y]) => { const r = document.getElementById('ring'); r.style.left = x + 'px'; r.style.top = y + 'px'; r.classList.remove('go'); void r.offsetWidth; r.classList.add('go'); }", [x, y])
        self.page.mouse.down()
        self.page.wait_for_timeout(70)
        self.page.mouse.up()
        self.page.wait_for_timeout(pause)

    def caption(self, text):
        self.page.evaluate("(t) => { const c = document.getElementById('cap'); if (!t) { c.classList.remove('on'); return; } c.textContent = t; c.classList.add('on'); }", text)

    def hold(self, ms):
        self.page.wait_for_timeout(ms)


def run(page, d: Director, app, stills: dict):
    """The storyboard: about 24 seconds."""
    a = app
    d.hold(1300)
    # 1 — paste FLEx rows: the program finds the segment in the project
    d.caption("Copy lines in FLEx, paste them into a note")
    d.click(a.locator("#editor .blk-body", has_text="The same suffix with a transitive verb"), fx=0.98)
    page.keyboard.press("End")
    page.keyboard.press("Enter")
    d.hold(250)
    a.locator("body").evaluate("""(b, plain) => { const dt = new DataTransfer(); dt.setData('text/plain', plain);
        document.activeElement.dispatchEvent(new InputEvent('beforeinput', { inputType: 'insertFromPaste', dataTransfer: dt, bubbles: true, cancelable: true })); }""", PASTE)
    a.locator(".modal").wait_for()
    d.hold(900)
    d.click(a.locator(".modal .btn.primary", has_text="Insert rendered"))
    a.locator("#editor .text-obj .segment[data-n='2']").wait_for()
    d.hold(400)
    # bring the new example into view, as anyone would after inserting it
    a.locator("#editor .text-obj").nth(1).evaluate("(e) => e.scrollIntoView({ behavior: 'smooth', block: 'center' })")
    d.hold(900)
    stills["step-paste"] = shot(page, a.locator("#editor .text-obj").nth(1))
    d.hold(600)
    # 2 — mark a word
    d.caption("Highlight words in any colour")
    word = a.locator("#editor .text-obj").nth(1).locator(".word-cell").nth(2).locator(".il-txt")
    d.click(word)
    a.locator(".popover").wait_for()
    d.hold(350)
    d.click(a.locator(".popover .sw").nth(1))
    d.hold(300)
    stills["step-style"] = shot(page, a.locator(".popover"))
    page.keyboard.press("Escape")
    d.hold(700)
    # 3 — fold a section
    d.caption("Fold a section away")
    q = a.locator("#editor .blk-h", has=a.locator(".blk-body", has_text="3.2 Questions"))
    x, y = d.at(q.locator(".blk-body"), fx=0.25)
    d.glide(x, y, pause=250)
    d.click(q.locator(".fold-tog"))
    d.hold(900)
    # 4 — collect the examples and export them to FLEx
    d.caption("Collect the examples, export them as a FLEx text")
    d.click(a.locator("#btn-note-menu"))
    a.locator(".popover").wait_for()
    d.hold(300)
    d.click(a.locator(".popover .menu-item", has_text="Collect the"))
    a.locator("#collection .coll-item").first.wait_for()
    d.hold(1100)
    stills["step-collect"] = shot(page, a.locator("#collection .coll-item").first)
    d.click(a.locator("[data-test='coll-export']"))
    a.locator(".modal").wait_for()
    d.hold(1900)
    d.caption("")
    d.hold(500)


def shot(page, focus=None):
    """A still for the steps section: the note pane only (the whole window is too small to read
    at the size a step shows it), without the drawn cursor and caption. → (png, box in CSS px)."""
    page.evaluate("() => ['cur', 'cap', 'ring'].forEach((id) => document.getElementById(id).style.visibility = 'hidden')")
    page.mouse.move(4, 4)                      # no hover outline on whatever the pointer was over
    page.wait_for_timeout(150)
    box = page.frame_locator("#app").locator("#editor-pane").bounding_box()
    if focus is not None:                      # the 16:10 window is centred on what the step shows
        fb = focus.bounding_box()
        box = dict(box, cy=fb["y"] + fb["height"] / 2)
    png = page.screenshot(type="png")
    page.evaluate("() => ['cur', 'cap', 'ring'].forEach((id) => document.getElementById(id).style.visibility = '')")
    return png, box


def chromium_path():
    root = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers"))
    for p in sorted(root.glob("chromium-*/chrome-linux/chrome"), reverse=True):
        return str(p)
    return None


def record(work: Path) -> tuple[list[tuple[float, Path]], dict]:
    from playwright.sync_api import sync_playwright
    h = Harness()
    api = h.api
    tab = api.init()["tabs"][0]["dir"] if api.init().get("tabs") else "Notes"
    for title, body in (("Field trip, 12 October", "Recorded two stories at the river.\n"), ("Serial verbs", "Notes for chapter 4.\n")):
        api.create_note(tab, "", title, body)
    note = api.create_note(tab, "", "Chapter 3 — Verbs", NOTE)
    stage = work / "stage.html"
    stage.write_text(STAGE.replace("APP", (UI / "index.html").as_uri()).replace("ICON", (UI / "img" / "icon-small.svg").as_uri()), encoding="utf-8")
    frames: list[tuple[float, Path]] = []
    stills: dict = {}
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
        page.goto(stage.as_uri())
        app = page.frame_locator("#app")
        app.locator("#tabs .tab-item").first.wait_for()
        app.locator(".note-card", has_text="Chapter 3").click()
        app.locator("#editor .text-obj .segment").first.wait_for()
        page.wait_for_timeout(1200)
        # the cursor starts in the note, the page is settled: now film
        cdp = ctx.new_cdp_session(page)

        def on_frame(ev):
            k = len(frames)
            f = work / f"f{k:05d}.jpg"
            f.write_bytes(base64.b64decode(ev["data"]))
            frames.append((ev["metadata"]["timestamp"], f))
            try:
                cdp.send("Page.screencastFrameAck", {"sessionId": ev["sessionId"]})
            except Exception:  # noqa: BLE001
                pass
        cdp.on("Page.screencastFrame", on_frame)
        cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 95, "maxWidth": int(W * SCALE), "maxHeight": int(H * SCALE), "everyNthFrame": 1})
        d = Director(page, app)
        try:
            run(page, d, app, stills)
        except Exception:
            fail = OUT.parent / "record-demo-failed.png"
            page.screenshot(path=str(fail))
            print("the storyboard stopped; the screen at that moment:", fail, file=sys.stderr)
            raise
        end = frames[-1][0] if frames else 0
        page.wait_for_timeout(300)
        cdp.send("Page.stopScreencast")
        end = max(end, frames[-1][0]) + 0.05
        frames.append((end, frames[-1][1]))
        browser.close()
    shutil.rmtree(h.tmp, ignore_errors=True)
    return frames, stills


def ff(*args):
    subprocess.run(["ffmpeg", "-y", "-v", "error", *args], check=True)


def encode(frames, work: Path):
    t0 = frames[0][0]
    lst = work / "frames.txt"
    with open(lst, "w", encoding="utf-8") as f:
        for (t, p), (t2, _) in zip(frames, frames[1:]):
            f.write(f"file '{p.name}'\nduration {max(0.001, t2 - t):.4f}\n")
        f.write(f"file '{frames[-1][1].name}'\n")
    raw = work / "raw.mp4"
    ff("-f", "concat", "-safe", "0", "-i", str(lst), "-vf", f"fps=30,scale={W}:{H}:flags=lanczos,format=yuv420p", "-c:v", "libx264", "-crf", "12", "-preset", "veryfast", str(raw))
    length = frames[-1][0] - t0
    first = work / "first.png"
    ff("-i", str(raw), "-frames:v", "1", str(first))
    # a seamless loop: the last 0.8 s cross-fade into the first frame, which the loop starts on
    looped = work / "loop.mp4"
    ff("-i", str(raw), "-loop", "1", "-t", "1.0", "-i", str(first), "-filter_complex",
       f"[1]fps=30,scale={W}:{H},format=yuv420p,settb=AVTB[s];[0]settb=AVTB[v];[v][s]xfade=transition=fade:duration=0.8:offset={length - 0.6:.3f},format=yuv420p",
       "-c:v", "libx264", "-crf", "12", "-preset", "veryfast", str(looped))
    OUT.mkdir(parents=True, exist_ok=True)
    mp4, webm, jpg = OUT / "scratchpad-loop.mp4", OUT / "scratchpad-loop.webm", OUT / "scratchpad-loop.jpg"
    ff("-i", str(looped), "-c:v", "libx264", "-preset", "slow", "-crf", "24", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", str(mp4))
    ff("-i", str(looped), "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "36", "-row-mt", "1", "-an", str(webm))
    ff("-i", str(mp4), "-frames:v", "1", "-q:v", "3", str(jpg))
    return [mp4, webm, jpg], length


def stills_out(stills: dict) -> list[Path]:
    """The three step pictures: the note pane, 16:10, WebP."""
    from io import BytesIO
    from PIL import Image
    out = []
    for name, (png, b) in stills.items():
        im = Image.open(BytesIO(png)).convert("RGB")
        k = SCALE
        x0, x1 = b["x"], b["x"] + b["width"]
        hh = b["width"] / 1.6                      # the steps' 16:10 slots
        cy = b.get("cy", b["y"] + hh / 2)
        y0 = max(b["y"], min(cy - hh / 2, b["y"] + b["height"] - hh))
        im = im.crop((int(x0 * k), int(y0 * k), int(x1 * k), int((y0 + hh) * k)))
        im = im.resize((1200, int(1200 * im.size[1] / im.size[0])), Image.LANCZOS)
        p = OUT / f"{name}.webp"
        im.save(p, "WEBP", quality=86, method=6)
        out.append(p)
    return out


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="fs-video-"))
    try:
        frames, stills = record(work)
        files, length = encode(frames, work)
        files += stills_out(stills)
        avail = OUT / "available.json"
        avail.write_text(json.dumps({
            "_about": "Files in this folder that the site's pages may show (docs/assets/media.js). Made by tools/record_demo.py.",
            "files": sorted(p.name for p in files)}, indent=2) + "\n", encoding="utf-8")
        for p in files:
            print(f"{p.relative_to(ROOT)}  {p.stat().st_size // 1024} KB")
        print(f"{len(frames)} frames, {length:.1f} s")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
