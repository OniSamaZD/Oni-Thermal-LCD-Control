from __future__ import annotations

import argparse,json,statistics,time
from pathlib import Path

import av,cv2,numpy as np,psutil

from thermalright_lcd.media import FitMode,MediaPipeline,configure_opencv_threads


def run(path:Path,variant:str,count:int):
    configure_opencv_threads(1);container=av.open(str(path));stream=container.streams.video[0];stream.thread_type="AUTO";stream.codec_context.thread_count=1;pipe5408=MediaPipeline();pipe5302=MediaPipeline();process=psutil.Process();cpu0=sum(process.cpu_times()[:2]);wall0=time.perf_counter();convert=[];branch=[];frames=0
    for frame in container.decode(stream):
        started=time.perf_counter()
        if variant=="shared-bgr":
            shared=frame.reformat(format="bgr24").to_ndarray(format="bgr24");inputs=(shared,shared)
        else:
            a=frame.reformat(width=1920,height=1080,format="bgr24",interpolation="BILINEAR").to_ndarray(format="bgr24")
            b=frame.reformat(width=1280,height=720,format="bgr24",interpolation="BILINEAR").to_ndarray(format="bgr24");inputs=(a,b)
        convert.append((time.perf_counter()-started)*1000);started=time.perf_counter()
        p1,e1=pipe5408.prepare_bgr(inputs[0],"0416:5408",FitMode.FILL,quality=88,generate_preview=False)
        p2,e2=pipe5302.prepare_bgr(inputs[1],"0416:5302",FitMode.FILL,quality=45,generate_preview=False)
        branch.append((time.perf_counter()-started)*1000);frames+=1
        if frames>=count:break
    wall=time.perf_counter()-wall0;cpu=sum(process.cpu_times()[:2])-cpu0;container.close()
    return {"variant":variant,"frames":frames,"wall_seconds":wall,"cpu_seconds":cpu,"cpu_ms_per_frame":cpu*1000/frames,"wall_ms_per_frame":wall*1000/frames,"conversion_ms_mean":statistics.mean(convert),"branch_ms_mean":statistics.mean(branch),"full_frame_conversions_per_source_frame":1 if variant=="shared-bgr" else 2,"python_native_branch_crossings":2,"output_sha256":{"0416:5408":e1.jpeg_sha256,"0416:5302":e2.jpeg_sha256}}


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--media",type=Path,required=True);parser.add_argument("--frames",type=int,default=300);parser.add_argument("--output",type=Path,required=True);args=parser.parse_args()
    report={"scenario":"native-crop-scale-ab","media":str(args.media),"results":[run(args.media,"shared-bgr",args.frames),run(args.media,"per-device-libswscale",args.frames)]}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2),encoding="utf-8");print(json.dumps(report,indent=2))


if __name__=="__main__":main()
