from __future__ import annotations

import ast
from collections import deque
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Mapping, Sequence
from uuid import uuid4

from PIL import Image, ImageDraw, ImageFont


WIDGET_KINDS = (
    "text value", "label + value", "horizontal bar", "vertical bar",
    "gauge", "line graph", "sparkline", "percentage", "icon + value",
    "static label", "image", "clock", "date", "panel", "rectangle", "separator",
)


class BoundedSensorHistory:
    """Fixed-capacity numeric history used by graphs; it can never retain frames."""
    def __init__(self, capacity: int = 240):self.capacity=max(2,int(capacity));self._values={}
    def append(self,sensor_id,value):
        try:value=float(value)
        except (TypeError,ValueError):return
        self._values.setdefault(sensor_id,deque(maxlen=self.capacity)).append(value)
    def get(self,sensor_id,default=()):return self._values.get(sensor_id,default)
    def __len__(self):return sum(map(len,self._values.values()))


@dataclass(slots=True)
class MonitorElement:
    kind: str
    x: int
    y: int
    width: int = 320
    height: int = 64
    text: str = ""
    sensor_id: str = ""
    unit: str = ""
    font_size: int = 32
    bold: bool = False
    color: str = "#f2f6ff"
    background: str = ""
    opacity: int = 255
    align: str = "left"
    padding: int = 6
    minimum: float = 0.0
    maximum: float = 100.0
    image: str = ""
    id: str = field(default_factory=lambda: uuid4().hex)
    provider: str = ""
    custom_label: str = ""
    format_string: str = ""
    decimals: int = 1
    prefix: str = ""
    suffix: str = ""
    vertical_align: str = "middle"
    font_family: str = "Segoe UI"
    font_weight: int = 400
    text_style: str = "normal"
    border_color: str = ""
    border_width: int = 0
    spacing: int = 4
    visibility_condition: str = ""
    locked: bool = False
    group_id: str = ""
    z_index: int = 0
    preserve_aspect: bool = True
    rotation: int = 0
    brightness: int = 100
    outline_color: str = ""
    outline_width: int = 0
    shadow_color: str = ""
    shadow_offset: int = 0
    visible: bool = True

    def __post_init__(self):
        aliases = {"sensor": "label + value", "text": "text value", "label": "static label", "bar": "horizontal bar", "graph": "line graph"}
        self.kind = aliases.get(self.kind, self.kind)
        if self.kind not in WIDGET_KINDS: raise ValueError(f"unknown monitor element kind: {self.kind}")
        if self.width < 1 or self.height < 1: raise ValueError("element dimensions must be positive")
        self.opacity = max(0, min(255, int(self.opacity)))
        self.decimals = max(0, min(8, int(self.decimals)))
        if self.align not in {"left", "center", "right"}: raise ValueError("invalid horizontal alignment")
        if self.vertical_align not in {"top", "middle", "bottom"}: raise ValueError("invalid vertical alignment")


@dataclass(slots=True)
class MonitorLayout:
    name: str
    target: str
    width: int
    height: int
    background: str = "#090d14"
    elements: list[MonitorElement] = field(default_factory=list)
    snap_to_grid: bool = True
    grid_size: int = 10
    alignment_guides: bool = True
    bindings: dict[str, str] = field(default_factory=dict)
    background_source: str = "template_artwork"
    background_image: str = ""
    background_fit: str = "fill"
    background_opacity: int = 100
    background_darken: int = 0
    background_x: int = 0
    background_y: int = 0
    background_zoom: float = 1.0
    background_rotation: int = 0
    background_brightness: int = 100

    def to_dict(self) -> dict: return asdict(self)

    @classmethod
    def from_dict(cls, raw: Mapping) -> "MonitorLayout":
        return cls(raw["name"], raw["target"], int(raw["width"]), int(raw["height"]), raw.get("background", "#090d14"), [MonitorElement(**item) for item in raw.get("elements", [])], bool(raw.get("snap_to_grid", True)), int(raw.get("grid_size", 10)), bool(raw.get("alignment_guides", True)), dict(raw.get("bindings", {})),raw.get("background_source","template_artwork"),raw.get("background_image",""),raw.get("background_fit","fill"),int(raw.get("background_opacity",100)),int(raw.get("background_darken",0)),int(raw.get("background_x",0)),int(raw.get("background_y",0)),float(raw.get("background_zoom",1.0)),int(raw.get("background_rotation",0)),int(raw.get("background_brightness",100)))


