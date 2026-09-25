from __future__ import annotations

import hashlib
import struct
import json
import base64
from dataclasses import dataclass

from .analyzer import jpeg_dimensions


@dataclass(frozen=True)
class EncodedFrame:
    vid_pid: str
    dimensions: tuple[int, int]
    jpeg_length: int
    jpeg_sha256: str
    writes: tuple[bytes, ...]
    protocol_profile: str = ""

    @property
    def total_bytes(self): return sum(map(len,self.writes))


def jpeg_payload(encoded: EncodedFrame) -> bytes:
    """Recover only the immutable JPEG payload from a validated frame."""
    if encoded.vid_pid == "0416:5408":
        blocks=[w[i:i+512] for w in encoded.writes for i in range(0,len(w),512) if w[i:i+2]==b"\x01\xff"]
        return b"".join(block[16:16+int.from_bytes(block[6:8],"little")] for block in blocks)
    if encoded.vid_pid == "0416:5302":
        stream=b"".join(encoded.writes);return stream[20:20+encoded.jpeg_length]
    raise ValueError("unsupported encoded-frame device")


def reframe_encoded(encoded: EncodedFrame) -> EncodedFrame:
    """Build fresh per-commit USB/HID framing around the cached JPEG bytes."""
    if encoded.protocol_profile.startswith("community-"):
        # Community frame envelopes contain no mutable transaction counter.
        # EncodedFrame and its byte writes are immutable and safe to resend.
        return encoded
    jpeg=jpeg_payload(encoded)
    return encode_5408(jpeg,encoded.protocol_profile) if encoded.vid_pid=="0416:5408" else encode_5302(jpeg)


def _validate_jpeg(jpeg: bytes, dimensions: tuple[int,int]) -> None:
    if not jpeg.startswith(b"\xff\xd8") or not jpeg.endswith(b"\xff\xd9"): raise ValueError("complete JPEG SOI/EOI required")
    if jpeg_dimensions(jpeg)!=dimensions: raise ValueError(f"JPEG must be {dimensions[0]}x{dimensions[1]}")


def encode_5408(jpeg: bytes, protocol_profile: str = "vendor-chunk-count-v1") -> EncodedFrame:
    _validate_jpeg(jpeg,(1920,462)); sub=[]
    if protocol_profile!="vendor-chunk-count-v1": raise ValueError("unknown PID 5408 protocol profile")
    chunk_count=len(jpeg)//496+1  # exact vendor rule; includes a zero-length final chunk when divisible
    for index in range(chunk_count):
        body=jpeg[index*496:(index+1)*496]
        header=b"\x01\xff"+struct.pack("<IH",len(jpeg),len(body))+b"\x01"+struct.pack("<HH",chunk_count,index)+b"\x00\x00\x00"
        sub.append(header+body+bytes(496-len(body)))
    sub.extend([bytes(512)]*((-len(sub))%4)) # vendor pads to a four-subpacket boundary
    writes=[]
    stream=b"".join(sub)
    for start in range(0,len(stream),4096): writes.append(stream[start:start+4096])
    return EncodedFrame("0416:5408",(1920,462),len(jpeg),hashlib.sha256(jpeg).hexdigest(),tuple(writes),protocol_profile)


def encode_5302(jpeg: bytes) -> EncodedFrame:
    _validate_jpeg(jpeg,(1280,480))
    header=bytes.fromhex("dadbdcdd")+struct.pack("<IHHII",2,1280,480,2,len(jpeg))
    stream=header+jpeg; writes=tuple(stream[i:i+512].ljust(512,b"\0") for i in range(0,len(stream),512))
    return EncodedFrame("0416:5302",(1280,480),len(jpeg),hashlib.sha256(jpeg).hexdigest(),writes,"pid5302-command2")


def encode_reference(model, *, jpeg: bytes | None = None, rgb565: bytes | None = None) -> EncodedFrame:
    """Frame one positively identified reference model without affecting proven encoders."""
    from .devices.thermalright_reference import frame_packets
    raw = rgb565 if model.pixel_format.startswith("rgb565") else jpeg
    if raw is None:raise ValueError(f"{model.pixel_format} payload is required")
    writes=frame_packets(model,raw)
    return EncodedFrame(model.key,model.render_size,len(raw),hashlib.sha256(raw).hexdigest(),writes,f"reference-{model.protocol}-{model.pixel_format}")


