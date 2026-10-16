"""Render the app icon: ui/img/icon.svg (48 px and up) and ui/img/icon-small.svg (16–32 px)
into PNGs and a multi-size Windows .ico, with the Chromium the Playwright tests already use.

    pip install playwright pillow      (dev only; the app itself needs neither)
    python tools/make_icons.py

Writes flex_scratchpad/ui/img/icon-<size>.png and flex_scratchpad/ui/img/flex-scratchpad.ico.
Re-run it after editing either SVG and commit the outputs."""
from __future__ import annotations

import io
import os
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

IMG = Path(__file__).resolve().parent.parent / "flex_scratchpad" / "ui" / "img"
SMALL = (16, 20, 24, 32)
LARGE = (40, 48, 64, 96, 128, 256)
PNGS = (32, 64, 128, 256, 512)


def render(page, svg: str, size: int) -> Image.Image:
    page.set_viewport_size({"width": size, "height": size})
    page.set_content('<html><body style="margin:0;background:transparent">'
                     f'<img id="i" src="data:image/svg+xml;base64,{_b64(svg)}" width="{size}" height="{size}"></body></html>')
    page.wait_for_function("document.getElementById('i').complete")
    png = page.locator("#i").screenshot(omit_background=True)
    return Image.open(io.BytesIO(png)).convert("RGBA")


def _b64(s: str) -> str:
    import base64
    return base64.b64encode(s.encode("utf-8")).decode("ascii")


def main() -> None:
    big = (IMG / "icon.svg").read_text(encoding="utf-8")
    small = (IMG / "icon-small.svg").read_text(encoding="utf-8")
    exe = os.environ.get("FS_CHROMIUM") or None          # as in tests/e2e: else an installed Playwright Chromium
    if not exe:
        root = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers"))
        found = sorted(root.glob("chromium-*/chrome-linux/chrome"), reverse=True)
        exe = str(found[0]) if found else None
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
        page = b.new_page(device_scale_factor=1)
        frames = {s: render(page, small if s in SMALL else big, s) for s in SMALL + LARGE}
        for s in PNGS:
            (render(page, small if s in SMALL else big, s)).save(IMG / f"icon-{s}.png")
        b.close()
    ico = IMG / "flex-scratchpad.ico"
    # each size drawn from its own SVG rendering (Pillow would otherwise scale one bitmap down)
    sizes = sorted(frames)
    frames[sizes[-1]].save(ico, format="ICO", sizes=[(s, s) for s in sizes],
                           append_images=[frames[s] for s in sizes[:-1]])
    print("wrote", ico, "and", ", ".join(f"icon-{s}.png" for s in PNGS))


if __name__ == "__main__":
    main()
