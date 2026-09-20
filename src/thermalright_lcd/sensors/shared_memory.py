from __future__ import annotations

from contextlib import closing
import ctypes
from ctypes import wintypes
import io
import os
from typing import Any, Callable, Protocol


class SnapshotReader(Protocol):
    """A snapshot may be raw bytes, XML text, or decoded fixture records."""
    def read(self) -> bytes | str | dict[str, Any] | list[dict[str, Any]]: ...


class ReadOnlyNamedMemoryReader:
    """Open a Windows named mapping with read access for one bounded snapshot.

    ``opener`` is injectable for tests and alternate documented APIs. It must
    return a context manager/object with ``read`` and ``close`` methods.
    """

    def __init__(
        self, name: str, size: int,
        opener: Callable[[str, int], Any] | None = None,
    ) -> None:
        if not name or size <= 0:
            raise ValueError("mapping name and positive maximum size are required")
        self.name, self.size = name, size
        self._opener = opener or self._open_windows

    @staticmethod
    def _open_windows(name: str, size: int):
        if os.name != "nt":
            raise OSError("Windows named shared memory is unavailable")
        # OpenFileMapping (rather than mmap(tagname=...)) is deliberate: the
        # latter may create a missing named mapping. This path can only open an
        # existing object with FILE_MAP_READ and never creates or writes one.
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenFileMappingW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
        kernel32.OpenFileMappingW.restype = wintypes.HANDLE
        kernel32.MapViewOfFile.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                           wintypes.DWORD, ctypes.c_size_t)
        kernel32.MapViewOfFile.restype = ctypes.c_void_p
        kernel32.UnmapViewOfFile.argtypes = (ctypes.c_void_p,)
        class MEMORY_BASIC_INFORMATION(ctypes.Structure):
            _fields_=[("BaseAddress",ctypes.c_void_p),("AllocationBase",ctypes.c_void_p),("AllocationProtect",wintypes.DWORD),("PartitionId",wintypes.WORD),("RegionSize",ctypes.c_size_t),("State",wintypes.DWORD),("Protect",wintypes.DWORD),("Type",wintypes.DWORD)]
        kernel32.VirtualQuery.argtypes=(ctypes.c_void_p,ctypes.POINTER(MEMORY_BASIC_INFORMATION),ctypes.c_size_t);kernel32.VirtualQuery.restype=ctypes.c_size_t
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        file_map_read = 0x0004
        handle = kernel32.OpenFileMappingW(file_map_read, False, name)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        view = None
        try:
            # A fixed requested view fails when a provider version creates a
            # smaller mapping. Map the existing object in full (length zero),
            # query that read-only region, then copy no more than our cap.
            view = kernel32.MapViewOfFile(handle, file_map_read, 0, 0, 0)
            if not view:
                raise ctypes.WinError(ctypes.get_last_error())
            info=MEMORY_BASIC_INFORMATION()
            if not kernel32.VirtualQuery(view,ctypes.byref(info),ctypes.sizeof(info)):
                raise ctypes.WinError(ctypes.get_last_error())
            return io.BytesIO(ctypes.string_at(view,min(size,int(info.RegionSize))))
        finally:
            if view: kernel32.UnmapViewOfFile(view)
            kernel32.CloseHandle(handle)

    def read(self) -> bytes:
        try:
            handle = self._opener(self.name, self.size)
        except OSError as exc:
            detail=f" (Windows error {getattr(exc,'winerror',None)}: {exc})" if getattr(exc,"winerror",None) else f" ({exc})"
            raise FileNotFoundError(f"shared memory {self.name!r} unavailable{detail}") from exc
        with closing(handle):
            handle.seek(0)
            return bytes(handle.read(self.size))


class FixtureSnapshotReader:
    """Small public helper useful to tests and diagnostics without live access."""
    def __init__(self, snapshot: Any): self.snapshot = snapshot
    def read(self): return self.snapshot
