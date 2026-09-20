"""Compare the former float32 compositor with cached uint8 composition."""
from __future__ import annotations
import argparse,json,statistics,time,tracemalloc
from pathlib import Path
import cv2,numpy as np
from PIL import Image
from thermalright_lcd.media import cache_overlay

def measure(fn,rounds):
    samples=[];tracemalloc.start()
    for _ in range(rounds):started=time.perf_counter();fn();samples.append((time.perf_counter()-started)*1000)
    _,peak=tracemalloc.get_traced_memory();tracemalloc.stop();return {"mean_ms":statistics.fmean(samples),"p95_ms":sorted(samples)[int(.95*(len(samples)-1))],"python_peak_bytes":peak}
def main():
    p=argparse.ArgumentParser();p.add_argument("--rounds",type=int,default=100);p.add_argument("--output",type=Path,default=Path("analysis/overlay-composite-benchmark.json"));a=p.parse_args();rng=np.random.default_rng(53025408);report={"schema":1,"rounds":a.rounds,"devices":{}}
    for device,size in {"0416:5408":(1920,462),"0416:5302":(1280,480)}.items():
        w,h=size;frame=rng.integers(0,256,(h,w,3),dtype=np.uint8);rgba=np.zeros((h,w,4),dtype=np.uint8);rgba[::3,:,0]=255;rgba[::3,:,3]=160;cached=cache_overlay(Image.fromarray(rgba,"RGBA"),size)
        def legacy():
            alpha=rgba[:,:,3:4].astype(np.float32)/255;return (frame.astype(np.float32)*(1-alpha)+rgba[:,:,:3][:,:,::-1].astype(np.float32)*alpha).astype(np.uint8)
        def optimized():return cv2.add(cv2.multiply(frame,cached.inverse_alpha,scale=1/255,dtype=cv2.CV_8U),cached.premultiplied_bgr)
        old=legacy();new=optimized();report["devices"][device]={"legacy":measure(legacy,a.rounds),"cached_uint8":measure(optimized,a.rounds),"maximum_channel_difference":int(np.abs(old.astype(np.int16)-new.astype(np.int16)).max())};cached.image.close()
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,indent=2),encoding="utf-8");print(json.dumps(report,indent=2))
if __name__=="__main__":main()
