"""Explicitly authorized, bounded physical FPS progression using known protocols only."""
from __future__ import annotations
import argparse,json,statistics,threading,time
from pathlib import Path

TARGETS=(30,45,60)

def _pct(values,p):
    if not values:return 0.0
    values=sorted(values);return values[min(len(values)-1,int((len(values)-1)*p))]

def prepare_frames(media:Path,device_id:str,count=120,quality_profile="Balanced"):
    import cv2
    from .media import MediaPipeline,FitMode,QUALITY_PROFILES
    capture=cv2.VideoCapture(str(media));frames=[];prepare_ms=[];jpeg_ms=[];pipe=MediaPipeline(1)
    try:
        while len(frames)<count:
            ok,bgr=capture.read()
            if not ok:break
            prepared,encoded=pipe.prepare_bgr(bgr,device_id,FitMode.FILL,0,QUALITY_PROFILES[quality_profile],generate_preview=False)
            frames.append(encoded);prepare_ms.append(float(pipe.last_metrics.get("total_prepare_ms",0)));jpeg_ms.append(float(pipe.last_metrics.get("jpeg_encode_ms",0)))
    finally:capture.release();pipe.clear()
    if len(frames)<60:raise ValueError("test video must supply at least 60 distinct frames")
    return frames,{"quality_profile":quality_profile,"prepare_ms":{"mean":statistics.mean(prepare_ms),"median":statistics.median(prepare_ms),"p95":_pct(prepare_ms,.95),"p99":_pct(prepare_ms,.99)},"jpeg_ms":{"mean":statistics.mean(jpeg_ms),"median":statistics.median(jpeg_ms),"p95":_pct(jpeg_ms,.95),"p99":_pct(jpeg_ms,.99)}}

def connection(root:Path,device_id:str,max_writes:int,max_bytes:int):
    from .device_connection import GeneratedFrameConnection
    from .live_state import RealUsbTransport,load_allowlist,load_sequence
    allow=load_allowlist(root/"config/device-allowlist.json");target=next(x for x in allow["devices"] if x["vid_pid"]==device_id)
    if not target.get("allowGuiGeneratedMedia"):raise RuntimeError("validated generated-media protocol gate is disabled")
    tx=root/("analysis/pid5408-new-session-first-frame.json" if device_id=="0416:5408" else "analysis/pid5302-same-session-first-frame.json")
    lifecycle=load_sequence(root/"analysis/session-report.json",tx,device_id,1,require_same_session=True)
    if device_id=="0416:5408":
        from .windows_usb import CtypesWinUsbApi,discover_identity
        transport=RealUsbTransport(target,lambda:discover_identity(target),CtypesWinUsbApi(),max_writes,max_bytes)
    else:
        from .windows_hid import CtypesWindowsHidApi,RealHidTransport,discover_hid_identity
        transport=RealHidTransport(target,lambda:discover_hid_identity(target),CtypesWindowsHidApi(),max_writes,max_bytes)
    return GeneratedFrameConnection(target,lifecycle,transport),target

