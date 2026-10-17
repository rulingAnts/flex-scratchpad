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
# beside the program as `ffmpeg/ffmpeg.exe`, where flex/audio.py's bundled_ffmpeg() looks; rclone
# likewise (tools/fetch_rclone.py) as `rclone/rclone.exe`, where backup.py's bundled_rclone() looks.
import os
from PyInstaller.utils.hooks import collect_all

block_cipher = None
here = os.path.abspath(os.path.dirname(SPEC))
root = os.path.dirname(here)

# The page, from the source tree by path (collect_data_files finds nothing when the package is not
# installed where the build runs, and a build without its ui/ cannot open a window).
pkg = os.path.join(root, "flex_scratchpad")
datas = []
for d, _, files in os.walk(os.path.join(pkg, "ui")):
    rel = os.path.relpath(d, root)
    datas += [(os.path.join(d, f), rel) for f in files]
# the build fingerprint of these sources (build_id() reads it: there are no .py files to hash)
import sys as _sys
_sys.path.insert(0, root)
import flex_scratchpad as _fs
work = os.path.join(here, "work")
os.makedirs(work, exist_ok=True)
with open(os.path.join(work, "BUILD_ID"), "w", encoding="utf-8") as _f:
    _f.write(_fs.build_id())
datas.append((os.path.join(work, "BUILD_ID"), "flex_scratchpad"))
binaries = []
hidden = ["flex_scratchpad.flex.lcm", "flex_scratchpad.flex.flextext", "flex_scratchpad.flex.demo",
          "flex_scratchpad.flex.flextext_check", "flex_scratchpad.flex.flextext_writer",
          "flex_scratchpad.backup", "flex_scratchpad.secrets_store"]
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

# FS_CONSOLE=1 builds a console copy ("FLEx Scratchpad (console)") for the release workflow's
# self-test: the same program, but an error prints a traceback to the log instead of opening a
# message box that waits for a click.
console = os.environ.get("FS_CONSOLE") == "1"
a = Analysis(
    [os.path.join(here, "launcher.py")],      # not flex_scratchpad/__main__.py: see launcher.py
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
    name="FLEx Scratchpad (console)" if console else "FLEx Scratchpad",
    debug=False,
    strip=False,
    upx=False,
    console=console,
    icon=os.path.join(root, "flex_scratchpad", "ui", "img", "flex-scratchpad.ico"),
)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=False, name="FLEx Scratchpad (console)" if console else "FLEx Scratchpad")
