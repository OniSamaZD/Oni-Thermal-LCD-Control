from __future__ import annotations

import ctypes
import os
from ctypes import wintypes


NAMES = {"TRCC", "USBLCD", "USBLCDNEW"}
_MATCH_NAMES = {name.casefold() for name in NAMES}
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_TH32CS_SNAPPROCESS = 0x00000002
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


class CtypesWindowsProcessApi:
    """Small Toolhelp wrapper used by the output conflict safety check."""

    def __init__(self):
        if os.name != "nt":
            raise OSError("Windows process enumeration is unavailable")
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        self.kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        self.kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
        self.kernel32.Process32FirstW.restype = wintypes.BOOL
        self.kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
        self.kernel32.Process32NextW.restype = wintypes.BOOL
        self.kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel32.OpenProcess.restype = wintypes.HANDLE
        self.kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        self.kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        self.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel32.CloseHandle.restype = wintypes.BOOL

    def snapshot(self):
        handle = self.kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
        if handle in (None, 0, _INVALID_HANDLE_VALUE):
            raise OSError(ctypes.get_last_error(), "CreateToolhelp32Snapshot failed")
        return handle

    @staticmethod
    def _entry():
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        return entry

    def first(self, snapshot):
        entry = self._entry()
        if not self.kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            raise OSError(ctypes.get_last_error(), "Process32FirstW failed")
        return entry.szExeFile, int(entry.th32ProcessID)

    def next(self, snapshot):
        entry = self._entry()
        if self.kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
            return entry.szExeFile, int(entry.th32ProcessID)
        if ctypes.get_last_error() == 18:  # ERROR_NO_MORE_FILES
            return None
        raise OSError(ctypes.get_last_error(), "Process32NextW failed")

    def path(self, process_id):
        handle = self.kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, process_id)
        if not handle:
            return None
        try:
            size = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not self.kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return None
            return buffer.value
        finally:
            self.close(handle)

    def close(self, handle):
        self.kernel32.CloseHandle(handle)


def _process_name(executable: str) -> str:
    name = os.path.basename(str(executable).strip())
    return name[:-4] if name.casefold().endswith(".exe") else name


def thermalright_processes(api=None):
    """Return running Thermalright helper conflicts without spawning a shell."""
    try:
        api = api or CtypesWindowsProcessApi()
        snapshot = api.snapshot()
    except (OSError, ValueError):
        return []
    matches = []
    try:
        try:
            entry = api.first(snapshot)
        except (OSError, ValueError):
            return []
        while entry is not None:
            executable, process_id = entry
            name = _process_name(executable)
            if name.casefold() in _MATCH_NAMES:
                try:
                    path = api.path(process_id)
                except (OSError, ValueError):
                    path = None
                matches.append({"ProcessName": name, "Id": int(process_id), "Path": path})
            try:
                entry = api.next(snapshot)
            except (OSError, ValueError):
                break
        return matches
    finally:
        api.close(snapshot)
