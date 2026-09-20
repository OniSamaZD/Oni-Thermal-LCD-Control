from __future__ import annotations
import time


class DisplaySyncController:
    """Coordinates timeline commands only; never owns media or transport work."""
    def __init__(self,cards=(),clock=time.perf_counter,prepare_shared=None,stop_shared=None):self.cards=list(cards);self.clock=clock;self.enabled=False;self.epoch=None;self.command_count=0;self.prepare_shared=prepare_shared;self.stop_shared=stop_shared
    def set_enabled(self,enabled):self.enabled=bool(enabled)
    def coordinate(self,action,source=None):
        if not self.enabled:return False
        self.command_count+=1
        if action=="play":
            self.epoch=self.clock()+.05
            for card in self.cards:card.timeline_epoch=self.epoch
            if self.prepare_shared:self.prepare_shared(self.epoch)
        for card in self.cards:getattr(card,action)(coordinated=True)
        if action=="stop" and self.stop_shared:self.stop_shared()
        return True
