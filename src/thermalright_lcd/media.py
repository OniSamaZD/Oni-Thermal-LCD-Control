from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from io import BytesIO
from pathlib import Path
from collections import OrderedDict,deque
import threading
import time
from PIL import Image,ImageOps,ImageEnhance
import numpy as np

_opencv_configured=False
def configure_opencv_threads(count:int|None=None):
    """Bound native workers for LCD-sized operations; override remains explicit."""
    global _opencv_configured
    import os,cv2
    selected=max(1,int(count if count is not None else os.environ.get("ONI_LCD_OPENCV_THREADS","1")))
    cv2.setNumThreads(selected);_opencv_configured=True;return selected

QUALITY_PROFILES={"Quality":95,"Balanced":88,"Performance":75,"Extreme FPS":45}

class FitMode(str,Enum): FIT="Fit";FILL="Fill";STRETCH="Stretch";CROP="Crop";CENTER="Center"

@dataclass(frozen=True)
class PreparedImage:
    canvas:Image.Image|None;jpeg:bytes;source:Path|None;mode:FitMode;rotation:int

@dataclass(frozen=True)
class CachedOverlay:
    image:Image.Image
    premultiplied_bgr:object
    inverse_alpha:object

class Pid5302ReportQualityController:
    """One bounded, near-boundary correction from Q45 to visually close Q44."""
    def __init__(self,max_boundary_distance=384):self.max_boundary_distance=max_boundary_distance;self.corrective_encodes=0;self.corrections_used=0
    def should_correct(self,jpeg_length):
        total=20+int(jpeg_length);reports=(total+511)//512;distance=total-(reports-1)*512
        return reports>1 and distance<=self.max_boundary_distance
    def choose(self,primary,corrected):
        self.corrective_encodes+=1
        if len(corrected)+20<=((len(primary)+20+511)//512-1)*512:self.corrections_used+=1;return corrected,44
        return primary,45

def cache_overlay(image:Image.Image,size:tuple[int,int])->CachedOverlay:
    import cv2
    rgba=np.asarray(image.convert("RGBA"))
    if (rgba.shape[1],rgba.shape[0])!=size:rgba=cv2.resize(rgba,size,interpolation=cv2.INTER_LINEAR)
    alpha=np.repeat(rgba[:,:,3:4],3,axis=2);bgr=np.ascontiguousarray(rgba[:,:,:3][:,:,::-1])
    premultiplied=cv2.multiply(bgr,alpha,scale=1/255,dtype=cv2.CV_8U);inverse=np.ascontiguousarray(255-alpha)
    premultiplied.setflags(write=False);inverse.setflags(write=False)
    return CachedOverlay(Image.fromarray(rgba,"RGBA"),premultiplied,inverse)

def render_image(image:Image.Image,size:tuple[int,int],mode:FitMode=FitMode.FIT,rotation:int=0,quality:int=95,source:Path|None=None,pan_x:int=0,pan_y:int=0,zoom:float=1.0,brightness:int=100,overlay:Image.Image|None=None)->PreparedImage:
    im=ImageOps.exif_transpose(image).convert("RGB")
    if rotation%360:im=im.rotate(-rotation%360,expand=True)
    zoom=max(1.0,min(8.0,float(zoom)))
    if zoom>1 or pan_x or pan_y:
        cw=max(1,int(im.width/zoom));ch=max(1,int(im.height/zoom));cx=im.width//2+int(pan_x);cy=im.height//2+int(pan_y);x=max(0,min(im.width-cw,cx-cw//2));y=max(0,min(im.height-ch,cy-ch//2));cropped=im.crop((x,y,x+cw,y+ch));im.close();im=cropped
    w,h=size
    if mode==FitMode.STRETCH: out=im.resize(size,Image.Resampling.LANCZOS)
    elif mode in (FitMode.FILL,FitMode.CROP): out=ImageOps.fit(im,size,Image.Resampling.LANCZOS,centering=(.5,.5))
    else:
        out=Image.new("RGB",size,"black")
        work=ImageOps.contain(im,size,Image.Resampling.LANCZOS) if mode==FitMode.FIT else im
        if mode==FitMode.CENTER and (work.width>w or work.height>h):work=ImageOps.fit(work,size,Image.Resampling.LANCZOS)
        out.paste(work,((w-work.width)//2,(h-work.height)//2))
    brightness=max(0,min(100,int(brightness)))
    if brightness!=100:
        adjusted=ImageEnhance.Brightness(out).enhance(brightness/100);out.close();out=adjusted
    if overlay is not None:
        if isinstance(overlay,CachedOverlay):overlay=overlay.image
        layer=overlay if overlay.mode=="RGBA" else overlay.convert("RGBA")
        if layer.size!=out.size:layer=layer.resize(out.size,Image.Resampling.BILINEAR)
        combined=Image.alpha_composite(out.convert("RGBA"),layer).convert("RGB");out.close();out=combined
    b=BytesIO();out.save(b,"JPEG",quality=quality,optimize=False,progressive=False,subsampling=2,dpi=(96,96))
    return PreparedImage(out,b.getvalue(),source,mode,rotation%360)

def render_static(path:Path,size:tuple[int,int],mode:FitMode=FitMode.FIT,rotation:int=0,quality:int=95,pan_x:int=0,pan_y:int=0,zoom:float=1.0,brightness:int=100)->PreparedImage:
    with Image.open(path) as src:return render_image(src,size,mode,rotation,quality,Path(path),pan_x,pan_y,zoom,brightness)

class MediaPipeline:
    """Small bounded cache for unchanged static media and protocol encoding."""
    from .capabilities import DEVICES as _DEVICE_CAPABILITIES
    TARGETS={key:value.encoded_size for key,value in _DEVICE_CAPABILITIES.items()}
    def __init__(self,max_static_entries:int=8,pid5302_report_correction:bool|None=None):
        if max_static_entries<1:raise ValueError("cache must retain at least one entry")
        import os
        self.max_static_entries=max_static_entries;self._cache=OrderedDict();self._lock=threading.Lock();self._final_buffers={};self.last_metrics={};self.metrics_history=deque(maxlen=2048);self.total_prepares=0;self.pid5302_quality=Pid5302ReportQualityController();self.pid5302_report_correction=(os.environ.get("ONI_LCD_PID5302_REPORT_CORRECTION","1")!="0" if pid5302_report_correction is None else bool(pid5302_report_correction));self.cache_metrics={"source_hits":0,"source_misses":0,"jpeg_skips":0,"composition_skips":0}
    def register_target(self,device_id,size):self.TARGETS[device_id]=tuple(size)
    def _target(self,device_id):
        if device_id not in self.TARGETS:
            from .devices.registry import device_definition
            self.TARGETS[device_id]=device_definition(device_id).encoded_size
        return self.TARGETS[device_id]
    def _encode(self,prepared,device_id):
        from .encoder import encode_5302,encode_5408,encode_reference,image_to_rgb565
        if device_id=="0416:5408":return encode_5408(prepared.jpeg)
        if device_id=="0416:5302":return encode_5302(prepared.jpeg)
        from .reference_runtime import reference_model
        model=reference_model(device_id)
        if device_id.startswith("community-ref:"):
            from .devices.community_panels import encode_community
            if model.pixel_format=="jpeg":return encode_community(model,jpeg=prepared.jpeg)
            from .devices.beadapanel_protocol import encode_rgb565
            return encode_community(model,pixels=encode_rgb565(prepared.canvas,model.render_size,order="BGR"))
        if model.pixel_format=="jpeg":return encode_reference(model,jpeg=prepared.jpeg)
        order="big" if model.pixel_format.endswith("be") else "little"
        return encode_reference(model,rgb565=image_to_rgb565(prepared.canvas,order))
    def _final_buffer(self,vid_pid):
        tw,th=self._target(vid_pid);buffer=self._final_buffers.get(vid_pid)
        if buffer is None or buffer.shape!=(th,tw,3):
            buffer=np.empty((th,tw,3),dtype=np.uint8);self._final_buffers[vid_pid]=buffer
        return buffer
    def prepare_static(self,path:Path,vid_pid:str,mode:FitMode=FitMode.FIT,rotation:int=0,quality:int=95,pan_x:int=0,pan_y:int=0,zoom:float=1.0,brightness:int=100):
        path=Path(path);stat=path.stat();key=(str(path.resolve()),stat.st_mtime_ns,stat.st_size,vid_pid,mode.value,rotation%360,quality,int(pan_x),int(pan_y),round(float(zoom),3),int(brightness))
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key);self.cache_metrics["source_hits"]+=1;self.cache_metrics["composition_skips"]+=1;self.cache_metrics["jpeg_skips"]+=1;return self._cache[key]
            self.cache_metrics["source_misses"]+=1
        prepared=render_static(path,self._target(vid_pid),mode,rotation,quality,pan_x,pan_y,zoom,brightness)
        encoded=self._encode(prepared,vid_pid)
        preview=prepared.canvas.copy();preview.thumbnail((720,240));prepared.canvas.close()
        value=(PreparedImage(preview,b"",prepared.source,prepared.mode,prepared.rotation),encoded)
        with self._lock:
            self._cache[key]=value;self._cache.move_to_end(key)
            while len(self._cache)>self.max_static_entries:
                _,old=self._cache.popitem(last=False);old[0].canvas.close()
        return value
    def prepare_image(self,image:Image.Image,vid_pid:str,mode:FitMode=FitMode.FIT,rotation:int=0,quality:int=95,pan_x:int=0,pan_y:int=0,zoom:float=1.0,brightness:int=100,overlay:Image.Image|None=None):
        """Prepare one decoded animation/video frame without retaining it."""
        prepared=render_image(image,self._target(vid_pid),mode,rotation,quality,None,pan_x,pan_y,zoom,brightness,overlay)
        encoded=self._encode(prepared,vid_pid)
        self.total_prepares+=1
        return prepared,encoded
    def prepare_bgr(self,bgr,vid_pid:str,mode:FitMode=FitMode.FIT,rotation:int=0,quality:int=88,
                    pan_x:int=0,pan_y:int=0,zoom:float=1.0,generate_preview:bool=True,brightness:int=100,overlay_rgba=None):
        """Fast native video path: early scale, turbo-JPEG, one small preview."""
        import cv2
        if not _opencv_configured:configure_opencv_threads()
        from .encoder import encode_5302,encode_5408,encode_reference,image_to_rgb565
        total_started=time.perf_counter();frame=bgr
        turns=(rotation%360)//90
        if turns==1:frame=cv2.rotate(frame,cv2.ROTATE_90_CLOCKWISE)
        elif turns==2:frame=cv2.rotate(frame,cv2.ROTATE_180)
        elif turns==3:frame=cv2.rotate(frame,cv2.ROTATE_90_COUNTERCLOCKWISE)
        zoom=max(1.0,min(8.0,float(zoom)))
        if zoom>1 or pan_x or pan_y:
            h,w=frame.shape[:2];cw=max(1,int(w/zoom));ch=max(1,int(h/zoom));cx=w//2+int(pan_x);cy=h//2+int(pan_y)
            x=max(0,min(w-cw,cx-cw//2));y=max(0,min(h-ch,cy-ch//2));frame=frame[y:y+ch,x:x+cw]
        tw,th=self._target(vid_pid);h,w=frame.shape[:2]
        if mode==FitMode.STRETCH:out=cv2.resize(frame,(tw,th),interpolation=cv2.INTER_AREA)
        elif mode in (FitMode.FILL,FitMode.CROP):
            scale=max(tw/w,th/h);nw,nh=max(1,round(w*scale)),max(1,round(h*scale));work=frame if (nw,nh)==(w,h) else cv2.resize(frame,(nw,nh),interpolation=cv2.INTER_AREA);x=(nw-tw)//2;y=(nh-th)//2;out=work[y:y+th,x:x+tw]
        else:
            scale=min(1.0 if mode==FitMode.CENTER else float("inf"),tw/w,th/h);nw,nh=max(1,round(w*scale)),max(1,round(h*scale));work=frame if (nw,nh)==(w,h) else cv2.resize(frame,(nw,nh),interpolation=cv2.INTER_AREA)
            # Fit/Center previously allocated and zeroed a new full LCD canvas
            # for every frame. Each MediaPipeline has one consumer, so this
            # device-sized buffer is safe to reuse after synchronous JPEG and
            # preview creation complete.
            out=self._final_buffer(vid_pid);out.fill(0);left=(tw-nw)//2;top=(th-nh)//2;out[top:top+nh,left:left+nw]=work
        brightness=max(0,min(100,int(brightness)))
        if brightness!=100:out=cv2.multiply(out,brightness/100)
        if overlay_rgba is not None:
            if isinstance(overlay_rgba,CachedOverlay):
                # `out` is owned by this pipeline for Fit/Center and may be
                # blended in place, eliminating two full-frame temporaries.
                if mode in (FitMode.FIT,FitMode.CENTER):
                    cv2.multiply(out,overlay_rgba.inverse_alpha,dst=out,scale=1/255,dtype=cv2.CV_8U);cv2.add(out,overlay_rgba.premultiplied_bgr,dst=out)
                else:out=cv2.add(cv2.multiply(out,overlay_rgba.inverse_alpha,scale=1/255,dtype=cv2.CV_8U),overlay_rgba.premultiplied_bgr)
            else:
                layer=overlay_rgba
                if isinstance(layer,Image.Image):layer=np.asarray(layer.convert("RGBA"))
                if layer.shape[1]!=tw or layer.shape[0]!=th:layer=cv2.resize(layer,(tw,th),interpolation=cv2.INTER_LINEAR)
                alpha=np.repeat(layer[:,:,3:4],3,axis=2);overlay_bgr=np.ascontiguousarray(layer[:,:,:3][:,:,::-1])
                out=cv2.add(cv2.multiply(out,255-alpha,scale=1/255,dtype=cv2.CV_8U),cv2.multiply(overlay_bgr,alpha,scale=1/255,dtype=cv2.CV_8U))
        transform_ms=(time.perf_counter()-total_started)*1000
        def encode_options(selected_quality):
            result=[cv2.IMWRITE_JPEG_QUALITY,int(selected_quality),cv2.IMWRITE_JPEG_PROGRESSIVE,0,cv2.IMWRITE_JPEG_OPTIMIZE,0]
            if hasattr(cv2,"IMWRITE_JPEG_SAMPLING_FACTOR"):result += [cv2.IMWRITE_JPEG_SAMPLING_FACTOR,cv2.IMWRITE_JPEG_SAMPLING_FACTOR_420]
            return result
        encode_started=time.perf_counter();ok,jpeg=cv2.imencode(".jpg",out,encode_options(quality));chosen_quality=int(quality);corrective=0
        if not ok:raise ValueError("OpenCV JPEG encoding failed")
        jpeg_bytes=None
        if vid_pid=="0416:5302" and int(quality)==45 and self.pid5302_report_correction and self.pid5302_quality.should_correct(len(jpeg)):
            ok2,jpeg2=cv2.imencode(".jpg",out,encode_options(44));corrective=1
            if not ok2:raise ValueError("OpenCV corrective JPEG encoding failed")
            primary_bytes=jpeg.tobytes();corrected_bytes=jpeg2.tobytes();jpeg_bytes,chosen_quality=self.pid5302_quality.choose(primary_bytes,corrected_bytes)
        encode_ms=(time.perf_counter()-encode_started)*1000
        if jpeg_bytes is None:jpeg_bytes=jpeg.tobytes()
        framing_started=time.perf_counter()
        if vid_pid=="0416:5408":encoded=encode_5408(jpeg_bytes)
        elif vid_pid=="0416:5302":encoded=encode_5302(jpeg_bytes)
        else:
            from .reference_runtime import reference_model
            model=reference_model(vid_pid)
            if vid_pid.startswith("community-ref:"):
                from .devices.community_panels import encode_community
                if model.pixel_format=="jpeg":encoded=encode_community(model,jpeg=jpeg_bytes)
                else:
                    from .devices.beadapanel_protocol import encode_rgb565
                    pil=Image.fromarray(cv2.cvtColor(out,cv2.COLOR_BGR2RGB));encoded=encode_community(model,pixels=encode_rgb565(pil,model.render_size,order="BGR"));pil.close()
            elif model.pixel_format=="jpeg":encoded=encode_reference(model,jpeg=jpeg_bytes)
            else:
                pil=Image.fromarray(cv2.cvtColor(out,cv2.COLOR_BGR2RGB));encoded=encode_reference(model,rgb565=image_to_rgb565(pil,"big" if model.pixel_format.endswith("be") else "little"));pil.close()
        framing_ms=(time.perf_counter()-framing_started)*1000
        canvas=None
        if generate_preview:
            scale=min(720/tw,240/th,1);preview=cv2.resize(out,(max(1,int(tw*scale)),max(1,int(th*scale))),interpolation=cv2.INTER_AREA)
            canvas=Image.fromarray(cv2.cvtColor(preview,cv2.COLOR_BGR2RGB))
        self.last_metrics={"timestamp":time.perf_counter(),"transform_ms":transform_ms,"jpeg_encode_ms":encode_ms,"framing_ms":framing_ms,"total_prepare_ms":(time.perf_counter()-total_started)*1000,"jpeg_bytes":len(jpeg_bytes),"protocol_bytes":encoded.total_bytes,"quality":chosen_quality,"corrective_encode":corrective,"reused_final_buffer":mode in (FitMode.FIT,FitMode.CENTER),"avoided_full_frame_temporaries":3 if overlay_rgba is not None and isinstance(overlay_rgba,CachedOverlay) and mode in (FitMode.FIT,FitMode.CENTER) else 1 if mode in (FitMode.FIT,FitMode.CENTER) else 0};self.metrics_history.append(self.last_metrics.copy());self.total_prepares+=1;return PreparedImage(canvas,b"",None,mode,rotation%360),encoded
    @property
    def cache_entries(self):
        with self._lock:return len(self._cache)
    def clear(self):
        with self._lock:
            for prepared,_ in self._cache.values():prepared.canvas.close()
            self._cache.clear();self._final_buffers.clear()
