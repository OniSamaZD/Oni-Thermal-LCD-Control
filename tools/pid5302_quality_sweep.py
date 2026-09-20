from __future__ import annotations
import argparse,json,statistics
from pathlib import Path
import cv2,numpy as np
from thermalright_lcd.hardware_monitor import MonitorRenderer,templates
from thermalright_lcd.media import MediaPipeline,cache_overlay
from thermalright_lcd.playback import PyAvVideoSource

def ssim(a,b):
    a=a.astype(np.float32);b=b.astype(np.float32);c1=6.5025;c2=58.5225
    ma=cv2.GaussianBlur(a,(11,11),1.5);mb=cv2.GaussianBlur(b,(11,11),1.5);va=cv2.GaussianBlur(a*a,(11,11),1.5)-ma*ma;vb=cv2.GaussianBlur(b*b,(11,11),1.5)-mb*mb;cov=cv2.GaussianBlur(a*b,(11,11),1.5)-ma*mb
    return float(np.mean(((2*ma*mb+c1)*(2*cov+c2))/((ma*ma+mb*mb+c1)*(va+vb+c2))))
def jpeg(encoded):
    stream=b''.join(encoded.writes);return stream[20:20+encoded.jpeg_length]
def main():
    p=argparse.ArgumentParser();p.add_argument('--media',type=Path,required=True);p.add_argument('--frames',type=int,default=30);p.add_argument('--output',type=Path,required=True);a=p.parse_args();source=PyAvVideoSource(a.media,decode_size=(1920,480),thread_count=1);pipeline=MediaPipeline();qualities=(45,44,43,42,41,40,38,36);rows={q:[] for q in qualities}
    layout=templates('0416:5302')['Gaming Dashboard'];renderer=MonitorRenderer(layout)
    for index in range(a.frames):
        frame=source.next_frame();values={'game.fps':120+index%20,'cpu.usage':35+index%40,'cpu.temperature':55+index%8,'gpu.usage':50+index%45,'gpu.temperature':62+index%9};image=renderer.render_overlay(values);overlay=cache_overlay(image,(1280,480));image.close();reference=None
        for q in qualities:
            _,encoded=pipeline.prepare_bgr(frame.native_bgr,'0416:5302',quality=q,generate_preview=False,overlay_rgba=overlay);data=jpeg(encoded);decoded=cv2.imdecode(np.frombuffer(data,np.uint8),cv2.IMREAD_COLOR)
            if reference is None:reference=decoded
            gray_a=cv2.cvtColor(reference,cv2.COLOR_BGR2GRAY);gray_b=cv2.cvtColor(decoded,cv2.COLOR_BGR2GRAY);rows[q].append({'bytes':len(data),'reports':len(encoded.writes),'encode_ms':pipeline.last_metrics['jpeg_encode_ms'],'psnr':cv2.PSNR(reference,decoded),'ssim':ssim(gray_a,gray_b)})
        overlay.image.close()
    source.close();result={'schema':1,'reference_quality':45,'frames':a.frames,'qualities':{str(q):{key:statistics.mean(x[key] for x in rows[q]) for key in rows[q][0]}|{'max_reports':max(x['reports'] for x in rows[q]),'min_reports':min(x['reports'] for x in rows[q])} for q in qualities}};a.output.write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result,indent=2))
if __name__=='__main__':main()
