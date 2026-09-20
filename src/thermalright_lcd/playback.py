from __future__ import annotations

import threading
import time
import shutil
import subprocess
import os
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from PIL import Image, ImageOps
from .subprocess_utils import hidden_subprocess_kwargs


def timeline_frame_indices(source_fps:float,target_fps:float,duration_seconds:float)->list[int]:
    """Timeline-correct frame selection; output FPS never changes duration."""
    if source_fps<=0 or target_fps<=0 or duration_seconds<=0:raise ValueError("FPS and duration must be positive")
    count=max(1,round(duration_seconds*target_fps))
    maximum=max(0,round(duration_seconds*source_fps)-1)
    return [min(maximum,int(i*source_fps/target_fps)) for i in range(count)]


@dataclass(frozen=True)
class MediaFrame:
    image: Image.Image|None
    duration_seconds: float
    index: int
    pts_seconds: float
    native_bgr: object|None = None


class FrameSource(Protocol):
    def next_frame(self)->MediaFrame|None: ...
    def close(self)->None: ...


class PillowAnimationSource:
    """Lazy GIF/animated-WebP decoder; retains only the current decoded frame."""
    def __init__(self,path:Path,loop:bool=True):
        self.path=Path(path);self.image=Image.open(self.path);self.loop=loop
        self.count=max(1,getattr(self.image,"n_frames",1));self.index=0;self.pts=0.0
    def next_frame(self):
        if self.index>=self.count:
            if not self.loop:return None
            self.index=0;self.pts=0.0
        self.image.seek(self.index);frame=ImageOps.exif_transpose(self.image).convert("RGB").copy()
        duration=max(.01,float(self.image.info.get("duration",100))/1000)
        result=MediaFrame(frame,duration,self.index,self.pts);self.index+=1;self.pts+=duration;return result
    def close(self):
        image,self.image=self.image,None
        if image is not None:image.close()
    def skip(self,count:int)->int:
        skipped=0
        for _ in range(max(0,count)):
            if self.index>=self.count:
                if not self.loop:break
                self.index=0;self.pts=0.0
            self.image.seek(self.index);duration=max(.01,float(self.image.info.get("duration",100))/1000);self.index+=1;self.pts+=duration;skipped+=1
        return skipped


class OpenCvVideoSource:
    """Bounded one-frame OpenCV decoder for common FFmpeg-backed video formats."""
    def __init__(self,path:Path,loop:bool=True):
        import cv2
        # OpenCV/FFmpeg otherwise defaults HEVC decoding to the machine's core
        # count. Two 4K captures then retain ~2 GB of codec buffers and create
        # roughly 90 extra threads. One decoder thread still exceeds both LCDs'
        # proven transport rates while keeping each capture bounded.
        cv2.setNumThreads(1)
        params=[cv2.CAP_PROP_N_THREADS,1] if hasattr(cv2,"CAP_PROP_N_THREADS") else []
        self.cv2=cv2;self.path=Path(path);self.capture=cv2.VideoCapture(str(path),cv2.CAP_FFMPEG,params);self.loop=loop;self.index=0;self.backend="CPU fallback (OpenCV/FFmpeg)";self.sequential_stream=False
        if not self.capture.isOpened():raise ValueError(f"unable to open video: {path}")
        self.decoder_threads=int(self.capture.get(cv2.CAP_PROP_N_THREADS)) if hasattr(cv2,"CAP_PROP_N_THREADS") else -1
        fps=float(self.capture.get(cv2.CAP_PROP_FPS));self.fps=fps if fps>0 else 30.0
    def next_frame(self):
        ok,bgr=self.capture.read()
        if not ok and self.loop:
            self.capture.set(self.cv2.CAP_PROP_POS_FRAMES,0);self.index=0;ok,bgr=self.capture.read()
        if not ok:return None
        # Preserve the decoder-native BGR array. Creating a full 4K RGB PIL copy
        # here costs ~24 MB/frame and defeats early output-resolution scaling.
        result=MediaFrame(None,1/self.fps,self.index,self.index/self.fps,bgr);self.index+=1;return result
    def close(self):
        capture,self.capture=self.capture,None
        if capture is not None:capture.release()
    def skip(self,count:int)->int:
        skipped=0
        for _ in range(max(0,count)):
            if self.capture.grab():self.index+=1;skipped+=1;continue
            if not self.loop:break
            self.capture.set(self.cv2.CAP_PROP_POS_FRAMES,0);self.index=0
            if not self.capture.grab():break
            self.index=1;skipped+=1
        return skipped


