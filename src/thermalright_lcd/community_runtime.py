"""Physical discovery and runtime bindings for supported community panels."""
from __future__ import annotations
from dataclasses import replace

from .device_discovery import DiscoveredDisplay
from .devices.community_panels import (CommunityConnection, MODELS, jl_command,
    lianli_packet,
    parse_beada_info, parse_jl_device_info, parse_jonsbo_identity,
    thermaltake_command)
from .devices.beadapanel_protocol import panel_link_start_tag
from .live_state import SafetyError, TransportError
from .reference_runtime import install_reference_binding
from .windows_serial import PySerialIo, enumerate_serial_candidates


class _HidIo:
    def __init__(self,path,api,initializer):self.path=path;self.api=api;self.initializer=initializer;self.handle=None
    def open(self):
        if self.handle is not None:return
        self.handle=self.api.open(self.path)
        try:self.initializer(self)
        except Exception:self.close();raise
    def write(self,data):
        count=self.api.write_report(self.handle,data,5000)
        if count!=len(data):raise TransportError(f"short HID write {count}/{len(data)}")
        return count
    def read(self,length=1025):return self.api.read_report(self.handle,length,2000)
    def close(self):
        handle,self.handle=self.handle,None
        if handle is not None:self.api.close(handle)


class _WinUsbIo:
    def __init__(self,path,api,out_endpoint,in_endpoint,initializer):
        self.path=path;self.api=api;self.out=out_endpoint;self.input=in_endpoint;self.initializer=initializer;self.file=None;self.usb=None
    def open(self):
        if self.usb is not None:return
        self.file=self.api.create_file(self.path,3000);self.usb=self.api.winusb_initialize(self.file)
        try:
            for ep in (self.out,self.input):self.api.query_pipe(self.usb,0,ep);self.api.set_timeout(self.usb,ep,3000)
            self.initializer(self)
        except Exception:self.close();raise
    def write(self,data):
        count=self.api.write_pipe(self.usb,self.out,data)
        if count!=len(data):raise TransportError(f"short WinUSB write {count}/{len(data)}")
        return count
    def read(self,length):return self.api.read_pipe(self.usb,self.input,length)
    def close(self):
        usb,file_handle=self.usb,self.file;self.usb=self.file=None
        if usb:self.api.free(usb)
        if file_handle:self.api.close_handle(file_handle)

class _ProbedSerialIo(PySerialIo):
    def __init__(self,*args,probe,**kwargs):super().__init__(*args,**kwargs);self.probe=probe
    def open(self):
        was_open=self.handle is not None;super().open()
        if not was_open:
            try:self.probe(self)
            except Exception:self.close();raise


def _response_ok(data:bytes)->bool:
    return b"200" in bytes(byte for byte in data if byte in (10,13) or 32<=byte<=126)

def _thermaltake_init(io):
    io.write(thermaltake_command("POST conn 1",100,timestamp_ms=0))
    if not _response_ok(io.read()):raise SafetyError("Thermaltake conn probe did not return 200")
    io.write(thermaltake_command("POST realtimeDisplay 1",101,body='{"enable":true}',content_type="json",timestamp_ms=0))
    if not _response_ok(io.read()):raise SafetyError("Thermaltake realtimeDisplay probe did not return 200")

def _beada_init(io):
    query=bytearray(20);query[:11]=b"STATUS-LINK";query[11]=1;query[12]=1
    from .devices.beadapanel_protocol import ones_complement_checksum
    query[16:18]=(20).to_bytes(2,"little");query[18:20]=ones_complement_checksum(query[:18]).to_bytes(2,"little")
    io.write(bytes(query));response=io.read(100);model=parse_beada_info(response)
    io.write(panel_link_start_tag(*model.render_size,protocol_version=response[22]))
    io.detected_model=model

def _lianli_init(io):
    io.write(lianli_packet(10))
    response=io.read(512)
    if len(response)!=512:raise SafetyError("Lian Li version probe did not return a 512-byte response")
    io.write(lianli_packet(123))
    if len(io.read(512))!=512:raise SafetyError("Lian Li stop-media probe was not acknowledged")

def _serial_read_frame(io):
    raw=io.read_until_quiet()
    start=raw.find(b"\x55\xaa")
    if start<0 or len(raw)<start+7:raise SafetyError("JL device-info response missing frame")
    length=int.from_bytes(raw[start+2:start+4],"little")
    if length<7 or start+length>len(raw):raise SafetyError("truncated JL response")
    frame=raw[start:start+length]
    if (sum(frame[:-2])&0xffff)!=int.from_bytes(frame[-2:],"little"):raise SafetyError("invalid JL response checksum")
    return frame[5:-2]

