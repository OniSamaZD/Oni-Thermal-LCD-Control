from __future__ import annotations

from PIL import Image


PANEL_LINK_TAG_BYTES = 270


def ones_complement_checksum(data: bytes) -> int:
    """16-bit one's-complement checksum used by published Panel-Link tags."""
    if len(data)%2:data+=b"\0"
    total=sum(int.from_bytes(data[index:index+2],"little") for index in range(0,len(data),2))
    while total>>16:total=(total&0xFFFF)+(total>>16)
    return (~total)&0xFFFF


def panel_link_start_tag(width: int, height: int, *, protocol_version: int = 2, pixel_format: str = "BGR16") -> bytes:
    if width<=0 or height<=0 or protocol_version not in {1,2}:raise ValueError("invalid Panel-Link dimensions or version")
    media_type="image/x-raw" if pixel_format=="BGR16" else "video/x-raw" if pixel_format=="RGB16" else None
    if media_type is None:raise ValueError("pixel format must be BGR16 or RGB16")
    caps=f"{media_type}, format={pixel_format}, width={width}, height={height}, framerate=0/1".encode("ascii")
    if len(caps)>255:raise ValueError("Panel-Link caps exceed field size")
    tag=bytearray(PANEL_LINK_TAG_BYTES);tag[:10]=b"PANEL-LINK";tag[10]=protocol_version;tag[11]=5 if protocol_version==2 else 1;tag[12:12+len(caps)]=caps
    tag[-2:]=ones_complement_checksum(tag[:-2]).to_bytes(2,"little")
    return bytes(tag)


def encode_rgb565(image: Image.Image, size: tuple[int,int], *, order: str = "BGR") -> bytes:
    if order not in {"RGB","BGR"}:raise ValueError("order must be RGB or BGR")
    work=image.convert("RGB")
    if work.size!=size:resized=work.resize(size,Image.Resampling.LANCZOS);work.close();work=resized
    output=bytearray(size[0]*size[1]*2)
    try:
        pixels = work.get_flattened_data() if hasattr(work, "get_flattened_data") else work.getdata()
        for index,(red,green,blue) in enumerate(pixels):
            first,third=(blue,red) if order=="BGR" else (red,blue);value=((first>>3)<<11)|((green>>2)<<5)|(third>>3);output[index*2:index*2+2]=value.to_bytes(2,"little")
    finally:work.close()
    return bytes(output)
