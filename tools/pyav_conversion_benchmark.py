"""Repeatable PyAV decode/reformat/to_ndarray A/B benchmark (offline)."""
from __future__ import annotations

import argparse,hashlib,json,statistics,time,tracemalloc
from pathlib import Path

import av
import psutil


def percentile(values,p):
    values=sorted(values);return values[min(len(values)-1,max(0,int((len(values)-1)*p)))] if values else 0


def run(path:Path,threads:int,frames:int,target:tuple[int,int]):
    process=psutil.Process();before=process.cpu_times();started=time.perf_counter();conversion=[];decoded=0;dropped=0;digest=hashlib.sha256();tracemalloc.start()
    container=av.open(str(path));stream=container.streams.video[0];stream.thread_type="AUTO";stream.codec_context.thread_count=threads
    source_w,source_h=stream.codec_context.width,stream.codec_context.height;tw,th=target;ratio=max(tw/source_w,th/source_h);size=(max(1,round(source_w*min(1,ratio))),max(1,round(source_h*min(1,ratio))))
    try:
        for packet in container.demux(stream):
            for frame in packet.decode():
                point=time.perf_counter();scaled=frame.reformat(width=size[0],height=size[1],format="bgr24",interpolation="BILINEAR");array=scaled.to_ndarray(format="bgr24");conversion.append((time.perf_counter()-point)*1000);digest.update(memoryview(array).cast("B")[:4096]);decoded+=1
                if decoded>=frames:break
            if decoded>=frames:break
    finally:container.close()
    current,peak=tracemalloc.get_traced_memory();tracemalloc.stop();elapsed=time.perf_counter()-started;after=process.cpu_times();cpu_seconds=(after.user-before.user)+(after.system-before.system)
    return {"decoder_threads":threads,"frames":decoded,"dropped":dropped,"target":list(target),"scaled_size":list(size),"wall_seconds":elapsed,"wall_ms_per_frame":elapsed*1000/max(1,decoded),"throughput_fps":decoded/max(.001,elapsed),"process_cpu_seconds":cpu_seconds,"single_core_equivalent_cpu_percent":cpu_seconds/max(.001,elapsed)*100,"conversion_ms":{"mean":statistics.fmean(conversion),"p95":percentile(conversion,.95),"p99":percentile(conversion,.99)},"python_tracemalloc_peak_bytes":peak,"shape":[array.shape[1],array.shape[0],array.shape[2]],"sample_sha256":digest.hexdigest()}

def run_timeline(path:Path,threads:int,duration:float=8):
    from thermalright_lcd.media import MediaPipeline,FitMode,QUALITY_PROFILES
    from thermalright_lcd.playback import PyAvVideoSource
    process=psutil.Process();source=PyAvVideoSource(path,(1920,480),loop=True,thread_count=threads,cover=True,hardware_acceleration=None);pipes={d:MediaPipeline(1) for d in ("0416:5408","0416:5302")};before=process.cpu_times();started=time.perf_counter();deadline=started;frames=0;drops=0;prepare=[]
    try:
        while time.perf_counter()-started<duration:
            frame=source.next_frame()
            if frame is None:break
            point=time.perf_counter()
            for device in pipes:
                prepared,_=pipes[device].prepare_bgr(frame.native_bgr,device,FitMode.FILL,0,QUALITY_PROFILES["Balanced"],generate_preview=False);prepare.append(pipes[device].last_metrics["total_prepare_ms"])
                if prepared.canvas is not None:prepared.canvas.close()
            frames+=1;deadline+=1/60;remaining=deadline-time.perf_counter()
            if remaining>0:time.sleep(remaining)
            else:drops+=max(0,int(-remaining*60))
    finally:source.close();[pipe.clear() for pipe in pipes.values()]
    elapsed=time.perf_counter()-started;after=process.cpu_times();cpu=(after.user-before.user)+(after.system-before.system)
    return {"decoder_threads":threads,"duration_seconds":elapsed,"produced_fps":frames/elapsed,"frames":frames,"deadline_misses":drops,"process_cpu_seconds":cpu,"single_core_equivalent_cpu_percent":cpu/elapsed*100,"prepare_ms_mean_per_branch":statistics.fmean(prepare),"decoder_backend":source.backend}


def main():
    p=argparse.ArgumentParser();p.add_argument("--media",type=Path,required=True);p.add_argument("--frames",type=int,default=600);p.add_argument("--repeats",type=int,default=3);p.add_argument("--output",type=Path,default=Path("analysis/pyav-conversion-ab.json"));a=p.parse_args();rows=[]
    for target in ((1920,480),(1280,480)):
        for repeat in range(a.repeats):
            for threads in (2,1):row=run(a.media,threads,a.frames,target);row["repeat"]=repeat+1;rows.append(row)
    timeline=[]
    for repeat in range(a.repeats):
        for threads in (2,1):row=run_timeline(a.media,threads);row["repeat"]=repeat+1;timeline.append(row)
    report={"schema":1,"media":str(a.media),"pyav_version":av.__version__,"api_note":"Installed PyAV exposes decoder thread_count; VideoFrame.reformat/to_ndarray expose no conversion-thread argument. A/B therefore constrains the codec context while measuring conversion separately.","rows":rows,"dual_output_60fps_timeline":timeline}
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,indent=2),encoding="utf-8");print(json.dumps(report,indent=2))
if __name__=="__main__":main()
