from __future__ import annotations

import hashlib
from pathlib import Path
from PIL import Image


NAMES={0xE0:"APP0",0xE1:"APP1",0xDB:"DQT",0xC0:"SOF0",0xC1:"SOF1",0xC2:"SOF2",0xC4:"DHT",0xDD:"DRI",0xDA:"SOS"}


def inspect_jpeg(path: Path) -> dict:
    data=Path(path).read_bytes();segments=[];i=2
    if not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9"):raise ValueError("incomplete JPEG")
    while i<len(data)-1:
        if data[i]!=0xff:i+=1;continue
        while i<len(data) and data[i]==0xff:i+=1
        marker=data[i];i+=1
        if marker in (0,1,0xd9) or 0xd0<=marker<=0xd7:continue
        length=int.from_bytes(data[i:i+2],"big");payload=data[i+2:i+length]
        segments.append({"marker":NAMES.get(marker,f"0x{marker:02x}"),"length":length,"sha256":hashlib.sha256(payload).hexdigest()})
        i+=length
        if marker==0xda:break
    with Image.open(path) as im:
        im.load();layers=[list(x) for x in getattr(im,"layer",[])]
        return {"path":str(Path(path).resolve()),"bytes":len(data),"sha256":hashlib.sha256(data).hexdigest(),
            "dimensions":list(im.size),"mode":im.mode,"baseline":any(x["marker"]=="SOF0" for x in segments),
            "progressive":any(x["marker"]=="SOF2" for x in segments),"components":layers,
            "subsampling":"4:2:0" if layers[:3]==[[1,2,2,0],[2,1,1,1],[3,1,1,1]] else "other",
            "jfif_unit":im.info.get("jfif_unit"),"jfif_density":list(im.info.get("jfif_density",())),
            "segments":segments,"eoi_at_end":True}


def compatibility_report(known: Path,candidate: Path) -> dict:
    a,b=inspect_jpeg(known),inspect_jpeg(candidate)
    def hashes(x,name):return [s["sha256"] for s in x["segments"] if s["marker"]==name]
    return {"known_working":a,"candidate":b,"comparison":{
        "same_dimensions":a["dimensions"]==b["dimensions"],"same_baseline_mode":a["baseline"]==b["baseline"]==True,
        "same_subsampling":a["subsampling"]==b["subsampling"]=="4:2:0",
        "same_huffman_tables":hashes(a,"DHT")==hashes(b,"DHT"),"same_quantization_tables":hashes(a,"DQT")==hashes(b,"DQT"),
        "same_jfif_density":(a["jfif_unit"],a["jfif_density"])==(b["jfif_unit"],b["jfif_density"]),
        "no_restart_markers":not hashes(a,"DRI") and not hashes(b,"DRI"),"both_strict_decode":True}}