def image_to_rgb565(image, byte_order: str = "little") -> bytes:
    """Convert an RGB PIL image to packed RGB565 in the model's required byte order."""
    import numpy as np
    rgb=np.asarray(image.convert("RGB"),dtype=np.uint16)
    values=((rgb[:,:,0]>>3)<<11)|((rgb[:,:,1]>>2)<<5)|(rgb[:,:,2]>>3)
    dtype="<u2" if byte_order=="little" else ">u2"
    return values.astype(dtype,copy=False).tobytes()


def validate_5408(encoded: EncodedFrame) -> dict:
    blocks=[w[i:i+512] for w in encoded.writes for i in range(0,4096,512) if w[i:i+2]==b"\x01\xff"]
    lengths=[int.from_bytes(x[6:8],"little") for x in blocks]
    jpeg=b"".join(x[16:16+n] for x,n in zip(blocks,lengths))
    expected_chunks=encoded.jpeg_length//496+1
    headers_valid=all(x[:2]==b"\x01\xff" and int.from_bytes(x[2:6],"little")==encoded.jpeg_length and
                      x[8]==1 and int.from_bytes(x[9:11],"little")==expected_chunks and
                      int.from_bytes(x[11:13],"little")==i and x[13:16]==b"\0\0\0" for i,x in enumerate(blocks))
    lengths_valid=bool(lengths) and all(n==496 for n in lengths[:-1]) and 0<=lengths[-1]<496
    jpeg_valid=(jpeg.startswith(b"\xff\xd8") and jpeg.endswith(b"\xff\xd9") and
                jpeg_dimensions(jpeg)==encoded.dimensions if jpeg else False)
    return {"valid":headers_valid and lengths_valid and jpeg_valid and len(jpeg)==encoded.jpeg_length and hashlib.sha256(jpeg).hexdigest()==encoded.jpeg_sha256,
            "chunks":len(blocks),"writes":len(encoded.writes),"total_bytes":encoded.total_bytes,
            "protocol_profile":encoded.protocol_profile,"command":1,"declared_chunk_count":expected_chunks,
            "headers_valid":headers_valid,"payload_lengths_valid":lengths_valid,"jpeg_soi_eoi_and_dimensions":jpeg_valid,
            "final_payload_length":lengths[-1] if lengths else None,
            "indices_contiguous":all(int.from_bytes(x[11:13],"little")==i for i,x in enumerate(blocks)),
            "padding_zero":all(not any(x[16+n:]) for x,n in zip(blocks,lengths)) and
                           all(not any(w[i:i+512]) for w in encoded.writes for i in range(0,4096,512) if w[i:i+2]!=b"\x01\xff")}


def validate_5302(encoded: EncodedFrame) -> dict:
    stream=b"".join(encoded.writes); declared=int.from_bytes(stream[16:20],"little"); eoi=stream.find(b"\xff\xd9",20)+2
    jpeg=stream[20:eoi]
    jpeg_valid=bool(jpeg) and jpeg.startswith(b"\xff\xd8") and jpeg.endswith(b"\xff\xd9") and jpeg_dimensions(jpeg)==encoded.dimensions
    return {"valid":stream[:4]==bytes.fromhex("dadbdcdd") and int.from_bytes(stream[4:8],"little")==2 and
                    (int.from_bytes(stream[8:10],"little"),int.from_bytes(stream[10:12],"little"))==(1280,480) and
                    int.from_bytes(stream[12:16],"little")==2 and declared==len(jpeg)==encoded.jpeg_length and
                    jpeg_valid and hashlib.sha256(jpeg).hexdigest()==encoded.jpeg_sha256,
            "writes":len(encoded.writes),"total_bytes":encoded.total_bytes,"eoi_boundary":eoi,
            "jpeg_soi_eoi_and_dimensions":jpeg_valid,"padding_zero":not any(stream[eoi:])}