def phase(root,device_id,frames,target_fps,duration,start_barrier=None,data_started_event=None,preparation=None):
    from .conflicts import thermalright_processes
    if thermalright_processes():raise RuntimeError("TRCC/USBLCD conflict process is running")
    max_reports=max(len(x.writes) for x in frames);max_bytes=max(x.total_bytes for x in frames);max_attempts=int(duration*target_fps)+4
    # Construct with explicit phase budgets; initialization consumes one write.
    sender,target=connection(root,device_id,1+max_attempts*max_reports,(2048 if device_id.endswith("5408") else 512)+max_attempts*max_bytes)
    open_started=time.perf_counter();sender.open();open_ms=(time.perf_counter()-open_started)*1000
    if start_barrier is not None:start_barrier.wait(timeout=15)
    if data_started_event is not None:data_started_event.set()
    completed=[];submitted=[];ages_start=[];ages_end=[];stale=0;last_slot=-1;error=None;started=time.perf_counter();wall_started=time.time()
    try:
        while True:
            now=time.perf_counter();elapsed=now-started
            if elapsed>=duration:break
            slot=int(elapsed*target_fps)
            if slot<=last_slot:
                time.sleep(min(.002,max(0,(last_slot+1)/target_fps-elapsed)));continue
            stale+=max(0,slot-last_slot-1);last_slot=slot;intended=started+slot/target_fps;ages_start.append((now-intended)*1000)
            try:submitted.append(time.perf_counter());sender(frames[slot%len(frames)])
            except Exception as exc:error=f"{type(exc).__name__}: {exc}";break
            completed.append(time.perf_counter());ages_end.append((completed[-1]-intended)*1000)
    finally:
        try:sender.close()
        except Exception as exc:error=error or f"close: {type(exc).__name__}: {exc}"
    metrics=list(sender.frame_metrics);times=[x["total_ms"] for x in metrics];acks=[x["ack_ms"] for x in metrics if x["ack_ms"]]
    active=(completed[-1]-started) if completed else 0;intervals=[(b-a)*1000 for a,b in zip(completed,completed[1:])];hidden=[max(0,(b-a)*1000) for a,b in zip(completed,submitted[1:])]
    return {"device":device_id,"target_fps":target_fps,"duration_budget_seconds":duration,"wall_started":wall_started,"clock":"time.perf_counter high-resolution monotonic","open_readiness_ms":open_ms,"completed_frames":len(completed),"actual_fps":((len(completed)-1)/active if len(completed)>1 and active else 0),"stable":error is None and len(completed)>=max(1,int(duration*target_fps*.85)),"error":error,"stale_drops":stale,"queue_depth_max":1,"preparation":preparation or {},"frame_bytes_mean":statistics.mean(x["bytes"] for x in metrics) if metrics else 0,"reports_mean":statistics.mean(x["reports"] for x in metrics) if metrics else 0,"throughput_bytes_per_second":sum(x["bytes"] for x in metrics)/max(active,.001),"frame_total_ms":{"minimum":min(times,default=0),"mean":statistics.mean(times) if times else 0,"median":statistics.median(times) if times else 0,"p95":_pct(times,.95),"p99":_pct(times,.99)},"write_ms":{"median":statistics.median([x["write_ms"] for x in metrics]) if metrics else 0,"p95":_pct([x["write_ms"] for x in metrics],.95)},"ack_ms":{"count":len(acks),"minimum":min(acks,default=0),"median":statistics.median(acks) if acks else 0,"p95":_pct(acks,.95),"p99":_pct(acks,.99)},"effective_interval_ms":{"mean":statistics.mean(intervals) if intervals else 0,"median":statistics.median(intervals) if intervals else 0,"p95":_pct(intervals,.95),"p99":_pct(intervals,.99)},"scheduler_deadline_lateness_ms":{"mean":statistics.mean(ages_start) if ages_start else 0,"median":statistics.median(ages_start) if ages_start else 0,"p95":_pct(ages_start,.95),"p99":_pct(ages_start,.99)},"hidden_wait_ms":{"mean":statistics.mean(hidden) if hidden else 0,"median":statistics.median(hidden) if hidden else 0,"p95":_pct(hidden,.95),"p99":_pct(hidden,.99)},"frame_age_complete_ms":{"median":statistics.median(ages_end) if ages_end else 0,"p95":_pct(ages_end,.95)},"writes":sender.transport.write_count,"written_bytes":sender.transport.write_bytes,"zero_retries":True,"protocol_commands":"known initialization + normal frame packets + exact ACK only"}

