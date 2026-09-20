from __future__ import annotations

import ctypes
import os
import time

from PySide6.QtCore import QCoreApplication, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


class SingleInstance(QObject):
    """One GUI runtime per Windows user, with second-launch activation."""

    activationRequested = Signal()

    def __init__(self, name: str = "OniThermalLcdControl-v1", parent=None):
        super().__init__(parent);self.name=name;self.server=QLocalServer(self)
        self._mutex=None
        self.server.newConnection.connect(self._accept)

    def acquire_or_notify(self, timeout_ms: int = 750) -> bool:
        if os.name=="nt":
            kernel32=ctypes.WinDLL("kernel32",use_last_error=True)
            kernel32.CreateMutexW.argtypes=(ctypes.c_void_p,ctypes.c_bool,ctypes.c_wchar_p);kernel32.CreateMutexW.restype=ctypes.c_void_p
            self._mutex=kernel32.CreateMutexW(None,False,f"Local\\{self.name}")
            primary=bool(self._mutex) and ctypes.get_last_error()!=183
        else:
            primary=self.server.listen(self.name)
        if primary:
            if not self.server.isListening():
                QLocalServer.removeServer(self.name)
                if not self.server.listen(self.name):raise RuntimeError(f"cannot create activation server: {self.server.errorString()}")
            return True
        client=QLocalSocket();client.connectToServer(self.name)
        deadline=time.monotonic()+timeout_ms/1000
        while client.state()!=QLocalSocket.ConnectedState and time.monotonic()<deadline:
            QCoreApplication.processEvents();client.waitForConnected(25)
        if client.state()==QLocalSocket.ConnectedState:
            client.write(b"activate\n");client.flush();client.waitForBytesWritten(timeout_ms);client.disconnectFromServer();return False
        return False

    def _accept(self):
        while self.server.hasPendingConnections():
            client=self.server.nextPendingConnection();client.readAll();client.disconnectFromServer();client.deleteLater()
            self.activationRequested.emit()

    def close(self):
        if self.server.isListening():self.server.close()
        if self._mutex and os.name=="nt":ctypes.WinDLL("kernel32").CloseHandle(self._mutex);self._mutex=None
