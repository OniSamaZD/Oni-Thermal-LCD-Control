"""Offline JPEG encoder benchmark at both physical LCD resolutions."""
from __future__ import annotations

import argparse,json,statistics,time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image,features


def measure(fn,rounds):
    values=[];sizes=[]
    for _ in range(rounds):
        started=time.perf_counter();data=fn();values.append((time.perf_counter()-started)*1000);sizes.append(len(data))
    return {"mean_ms":statistics.fmean(values),"p95_ms":sorted(values)[max(0,int(len(values)*.95)-1)],"fps_equivalent":1000/statistics.fmean(values),"mean_bytes":round(statistics.fmean(sizes))}


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--rounds",type=int,default=40);parser.add_argument("--output",type=Path,default=Path("analysis/jpeg-benchmark.json"));args=parser.parse_args()
    report={"schema":1,"rounds":args.rounds,"pillow_libjpeg_turbo":bool(features.check_feature("libjpeg_turbo")),"opencv_version":cv2.__version__,"devices":{}}
    rng=np.random.default_rng(54085302)
    for device,(width,height) in {"0416:5408":(1920,462),"0416:5302":(1280,480)}.items():
        bgr=rng.integers(0,256,(height,width,3),dtype=np.uint8);rgb=cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB);pil=Image.fromarray(rgb)
        result={}
        for quality in (45,75,88,95):
            options=[cv2.IMWRITE_JPEG_QUALITY,quality,cv2.IMWRITE_JPEG_PROGRESSIVE,0,cv2.IMWRITE_JPEG_OPTIMIZE,0]
            result[str(quality)]={
                "opencv":measure(lambda:cv2.imencode(".jpg",bgr,options)[1].tobytes(),args.rounds),
                "pillow":measure(lambda q=quality:(lambda b:(pil.save(b,"JPEG",quality=q,optimize=False,progressive=False,subsampling=2),b.getvalue())[1])(__import__("io").BytesIO()),args.rounds),
            }
        report["devices"][device]=result
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2),encoding="utf-8");print(json.dumps(report,indent=2))


if __name__=="__main__":main()