def run(root:Path,media:Path,duration:float,output:Path):
    results={};prepared={}
    for device in ("0416:5408","0416:5302"):
        quality="Balanced" if device=="0416:5408" else "Extreme FPS"
        prepared[device],prep=prepare_frames(media,device,quality_profile=quality)
        results[device]=[phase(root,device,prepared[device],fps,duration,preparation=prep) for fps in TARGETS]
    stable={device:max((x["target_fps"] for x in rows if x["stable"]),default=0) for device,rows in results.items()}
    dual={};gate=threading.Event();barrier=threading.Barrier(2)
    def worker(device):gate.wait();dual[device]=phase(root,device,prepared[device],stable[device] or 10,duration,barrier,preparation=prep[device])
    threads=[threading.Thread(target=worker,args=(d,),name=f"physical-fps-{d}") for d in results]
    for t in threads:t.start()
    gate.set()
    for t in threads:t.join()
    report={"schema":1,"authorization":"user explicitly authorized controlled known-protocol physical FPS validation","media":str(media),"duration_per_stage_seconds":duration,"targets":list(TARGETS),"results":results,"maximum_stable_target":stable,"dual":dual,"no_unknown_commands":True,"zero_retries":True}
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,indent=2),encoding="utf-8");return report

def run_dual_only(root:Path,media:Path,duration:float,prior:Path,output:Path):
    import psutil
    previous=json.loads(prior.read_text(encoding="utf-8"));stable=previous["maximum_stable_target"]
    prepared_data={d:prepare_frames(media,d) for d in ("0416:5408","0416:5302")};prepared={d:value[0] for d,value in prepared_data.items()};prep={d:value[1] for d,value in prepared_data.items()};dual={};gate=threading.Event();started=threading.Event();barrier=threading.Barrier(2);process=psutil.Process();logical=psutil.cpu_count(logical=True) or 1
    def worker(device):gate.wait();dual[device]=phase(root,device,prepared[device],stable[device],duration,barrier,started,prep[device])
    threads=[threading.Thread(target=worker,args=(d,),name=f"physical-fps-{d}") for d in prepared]
    for t in threads:t.start()
    gate.set();started.wait(20);process.cpu_percent(None);samples=[]
    while any(t.is_alive() for t in threads):samples.append({"cpu_raw":process.cpu_percent(.2),"rss_mb":process.memory_info().rss/1048576,"threads":process.num_threads()})
    for t in threads:t.join()
    starts=[x["wall_started"] for x in dual.values()];report={"schema":1,"authorization":"user authorized known-protocol physical FPS dual validation","duration_seconds":duration,"targets":stable,"dual":dual,"start_skew_ms":(max(starts)-min(starts))*1000,"resources":{"cpu_normalized_mean":statistics.mean(x["cpu_raw"] for x in samples)/logical,"cpu_normalized_peak":max(x["cpu_raw"] for x in samples)/logical,"rss_peak_mb":max(x["rss_mb"] for x in samples),"threads_peak":max(x["threads"] for x in samples)},"usb_unknown_commands":0,"zero_retries":True}
    output.write_text(json.dumps(report,indent=2),encoding="utf-8");return report

def run_quality_study(root:Path,media:Path,duration:float,output:Path):
    """Measure whether JPEG size, rather than known transport ordering, limits 60 FPS."""
    rows={};summaries={}
    for device in ("0416:5408","0416:5302"):
        rows[device]=[]
        for quality in ("Quality","Balanced","Performance"):
            frames,prep=prepare_frames(media,device,quality_profile=quality)
            result=phase(root,device,frames,60,duration,preparation=prep);result["quality_profile"]=quality
            rows[device].append(result)
        summaries[device]={"best_actual_fps":max(x["actual_fps"] for x in rows[device]),"best_profile":max(rows[device],key=lambda x:x["actual_fps"])["quality_profile"]}
    report={"schema":1,"authorization":"user explicitly authorized known-protocol physical optimization testing","duration_per_stage_seconds":duration,"requested_fps":60,"results":rows,"summary":summaries,"protocol_changes":0,"unknown_commands":0,"zero_retries":True}
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,indent=2),encoding="utf-8");return report

