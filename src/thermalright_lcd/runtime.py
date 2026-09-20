from __future__ import annotations
import threading,time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from .persistence import PersistencePolicy

class SessionState(str,Enum):
    DISCONNECTED="Disconnected";CONNECTED="Connected";READY="Ready";DISPLAYING="Displaying"
    PLAYING="Playing";PAUSED="Paused";RECONNECTING="Reconnecting";DEVICE_BUSY="Device Busy"
    ERROR="Error";STOPPED="Stopped";RUNNING="Running"

@dataclass
class SessionMetrics:
    sent:int=0;dropped:int=0;bytes:int=0;last_send_ms:float=0;last_error:str=""
    actual_fps:float=0;usb_bytes_per_second:float=0;ack_latency_ms:float=0
    scheduler_overruns:int=0;overrun_ms:float=0
    complete_interval_ms:float=0;scheduler_latency_ms:float=0;hidden_wait_ms:float=0
    refresh_opportunities:int=0;usb_send_skips:int=0
    content_sends:int=0;keepalive_sends:int=0;held_frame_generation:int=0;transport_frames_rebuilt:int=0

class LatestFrameQueue:
    def __init__(self):self._item=None;self._put_at=None;self._lock=threading.Lock();self.dropped=0;self.last_age_ms=0.0
    def put(self,item):
        with self._lock:
            if self._item is not None:self.dropped+=1
            self._item=item;self._put_at=time.perf_counter()
    def take(self):
        with self._lock:
            item,put_at,self._item,self._put_at=self._item,self._put_at,None,None
            self.last_age_ms=max(0.0,(time.perf_counter()-put_at)*1000) if item is not None and put_at is not None else 0.0
            return item
    def clear(self):
        with self._lock:self._item=None;self._put_at=None;self.last_age_ms=0.0
    def __len__(self):
        with self._lock:return int(self._item is not None)