class PyAvVideoSource:
    """In-process libavcodec decoder with native early scale and no helper process."""
    def __init__(self,path:Path,decode_size:tuple[int,int]|None=None,loop:bool=True,thread_count:int=1,cover:bool=True,hardware_acceleration:str|None="auto"):
        import av
        self.av=av;self.path=Path(path);self.loop=loop;self.hwaccel=None
        self.container=av.open(str(path));probe_stream=self.container.streams.video[0]
        selected="d3d11va" if hardware_acceleration=="auto" and (probe_stream.codec_context.name in {"hevc","h265"} or probe_stream.codec_context.width*probe_stream.codec_context.height>1920*1080) else None if hardware_acceleration=="auto" else hardware_acceleration
        if selected:
            from av.codec.hwaccel import HWAccel
            try:self.container.close();self.hwaccel=HWAccel(selected,allow_software_fallback=True);self.container=av.open(str(path),hwaccel=self.hwaccel)
            except Exception:self.hwaccel=None;self.container=av.open(str(path))
        self.stream=self.container.streams.video[0]
        self.stream.thread_type="AUTO";self.stream.codec_context.thread_count=max(1,int(thread_count));rate=self.stream.average_rate or self.stream.base_rate
        self.source_fps=float(rate) if rate else 30.0;self.fps=self.source_fps;self.index=0;self.backend=f"In-process PyAV {selected.upper()} (fallback allowed)" if self.hwaccel else "In-process PyAV software";self.decoder_threads=self.stream.codec_context.thread_count;self.sequential_stream=True
        source_w=max(1,int(self.stream.codec_context.width));source_h=max(1,int(self.stream.codec_context.height));self.output_size=None
        if decode_size:
            target_w,target_h=decode_size;ratio=(max(target_w/source_w,target_h/source_h) if cover else min(target_w/source_w,target_h/source_h));scale=min(1.0,ratio);self.output_size=(max(1,round(source_w*scale)),max(1,round(source_h*scale)))
        self._frames=self._decode()
    def _decode(self):
        for packet in self.container.demux(self.stream):
            for frame in packet.decode():yield frame
    def next_frame(self):
        try:frame=next(self._frames)
        except StopIteration:
            if not self.loop:return None
            self.container.seek(0,stream=self.stream);self._frames=self._decode();self.index=0
            try:frame=next(self._frames)
            except StopIteration:return None
        if self.output_size:frame=frame.reformat(width=self.output_size[0],height=self.output_size[1],format="bgr24",interpolation="BILINEAR")
        bgr=frame.to_ndarray(format="bgr24");pts=(float(frame.time) if frame.time is not None else self.index/self.source_fps)
        result=MediaFrame(None,1/self.source_fps,self.index,pts,bgr);self.index+=1;return result
    def skip(self,count:int)->int:
        skipped=0
        for _ in range(max(0,count)):
            try:next(self._frames);self.index+=1;skipped+=1
            except StopIteration:break
        return skipped
    def close(self):
        container,self.container=self.container,None
        if container is not None:container.close()


