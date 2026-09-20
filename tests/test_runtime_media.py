import itertools,statistics,tempfile,time,unittest
from pathlib import Path
from PIL import Image
from thermalright_lcd.media import cache_overlay,render_static,FitMode,MediaPipeline,Pid5302ReportQualityController
from thermalright_lcd.runtime import DisplaySession,DisplayManager,LatestFrameQueue,SessionState
from thermalright_lcd.persistence import PersistencePolicy5302,PersistencePolicy5408,bounded_test_plan,bounded_generated_plan,video_transport_target
from thermalright_lcd.output_rate import OutputRateKind,resolve_output_rate

class RuntimeMediaTests(unittest.TestCase):
    def test_fit_reuses_final_buffer_and_matches_previous_pixels(self):
        import cv2,numpy as np
        from PIL import Image,ImageDraw
        from thermalright_lcd.encoder import jpeg_payload
        source=np.arange(480*853*3,dtype=np.uint8).reshape((480,853,3))
        layer=Image.new("RGBA",(1280,480),(0,0,0,0));draw=ImageDraw.Draw(layer);draw.rectangle((20,30,500,180),fill=(20,180,240,173));overlay=cache_overlay(layer,(1280,480));layer.close()
        bordered=cv2.copyMakeBorder(source,0,0,(1280-853)//2,1280-853-(1280-853)//2,cv2.BORDER_CONSTANT,value=(0,0,0))
        reference=cv2.add(cv2.multiply(bordered,overlay.inverse_alpha,scale=1/255,dtype=cv2.CV_8U),overlay.premultiplied_bgr)
        options=[cv2.IMWRITE_JPEG_QUALITY,75,cv2.IMWRITE_JPEG_PROGRESSIVE,0,cv2.IMWRITE_JPEG_OPTIMIZE,0]
        if hasattr(cv2,"IMWRITE_JPEG_SAMPLING_FACTOR"):options += [cv2.IMWRITE_JPEG_SAMPLING_FACTOR,cv2.IMWRITE_JPEG_SAMPLING_FACTOR_420]
        ok,jpeg=cv2.imencode(".jpg",reference,options);self.assertTrue(ok)
        pipe=MediaPipeline();_,encoded=pipe.prepare_bgr(source,"0416:5302",FitMode.FIT,quality=75,generate_preview=False,overlay_rgba=overlay);first=pipe._final_buffers["0416:5302"]
        self.assertEqual(jpeg_payload(encoded),jpeg.tobytes());self.assertTrue(pipe.last_metrics["reused_final_buffer"]);self.assertEqual(pipe.last_metrics["avoided_full_frame_temporaries"],3)
        pipe.prepare_bgr(source,"0416:5302",FitMode.FIT,quality=75,generate_preview=False,overlay_rgba=overlay);self.assertIs(pipe._final_buffers["0416:5302"],first)
        pipe.clear();self.assertFalse(pipe._final_buffers);overlay.image.close()
    def test_opt_in_trace_records_idle_commit_and_shutdown_without_changing_send(self):
        events=[];sent=[];policy=PersistencePolicy5408();object.__setattr__(policy,"keepalive_interval_seconds",.025)
        session=DisplaySession("trace",lambda frame:(sent.append(frame) or len(frame)),refresh_interval=None,policy=policy,trace_hook=lambda event,**fields:events.append((event,fields)))
        session.set_media(b"frame",immediate=True);session.play();time.sleep(.075);session.stop()
        names=[event for event,_ in events]
        self.assertIn("content_queued",names);self.assertIn("transport_start",names);self.assertIn("transport_complete",names)
        self.assertIn("cached_commit_due",names);self.assertIn("stop_complete",names);self.assertGreaterEqual(len(sent),2)

    def test_trace_hook_failure_never_changes_runtime_behavior(self):
        sent=[];session=DisplaySession("trace-failure",lambda frame:(sent.append(frame) or len(frame)),trace_hook=lambda *_args,**_fields:(_ for _ in ()).throw(RuntimeError("observer failed")))
        session.set_media(b"frame");session.play();time.sleep(.03);session.stop();self.assertEqual(sent,[b"frame"])

    def test_fractional_output_rates_are_not_truncated(self):
        tenth=resolve_output_rate("0.1","0416:5408",animated=False);self.assertEqual(tenth.kind,OutputRateKind.FIXED);self.assertEqual(tenth.fps,.1);self.assertEqual(tenth.interval_seconds,10.0)
        self.assertEqual(resolve_output_rate("0.2","0416:5302",animated=False).interval_seconds,10.0)
        self.assertEqual(resolve_output_rate("0.5","0416:5302",animated=False).interval_seconds,2.0)
        self.assertIsNone(resolve_output_rate("Event-driven","0416:5302",animated=False).interval_seconds)
    def test_automatic_static_and_video_preserve_distinct_proven_targets(self):
        static=resolve_output_rate("Automatic","0416:5408",animated=False)
        video=resolve_output_rate("Automatic","0416:5408",animated=True,quality_profile="Balanced")
        self.assertEqual(static.fps,PersistencePolicy5408().requested_fps);self.assertEqual(video.fps,video_transport_target("0416:5408"))
    def test_event_driven_session_sends_only_changed_or_explicit_frames(self):
        sent=[];session=DisplaySession("event",lambda x:(sent.append(x) or len(x)),refresh_interval=None);frame=b"x"
        session.set_media(frame);session.play();time.sleep(.04);session.set_media(frame);time.sleep(.04)
        self.assertEqual(len(sent),1);self.assertGreaterEqual(session.metrics.usb_send_skips,1)
        session.refresh_now();time.sleep(.04);session.stop();self.assertEqual(len(sent),2)
    def test_event_driven_held_frame_uses_cached_transport_keepalive_only(self):
        sent=[];policy=PersistencePolicy5302();object.__setattr__(policy,"keepalive_interval_seconds",.03)
        session=DisplaySession("event-keepalive",lambda x:(sent.append(x) or len(x)),refresh_interval=None,policy=policy);frame=b"encoded"
        session.set_media(frame,immediate=True);session.play();time.sleep(.11);session.stop()
        self.assertEqual(session.metrics.content_sends,1);self.assertGreaterEqual(session.metrics.keepalive_sends,2)
        self.assertEqual(session.metrics.held_frame_generation,1);self.assertTrue(all(x is frame for x in sent))
    def test_physical_commit_floor_is_separate_and_proven_half_fps(self):
        self.assertEqual(PersistencePolicy5408().keepalive_interval_seconds,2.0)
        self.assertEqual(PersistencePolicy5302().keepalive_interval_seconds,2.0)
        self.assertTrue(PersistencePolicy5408().requires_continuous_frames)
        self.assertTrue(PersistencePolicy5302().requires_continuous_frames)
    def test_low_rate_wait_never_clears_held_frame_and_change_is_interruptible(self):
        sent=[];policy=PersistencePolicy5408();object.__setattr__(policy,"keepalive_interval_seconds",.03)
        session=DisplaySession("low",lambda x:(sent.append((x,time.monotonic())) or len(x)),refresh_interval=10,policy=policy)
        session.set_media(b"old",immediate=True);session.play();time.sleep(.04);changed=time.monotonic();session.set_media(b"new",immediate=True);time.sleep(.04);session.stop()
        self.assertIn(b"new",[x[0] for x in sent]);self.assertLess(next(t for x,t in sent if x==b"new")-changed,.05)
    def test_refresh_interval_change_resets_old_deadline(self):
        sent=[];session=DisplaySession("change",lambda x:(sent.append(time.monotonic()) or len(x)),refresh_interval=10.0)
        session.set_media(b"x");session.play();time.sleep(.04);session.set_refresh_interval(None);session.set_media(b"y");time.sleep(.04);session.stop()
        self.assertEqual(len(sent),2);self.assertLess(sent[1]-sent[0],.08)
    def test_fractional_absolute_deadline_and_interruptible_long_wait(self):
        sent=[];session=DisplaySession("fractional",lambda x:(sent.append(time.monotonic()) or 1),refresh_interval=.1)
        session.set_media(b"x");session.play();time.sleep(.36);started=time.monotonic();session.stop();self.assertLess(time.monotonic()-started,.08)
        self.assertGreaterEqual(len(sent),4);intervals=[b-a for a,b in zip(sent,sent[1:])];self.assertAlmostEqual(statistics.mean(intervals),.1,delta=.025)
    def test_pid5302_report_quality_controller_is_bounded_and_boundary_aware(self):
        controller=Pid5302ReportQualityController();self.assertTrue(controller.should_correct(800));primary=b'x'*800;smaller=b'x'*490;chosen,quality=controller.choose(primary,smaller);self.assertEqual((len(chosen),quality),(490,44));self.assertEqual((controller.corrective_encodes,controller.corrections_used),(1,1))
        chosen,quality=controller.choose(primary,b'x'*790);self.assertEqual(quality,45);self.assertEqual(controller.corrective_encodes,2)
    def test_pid5302_report_correction_can_be_disabled_for_ab_measurement(self):
        self.assertTrue(MediaPipeline().pid5302_report_correction)
        self.assertFalse(MediaPipeline(pid5302_report_correction=False).pid5302_report_correction)
    def test_cached_overlay_is_reusable_and_bounded(self):
        overlay=Image.new("RGBA",(1280,480),(255,0,0,128));cached=cache_overlay(overlay,(1280,480));self.assertEqual(cached.image.size,(1280,480));self.assertFalse(cached.premultiplied_bgr.flags.writeable);self.assertFalse(cached.inverse_alpha.flags.writeable)
        import numpy as np
        frame=np.zeros((480,1280,3),dtype=np.uint8);pipe=MediaPipeline();prepared,encoded=pipe.prepare_bgr(frame,"0416:5302",overlay_rgba=cached,generate_preview=True);self.assertGreater(encoded.total_bytes,0);self.assertGreater(prepared.canvas.getpixel((10,10))[0],100);prepared.canvas.close();cached.image.close()
    def test_resize_modes_dimensions(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"x.png";Image.new("RGB",(100,300),"red").save(p)
            for mode in FitMode:self.assertEqual(render_static(p,(1280,480),mode,90).canvas.size,(1280,480))
    def test_latest_queue_is_bounded(self):
        q=LatestFrameQueue();q.put(1);q.put(2);q.put(3);self.assertEqual((len(q),q.take(),q.dropped),(1,3,2))
    def test_dual_sessions_are_independent(self):
        a=[];b=[];sa=DisplaySession("a",lambda x:(a.append(x)or len(x)));sb=DisplaySession("b",lambda x:(b.append(x)or len(x)))
        m=DisplayManager({"a":sa,"b":sb});m.start_all();sa.submit(b"A");sb.submit(b"B");time.sleep(.05);m.stop_all()
        self.assertEqual((a,b),([b"A"],[b"B"]))
    def test_failure_does_not_stop_other(self):
        good=[];bad=DisplaySession("bad",lambda x:(_ for _ in()).throw(IOError("x")));ok=DisplaySession("ok",lambda x:(good.append(x)or 1))
        bad.start();ok.start();bad.submit(b"x");ok.submit(b"y");time.sleep(.05);self.assertEqual(bad.state,SessionState.ERROR);self.assertTrue(good);ok.stop()
    def test_static_protocol_cache_is_bounded(self):
        with tempfile.TemporaryDirectory() as d:
            pipe=MediaPipeline(1);a=Path(d)/"a.png";b=Path(d)/"b.png";Image.new("RGB",(10,10),"red").save(a);Image.new("RGB",(10,10),"blue").save(b)
            first=pipe.prepare_static(a,"0416:5302");again=pipe.prepare_static(a,"0416:5302")
            self.assertIs(first,again);self.assertEqual(first[1].dimensions,(1280,480));pipe.prepare_static(b,"0416:5302");self.assertEqual(pipe.cache_entries,1)
            self.assertEqual(pipe.cache_metrics["source_hits"],1);self.assertEqual(pipe.cache_metrics["jpeg_skips"],1)
    def test_software_brightness_changes_luminance_and_cache_identity(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"white.png";Image.new("RGB",(32,16),"white").save(p);pipe=MediaPipeline(2)
            full=pipe.prepare_static(p,"0416:5302",brightness=100)
            dim=pipe.prepare_static(p,"0416:5302",brightness=25)
            self.assertGreater(full[0].canvas.resize((1,1)).getpixel((0,0))[0],dim[0].canvas.resize((1,1)).getpixel((0,0))[0])
            self.assertIs(dim,pipe.prepare_static(p,"0416:5302",brightness=25))
            self.assertIsNot(full,dim)
    def test_static_repeated_frame_persistence_and_pause(self):
        sent=[]
        session=DisplaySession("5302",lambda x:(sent.append((x,time.monotonic())) or len(x)),refresh_interval=.015)
        session.set_media(b"cached");session.play();time.sleep(.085);session.pause();at_pause=len(sent);time.sleep(.04)
        self.assertGreaterEqual(at_pause,3);self.assertEqual(len(sent),at_pause);self.assertTrue(all(x[0] is sent[0][0] for x in sent));session.stop()
    def test_absolute_deadline_does_not_add_full_period_after_blocking_send(self):
        def blocking_send(frame):time.sleep(.015);return len(frame)
        session=DisplaySession("absolute",blocking_send,refresh_interval=1/60);session.set_media(b"frame");session.play();time.sleep(.38);session.stop()
        intervals=[x["complete_interval_ms"] for x in session.frame_timings if x["complete_interval_ms"]]
        self.assertGreaterEqual(len(intervals),15)
        self.assertLess(statistics.median(intervals),20.0)
        self.assertGreater(session.metrics.actual_fps,50.0)
        self.assertLess(session.metrics.hidden_wait_ms,8.0)
        self.assertTrue(all("target_deadline" in x and "physical_completion" in x for x in session.frame_timings))
    def test_late_mixed_hid_transfers_do_not_inject_residual_gui_wait(self):
        durations=itertools.cycle((.016,.024))
        def hid_like_send(frame):time.sleep(next(durations));return len(frame)
        session=DisplaySession("5302-gui",hid_like_send,refresh_interval=1/60)
        session.set_media(b"frame");session.play();time.sleep(.62);session.stop()
        intervals=[x["complete_interval_ms"] for x in session.frame_timings if x["complete_interval_ms"]]
        # A future-skipping late-deadline policy falls to roughly 30-36 FPS.
        # The benchmark-compatible policy immediately consumes the latest slot
        # and is bounded by the alternating transfer duration itself (~50 FPS).
        self.assertGreater(session.metrics.actual_fps,46.0)
        self.assertLess(statistics.mean(intervals),22.0)
        self.assertGreater(session.metrics.scheduler_overruns,0)
        self.assertLess(statistics.median(x["hidden_wait_ms"] for x in session.frame_timings),2.0)
    def test_independent_persistence_policies_and_hard_budgets(self):
        a,b=PersistencePolicy5408(),PersistencePolicy5302();self.assertNotEqual(a.interval_seconds,b.interval_seconds)
        plan=bounded_test_plan("0416:5302",30);self.assertTrue(plan["offline_only"]);self.assertFalse(plan["live_authorized"])
        self.assertEqual((plan["frame_count_hard_max"],plan["writes_hard_max"],plan["bytes_hard_max"]),(350,117251,60032512))
        plan5408=bounded_test_plan("0416:5408",30);self.assertEqual((plan5408["frame_count_hard_max"],plan5408["writes_hard_max"],plan5408["bytes_hard_max"],plan5408["expected_ack_count"]),(180,8101,32811008,180))
        generated=bounded_generated_plan("0416:5408",30,120832,"generated",30)
        self.assertEqual((generated["writes_hard_max"],generated["bytes_hard_max"]),(5401,21751808))
    def test_measured_video_auto_targets_are_quality_and_device_specific(self):
        self.assertEqual(video_transport_target("0416:5408","Performance"),45.0)
        self.assertEqual(video_transport_target("0416:5302","Quality"),20.0)
        self.assertEqual(video_transport_target("0416:5302","Balanced"),30.0)
        self.assertEqual(video_transport_target("0416:5302","Performance"),43.0)
        self.assertEqual(video_transport_target("0416:5302","Extreme FPS"),54.0)