class DisplaySession:
    """Independent long-lived worker. Hardware send callback remains externally gated."""
    def __init__(self,name,send,refresh_interval=None,policy:PersistencePolicy|None=None,trace_hook=None):
        self.name=name;self.send=send;self.policy=policy
        self.refresh_interval=policy.interval_seconds if policy and refresh_interval is None else refresh_interval
        self.keepalive_interval=(policy.keepalive_interval_seconds if policy and policy.requires_continuous_frames else refresh_interval)
        self.queue=LatestFrameQueue();self.metrics=SessionMetrics();self.state=SessionState.STOPPED
        self._stop=threading.Event();self._paused=threading.Event();self._wake=threading.Event();self._immediate=threading.Event();self._thread=None;self._last=None;self._sent_times=deque(maxlen=120);self.frame_timings=deque(maxlen=240);self._lifecycle_lock=threading.RLock();self.worker_starts=0;self._rate_generation=0;self.trace_hook=trace_hook
    def _trace(self,event,**fields):
        hook=self.trace_hook
        if hook is not None:
            try:hook(event,device_id=self.name,**fields)
            except Exception:pass
    def start(self):
        with self._lifecycle_lock:
            if self._thread and self._thread.is_alive():return False
            self._stop.clear();self._paused.clear();self.state=SessionState.PLAYING;self._thread=threading.Thread(target=self._run,name=f"display-{self.name}",daemon=True);self.worker_starts+=1;self._thread.start();self._trace("worker_started",worker_starts=self.worker_starts,state=self.state.value);return True
    def set_media(self,frame,force=False,immediate=False):
        if not force and frame is self._last and len(self.queue)==0:
            self.metrics.usb_send_skips+=1;return False
        self.queue.put((frame,bool(immediate)));self.metrics.held_frame_generation+=1;self._trace("content_queued",immediate=bool(immediate),generation=self.metrics.held_frame_generation,queue_depth=len(self.queue))
        if immediate:self._immediate.set()
        self._wake.set()
        return True
    def clear_media(self):
        self.queue.clear();self._last=None;self._wake.set();self._trace("held_frame_cleared")
    def submit(self,frame):self.set_media(frame)
    def play(self):
        if not self._thread or not self._thread.is_alive():self.start()
        self._paused.clear();self.state=SessionState.PLAYING;self._wake.set();self._trace("play",state=self.state.value)
    def pause(self):
        self._paused.set();self.state=SessionState.PAUSED;self._trace("pause",state=self.state.value)
        close=getattr(self.send,"close",None)
        if close:
            try:close()
            except Exception as e:self.metrics.last_error=str(e);self.state=SessionState.ERROR
    def set_refresh_interval(self,interval:float|None):
        if interval is not None and interval<=0:raise ValueError("refresh interval must be positive")
        self.refresh_interval=float(interval) if interval is not None else None;self._rate_generation+=1
        if self.policy is None:self.keepalive_interval=self.refresh_interval
        self._wake.set();self._trace("refresh_interval_changed",refresh_interval=self.refresh_interval,keepalive_interval=self.keepalive_interval,rate_generation=self._rate_generation)
    def refresh_now(self):
        if self._last is None:return False
        self._trace("explicit_refresh_requested")
        return self.set_media(self._last,force=True,immediate=True)
    def _run(self):
        content_deadline=None;keepalive_deadline=None;last_completion=None;rate_generation=self._rate_generation
        while not self._stop.is_set():
            if rate_generation!=self._rate_generation:
                content_deadline=None;rate_generation=self._rate_generation
                if self.policy is None:keepalive_deadline=None
            if self._paused.is_set():self._wake.wait(.05);self._wake.clear();continue
            # Pace *all* frames, including newly submitted video frames. The old
            # ordering sent every new frame immediately and also repeated the
            # last frame on the persistence deadline, producing extra USB work.
            queued=len(self.queue)>0
            wait_deadlines=[x for x in (content_deadline if queued else None,keepalive_deadline if self._last is not None else None) if x is not None]
            deadline=min(wait_deadlines) if wait_deadlines else None
            if deadline is not None:
                wait_started=time.perf_counter();remaining=deadline-wait_started
                if remaining>0:
                    # CPython's Windows Event.wait() uses the coarse kernel
                    # wait granularity here (~15.6 ms on the target system),
                    # while time.sleep() uses a high-resolution waitable timer.
                    # A cadence wait is intentionally not woken by incoming
                    # frames: they overwrite the bounded latest slot. Stop and
                    # pause therefore have at most one frame-period latency.
                    self._trace("worker_sleep_enter",reason="cadence",remaining_seconds=remaining,queued=queued)
                    if remaining>=.05:self._wake.wait(remaining)
                    else:time.sleep(remaining)
                    self._trace("worker_sleep_exit",reason="cadence")
                    self._wake.clear()
                    if self._stop.is_set():break
                    if self._paused.is_set():continue
                    if time.perf_counter()<deadline and not self._immediate.is_set():continue
                self.metrics.hidden_wait_ms=max(0.0,(time.perf_counter()-wait_started)*1000)
            item=self.queue.take();frame=None;send_kind="content"
            if item is not None:
                candidate,immediate=item
                if immediate:self._immediate.clear()
                now=time.perf_counter()
                if immediate or content_deadline is None or now>=content_deadline:frame=candidate
                else:self.queue.put(item)
            if frame is None and self._last is not None and keepalive_deadline is not None and time.perf_counter()>=keepalive_deadline:
                # Cache pixels/JPEG, never mutable transaction state.  Each
                # physical commit gets the same freshly constructed framing
                # and normal send/ACK path as an ordinary content frame.
                from .encoder import EncodedFrame,reframe_encoded
                self._trace("cached_commit_due",target_deadline=keepalive_deadline)
                frame=reframe_encoded(self._last) if isinstance(self._last,EncodedFrame) else self._last
                if frame is not self._last:self.metrics.transport_frames_rebuilt+=1
                send_kind="keepalive";self.metrics.refresh_opportunities+=1
            if frame is None:
                self._trace("worker_idle_enter",reason="no_frame_or_deadline")
                self._wake.wait();self._wake.clear();self._trace("worker_idle_exit",reason="signalled");continue
            try:
                wake=time.perf_counter();target_deadline=(content_deadline if send_kind=="content" else keepalive_deadline) or wake
                self.metrics.scheduler_latency_ms=max(0.0,(wake-target_deadline)*1000)
                started=wake;t=time.perf_counter();self._trace("transport_start",send_kind=send_kind,target_deadline=target_deadline);n=self.send(frame);completed=time.perf_counter();self.metrics.last_send_ms=(completed-t)*1000
                frame_metrics=getattr(self.send,"frame_metrics",None)
                if frame_metrics:self.metrics.ack_latency_ms=float(frame_metrics[-1].get("ack_ms",0))
                self.metrics.sent+=1;self.metrics.bytes+=n
                if send_kind=="content":self._last=frame;self.metrics.content_sends+=1
                else:self.metrics.keepalive_sends+=1
                now=completed;self._sent_times.append((now,n))
                interval_ms=(completed-last_completion)*1000 if last_completion is not None else 0.0
                last_completion=completed;self.metrics.complete_interval_ms=interval_ms
                self.frame_timings.append({"send_kind":send_kind,"target_deadline":target_deadline,"scheduler_wake":wake,"usb_submission_start":started,"physical_completion":completed,"complete_interval_ms":interval_ms,"transport_ms":self.metrics.last_send_ms,"ack_ms":self.metrics.ack_latency_ms,"queue_age_ms":self.queue.last_age_ms,"scheduler_latency_ms":self.metrics.scheduler_latency_ms,"hidden_wait_ms":self.metrics.hidden_wait_ms,"session_state":self.state.value,"held_frame_generation":self.metrics.held_frame_generation,"rate_generation":self._rate_generation})
                self._trace("transport_complete",send_kind=send_kind,bytes=n,transport_ms=self.metrics.last_send_ms,ack_ms=self.metrics.ack_latency_ms,complete_interval_ms=interval_ms,session_state=self.state.value)
                if len(self._sent_times)>1:
                    span=self._sent_times[-1][0]-self._sent_times[0][0]
                    if span>0:self.metrics.actual_fps=(len(self._sent_times)-1)/span;self.metrics.usb_bytes_per_second=sum(x[1] for x in list(self._sent_times)[1:])/span
                # One absolute cadence owns transport pacing. Preparation may
                # publish at source rate; the latest-frame slot coalesces it.
                # Never add a full interval after blocking USB completion.
                if send_kind=="content":content_deadline=(target_deadline+self.refresh_interval) if self.refresh_interval else None
                if self.keepalive_interval:
                    keepalive_deadline=(completed+self.keepalive_interval if self.policy else target_deadline+self.keepalive_interval)
                else:keepalive_deadline=None
                if content_deadline is not None:
                    late=max(0.0,time.perf_counter()-content_deadline)
                    # Blocking I/O near the cadence is saturation, not queued
                    # work. Keep the absolute deadline behind the clock so the
                    # next latest frame starts immediately. Advancing it into
                    # the future here adds a residual host wait after every
                    # slow HID transfer (the packaged PID 5302 ~36 FPS bug).
                    # Subsequent completions advance this same cadence one
                    # interval at a time; no preparation or second clock owns
                    # pacing and the latest slot remains bounded.
                    if late>=.001:
                        self.metrics.scheduler_overruns+=1;self.metrics.overrun_ms+=late*1000
                self.state=SessionState.DISPLAYING
            except Exception as e:self.metrics.last_error=str(e);self.state=SessionState.ERROR;self._trace("transport_error",error=str(e),state=self.state.value);break
        self.metrics.dropped=self.queue.dropped
        if self.state!=SessionState.ERROR:self.state=SessionState.STOPPED
        self._trace("worker_exited",state=self.state.value)
    def stop(self,timeout=2):
        with self._lifecycle_lock:thread=self._thread;self._stop.set();self._paused.clear();self._wake.set();self._trace("stop_requested")
        if thread:thread.join(timeout)
        if thread and thread.is_alive():
            self.metrics.last_error="display worker did not stop within timeout";self.state=SessionState.ERROR;return False
        close=getattr(self.send,"close",None)
        if close:
            try:close()
            except Exception as e:self.metrics.last_error=str(e);self.state=SessionState.ERROR
        self.clear_media();self._sent_times.clear();self._wake.clear();self._immediate.clear()
        with self._lifecycle_lock:
            if self._thread is thread:self._thread=None
        if self.state!=SessionState.ERROR:self.state=SessionState.STOPPED
        self._trace("stop_complete",state=self.state.value,error=self.metrics.last_error)
        return self.state!=SessionState.ERROR

class DisplayManager:
    def __init__(self,sessions):self.sessions=dict(sessions)
    def start_all(self):
        for x in self.sessions.values():x.start()
    def stop_all(self):
        for x in self.sessions.values():x.stop()
