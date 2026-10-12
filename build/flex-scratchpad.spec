# PyInstaller spec — a ONEDIR build (never onefile: a onefile exe is a bootloader parent plus the
# real child process, and killing the parent orphans the child).
#
#   pip install "flex-scratchpad[build]"   (or: pip install pyinstaller pywebview)
#   pyinstaller build/flex-scratchpad.spec --distpath build/dist --workpath build/work
#
# flexicon + pythonnet are NOT bundled here on purpose: they load FieldWorks' own DLLs from the
# installed FieldWorks, and shipping them inside the bundle pins a FieldWorks version. Install
# them into the Python the bundle was built from, or run from a venv:  flex-scratchpad --check
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None
here = os.path.abspath(os.path.dirname(SPEC))
root = os.path.dirname(here)

datas = collect_data_files("flex_scratchpad", includes=["ui/**/*"])
hidden = ["flex_scratchpad.flex.lcm", "flex_scratchpad.flex.flextext", "flex_scratchpad.flex.demo"]
try:
    hidden += collect_submodules("flexicon")
    hidden += ["clr", "clr_loader", "pythonnet"]
except Exception:  # flexicon not installed where the build runs — fine, it is optional
    pass

a = Analysis(
    [os.path.join(root, "flex_scratchpad", "__main__.py")],
    pathex=[root],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "PyQt5", "PySide6"],
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
)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=False, name="FLEx Scratchpad")