def run_quality_dual(root:Path,media:Path,duration:float,output:Path):
    """Longer synchronized validation at the measured best safe quality targets."""
    import psutil
    plans={"0416:5408":("Balanced",45),"0416:5302":("Performance",38)}
    prepared_data={d:prepare_frames(media,d,quality_profile=q) for d,(q,_) in plans.items()};prepared={d:value[0] for d,value in prepared_data.items()};prep={d:value[1] for d,value in prepared_data.items()};dual={};gate=threading.Event();barrier=threading.Barrier(2);process=psutil.Process();logical=psutil.cpu_count(logical=True) or 1
    def worker(device):gate.wait();dual[device]=phase(root,device,prepared[device],plans[device][1],duration,barrier,preparation=prep[device])
    threads=[threading.Thread(target=worker,args=(d,),name=f"physical-quality-dual-{d}") for d in plans]
    for thread in threads:thread.start()
    gate.set();process.cpu_percent(None);samples=[]
    while any(thread.is_alive() for thread in threads):samples.append({"cpu_raw":process.cpu_percent(.2),"rss_mb":process.memory_info().rss/1048576,"threads":process.num_threads()})
    for thread in threads:thread.join()
    starts=[x["wall_started"] for x in dual.values()];report={"schema":1,"authorization":"user authorized known-protocol physical optimization and synchronized dual testing","duration_seconds":duration,"plans":{d:{"quality":q,"target_fps":fps} for d,(q,fps) in plans.items()},"dual":dual,"start_skew_ms":(max(starts)-min(starts))*1000,"resources":{"cpu_normalized_mean":statistics.mean(x["cpu_raw"] for x in samples)/logical,"cpu_normalized_peak":max(x["cpu_raw"] for x in samples)/logical,"rss_peak_mb":max(x["rss_mb"] for x in samples),"threads_peak":max(x["threads"] for x in samples)},"protocol_changes":0,"unknown_commands":0,"zero_retries":True}
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,indent=2),encoding="utf-8");return report

def run_single(root:Path,media:Path,duration:float,output:Path,device:str,target:float,quality:str):
    frames,prep=prepare_frames(media,device,quality_profile=quality);result=phase(root,device,frames,target,duration,preparation=prep);result["quality_profile"]=quality
    report={"schema":1,"authorization":"known-protocol physical optimization validation","result":result,"protocol_changes":0,"unknown_commands":0,"zero_retries":True};output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,indent=2),encoding="utf-8");return report

def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument("--root",type=Path,default=Path.cwd());p.add_argument("--media",type=Path,required=True);p.add_argument("--duration",type=float,default=3);p.add_argument("--output",type=Path,required=True);p.add_argument("--dual-only-from",type=Path);p.add_argument("--quality-study",action="store_true");p.add_argument("--quality-dual",action="store_true");p.add_argument("--single-device",choices=("0416:5408","0416:5302"));p.add_argument("--target",type=float,default=60);p.add_argument("--quality",choices=tuple(__import__("thermalright_lcd.media",fromlist=["QUALITY_PROFILES"]).QUALITY_PROFILES),default="Balanced");p.add_argument("--authorized-known-protocol-only",action="store_true");a=p.parse_args(argv)
    if not a.authorized_known_protocol_only:raise SystemExit("explicit known-protocol authorization flag required")
    result=run_single(a.root,a.media,a.duration,a.output,a.single_device,a.target,a.quality) if a.single_device else run_quality_dual(a.root,a.media,a.duration,a.output) if a.quality_dual else run_quality_study(a.root,a.media,a.duration,a.output) if a.quality_study else run_dual_only(a.root,a.media,a.duration,a.dual_only_from,a.output) if a.dual_only_from else run(a.root,a.media,a.duration,a.output)
    print(json.dumps(result,indent=2));return 0
if __name__=="__main__":raise SystemExit(main())
