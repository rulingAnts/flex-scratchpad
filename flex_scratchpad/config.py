"""Per-user app configuration (NOT the notebook): where the notebook lives, window geometry.

Stored as JSON in the platform's per-user config folder:
  Windows  %APPDATA%\\FLEx Scratchpad\\config.json
  macOS    ~/Library/Application Support/FLEx Scratchpad/config.json
  Linux    $XDG_CONFIG_HOME/flex-scratchpad/config.json
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from . import APP_NAME


def config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        return base / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "flex-scratchpad"


def local_data_dir() -> Path:
    """Non-roaming data (the WebView2 profile). Same as config_dir() off Windows."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / APP_NAME
    return config_dir()


def default_notebook_dir() -> Path:
    docs = Path.home() / "Documents"
    return (docs if docs.is_dir() else Path.home()) / APP_NAME


DEFAULTS = {
    "notebook": "",          # '' → default_notebook_dir()
    "window": {"width": 1280, "height": 820},
}


class AppConfig:
    def __init__(self, path: Path | None = None):
        self.path = path or (config_dir() / "config.json")
        self.data = json.loads(json.dumps(DEFAULTS))
        self.load()

    def load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                self.data.update(loaded)
        except (OSError, ValueError):
            pass

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.path)

    @property
    def notebook_dir(self) -> Path:
        p = self.data.get("notebook") or ""
        return Path(p) if p else default_notebook_dir()

    @notebook_dir.setter
    def notebook_dir(self, value: str | Path) -> None:
        self.data["notebook"] = str(value)
        self.save()