class FfmpegScaledVideoSource:
    """Optional early-downscale decoder; one bounded helper per playing video."""
    def __init__(self,path:Path,decode_size:tuple[int,int],loop:bool=True,executable:str|None=None,hardware_acceleration:str|None=None,output_fps:float|None=None):
        import cv2
        self.path=Path(path);self.loop=loop;self.executable=executable or shutil.which("ffmpeg");self.sequential_stream=True
        if not self.executable:raise ValueError("ffmpeg executable is unavailable")
        probe=cv2.VideoCapture(str(path),cv2.CAP_FFMPEG,[cv2.CAP_PROP_N_THREADS,1]);fps=float(probe.get(cv2.CAP_PROP_FPS));probe.release();self.source_fps=fps if fps>0 else 30.0;self.fps=float(output_fps) if output_fps else self.source_fps
        self.width,self.height=map(int,decode_size);self.frame_bytes=self.width*self.height*3;self.index=0;self.closed=False
        command=[self.executable,"-hide_banner","-loglevel","error","-threads","1","-filter_threads","1","-filter_complex_threads","1"]
        if hardware_acceleration:command += ["-hwaccel",hardware_acceleration]
        if loop:command += ["-stream_loop","-1"]
        select=f"fps={float(output_fps):.6f}," if output_fps else ""
        vf=(select+f"scale={self.width}:{self.height}:force_original_aspect_ratio=decrease:flags=fast_bilinear,"
            f"pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2:black")
        command += ["-i",str(self.path),"-an","-sn","-vf",vf,"-pix_fmt","bgr24","-f","rawvideo","pipe:1"]
        self.backend=f"Hardware ({hardware_acceleration})" if hardware_acceleration else "CPU fallback (FFmpeg scaled)"
        self.process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,bufsize=self.frame_bytes*2,**hidden_subprocess_kwargs())
        self._first=self.process.stdout.read(self.frame_bytes)
        if len(self._first)!=self.frame_bytes:
            detail=self.process.stderr.read(2048).decode("utf-8","replace").strip();self.close();raise ValueError(detail or "FFmpeg produced no complete first frame")
    def next_frame(self):
        import numpy as np
        if self.closed:return None
        data,self._first=self._first,None
        if data is None:data=self.process.stdout.read(self.frame_bytes)
        if len(data)!=self.frame_bytes:return None
        bgr=np.frombuffer(data,dtype=np.uint8).reshape((self.height,self.width,3)).copy();result=MediaFrame(None,1/self.fps,self.index,self.index/self.fps,bgr);self.index+=1;return result
    def skip(self,count):
        skipped=0
        for _ in range(max(0,count)):
            data=self.process.stdout.read(self.frame_bytes)
            if len(data)!=self.frame_bytes:break
            self.index+=1;skipped+=1
        return skipped
    def close(self):
        if self.closed:return
        self.closed=True
        if self.process.stdout:self.process.stdout.close()
        if self.process.stderr:self.process.stderr.close()
        if self.process.poll() is None:
            self.process.terminate()
            try:self.process.wait(2)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait(2)


def open_frame_source(path:Path,loop:bool=True,decode_size:tuple[int,int]|None=None,prefer_scaled_ffmpeg:bool=True,output_fps:float|None=None,decode_cover:bool=True,decoder_backend:str|None=None)->FrameSource:
    suffix=Path(path).suffix.lower()
    if suffix in {".gif",".webp"}:
        source=PillowAnimationSource(path,loop)
        if source.count>1:return source
        source.close()
    if suffix in {".mp4",".webm",".mkv",".mov",".avi",".m4v"}:
        fallback_reason="scaled FFmpeg path unavailable"
        decoder=(decoder_backend or os.environ.get("ONI_LCD_DECODER","external")).lower()
        if decoder=="pyav":
            try:return PyAvVideoSource(path,decode_size,loop,cover=decode_cover)
            except Exception as exc:fallback_reason=f"PyAV failed: {type(exc).__name__}: {exc}"
        elif decoder=="opencv":return OpenCvVideoSource(path,loop)
        if prefer_scaled_ffmpeg and decode_size and shutil.which("ffmpeg"):
            try:return FfmpegScaledVideoSource(path,decode_size,loop,hardware_acceleration=os.environ.get("ONI_LCD_HW_DECODE") or None,output_fps=output_fps)
            except Exception as exc:fallback_reason=f"scaled FFmpeg failed: {type(exc).__name__}: {exc}"
        source=OpenCvVideoSource(path,loop);source.backend=f"CPU fallback (OpenCV/FFmpeg; {fallback_reason})";return source
    raise ValueError(f"not animated/video media: {suffix}")


@dataclass
class SchedulerMetrics:
    decoded:int=0;delivered:int=0;dropped:int=0;actual_fps:float=0.0;decode_fps:float=0.0;mean_delivery_ms:float=0.0;last_error:str=""


