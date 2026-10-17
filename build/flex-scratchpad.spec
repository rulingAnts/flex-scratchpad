# PyInstaller spec — a ONEDIR build (never onefile: a onefile exe is a bootloader parent plus the
# real child process, and killing the parent orphans the child).
#
#   pip install ".[build,flex]" pywebview
#   pyinstaller build/flex-scratchpad.spec --distpath build/dist --workpath build/work --noconfirm
#
# flexicon and pythonnet ARE bundled (2026-10-16, for the first release): a packaged program has no
# Python a user could install them into, and without them it could only open .flextext files.
# flexicon finds FieldWorks itself at run time (its registry key, then FieldWorks.exe's folder on
# sys.path) and loads FieldWorks' own DLLs from there, so the FieldWorks version is whatever is
# installed; a FieldWorks that needs a newer flexicon needs a new release of this app.
#
# ffmpeg is not a Python module: the release workflow fetches it (tools/fetch_ffmpeg.py) and puts it
# beside the program as `ffmpeg/ffmpeg.exe`, where flex/audio.py's bundled_ffmpeg() looks.
import os
from PyInstaller.utils.hooks import collect_all, collect_data_files

block_cipher = None
here = os.path.abspath(os.path.dirname(SPEC))
root = os.path.dirname(here)

datas = collect_data_files("flex_scratchpad", includes=["ui/**/*"])
binaries = []
hidden = ["flex_scratchpad.flex.lcm", "flex_scratchpad.flex.flextext", "flex_scratchpad.flex.demo",
          "flex_scratchpad.flex.flextext_check", "flex_scratchpad.flex.flextext_writer"]
# pywebview (the window), pythonnet + clr_loader (.NET: pywebview's WinForms backend and flexicon
# both need it), flexicon (+ its flexlibs2 compatibility package). collect_all takes each package's
# modules, data files and native DLLs (Python.Runtime.dll, ClrLoader.dll …).
for pkg in ("webview", "pythonnet", "clr_loader", "flexicon", "flexlibs2"):
    try:
        d, b, h = collect_all(pkg)
    except Exception:  # not installed where the build runs (the [flex] extra is optional off Windows)
        continue
    datas += d
    binaries += b
    hidden += h
hidden += ["clr", "_cffi_backend"]

a = Analysis(
    [os.path.join(root, "flex_scratchpad", "__main__.py")],
    pathex=[root],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "PyQt5", "PySide6", "pytest", "playwright"],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="FLEx Scratchpad",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=os.path.join(root, "flex_scratchpad", "ui", "img", "flex-scratchpad.ico"),
)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=False, name="FLEx Scratchpad")
