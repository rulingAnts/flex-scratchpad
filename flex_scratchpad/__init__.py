"""FLEx Scratchpad — a notebook that shows live FieldWorks objects inside notes.

Python owns the FieldWorks project (through flexicon / LCM) and the notebook on disk; the
notebook UI is HTML and JavaScript shown in a native pywebview window and talks to Python only
through pywebview's exposed ``js_api`` (no HTTP server of any kind).
"""

__version__ = "0.1.0"
APP_NAME = "FLEx Scratchpad"
