from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass,fields
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class PreviewTransform:
    native_width: int
    native_height: int
    preview_width: float
    preview_height: float

    @property
    def scale(self):
        return min(self.preview_width / self.native_width, self.preview_height / self.native_height)

    @property
    def offset(self):
        return ((self.preview_width - self.native_width * self.scale) / 2,
                (self.preview_height - self.native_height * self.scale) / 2)

    def preview_to_native(self, x, y):
        ox, oy = self.offset
        return ((x - ox) / self.scale, (y - oy) / self.scale)

    def native_to_preview(self, x, y):
        ox, oy = self.offset
        return (ox + x * self.scale, oy + y * self.scale)


class LayoutEditController:
    """Shared, serialization-level layout mutations for Home and Designer."""
    def __init__(self, layout, *, history_limit=100):
        self.layout = layout;self.enabled = False;self.selected_ids = set();self.history_limit = history_limit
        self._undo = [];self._redo = []
        self._external_before = None

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)
        if not self.enabled:self.selected_ids.clear()

    def select(self, ids, *, additive=False):
        if not self.enabled:return
        valid={e.id for e in self.layout.elements};chosen=set(ids)&valid
        self.selected_ids=(self.selected_ids|chosen) if additive else chosen

    def _selected(self):return [e for e in self.layout.elements if e.id in self.selected_ids and not e.locked]
    def _snapshot(self):return self.layout.to_dict()
    def _restore(self, raw):
        restored=type(self.layout).from_dict(deepcopy(raw))
        for field in fields(restored):setattr(self.layout,field.name,getattr(restored,field.name))
        self.selected_ids&={e.id for e in self.layout.elements}
    def _mutate(self, action):
        if not self.enabled:return False
        before=self._snapshot();action()
        if self._snapshot()==before:return False
        self._undo.append(before);del self._undo[:-self.history_limit];self._redo.clear();return True
    def begin_external(self):
        if self.enabled and self._external_before is None:self._external_before=self._snapshot()
    def end_external(self):
        before,self._external_before=self._external_before,None
        if before is None or before==self._snapshot():return False
        self._undo.append(before);del self._undo[:-self.history_limit];self._redo.clear();return True
    def move(self, dx, dy):
        def action():
            for e in self._selected():e.x=max(0,min(self.layout.width-e.width,round(e.x+dx)));e.y=max(0,min(self.layout.height-e.height,round(e.y+dy)))
        return self._mutate(action)
    def scale(self, factor):
        scale_factor=max(.25,min(2,float(factor)))
        def action():
            items=self._selected()
            if not items:return
            left=min(e.x for e in items);top=min(e.y for e in items)
            for e in items:e.x=round(left+(e.x-left)*scale_factor);e.y=round(top+(e.y-top)*scale_factor);e.width=max(10,round(e.width*scale_factor));e.height=max(10,round(e.height*scale_factor));e.font_size=max(6,round(e.font_size*scale_factor))
        return self._mutate(action)
    def align(self, edge):
        def action():
            items=self._selected()
            if len(items)<2:return
            if edge=='left':value=min(e.x for e in items);pairs=((e,'x',value) for e in items)
            elif edge=='right':value=max(e.x+e.width for e in items);pairs=((e,'x',value-e.width) for e in items)
            elif edge=='top':value=min(e.y for e in items);pairs=((e,'y',value) for e in items)
            elif edge=='bottom':value=max(e.y+e.height for e in items);pairs=((e,'y',value-e.height) for e in items)
            else:return
            for e,name,value in pairs:setattr(e,name,value)
        return self._mutate(action)
    def distribute(self, axis):
        def action():
            items=self._selected()
            if len(items)<3:return
            items.sort(key=lambda e:e.x if axis=='horizontal' else e.y);start=getattr(items[0],'x' if axis=='horizontal' else 'y');end=getattr(items[-1],'x' if axis=='horizontal' else 'y');step=(end-start)/(len(items)-1)
            for index,e in enumerate(items):setattr(e,'x' if axis=='horizontal' else 'y',round(start+index*step))
        return self._mutate(action)
    def duplicate(self):
        def action():
            copies=[]
            for source in self._selected():
                item=deepcopy(source);item.id=uuid4().hex;item.x=min(self.layout.width-item.width,item.x+self.layout.grid_size);item.y=min(self.layout.height-item.height,item.y+self.layout.grid_size);item.group_id='';copies.append(item)
            self.layout.elements.extend(copies);self.selected_ids={e.id for e in copies}
        return self._mutate(action)
    def delete(self):return self._mutate(lambda:self.layout.elements.__setitem__(slice(None),[e for e in self.layout.elements if e.id not in self.selected_ids]))
    def change_z(self, delta):return self._mutate(lambda:[setattr(e,'z_index',e.z_index+delta) for e in self._selected()])
    def set_visibility(self, element_id, visible):
        def action():
            element=next((e for e in self.layout.elements if e.id==element_id),None)
            if element is not None:element.visible=bool(visible)
        return self._mutate(action)
    def undo(self):
        if not self.enabled or not self._undo:return False
        self._redo.append(self._snapshot());self._restore(self._undo.pop());return True
    def redo(self):
        if not self.enabled or not self._redo:return False
        self._undo.append(self._snapshot());self._restore(self._redo.pop());return True