class _Missing(dict):
    def __missing__(self, key): return "--"


def _number(value, decimals):
    if isinstance(value, bool): return str(value)
    if isinstance(value, (int, float)): return f"{float(value):.{decimals}f}"
    return "--" if value is None else str(value)


def condition_visible(expression: str, values: Mapping[str, object]) -> bool:
    """Evaluate only names, constants, boolean operators and comparisons."""
    if not expression.strip(): return True
    aliases={key.replace(":","_").replace(".","_"):value for key,value in values.items()}
    try: tree=ast.parse(expression,mode="eval")
    except SyntaxError: return False
    allowed=(ast.Expression,ast.BoolOp,ast.UnaryOp,ast.Compare,ast.Name,ast.Constant,ast.And,ast.Or,ast.Not,ast.Eq,ast.NotEq,ast.Gt,ast.GtE,ast.Lt,ast.LtE,ast.Load,ast.Is,ast.IsNot)
    if any(not isinstance(node,allowed) for node in ast.walk(tree)): return False
    try:return bool(eval(compile(tree,"<visibility>","eval"),{"__builtins__":{}},aliases))
    except (NameError,TypeError,ValueError):return False


class MonitorRenderer:
    """Bounded renderer that caches a static layer but no sensor frames."""
    def __init__(self,layout:MonitorLayout):self.layout=layout;self._font_cache={};self.render_count=0;self.overlay_render_count=0;self._static=self._render_static()
    def _font(self,e):
        key=(e.font_family,e.font_size,e.bold,e.font_weight,e.text_style)
        if key in self._font_cache:return self._font_cache[key]
        candidates=[];family=e.font_family or "Segoe UI"
        if e.bold or e.font_weight>=600:candidates.extend((f"{family} Bold.ttf","segoeuib.ttf"))
        if e.text_style in {"italic","bold italic"}:candidates.extend((f"{family} Italic.ttf","segoeuii.ttf"))
        candidates.extend((f"{family}.ttf","segoeui.ttf"))
        for name in candidates:
            try:self._font_cache[key]=ImageFont.truetype(name,e.font_size);return self._font_cache[key]
            except OSError:pass
        self._font_cache[key]=ImageFont.load_default();return self._font_cache[key]
    def _render_static(self):
        transparent=self.layout.background_source in {"transparent","current_media"}
        out=Image.new("RGBA",(self.layout.width,self.layout.height),(0,0,0,0) if transparent else self.layout.background)
        if self.layout.background_source=="custom_image" and self.layout.background_image and Path(self.layout.background_image).is_file():
            with Image.open(self.layout.background_image) as source:
                image=source.convert("RGBA")
                if self.layout.background_fit=="fit":image.thumbnail(out.size)
                elif self.layout.background_fit=="center":image.thumbnail(out.size)
                else:
                    from PIL import ImageOps
                    image=ImageOps.fit(image,out.size,Image.Resampling.LANCZOS)
                zoom=max(.1,min(8.,self.layout.background_zoom))
                if zoom!=1:image=image.resize((max(1,round(image.width*zoom)),max(1,round(image.height*zoom))),Image.Resampling.LANCZOS)
                if self.layout.background_rotation%360:image=image.rotate(-self.layout.background_rotation%360,expand=True, resample=Image.Resampling.BICUBIC)
                if self.layout.background_brightness!=100:
                    from PIL import ImageEnhance
                    image=ImageEnhance.Brightness(image).enhance(max(0,self.layout.background_brightness)/100)
                if self.layout.background_opacity<100:image.putalpha(image.getchannel("A").point(lambda a:a*max(0,min(100,self.layout.background_opacity))//100))
                out.alpha_composite(image,((out.width-image.width)//2+self.layout.background_x,(out.height-image.height)//2+self.layout.background_y))
        elif self.layout.background_source=="template_artwork":self._draw_artwork(out)
        if self.layout.background_darken:
            shade=Image.new("RGBA",out.size,(0,0,0,round(255*max(0,min(100,self.layout.background_darken))/100)));out.alpha_composite(shade)
        for e in sorted(self.layout.elements,key=lambda item:item.z_index):
            if e.kind in {"static label","image","panel","rectangle","separator"}:self._draw_element(out,e,{}, {})
        return out
    def _draw_artwork(self,out):
        """Original procedural dashboard artwork; no third-party wallpaper."""
        overlay=Image.new("RGBA",out.size,(0,0,0,0));draw=ImageDraw.Draw(overlay,"RGBA");w,h=out.size;name=self.layout.name.casefold()
        palettes={
            "oni crimson":("#ff365f","#40101f"),"ice":("#8bdcff","#dfeaf2"),
            "carbon":("#ef445c","#24272d"),"racing":("#ff3948","#2f1117"),
            "sci-fi":("#55f0d0","#102f38"),"minimal dark":("#dbe7f5","#141b26"),
            "gaming":("#48e0b5","#17324a"),"benchmark":("#ffd166","#3b2a16"),
            "thermal":("#ff806b","#401a24"),"cpu":("#62b5ff","#152c4a"),
            "gpu":("#a98cff","#291b4b"),"power":("#ffca64","#3b2814"),
            "network":("#4dd9ff","#123244"),"storage":("#ffd66b","#3b3114"),
            "cooling":("#52d7dd","#12343b"),"cyber":("#00e8ff","#161848"),
            "neon":("#ff35c8","#231246"),"diagnostic":("#ff5565","#40131c"),
        }
        key=next((key for key in palettes if key in name),"clean" if "clean" in name or "minimal" in name else "default")
        accent,shadow=palettes.get(key,("#7183ff","#17233a"));a=tuple(int(accent[i:i+2],16) for i in (1,3,5));s=tuple(int(shadow[i:i+2],16) for i in (1,3,5))
        # Subtle layered gradient bands are cheap, static, and resolution-native.
        for y in range(0,h,8):
            alpha=int(32*(1-y/max(1,h)));draw.rectangle((0,y,w,y+8),fill=(*s,alpha))
        if key in {"gaming","cyber","benchmark","diagnostic","default"}:
            step=48 if w>1500 else 36
            for x in range(-h,w,step):draw.line((x,0,x+h,h),fill=(*a,22),width=2)
            for y in range(0,h,step):draw.line((0,y,w,y),fill=(*a,14),width=1)
        if key in {"oni crimson","neon","racing","carbon","ice"}:
            # Distinct original wide-panel environments rather than a flat
            # color behind identical cards.
            horizon=int(h*.62);draw.polygon(((0,horizon),(int(w*.20),int(h*.28)),(int(w*.38),horizon),(int(w*.58),int(h*.18)),(int(w*.78),horizon),(w,int(h*.31)),(w,h),(0,h)),fill=(*s,54))
            for index in range(7):
                offset=index*max(38,w//18);draw.line((offset,h,offset+int(w*.22),0),fill=(*a,20+index*2),width=2)
            draw.line((0,horizon,w,horizon),fill=(*a,82),width=2)
        if key=="oni crimson":
            cx=int(w*.5);cy=int(h*.48);radius=int(h*.23)
            draw.ellipse((cx-radius,cy-radius,cx+radius,cy+radius),outline=(*a,90),width=max(4,h//55));draw.ellipse((cx-radius//2,cy-radius//2,cx+radius//2,cy+radius//2),outline=(*a,45),width=2)
            draw.polygon(((cx,cy-radius+8),(cx+radius//2,cy+radius//2),(cx,cy+radius//4),(cx-radius//2,cy+radius//2)),fill=(*a,35))
        elif key=="ice":
            for index in range(5):
                x=int(w*(.08+index*.21));draw.polygon(((x,0),(x+int(w*.13),0),(x-int(w*.02),h),(x-int(w*.14),h)),fill=(220,242,255,12+index*4))
        elif key in {"carbon","racing"}:
            tile=max(18,h//14)
            for y in range(0,h,tile):
                for x in range(-tile,w,tile*2):draw.polygon(((x+(y//tile%2)*tile,y),(x+tile+(y//tile%2)*tile,y),(x+2*tile+(y//tile%2)*tile,y+tile),(x+tile+(y//tile%2)*tile,y+tile)),fill=(255,255,255,8))
        if key in {"thermal","cooling"}:
            for radius in range(70,min(w,h),70):draw.ellipse((w-radius-24,h//2-radius,w+radius-24,h//2+radius),outline=(*a,30),width=8)
        if key in {"network","storage","power"}:
            points=[(0,int(h*.78)),(int(w*.18),int(h*.62)),(int(w*.34),int(h*.72)),(int(w*.55),int(h*.38)),(int(w*.72),int(h*.52)),(w,int(h*.18))]
            draw.line(points,fill=(*a,35),width=5)
        draw.polygon(((0,0),(int(w*.34),0),(0,int(h*.72))),fill=(*a,13));draw.polygon(((w,h),(int(w*.66),h),(w,int(h*.28))),fill=(*a,10));out.alpha_composite(overlay)
    def _formatted(self,e,values):
        raw=values.get(e.sensor_id);formatted=_number(raw,e.decimals);fields=_Missing({key:_number(value,e.decimals) for key,value in values.items()});fields.update(value=formatted,unit=e.unit,label=e.custom_label)
        template=e.format_string or e.text
        if template:
            try:body=template.format_map(fields)
            except (ValueError,KeyError):body=template
        elif e.kind=="text value":body=f"{formatted}{e.unit}"
        elif e.kind=="percentage":body=f"{formatted}%"
        else:body=f"{e.custom_label}{e.spacing*' ' if e.custom_label else ''}{formatted}{e.unit}"
        return f"{e.prefix}{body}{e.suffix}",raw
    def _text_xy(self,draw,e,text,font):
        box=draw.textbbox((0,0),text,font=font);tw,th=box[2]-box[0],box[3]-box[1]
        x=e.padding if e.align=="left" else (e.width-tw)/2 if e.align=="center" else e.width-e.padding-tw
        y=e.padding if e.vertical_align=="top" else (e.height-th)/2 if e.vertical_align=="middle" else e.height-e.padding-th
        return x,y
    def _draw_element(self,destination,e,values,history):
        if not e.visible:return
        if not condition_visible(e.visibility_condition,values):return
        layer=Image.new("RGBA",(e.width,e.height),(0,0,0,0));draw=ImageDraw.Draw(layer)
        if e.background:draw.rounded_rectangle((0,0,e.width-1,e.height-1),min(10,e.height//3),fill=e.background)
        if e.border_width and e.border_color:draw.rounded_rectangle((0,0,e.width-1,e.height-1),min(10,e.height//3),outline=e.border_color,width=e.border_width)
        text,raw=self._formatted(e,values);px=min(e.padding,max(0,(e.width-1)//2));py=min(e.padding,max(0,(e.height-1)//2));inner=(px,py,max(px,e.width-px-1),max(py,e.height-py-1))
        if e.kind in {"text value","label + value","percentage","icon + value","static label","clock","date"}:
            if e.kind=="static label":text=e.text or e.custom_label
            elif e.kind in {"clock","date"}:
                from datetime import datetime
                text=datetime.now().strftime(e.format_string or ("%H:%M" if e.kind=="clock" else "%A, %d %B"))
            if e.kind=="icon + value" and e.image and Path(e.image).is_file():
                with Image.open(e.image) as source:icon=source.convert("RGBA");icon.thumbnail((max(1,e.height-2*e.padding),max(1,e.height-2*e.padding)));layer.alpha_composite(icon,(e.padding,e.padding))
            font=self._font(e);xy=self._text_xy(draw,e,text,font)
            if e.shadow_color and e.shadow_offset:draw.text((xy[0]+e.shadow_offset,xy[1]+e.shadow_offset),text,fill=e.shadow_color,font=font)
            draw.text(xy,text,fill=e.color,font=font,stroke_width=max(0,e.outline_width),stroke_fill=e.outline_color or None)
        elif e.kind in {"horizontal bar","vertical bar","gauge"}:
            try:ratio=max(0.,min(1.,(float(raw)-e.minimum)/max(.001,e.maximum-e.minimum)))
            except (TypeError,ValueError):ratio=0.;track=e.background or "#202b3c"
            track=e.background or "#202b3c"
            if e.kind=="horizontal bar":draw.rounded_rectangle(inner,max(1,(inner[3]-inner[1])//2),fill=track);draw.rounded_rectangle((inner[0],inner[1],inner[0]+(inner[2]-inner[0])*ratio,inner[3]),max(1,(inner[3]-inner[1])//2),fill=e.color)
            elif e.kind=="vertical bar":draw.rounded_rectangle(inner,5,fill=track);top=inner[3]-(inner[3]-inner[1])*ratio;draw.rounded_rectangle((inner[0],top,inner[2],inner[3]),5,fill=e.color)
            else:draw.arc(inner,180,360,fill=track,width=max(3,e.border_width or 8));draw.arc(inner,180,180+180*ratio,fill=e.color,width=max(3,e.border_width or 8))
        elif e.kind in {"line graph","sparkline"}:
            points=list(history.get(e.sensor_id,()))[-max(2,e.width):]
            if len(points)>1:
                span=max(.001,e.maximum-e.minimum);coords=[(e.padding+i*(e.width-2*e.padding)/(len(points)-1),e.height-e.padding-max(0,min(e.height-2*e.padding,(float(v)-e.minimum)/span*(e.height-2*e.padding)))) for i,v in enumerate(points)];draw.line(coords,fill=e.color,width=3 if e.kind=="line graph" else 2)
        elif e.kind=="image" and e.image and Path(e.image).is_file():
            with Image.open(e.image) as source:
                image=source.convert("RGBA")
                if e.preserve_aspect:image.thumbnail((e.width,e.height))
                else:image=image.resize((e.width,e.height),Image.Resampling.LANCZOS)
                if e.rotation%360:image=image.rotate(-e.rotation%360,expand=True,resample=Image.Resampling.BICUBIC)
                if e.brightness!=100:
                    from PIL import ImageEnhance
                    image=ImageEnhance.Brightness(image).enhance(max(0,e.brightness)/100)
                layer.alpha_composite(image,((e.width-image.width)//2,(e.height-image.height)//2))
        elif e.kind in {"panel","rectangle"}:draw.rounded_rectangle((0,0,e.width-1,e.height-1),10 if e.kind=="panel" else 0,fill=e.background or "#172033",outline=e.border_color or None,width=max(1,e.border_width))
        elif e.kind=="separator":draw.line((0,e.height//2,e.width,e.height//2),fill=e.color,width=max(1,e.border_width or 2))
        if e.opacity<255:layer.putalpha(layer.getchannel("A").point(lambda alpha:alpha*e.opacity//255))
        destination.alpha_composite(layer,(e.x,e.y))
    def render(self,values:Mapping[str,object],history:Mapping[str,Sequence[float]]|None=None):
        self.render_count+=1
        resolved=dict(values)
        for alias,qualified_id in self.layout.bindings.items():resolved[alias]=values.get(qualified_id)
        out=self._static.copy();history=history or {}
        for e in sorted(self.layout.elements,key=lambda item:item.z_index):
            if e.kind not in {"static label","image","panel","rectangle","separator"}:self._draw_element(out,e,resolved,history)
        return out.convert("RGB")

    def render_overlay(self,values:Mapping[str,object],history:Mapping[str,Sequence[float]]|None=None):
        """Render only widgets into a transparent cached sensor overlay."""
        self.overlay_render_count+=1
        resolved=dict(values)
        for alias,qualified_id in self.layout.bindings.items():resolved[alias]=values.get(qualified_id)
        out=Image.new("RGBA",(self.layout.width,self.layout.height),(0,0,0,0));history=history or {}
        for e in sorted(self.layout.elements,key=lambda item:item.z_index):self._draw_element(out,e,resolved,history)
        return out


def _sensor(name,sensor,x,y,unit=""):return MonitorElement("label + value",x,y,360,70,sensor_id=sensor,unit=unit,font_size=34,bold=True,custom_label=name)
def templates(target):
    """Return the built-in layout catalog (intentionally empty)."""
    return {}
