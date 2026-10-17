"""Secrets the app keeps for the user (the backup's access keys and encryption password).

On Windows they live in the Windows Credential Manager (Control Panel › Credential Manager ›
Windows Credentials, "FLEx Scratchpad/…"), Windows' own keychain: stored by Windows, readable only
by this Windows account, and never written to a file the app owns (Seth, 2026-10-17: "able to
store secrets securely or put them in Windows' equivalent of keychain"). Credential Manager is
reached through advapi32 with ctypes, so there is no extra dependency.

Off Windows (development and the tests) a file in the per-user config folder, readable by the
user only, stands in for it. The secrets are only ever handed to rclone through its environment,
never on a command line and never in an rclone.conf.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PREFIX = "FLEx Scratchpad/"


class SecretStore:
    """get / set / delete by name; `where` says, for the UI, where they are kept."""

    where = ""

    def get(self, name: str) -> str | None:
        raise NotImplementedError

    def set(self, name: str, value: str) -> None:
        raise NotImplementedError

    def delete(self, name: str) -> None:
        raise NotImplementedError

    def has(self, name: str) -> bool:
        return bool(self.get(name))


class MemoryStore(SecretStore):
    where = "memory (tests)"

    def __init__(self):
        self._d: dict[str, str] = {}

    def get(self, name):
        return self._d.get(name)

    def set(self, name, value):
        self._d[name] = value

    def delete(self, name):
        self._d.pop(name, None)


class FileStore(SecretStore):
    """Off Windows only: a JSON file the user alone may read (mode 600)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.where = f"{self.path} (readable by this user only)"

    def _read(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _write(self, d: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(d, f)
        os.replace(tmp, self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def get(self, name):
        return self._read().get(name)

    def set(self, name, value):
        d = self._read()
        d[name] = value
        self._write(d)

    def delete(self, name):
        d = self._read()
        if d.pop(name, None) is not None:
            self._write(d)


class WindowsCredentialStore(SecretStore):
    """Generic credentials in the Windows Credential Manager, one per secret, kept on this
    computer for this Windows account (CRED_PERSIST_LOCAL_MACHINE: not carried to other
    computers by a roaming profile)."""

    where = "Windows Credential Manager"
    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2
    ERROR_NOT_FOUND = 1168

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        class FILETIME(ctypes.Structure):
            _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

        class CREDENTIALW(ctypes.Structure):
            _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                        ("Comment", wintypes.LPWSTR), ("LastWritten", FILETIME), ("CredentialBlobSize", wintypes.DWORD),
                        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)), ("Persist", wintypes.DWORD),
                        ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                        ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]

        self._ct, self._C = ctypes, CREDENTIALW
        adv = ctypes.WinDLL("advapi32", use_last_error=True)
        self._write = adv.CredWriteW
        self._write.argtypes = [ctypes.POINTER(CREDENTIALW), wintypes.DWORD]
        self._write.restype = wintypes.BOOL
        self._read = adv.CredReadW
        self._read.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(CREDENTIALW))]
        self._read.restype = wintypes.BOOL
        self._delete = adv.CredDeleteW
        self._delete.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        self._delete.restype = wintypes.BOOL
        self._free = adv.CredFree
        self._free.argtypes = [ctypes.c_void_p]
        self._free.restype = None

    def get(self, name):
        ct = self._ct
        p = ct.POINTER(self._C)()
        if not self._read(PREFIX + name, self.CRED_TYPE_GENERIC, 0, ct.byref(p)):
            if ct.get_last_error() == self.ERROR_NOT_FOUND:
                return None
            raise OSError(ct.get_last_error(), "Could not read from the Windows Credential Manager")
        try:
            c = p.contents
            raw = ct.string_at(c.CredentialBlob, c.CredentialBlobSize)
            return raw.decode("utf-16-le")
        finally:
            self._free(p)

    def set(self, name, value):
        ct = self._ct
        blob = (value or "").encode("utf-16-le")
        buf = (ct.c_ubyte * max(1, len(blob))).from_buffer_copy(blob or b"\0")
        c = self._C()
        c.Type = self.CRED_TYPE_GENERIC
        c.TargetName = PREFIX + name
        c.Comment = "FLEx Scratchpad: notebook backup"
        c.CredentialBlobSize = len(blob)
        c.CredentialBlob = ct.cast(buf, ct.POINTER(ct.c_ubyte))
        c.Persist = self.CRED_PERSIST_LOCAL_MACHINE
        c.UserName = "FLEx Scratchpad"
        if not self._write(ct.byref(c), 0):
            raise OSError(ct.get_last_error(), "Could not save to the Windows Credential Manager")

    def delete(self, name):
        if not self._delete(PREFIX + name, self.CRED_TYPE_GENERIC, 0) and self._ct.get_last_error() != self.ERROR_NOT_FOUND:
            raise OSError(self._ct.get_last_error(), "Could not remove from the Windows Credential Manager")


def default_store() -> SecretStore:
    if sys.platform == "win32":
        return WindowsCredentialStore()
    from .config import config_dir
    return FileStore(config_dir() / "secrets.json")