def write_encoded(jpeg_path, output_dir, vid_pid: str) -> dict:
    jpeg=jpeg_path.read_bytes(); encoded=encode_5408(jpeg) if vid_pid=="0416:5408" else encode_5302(jpeg)
    validation=validate_5408(encoded) if vid_pid=="0416:5408" else validate_5302(encoded)
    if not validation["valid"]: raise ValueError("internal encoded-frame validation failed")
    output_dir.mkdir(parents=True,exist_ok=True)
    # Re-encoding a smaller JPEG must not leave stale tail writes that would be
    # appended to the generated transaction.
    for stale in output_dir.glob("write_*.bin"):stale.unlink()
    for i,payload in enumerate(encoded.writes): (output_dir/f"write_{i:04d}.bin").write_bytes(payload)
    report={"vid_pid":vid_pid,"source":str(jpeg_path.resolve()),"dimensions":encoded.dimensions,
            "jpeg_length":encoded.jpeg_length,"jpeg_sha256":encoded.jpeg_sha256,
            "protocol_profile":encoded.protocol_profile,
            "write_count":len(encoded.writes),"total_bytes":encoded.total_bytes,"validation":validation,
            "live_transmission_authorized":False}
    (output_dir/"manifest.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    return report


def prepare_generated_transaction(encoded_dir, reference_report, output_path) -> dict:
    manifest=json.loads((encoded_dir/"manifest.json").read_text(encoding="utf-8"))
    vid_pid=manifest["vid_pid"]
    if vid_pid not in ("0416:5408","0416:5302"):raise ValueError("unsupported generated transaction device")
    if vid_pid=="0416:5408" and manifest.get("protocol_profile")!="vendor-chunk-count-v1":
        raise ValueError("generated PID 5408 preparation requires corrected vendor chunk-count framing")
    writes=[p.read_bytes() for p in sorted(encoded_dir.glob("write_*.bin"))]
    if not writes:raise ValueError("malformed generated write set")
    if vid_pid=="0416:5408":
        if any(len(x)!=4096 for x in writes[:-1]) or len(writes[-1]) not in (2048,4096):
            raise ValueError("malformed generated PID 5408 write boundaries")
    elif any(len(x)!=512 for x in writes):raise ValueError("malformed generated PID 5302 write set")
    ref=json.loads(reference_report.read_text(encoding="utf-8")); rtx=ref["devices"][vid_pid]["transactions"][0]
    if vid_pid=="0416:5408" and int.from_bytes(bytes.fromhex(rtx["header_hex"])[9:11],"little") != rtx["protocol_chunk_count"]:
        raise ValueError("reference does not obey confirmed vendor chunk-count framing")
    start=rtx["start_timestamp"]
    packets=[{"packet":i+1,"timestamp":start+i*0.000302,"sha256":hashlib.sha256(w).hexdigest(),
              "payload_b64":base64.b64encode(w).decode("ascii")} for i,w in enumerate(writes)]
    tx={"index":1,"source_kind":"generated","complete":True,"first_packet":1,"last_out_packet":len(writes),
        "start_timestamp":start,"end_out_timestamp":packets[-1]["timestamp"],"transfer_count":len(writes),
        "usb_payload_bytes":sum(map(len,writes)),"jpeg_bytes":manifest["jpeg_length"],
        "jpeg_sha256":manifest["jpeg_sha256"],"header_hex":writes[0][:(16 if vid_pid=="0416:5408" else 20)].hex(),
        "expected_response":rtx["expected_response"],"payload_packets":packets}
    if vid_pid=="0416:5408":tx["protocol_chunk_count"]=int.from_bytes(writes[0][9:11],"little")
    report={"capture":None,"source_kind":"generated","generated_manifest":str((encoded_dir/"manifest.json").resolve()),
            "generated_validation":manifest["validation"],
            "reference_transaction":str(reference_report.resolve()),
            "devices":{vid_pid:{"capture_device":None,"interface":0 if vid_pid=="0416:5408" else 1,
                                "endpoint":"0x09" if vid_pid=="0416:5408" else "0x02",
                                "transfer_type":"bulk" if vid_pid=="0416:5408" else "interrupt","transactions":[tx]}}}
    output_path.write_text(json.dumps(report,indent=2),encoding="utf-8")
    return {"output":str(output_path.resolve()),"sequence_id":f"{vid_pid}/{output_path.stem}-transaction-1",
            "source_kind":"generated","write_count":len(writes),"frame_bytes":sum(map(len,writes)),
            "jpeg_sha256":manifest["jpeg_sha256"],"live_transmission_authorized":False}
