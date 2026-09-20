from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable

class ConnectionState(str,Enum): DISCONNECTED="Disconnected";CONNECTING="Connecting";CONNECTED="Connected";ERROR="Error"

@dataclass
class SupervisorMetrics:
    discoveries:int=0;connects:int=0;disconnects:int=0;last_error:str=""

class DeviceSupervisor:
    """Readiness/reconnect coordinator; connect callback remains externally authorization-gated."""
    def __init__(self,discover:Callable[[],bool],connect:Callable[[],None],disconnect:Callable[[],None],interval:float=2):
        self.discover=discover;self.connect=connect;self.disconnect=disconnect;self.interval=interval
        self.state=ConnectionState.DISCONNECTED;self.metrics=SupervisorMetrics();self._stop=threading.Event();self._thread=None
    def start(self):
        if self._thread and self._thread.is_alive():return
        self._stop.clear();self._thread=threading.Thread(target=self._run,name="device-supervisor",daemon=True);self._thread.start()
    def _run(self):
        while not self._stop.wait(self.interval):
            try:
                present=bool(self.discover());self.metrics.discoveries+=1
                if present and self.state!=ConnectionState.CONNECTED:
                    self.state=ConnectionState.CONNECTING;self.connect();self.metrics.connects+=1;self.state=ConnectionState.CONNECTED
                elif not present and self.state==ConnectionState.CONNECTED:
                    self.disconnect();self.metrics.disconnects+=1;self.state=ConnectionState.DISCONNECTED
            except Exception as exc:self.metrics.last_error=str(exc);self.state=ConnectionState.ERROR
    def stop(self,timeout:float=2):
        self._stop.set()
        if self._thread:self._thread.join(timeout)
        if self.state==ConnectionState.CONNECTED:self.disconnect();self.metrics.disconnects+=1
        self.state=ConnectionState.DISCONNECTED