class FrameScheduler:
    """Two-stage, single-slot scheduler: decode timing never builds a frame backlog."""
    def __init__(self,source:FrameSource,deliver:Callable[[MediaFrame],None],target_fps:float|None=None,
                 clock:Callable=time.perf_counter,sleep:Callable=time.sleep,start_epoch:float|None=None):
        if target_fps is not None and not 1<=target_fps<=240:raise ValueError("target_fps outside 1..240")
        self.source=source;self.deliver=deliver;self.target_fps=target_fps;self.clock=clock;self.sleep=sleep;self.start_epoch=start_epoch
        self.metrics=SchedulerMetrics();self._stop=threading.Event();self._paused=threading.Event();self._thread=None;self._delivery_thread=None;self._condition=threading.Condition();self._latest=None;self._decode_done=False;self._source_closed=False;self.worker_starts=0
    def start(self):
        if self.is_active:return False
        self._stop.clear();self._paused.clear();self._decode_done=False;self._latest=None
        self._delivery_thread=threading.Thread(target=self._deliver_latest,name="media-delivery",daemon=True);self._thread=threading.Thread(target=self._run,name="media-decoder",daemon=True);self.worker_starts+=2;self._delivery_thread.start();self._thread.start();return True
    @property
    def is_active(self):return bool((self._thread and self._thread.is_alive()) or (self._delivery_thread and self._delivery_thread.is_alive()))
    @property
    def pending_frames(self):
        with self._condition:return int(self._latest is not None)
    @property
    def active_workers(self):return sum(int(x is not None and x.is_alive()) for x in (self._thread,self._delivery_thread))
    def pause(self):self._paused.set()
    def resume(self):
        self._paused.clear()
        with self._condition:self._condition.notify_all()
    def _offer(self,frame):
        with self._condition:
            if self._latest is not None:
                self.metrics.dropped+=1
                try:
                    if self._latest.image is not None:self._latest.image.close()
                except Exception:pass
            self._latest=frame;self._condition.notify()
    def _skip(self,count):
        if count<=0:return 0
        # A raw FFmpeg pipe is sequential: "skipping" still decodes and copies
        # every frame. Reset the deadline instead of doing guaranteed-stale work.
        if getattr(self.source,"sequential_stream",False):return 0
        skip=getattr(self.source,"skip",None)
        if skip:return int(skip(count))
        skipped=0
        for _ in range(count):
            frame=self.source.next_frame()
            if frame is None:break
            try:
                if frame.image is not None:frame.image.close()
            except Exception:pass
            skipped+=1
        return skipped
    def _run(self):
        due=max(self.clock(),self.start_epoch or 0);timeline_started=due;paused_total=0.0;pause_mark=None;last_pts=-1.0;interval_hint=1/self.target_fps if self.target_fps else 1/30;decode_started=self.clock()
        try:
            while not self._stop.is_set():
                if self._paused.is_set():
                    if pause_mark is None:pause_mark=self.clock()
                    with self._condition:self._condition.wait(.1)
                    due=self.clock();continue
                if pause_mark is not None:paused_total+=self.clock()-pause_mark;pause_mark=None
                now=self.clock()
                if now<due:self.sleep(min(due-now,.05));continue
                if now>due+interval_hint:
                    count=min(120,int((now-due)//interval_hint));skipped=self._skip(count);self.metrics.decoded+=skipped;self.metrics.dropped+=max(skipped,count if getattr(self.source,"sequential_stream",False) else skipped);due=(now if getattr(self.source,"sequential_stream",False) else due+skipped*interval_hint)
                frame=self.source.next_frame()
                if frame is None:break
                if frame.pts_seconds<last_pts:timeline_started=self.clock();paused_total=0.0
                timeline_now=max(0.0,self.clock()-timeline_started-paused_total)
                while frame.pts_seconds+frame.duration_seconds<timeline_now and not self._stop.is_set():
                    try:
                        if frame.image is not None:frame.image.close()
                    except Exception:pass
                    self.metrics.decoded+=1;self.metrics.dropped+=1
                    frame=self.source.next_frame()
                    if frame is None:break
                if frame is None:break
                last_pts=frame.pts_seconds
                self.metrics.decoded+=1
                self.metrics.decode_fps=self.metrics.decoded/max(.001,self.clock()-decode_started)
                interval=max(frame.duration_seconds,1/self.target_fps) if self.target_fps else frame.duration_seconds
                interval_hint=interval;self._offer(frame);due+=interval
        except Exception as exc:self.metrics.last_error=str(exc)
        finally:
            self._decode_done=True
            with self._condition:self._condition.notify_all()
            if not self._delivery_thread or not self._delivery_thread.is_alive():self._close_source()
    def _deliver_latest(self):
        started=self.clock()
        try:
            while not self._stop.is_set():
                with self._condition:
                    while self._latest is None and not self._decode_done and not self._stop.is_set():self._condition.wait(.1)
                    if self._stop.is_set():break
                    if self._latest is None and self._decode_done:break
                    frame,self._latest=self._latest,None
                delivery_started=time.perf_counter()
                try:self.deliver(frame)
                finally:
                    try:
                        if frame.image is not None:frame.image.close()
                    except Exception:pass
                self.metrics.delivered+=1;elapsed_ms=(time.perf_counter()-delivery_started)*1000;self.metrics.mean_delivery_ms += (elapsed_ms-self.metrics.mean_delivery_ms)/self.metrics.delivered;self.metrics.actual_fps=self.metrics.delivered/max(.001,self.clock()-started)
        except Exception as exc:self.metrics.last_error=str(exc);self._stop.set()
        finally:
            if self._decode_done:self._close_source()
            with self._condition:
                if self._latest is not None:
                    try:
                        if self._latest.image is not None:self._latest.image.close()
                    except Exception:pass
                self._latest=None
    def _close_source(self):
        if self._source_closed:return
        try:self.source.close()
        except Exception as exc:self.metrics.last_error=self.metrics.last_error or str(exc)
        finally:self._source_closed=True
    def stop(self,timeout:float=2):
        self._stop.set();self._paused.clear()
        with self._condition:
            if self._latest is not None:
                try:
                    if self._latest.image is not None:self._latest.image.close()
                except Exception:pass
            self._latest=None;self._condition.notify_all()
        deadline=time.perf_counter()+timeout
        for thread in (self._thread,self._delivery_thread):
            if thread and thread is not threading.current_thread():thread.join(max(0,deadline-time.perf_counter()))
        alive=self.is_active
        if not alive:self._close_source();self._thread=None;self._delivery_thread=None
        return not alive


class SharedFrameScheduler:
    """One decoder feeding independent bounded latest-frame consumer slots."""
    def __init__(self,source:FrameSource,consumers:dict[str,Callable[[MediaFrame],None]],target_fps:float|None=None,start_epoch:float|None=None):
        self.source=source;self.consumers=dict(consumers);self.target_fps=target_fps;self.start_epoch=start_epoch;self.started_at=0.0;self._stop=threading.Event();self._condition=threading.Condition();self._latest={name:None for name in consumers};self._enabled={name:True for name in consumers};self._workers=[];self.dropped=defaultdict(int);self.delivered=defaultdict(int);self.errors={};self.scheduler=FrameScheduler(source,self._fanout,target_fps,start_epoch=start_epoch)
    def _fanout(self,frame:MediaFrame):
        with self._condition:
            for name in self.consumers:
                if not self._enabled[name]:continue
                if self._latest[name] is not None:self.dropped[name]+=1
                self._latest[name]=MediaFrame(None,frame.duration_seconds,frame.index,frame.pts_seconds,frame.native_bgr)
            self._condition.notify_all()
    def _consume(self,name):
        while not self._stop.is_set():
            with self._condition:
                while self._latest[name] is None and not self._stop.is_set():self._condition.wait()
                if self._stop.is_set():break
                frame,self._latest[name]=self._latest[name],None
            try:self.consumers[name](frame);self.delivered[name]+=1
            except Exception as exc:
                self.errors[name]=f"{type(exc).__name__}: {exc}"
                with self._condition:self._enabled[name]=False;self._latest[name]=None
    def start(self):
        if self._workers:return False
        self._stop.clear();self.started_at=time.perf_counter();self._workers=[threading.Thread(target=self._consume,args=(name,),name=f"shared-media-{name}",daemon=True) for name in self.consumers]
        for worker in self._workers:worker.start()
        self.scheduler.start();return True
    def set_enabled(self,name,enabled):
        with self._condition:self._enabled[name]=bool(enabled);self._condition.notify_all()
    def stop(self,timeout=2):
        self._stop.set()
        with self._condition:self._condition.notify_all()
        ok=self.scheduler.stop(timeout);workers=list(self._workers)
        for worker in workers:worker.join(timeout)
        alive=any(worker.is_alive() for worker in workers);self._workers=[];self._latest={name:None for name in self.consumers};return ok and not alive
    @property
    def active_workers(self):return sum(worker.is_alive() for worker in self._workers)+self.scheduler.active_workers
