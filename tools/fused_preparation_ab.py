"""Offline A/B for a direct source-crop -> reusable final BGR buffer path."""
from __future__ import annotations

import argparse,json,statistics,time
from pathlib import Path

import cv2,numpy as np,psutil
from PIL import Image,ImageDraw

from thermalright_lcd.media import CachedOverlay,FitMode,MediaPipeline,cache_overlay
from thermalright_lcd.playback import PyAvVideoSource


def percentile(values,f=.95):
    values=sorted(values);return values[min(len(values)-1,round((len(values)-1)*f))] if values else 0.0


def direct_fill(frame,target,destination,overlay:CachedOverlay):
    tw,th=target;h,w=frame.shape[:2];source_ratio=w/h;target_ratio=tw/th
    if source_ratio>target_ratio:
        crop_w=max(1,round(h*target_ratio));x=(w-crop_w)//2;source=frame[:,x:x+crop_w]
    else:
        crop_h=max(1,round(w/target_ratio));y=(h-crop_h)//2;source=frame[y:y+crop_h,:]
    if source.shape[1: :-1] == (tw,th):np.copyto(destination,source)
    else:cv2.resize(source,(tw,th),dst=destination,interpolation=cv2.INTER_AREA)
    cv2.multiply(destination,overlay.inverse_alpha,dst=destination,scale=1/255,dtype=cv2.CV_8U)
    cv2.add(destination,overlay.premultiplied_bgr,dst=destination)
    return destination


def sample_overlay(size):
    image=Image.new("RGBA",size,(0,0,0,0));draw=ImageDraw.Draw(image);draw.rounded_rectangle((20,20,size[0]//3,120),12,fill=(7,14,25,180));draw.text((40,45),"GPU 63 C  82%",fill=(255,255,255,255));result=cache_overlay(image,size);image.close();return result


def run(media,device,frames,variant):
    target=MediaPipeline.TARGETS[device];overlay=sample_overlay(target);source=PyAvVideoSource(media,(1920,1080),loop=True,thread_count=1,cover=True,hardware_acceleration=None);pipe=MediaPipeline();destination=np.empty((target[1],target[0],3),np.uint8);durations=[];cpu0=psutil.Process().cpu_times();wall0=time.perf_counter();last=None
    try:
        for _ in range(frames):
            frame=source.next_frame();started=time.perf_counter()
            if variant=="production":
                prepared,_=pipe.prepare_bgr(frame.native_bgr,device,FitMode.FILL,quality=88 if device.endswith("5408") else 45,generate_preview=False,overlay_rgba=overlay);prepared.canvas and prepared.canvas.close();last=pipe.last_metrics
            else:
                out=direct_fill(frame.native_bgr,target,destination,overlay);ok,jpeg=cv2.imencode(".jpg",out,[cv2.IMWRITE_JPEG_QUALITY,88 if device.endswith("5408") else 45,cv2.IMWRITE_JPEG_PROGRESSIVE,0,cv2.IMWRITE_JPEG_OPTIMIZE,0]);assert ok;last={"jpeg_bytes":len(jpeg)}
            durations.append((time.perf_counter()-started)*1000)
    finally:source.close();overlay.image.close()
    elapsed=time.perf_counter()-wall0;cpu1=psutil.Process().cpu_times();cpu=(cpu1.user+cpu1.system)-(cpu0.user+cpu0.system)
    return {"device":device,"variant":variant,"frames":frames,"wall_seconds":elapsed,"process_cpu_seconds":cpu,"cpu_ms_per_frame":1000*cpu/frames,"operation_ms_mean":statistics.fmean(durations),"operation_ms_p95":percentile(durations),"jpeg_bytes_last":last["jpeg_bytes"],"full_frame_temporary_resize":variant=="production" and device.endswith("5302"),"reusable_final_buffer":variant=="fused"}


def correctness(media,device):
    target=MediaPipeline.TARGETS[device];overlay=sample_overlay(target);source=PyAvVideoSource(media,(1920,1080),loop=False,thread_count=1,hardware_acceleration=None);frame=source.next_frame();pipe=MediaPipeline();prepared,_=pipe.prepare_bgr(frame.native_bgr,device,FitMode.FILL,quality=88 if device.endswith("5408") else 45,generate_preview=False,overlay_rgba=overlay)
    # Recreate production pixels without JPEG for a direct pixel comparison.
    h,w=frame.native_bgr.shape[:2];tw,th=target;scale=max(tw/w,th/h);nw,nh=round(w*scale),round(h*scale);work=frame.native_bgr if (nw,nh)==(w,h) else cv2.resize(frame.native_bgr,(nw,nh),interpolation=cv2.INTER_AREA);x=(nw-tw)//2;y=(nh-th)//2;reference=work[y:y+th,x:x+tw];reference=cv2.add(cv2.multiply(reference,overlay.inverse_alpha,scale=1/255,dtype=cv2.CV_8U),overlay.premultiplied_bgr)
    fused=direct_fill(frame.native_bgr,target,np.empty((th,tw,3),np.uint8),overlay);diff=cv2.absdiff(reference,fused);mse=float(np.mean((reference.astype(np.float32)-fused.astype(np.float32))**2));source.close();overlay.image.close()
    return {"device":device,"max_channel_difference":int(diff.max()),"mean_absolute_difference":float(diff.mean()),"psnr_db":float("inf") if mse==0 else float(10*np.log10(255*255/mse))}


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--media",type=Path,required=True);parser.add_argument("--frames",type=int,default=180);parser.add_argument("--output",type=Path,required=True);args=parser.parse_args();rows=[]
    for device in ("0416:5408","0416:5302"):
        for variant in ("production","fused"):rows.append(run(args.media,device,args.frames,variant))
    report={"schema":1,"media":str(args.media),"rows":rows,"correctness":[correctness(args.media,d) for d in ("0416:5408","0416:5302")]};args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2),encoding="utf-8");print(json.dumps(report,indent=2))


if __name__=="__main__":main()
