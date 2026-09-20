"""USB-free per-display decode/transform/JPEG/framing benchmark."""
from __future__ import annotations
import argparse,json,time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .media import FitMode,MediaPipeline,QUALITY_PROFILES
from .playback import OpenCvVideoSource


def _rate(fn,seconds=.75):
    count=0;started=time.perf_counter();last=None
    while time.perf_counter()-started<seconds:last=fn();count+=1
    elapsed=time.perf_counter()-started;return {"fps":count/elapsed,"mean_ms":elapsed*1000/count,"count":count,"last":last}


def benchmark(media:Path,output:Path,seconds=.75):
    import cv2,psutil
    process=psutil.Process();source=OpenCvVideoSource(media,loop=True);fps=source.fps
    decoded=[None]
    def decode():
        frame=source.next_frame();decoded[0]=frame.native_bgr;return frame.native_bgr.nbytes
    decode_result=_rate(decode,seconds);source.close();bgr=decoded[0]
    devices={}
    for vid_pid,size in MediaPipeline.TARGETS.items():
        pipe=MediaPipeline(1);target=tuple(size);device={"source_fps":fps,"decode_fps":decode_result["fps"],"source_dimensions":[bgr.shape[1],bgr.shape[0]],"output_dimensions":list(target),"qualities":{}}
        transformed=cv2.resize(bgr,target,interpolation=cv2.INTER_AREA)
        transform=_rate(lambda:cv2.resize(bgr,target,interpolation=cv2.INTER_AREA),seconds)
        device["transform_fps"]=transform["fps"];device["transform_ms"]=transform["mean_ms"]
        for name,quality in QUALITY_PROFILES.items():
            options=[cv2.IMWRITE_JPEG_QUALITY,quality,cv2.IMWRITE_JPEG_PROGRESSIVE,0,cv2.IMWRITE_JPEG_OPTIMIZE,0,cv2.IMWRITE_JPEG_SAMPLING_FACTOR,cv2.IMWRITE_JPEG_SAMPLING_FACTOR_420]
            encoded=[]
            def jpeg():ok,j=cv2.imencode('.jpg',transformed,options);encoded.append(j.tobytes());return j.size
            enc=_rate(jpeg,seconds);sample=encoded[-1];encoded.clear()
            from .encoder import encode_5408,encode_5302
            framing=_rate(lambda:(encode_5408(sample) if vid_pid=="0416:5408" else encode_5302(sample)).total_bytes,seconds)
            prepared=[]
            def full():
                p,e=pipe.prepare_bgr(bgr,vid_pid,FitMode.FILL,0,quality);p.canvas.close();prepared.append(e.total_bytes);return e.total_bytes
            full_result=_rate(full,seconds)
            device["qualities"][name]={"jpeg_quality":quality,"jpeg_fps":enc["fps"],"jpeg_ms":enc["mean_ms"],"jpeg_bytes":len(sample),"protocol_framing_fps":framing["fps"],"protocol_framing_ms":framing["mean_ms"],"full_prepare_fps":full_result["fps"],"full_prepare_ms":full_result["mean_ms"],"protocol_bytes":prepared[-1]}
        devices[vid_pid]=device
    def concurrent(vid_pid):
        pipe=MediaPipeline(1);count=0;started=time.perf_counter()
        while time.perf_counter()-started<seconds:
            p,_=pipe.prepare_bgr(bgr,vid_pid,FitMode.FILL,0,QUALITY_PROFILES["Balanced"]);p.canvas.close();count+=1
        return count/(time.perf_counter()-started)
    rss_before=process.memory_info().rss/1048576;cpu0=process.cpu_times();started=time.perf_counter()
    with ThreadPoolExecutor(max_workers=2,thread_name_prefix="benchmark-display") as pool:dual=dict(zip(MediaPipeline.TARGETS,pool.map(concurrent,MediaPipeline.TARGETS)))
    elapsed=time.perf_counter()-started;cpu1=process.cpu_times();rss_after=process.memory_info().rss/1048576
    report={"schema":1,"media":str(media),"offline_only":True,"usb_writes":0,"devices":devices,"dual_balanced_fps":dual,"dual_elapsed_seconds":elapsed,"dual_cpu_percent_raw":100*((cpu1.user+cpu1.system)-(cpu0.user+cpu0.system))/elapsed,"dual_rss_before_mb":rss_before,"dual_rss_after_mb":rss_after}
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,indent=2),encoding="utf-8");return report


def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument("--media",type=Path,required=True);p.add_argument("--output",type=Path,required=True);p.add_argument("--seconds",type=float,default=.75);a=p.parse_args(argv);r=benchmark(a.media,a.output,a.seconds);print(json.dumps({"output":str(a.output),"usb_writes":0,"dual_balanced_fps":r["dual_balanced_fps"]},indent=2));return 0
if __name__=="__main__":raise SystemExit(main())