def _probe_serial(candidate, serial_factory=None):
    if candidate.vid_pid=="33c3:f101":
        io=PySerialIo(candidate.port,9600,serial_factory=serial_factory);io.open()
        try:io.write(b"\xf0\xa5\x5a\x0f");_,size,_=parse_jonsbo_identity(io.read_until_quiet())
        except Exception:io.close();raise
        model=replace(MODELS["jonsbo-ds916"],native_size=size,render_size=size)
        def validate_jonsbo(runtime_io):
            runtime_io.write(b"\xf0\xa5\x5a\x0f");_,runtime_size,_=parse_jonsbo_identity(runtime_io.read_until_quiet())
            if runtime_size!=model.render_size:raise SafetyError("Jonsbo identity changed during reconnect")
        return model,lambda:CommunityConnection(model,_ProbedSerialIo(candidate.port,9600,serial_factory=serial_factory,probe=validate_jonsbo))
    io=PySerialIo(candidate.port,2_000_000,open_delay=.2,serial_factory=serial_factory);io.open()
    try:
        io.write(b"\xff\xd9\xff\xd9\0\0\0\0");io.write(jl_command(0x06));name,size,angle=parse_jl_device_info(_serial_read_frame(io))
    except Exception:io.close();raise
    io.close();model=replace(MODELS["jl"],name=name,native_size=size,render_size=size,orientation=f"rotation-{angle}")
    def validate_jl(runtime_io):
        runtime_io.write(b"\xff\xd9\xff\xd9\0\0\0\0");runtime_io.write(jl_command(0x06));_,runtime_size,_=parse_jl_device_info(_serial_read_frame(runtime_io))
        if runtime_size!=model.render_size:raise SafetyError("JL identity changed during reconnect")
    return model,lambda:CommunityConnection(model,_ProbedSerialIo(candidate.port,2_000_000,open_delay=.2,serial_factory=serial_factory,probe=validate_jl),close_command=jl_command(0x21))

def enumerate_community_winusb_candidates(path_enumerator=None):
    from .windows_usb import enumerate_registered_winusb_paths
    pairs=("4e58:1001","4e58:1002","1cbe:a088","1cbe:a092","1cbe:a068","1cbe:a034")
    items=(path_enumerator or enumerate_registered_winusb_paths)(pairs)
    return tuple((path.lower(),vid_pid,path) for vid_pid,path in items)

def discover_community_displays(*, serial_candidates=None, hid_paths=None, hid_inspector=None, hid_api=None, winusb_candidates=None, winusb_api=None, serial_factory=None):
    results=[]
    serial_candidates=enumerate_serial_candidates() if serial_candidates is None else tuple(serial_candidates)
    for candidate in serial_candidates:
        try:model,factory=_probe_serial(candidate,serial_factory);binding=install_reference_binding(candidate.instance_id,model,factory,namespace="community-ref");results.append(DiscoveredDisplay(candidate.instance_id,binding.device_id,"connected",model.name))
        except Exception as exc:results.append(DiscoveredDisplay(candidate.instance_id,f"unsupported:{candidate.vid_pid}","blocked",str(exc)))
    from .windows_hid import CtypesWindowsHidApi,enumerate_paths,inspect_path
    paths=enumerate_paths() if hid_paths is None else tuple(hid_paths);inspector=hid_inspector or inspect_path;api=hid_api or CtypesWindowsHidApi()
    for path in paths:
        try:info=inspector(path);vid_pid=f"{info.vid:04x}:{info.pid:04x}"
        except Exception:continue
        key={"264a:2347":"thermaltake-6","26ce:0a10":"asrock-pg360"}.get(vid_pid)
        if not key:continue
        stable=path.lower();model=MODELS[key]
        try:
            if info.output_report_bytes < 1025 or info.input_report_bytes < 1025:raise SafetyError("HID report geometry is incompatible with the panel protocol")
            probe=_HidIo(path,api,_thermaltake_init);probe.open();probe.close()
            factory=lambda p=path,m=model:CommunityConnection(m,_HidIo(p,api,_thermaltake_init),close_command=thermaltake_command("POST realtimeDisplay 1",999,body='{"enable":false}',content_type="json",timestamp_ms=0))
            binding=install_reference_binding(stable,model,factory,namespace="community-ref");results.append(DiscoveredDisplay(stable,binding.device_id,"connected",model.name))
        except Exception as exc:results.append(DiscoveredDisplay(stable,f"unsupported:{vid_pid}","blocked",str(exc)))
    candidates=enumerate_community_winusb_candidates() if winusb_candidates is None else tuple(winusb_candidates)
    if candidates:
        from .windows_usb import CtypesWinUsbApi
        api_factory=(lambda:winusb_api) if winusb_api is not None else CtypesWinUsbApi
        for stable,vid_pid,path in candidates:
            try:
                probe_api=api_factory()
                if vid_pid.startswith("4e58:"):
                    probe=_WinUsbIo(path,probe_api,0x02,0x82,_beada_init);probe.open();model=probe.detected_model;probe.close()
                    factory=lambda p=path,m=model:CommunityConnection(m,_WinUsbIo(p,api_factory(),0x02,0x82,_beada_init))
                else:
                    key={"1cbe:a088":"lianli-88","1cbe:a092":"lianli-92","1cbe:a068":"lianli-oled","1cbe:a034":"lianli-lcd"}[vid_pid];model=MODELS[key]
                    probe=_WinUsbIo(path,probe_api,0x01,0x81,_lianli_init);probe.open();probe.close()
                    factory=lambda p=path,m=model:CommunityConnection(m,_WinUsbIo(p,api_factory(),0x01,0x81,_lianli_init),close_command=lianli_packet(123))
                binding=install_reference_binding(stable,model,factory,namespace="community-ref");results.append(DiscoveredDisplay(stable,binding.device_id,"connected",model.name))
            except Exception as exc:results.append(DiscoveredDisplay(stable,f"unsupported:{vid_pid}","blocked",str(exc)))
    return tuple(results)
