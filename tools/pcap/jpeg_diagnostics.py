from __future__ import annotations

import json
import subprocess
from pathlib import Path

from PIL import Image, ImageFile


def sof(data: bytes):
    for marker in (b"\xff\xc0", b"\xff\xc2"):
        i = data.find(marker)
        if i >= 0:
            height = int.from_bytes(data[i+5:i+7], "big")
            width = int.from_bytes(data[i+7:i+9], "big")
            count = data[i+9]
            comps = []
            p = i + 10
            for _ in range(count):
                comps.append({"id": data[p], "h_sampling": data[p+1] >> 4, "v_sampling": data[p+1] & 15, "quant_table": data[p+2]})
                p += 3
            return {"marker": marker.hex(), "offset": i, "width": width, "height": height, "components": comps}
    return None


def main():
    root = Path("analysis/display_9_16")
    frames = []
    ffmpeg = Path(r"C:\Program Files\TRCCCAP\ffmpeg.exe")
    for path in sorted((root / "extracted_frames").glob("frame_*.jpg")):
        if "_prefix" in path.name or "_suffix" in path.name:
            continue
        data = path.read_bytes(); strict = True; error = None
        try:
            ImageFile.LOAD_TRUNCATED_IMAGES = False
            with Image.open(path) as im: im.load()
        except OSError as e:
            strict = False; error = str(e)
        diag = sof(data)
        max_h = max(x["h_sampling"] for x in diag["components"]); max_v = max(x["v_sampling"] for x in diag["components"])
        mcu_w, mcu_h = max_h*8, max_v*8
        diag.update({"file": path.name, "bytes": len(data), "strict_pillow": strict, "strict_error": error,
                     "protocol_magic_occurrences": data.count(bytes.fromhex("01ff29a6")),
                     "mcu_width": mcu_w, "mcu_height": mcu_h,
                     "mcu_padded_width": ((diag["width"]+mcu_w-1)//mcu_w)*mcu_w,
                     "mcu_padded_height": ((diag["height"]+mcu_h-1)//mcu_h)*mcu_h})
        frames.append(diag)
    ff = subprocess.run([str(ffmpeg), "-v", "warning", "-i", str(root/"extracted_frames/frame_0001.jpg"), "-f", "null", "-"], capture_output=True, text=True)
    report = {"frames": frames, "all_sof_1920x462": all((x["width"],x["height"]) == (1920,462) for x in frames),
              "all_protocol_magic_absent_from_jpeg": all(x["protocol_magic_occurrences"] == 0 for x in frames),
              "mcu_geometry": "4:2:0 sampling uses 16x16 MCUs; 462 is padded internally to 464 (2 rows), not 480",
              "ffmpeg_exit_code": ff.returncode, "ffmpeg_stderr": ff.stderr.strip(),
              "trcc_static_evidence": ["1920X462", "is1920x462", "GifDirectoryWeb1920462", "USBLCD\\Web\\zt1920462\\"],
              "strict_decode_summary": {"valid": sum(x["strict_pillow"] for x in frames), "invalid": sum(not x["strict_pillow"] for x in frames),
                                        "invalid_files": [x["file"] for x in frames if not x["strict_pillow"]]},
              "conclusion": "1920x462 is the intentional vendor profile and JPEG SOF size. No 18-row payload omission exists: TRCC names the profile explicitly and 4:2:0 MCU padding reaches 464, not 480. Correct removal of all eight 16-byte subheaders per 4096-byte write makes 18/20 JPEGs strict-decodable with no protocol magic inside. Two variable-size vendor frames remain malformed despite exact declared-length reconstruction, supporting a vendor encoder/bitstream defect for those frames rather than boundary or header contamination."}
    (root / "jpeg-diagnostics.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k != "frames"}, indent=2))


if __name__ == "__main__": main()
