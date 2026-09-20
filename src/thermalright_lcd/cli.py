from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime
from pathlib import Path

from .analyzer import analyze
from .transactions import write_transactions,write_selected_transaction,extract_jpeg
from .replay import dry_run, dry_run_session
from .session import write_session_report
from .live_state import (DryRunUsbTransport, LiveReplayMachine, PersistentReplayMachine,expected_identity,
                         load_sequence, load_allowlist, preflight, live_preflight,
                         require_live_authorization, RealUsbTransport)
from .encoder import write_encoded, prepare_generated_transaction
from .persistence import POLICIES,bounded_test_plan,bounded_generated_plan
from .dual_live import run_dual_persistence


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="thermalright-lcd")
    sub = parser.add_subparsers(dest="command", required=True)
    a = sub.add_parser("analyze", help="offline analysis of a USBPcap PCAPNG")
    a.add_argument("capture", type=Path)
    a.add_argument("--output", type=Path, default=Path("analysis/display_9_16"))
    a.add_argument("--device", type=int, help="restrict analysis to a transient capture device address")
    sub.add_parser("devices", help="read-only Windows PnP inventory")
    tx = sub.add_parser("transactions", help="isolate captured vendor frame transactions")
    tx.add_argument("capture", type=Path)
    tx.add_argument("--output", type=Path, default=Path("analysis/transactions.json"))
    st=sub.add_parser("select-transaction",help="compact one capture-derived transaction for regression/replay")
    st.add_argument("report",type=Path);st.add_argument("--device",required=True,choices=["0416:5408","0416:5302"])
    st.add_argument("--transaction",type=int,required=True);st.add_argument("--output",type=Path,required=True)
    rp = sub.add_parser("replay", help="offline replay validation (dry-run only)")
    rp.add_argument("transaction_file", type=Path, nargs="?")
    rp.add_argument("--allowlist", type=Path, default=Path("config/device-allowlist.json"))
    rp.add_argument("--device", required=True)
    rp.add_argument("--transaction", type=int, default=1)
    rp.add_argument("--sequence")
    rp.add_argument("--send", action="store_true")
    rp.add_argument("--i-understand-live-usb", action="store_true")
    rp.add_argument("--hold-open-seconds",type=float,default=0.0,help="authorized diagnostic hold after frame; no added writes; max 30")
    rp.add_argument("--session-file", type=Path, default=Path("analysis/session-report.json"))
    pr=sub.add_parser("persistence-replay",help="bounded repeated captured-frame proof; offline unless every live gate passes")
    pr.add_argument("transaction_file",type=Path);pr.add_argument("--session-file",type=Path,default=Path("analysis/session-report.json"))
    pr.add_argument("--allowlist",type=Path,default=Path("config/device-allowlist.json"));pr.add_argument("--inventory",type=Path,default=Path("analysis/device_inventory.json"))
    pr.add_argument("--device",required=True,help="exact stable device ID");pr.add_argument("--sequence",required=True);pr.add_argument("--duration",type=float,default=30.0)
    pr.add_argument("--transaction",type=int,default=1);pr.add_argument("--send",action="store_true");pr.add_argument("--i-understand-live-usb",action="store_true")
    dp=sub.add_parser("dual-persistence-live",help="one guarded simultaneous captured-frame proof for both allowlisted LCDs")
    dp.add_argument("--pid5302-transaction",type=Path,default=Path("analysis/pid5302-same-session-first-frame.json"))
    dp.add_argument("--pid5408-transaction",type=Path,default=Path("analysis/pid5408-new-session-first-frame.json"))
    dp.add_argument("--session-file",type=Path,default=Path("analysis/session-report.json"));dp.add_argument("--allowlist",type=Path,default=Path("config/device-allowlist.json"));dp.add_argument("--inventory",type=Path,default=Path("analysis/device_inventory.json"))
    dp.add_argument("--duration",type=float,default=30.0);dp.add_argument("--send",action="store_true");dp.add_argument("--i-understand-live-usb",action="store_true")
    dg=sub.add_parser("dual-generated-live",help="prepare or run one guarded simultaneous generated-static proof")
    dg.add_argument("--pid5302-transaction",type=Path,default=Path("analysis/pid5302-dual-generated-test.json"))
    dg.add_argument("--pid5408-transaction",type=Path,default=Path("analysis/pid5408-dual-generated-test.json"))
    dg.add_argument("--session-file",type=Path,default=Path("analysis/session-report.json"));dg.add_argument("--allowlist",type=Path,default=Path("config/device-allowlist.json"));dg.add_argument("--inventory",type=Path,default=Path("analysis/device_inventory.json"))
    dg.add_argument("--duration",type=float,default=30.0);dg.add_argument("--send",action="store_true");dg.add_argument("--i-understand-live-usb",action="store_true")
    sr = sub.add_parser("session-report", help="offline ordered USB session lifecycle report")
    sr.add_argument("capture", type=Path)
    sr.add_argument("--device", choices=["0416:5408", "0416:5302"])
    sr.add_argument("--output", type=Path, default=Path("analysis/session-report.json"))
    rs = sub.add_parser("session-replay", help="offline full-session dry-run; never opens USB")
    rs.add_argument("session_file", type=Path)
    rs.add_argument("transaction_file", type=Path)
    rs.add_argument("--allowlist", type=Path, default=Path("config/device-allowlist.json"))
    rs.add_argument("--device", required=True, choices=["0416:5408", "0416:5302"])
    rs.add_argument("--transaction", type=int, default=1)
    sim = sub.add_parser("simulate-live-replay", help="run fail-closed state machine without USB hardware")
    sim.add_argument("session_file", type=Path); sim.add_argument("transaction_file", type=Path)
    sim.add_argument("--allowlist", type=Path, default=Path("config/device-allowlist.json"))
    sim.add_argument("--device", required=True, choices=["0416:5408", "0416:5302"])
    sim.add_argument("--transaction", type=int, default=1)
    vl = sub.add_parser("validate-live-session", help="read-only live preflight; does not open endpoints")
    vl.add_argument("session_file", type=Path); vl.add_argument("transaction_file", type=Path)
    vl.add_argument("--allowlist", type=Path, default=Path("config/device-allowlist.json"))
    vl.add_argument("--inventory", type=Path, default=Path("analysis/device_inventory.json"))
    vl.add_argument("--device", required=True, choices=["0416:5408", "0416:5302"])
    lp = sub.add_parser("live-preflight", help="fresh read-only prerequisites; never writes endpoints")
    lp.add_argument("--device", required=True, help="exact stable PnP instance ID")
    lp.add_argument("--sequence", required=True)
    lp.add_argument("--session-file", type=Path, default=Path("analysis/session-report.json"))
    lp.add_argument("--transaction-file", type=Path, default=Path("analysis/transactions.json"))
    lp.add_argument("--allowlist", type=Path, default=Path("config/device-allowlist.json"))
    lp.add_argument("--inventory", type=Path, default=Path("analysis/device_inventory.json"))
    lp.add_argument("--transaction",type=int,default=1)
    enc=sub.add_parser("encode-frame",help="offline JPEG protocol encoder; never transmits")
    enc.add_argument("jpeg",type=Path); enc.add_argument("--device",required=True,choices=["0416:5408","0416:5302"])
    enc.add_argument("--output",type=Path,required=True)
    ex=sub.add_parser("extract-transaction-jpeg",help="offline extraction from transaction JSON")
    ex.add_argument("report",type=Path); ex.add_argument("--device",required=True,choices=["0416:5408","0416:5302"])
    ex.add_argument("--transaction",type=int,default=1); ex.add_argument("--output",type=Path,required=True)
    pg=sub.add_parser("prepare-generated-live-sequence",help="offline generated-frame sequence preparation; never transmits")
    pg.add_argument("encoded_dir",type=Path);pg.add_argument("--reference",type=Path,required=True);pg.add_argument("--output",type=Path,required=True)
    cs=sub.add_parser("capture-selftest",help="recorder-only USBPcap validation; never opens a target device")
    cs.add_argument("--controller",default="USBPcap3");cs.add_argument("--duration",type=int,default=10)
    cs.add_argument("--output",type=Path)
    cr=sub.add_parser("compare-hid-replay",help="offline byte/timing comparison of a PID 5302 HID capture")
    cr.add_argument("capture",type=Path);cr.add_argument("--session-file",type=Path,default=Path("analysis/session-report.json"))
    cr.add_argument("--transaction-file",type=Path,default=Path("analysis/pid5302-same-session-first-frame.json"));cr.add_argument("--output",type=Path,required=True)
    args = parser.parse_args(argv)
    if args.command == "analyze":
        print(json.dumps(analyze(args.capture, args.output, args.device), indent=2))
        return 0
    if args.command == "transactions":
        print(json.dumps(write_transactions(args.capture, args.output), indent=2))
        return 0
    if args.command=="select-transaction":
        result=write_selected_transaction(args.report,args.output,args.device,args.transaction)
        print(json.dumps({"output":str(args.output),"device":args.device,"original_index":args.transaction,
                          "transfer_count":result["devices"][args.device]["transactions"][0]["transfer_count"]},indent=2));return 0
    if args.command == "replay":
        if args.send:
            allow=load_allowlist(args.allowlist); target=next((x for x in allow["devices"] if x["stable_instance_id"]==args.device),None)
            if not target: raise SystemExit("live authorization failed: exact stable device ID is not allowlisted")
            txfile=args.transaction_file or Path("analysis/transactions.json")
            seq=load_sequence(args.session_file,txfile,target["vid_pid"],args.transaction,require_same_session=True)
            pf=live_preflight(args.allowlist,args.session_file,txfile,args.device,args.sequence,
                              args.inventory if hasattr(args,'inventory') else Path("analysis/device_inventory.json"),args.transaction)
            if not pf["pass"]: raise SystemExit("live preflight failed: "+json.dumps(pf["checks"],sort_keys=True))
            friendly="Thermalright 6-inch LCD" if target["vid_pid"]=="0416:5302" else "Thermalright 9.16-inch LCD"
            summary={"title":"FIRST LIVE TEST REVIEW","target":friendly,"friendly_name":"USBDISPLAY",
                     "stable_id":target["stable_instance_id"],"vid_pid":target["vid_pid"],"container_id":target["container_id"],
                     "interface":target["interface"],"out_endpoint":target["endpoint"],"in_endpoint":target["response_endpoint"],
                     "sequence_id":seq["id"],"frame_sha256":seq["jpeg_sha256"],"frame_dimensions":seq["dimensions"],
                     "frame_bytes":seq["jpeg_bytes"],"write_count":1+len(seq["frame"]),
                     "total_session_bytes":len(seq["init"])+sum(map(len,seq["frame"])),
                     "expected_ready_sha256":__import__('hashlib').sha256(seq["ready"]).hexdigest(),
                     "expected_ack_sha256":__import__('hashlib').sha256(seq["ack"]).hexdigest() if seq["ack"] else None,
                     "timeouts_ms":pf["timeout_policy"],"hold_open_seconds":args.hold_open_seconds,
                     "additional_hold_writes":0,"retries":0}
            generated=seq.get("source_kind")=="generated"
            phrase_expected=("SEND ONE GENERATED FRAME" if generated else
                             "SEND PID 5302 CAPTURED FRAME" if target["vid_pid"]=="0416:5302" else
                             "SEND EXACT CAPTURED FRAME")
            summary["source_kind"]=seq.get("source_kind","captured");summary["authorization_phrase"]=phrase_expected
            print(json.dumps(summary,indent=2)); phrase=input(f"Type {phrase_expected} to continue: ")
            require_live_authorization(target,args.device,args.sequence,seq["id"],True,args.i_understand_live_usb,phrase,phrase_expected)
            budget_count=1+len(seq["frame"]); budget_bytes=len(seq["init"])+sum(map(len,seq["frame"]))
            if not 0<=args.hold_open_seconds<=30:raise SystemExit("hold-open-seconds must be between 0 and 30")
            if target.get("access_method")=="windows-hid":
                from .windows_hid import CtypesWindowsHidApi,RealHidTransport,discover_hid_identity
                transport=RealHidTransport(target,lambda:discover_hid_identity(target),CtypesWindowsHidApi(),budget_count,budget_bytes)
            else:
                from .windows_usb import CtypesWinUsbApi, discover_identity
                transport=RealUsbTransport(target,lambda:discover_identity(target),CtypesWinUsbApi(),budget_count,budget_bytes)
            result=LiveReplayMachine(target,seq,transport,hold_open_ms=round(args.hold_open_seconds*1000)).run()
            print(json.dumps(result,indent=2)); return 0 if result["success"] else 2
        if args.transaction_file is None: raise SystemExit("transaction_file is required for dry-run replay")
        print(json.dumps(dry_run(args.transaction_file, args.allowlist, args.device, args.transaction), indent=2))
        return 0
    if args.command=="persistence-replay":
        allow=load_allowlist(args.allowlist);target=next((x for x in allow["devices"] if x["stable_instance_id"].lower()==args.device.lower()),None)
        if not target:raise SystemExit("exact stable device ID is not allowlisted")
        if args.duration!=30.0:raise SystemExit("first persistence proof is hard-locked to exactly 30 seconds")
        seq=load_sequence(args.session_file,args.transaction_file,target["vid_pid"],args.transaction,require_same_session=True)
        plan=bounded_test_plan(target["vid_pid"],args.duration);policy=POLICIES[target["vid_pid"]]
        if seq["id"]!=args.sequence or seq["id"]!=plan["sequence_id"]:raise SystemExit("exact persistence sequence mismatch")
        if args.send:
            pf=live_preflight(args.allowlist,args.session_file,args.transaction_file,args.device,args.sequence,args.inventory,args.transaction)
            if not pf["pass"]:raise SystemExit("live preflight failed: "+json.dumps(pf["checks"],sort_keys=True))
            phrase_expected="SEND PID 5302 CAPTURED FRAME FOR 30 SECONDS" if target["vid_pid"]=="0416:5302" else "SEND PID 5408 CAPTURED FRAME FOR 30 SECONDS"
            print(json.dumps({"title":"BOUNDED PERSISTENCE PROOF","friendly_name":"Thermalright 6-inch LCD" if target["vid_pid"]=="0416:5302" else "Thermalright 9.16-inch LCD","stable_id":args.device,"vid_pid":target["vid_pid"],"container_id":target["container_id"],"interface":target["interface"],"out_endpoint":target["endpoint"],"in_endpoint":target["response_endpoint"],"sequence":seq["id"],"frame_sha256":seq["jpeg_sha256"],"plan":plan,"NO_RETRIES":True,"confirmation_phrase":phrase_expected},indent=2))
            phrase=input(f"Type {phrase_expected} to continue: ")
            require_live_authorization(target,args.device,args.sequence,seq["id"],True,args.i_understand_live_usb,phrase,phrase_expected)
            if target.get("access_method")=="windows-hid":
                from .windows_hid import CtypesWindowsHidApi,RealHidTransport,discover_hid_identity
                transport=RealHidTransport(target,lambda:discover_hid_identity(target),CtypesWindowsHidApi(),plan["writes_hard_max"],plan["bytes_hard_max"])
            else:
                from .windows_usb import CtypesWinUsbApi,discover_identity
                transport=RealUsbTransport(target,lambda:discover_identity(target),CtypesWinUsbApi(),plan["writes_hard_max"],plan["bytes_hard_max"])
            result=PersistentReplayMachine(target,seq,transport,plan["frame_count_hard_max"],policy.interval_seconds,duration_seconds=args.duration).run()
        else:
            responses=[seq["ready"]]+([seq["ack"]]*plan["frame_count_hard_max"] if seq["ack"] else [])
            transport=DryRunUsbTransport(expected_identity(target),responses);clock=[0.0]
            def now():clock[0]+=.00001;return clock[0]
            result=PersistentReplayMachine(target,seq,transport,plan["frame_count_hard_max"],policy.interval_seconds,clock=now,sleeper=lambda s:clock.__setitem__(0,clock[0]+s),duration_seconds=args.duration).run()
        print(json.dumps({"plan":plan,"result":result},indent=2));return 0 if result["success"] else 2
    if args.command=="dual-persistence-live":
        if not args.send or not args.i_understand_live_usb:raise SystemExit("dual live test requires --send and --i-understand-live-usb")
        if args.duration!=30.0:raise SystemExit("dual proof is hard-locked to exactly 30 seconds")
        allow=load_allowlist(args.allowlist);targets={x["vid_pid"]:x for x in allow["devices"]}
        files={"0416:5302":args.pid5302_transaction,"0416:5408":args.pid5408_transaction};specs={};preflights={}
        for pid in ("0416:5302","0416:5408"):
            target=targets[pid];seq=load_sequence(args.session_file,files[pid],pid,1,require_same_session=True);plan=bounded_test_plan(pid,30)
            if seq["id"]!=plan["sequence_id"] or seq.get("source_kind")!="captured":raise SystemExit(f"{pid} is not the exact capture-derived persistence sequence")
            pf=live_preflight(args.allowlist,args.session_file,files[pid],target["stable_instance_id"],seq["id"],args.inventory,1);preflights[pid]=pf
            if not pf["pass"]:raise SystemExit(f"{pid} live preflight failed: "+json.dumps(pf["checks"],sort_keys=True))
            specs[pid]={"target":target,"sequence":seq,"plan":plan,"policy":POLICIES[pid]}
        phrase_expected="SEND BOTH CAPTURED FRAMES FOR 30 SECONDS"
        print(json.dumps({"title":"SIMULTANEOUS DUAL CAPTURED-FRAME PERSISTENCE PROOF","duration_seconds":30,"generated_media":False,"automatic_retries":0,
            "devices":{pid:{"stable_id":s["target"]["stable_instance_id"],"container_id":s["target"]["container_id"],"interface":s["target"]["interface"],"out_endpoint":s["target"]["endpoint"],"in_endpoint":s["target"]["response_endpoint"],"sequence":s["sequence"]["id"],"jpeg_sha256":s["sequence"]["jpeg_sha256"],"plan":s["plan"]} for pid,s in specs.items()},"confirmation_phrase":phrase_expected},indent=2))
        phrase=input(f"Type {phrase_expected} to continue: ")
        for pid,s in specs.items():require_live_authorization(s["target"],s["target"]["stable_instance_id"],s["sequence"]["id"],s["sequence"]["id"],True,True,phrase,phrase_expected)
        from .windows_hid import CtypesWindowsHidApi,RealHidTransport,discover_hid_identity
        from .windows_usb import CtypesWinUsbApi,discover_identity
        s=specs["0416:5302"];hid_target=s["target"];s["transport"]=RealHidTransport(hid_target,lambda target=hid_target:discover_hid_identity(target),CtypesWindowsHidApi(),s["plan"]["writes_hard_max"],s["plan"]["bytes_hard_max"])
        s=specs["0416:5408"];usb_target=s["target"];s["transport"]=RealUsbTransport(usb_target,lambda target=usb_target:discover_identity(target),CtypesWinUsbApi(),s["plan"]["writes_hard_max"],s["plan"]["bytes_hard_max"])
        result=run_dual_persistence(specs,30);print(json.dumps({"preflights":preflights,"result":result},indent=2));return 0 if result["success"] else 2
    if args.command=="dual-generated-live":
        if args.duration!=30.0:raise SystemExit("generated dual proof is hard-locked to exactly 30 seconds")
        allow=load_allowlist(args.allowlist);targets={x["vid_pid"]:x for x in allow["devices"]}
        files={"0416:5302":args.pid5302_transaction,"0416:5408":args.pid5408_transaction};specs={};preflights={}
        for pid in ("0416:5302","0416:5408"):
            report=json.loads(files[pid].read_text(encoding="utf-8"));validation=report.get("generated_validation",{})
            if report.get("source_kind")!="generated" or not validation.get("valid") or not validation.get("padding_zero"):
                raise SystemExit(f"{pid} generated transaction is not offline-validated")
            seq=load_sequence(args.session_file,files[pid],pid,1,require_same_session=True)
            plan=bounded_generated_plan(pid,len(seq["frame"]),sum(map(len,seq["frame"])),seq["id"],30)
            specs[pid]={"target":targets[pid],"sequence":seq,"plan":plan,"policy":POLICIES[pid]}
        phrase_expected="SEND BOTH GENERATED FRAMES FOR 30 SECONDS"
        summary={"title":"SIMULTANEOUS DUAL GENERATED-STATIC PROOF","duration_seconds":30,"generated_media":True,
                 "automatic_retries":0,"devices":{pid:{"stable_id":s["target"]["stable_instance_id"],"container_id":s["target"]["container_id"],"interface":s["target"]["interface"],"out_endpoint":s["target"]["endpoint"],"in_endpoint":s["target"]["response_endpoint"],"sequence":s["sequence"]["id"],"jpeg_sha256":s["sequence"]["jpeg_sha256"],"dimensions":s["sequence"]["dimensions"],"plan":s["plan"]} for pid,s in specs.items()},"confirmation_phrase":phrase_expected,"live_authorization_flags":False}
        if not args.send:
            print(json.dumps(summary,indent=2));return 0
        if not args.i_understand_live_usb:raise SystemExit("dual generated live test requires --i-understand-live-usb")
        for pid,s in specs.items():
            pf=live_preflight(args.allowlist,args.session_file,files[pid],s["target"]["stable_instance_id"],s["sequence"]["id"],args.inventory,1);preflights[pid]=pf
            if not pf["pass"]:raise SystemExit(f"{pid} live preflight failed: "+json.dumps(pf["checks"],sort_keys=True))
        print(json.dumps(summary,indent=2));phrase=input(f"Type {phrase_expected} to continue: ")
        for pid,s in specs.items():require_live_authorization(s["target"],s["target"]["stable_instance_id"],s["sequence"]["id"],s["sequence"]["id"],True,True,phrase,phrase_expected)
        from .windows_hid import CtypesWindowsHidApi,RealHidTransport,discover_hid_identity
        from .windows_usb import CtypesWinUsbApi,discover_identity
        s=specs["0416:5302"];target=s["target"];s["transport"]=RealHidTransport(target,lambda target=target:discover_hid_identity(target),CtypesWindowsHidApi(),s["plan"]["writes_hard_max"],s["plan"]["bytes_hard_max"])
        s=specs["0416:5408"];target=s["target"];s["transport"]=RealUsbTransport(target,lambda target=target:discover_identity(target),CtypesWinUsbApi(),s["plan"]["writes_hard_max"],s["plan"]["bytes_hard_max"])
        result=run_dual_persistence(specs,30);print(json.dumps({"preflights":preflights,"result":result},indent=2));return 0 if result["success"] else 2
    if args.command == "session-report":
        print(json.dumps(write_session_report(args.capture, args.output, args.device), indent=2))
        return 0
    if args.command == "session-replay":
        print(json.dumps(dry_run_session(args.session_file, args.transaction_file, args.allowlist,
                                         args.device, args.transaction), indent=2))
        return 0
    if args.command == "simulate-live-replay":
        allow=load_allowlist(args.allowlist); target=next(x for x in allow["devices"] if x["vid_pid"]==args.device)
        seq=load_sequence(args.session_file,args.transaction_file,args.device,args.transaction)
        responses=[seq["ready"]]+([seq["ack"]] if seq["ack"] else [])
        result=LiveReplayMachine(target,seq,DryRunUsbTransport(expected_identity(target),responses)).run()
        print(json.dumps(result,indent=2)); return 0 if result["success"] else 2
    if args.command == "validate-live-session":
        result=preflight(args.allowlist,args.session_file,args.transaction_file,args.device,args.inventory)
        print(json.dumps(result,indent=2)); return 0 if result["live_preconditions_pass"] else 2
    if args.command == "live-preflight":
        result=live_preflight(args.allowlist,args.session_file,args.transaction_file,args.device,args.sequence,args.inventory,args.transaction)
        print(json.dumps(result,indent=2)); return 0 if result["pass"] else 2
    if args.command == "encode-frame":
        print(json.dumps(write_encoded(args.jpeg,args.output,args.device),indent=2)); return 0
    if args.command == "extract-transaction-jpeg":
        print(json.dumps(extract_jpeg(args.report,args.device,args.transaction,args.output),indent=2)); return 0
    if args.command == "prepare-generated-live-sequence":
        print(json.dumps(prepare_generated_transaction(args.encoded_dir,args.reference,args.output),indent=2)); return 0
    if args.command=="capture-selftest":
        from .capture_recorder import capture_selftest
        output=args.output or Path("captures/originals")/f"usbpcap_selftest_{datetime.now():%Y%m%d_%H%M%S}.pcap"
        print(json.dumps(capture_selftest(args.controller,args.duration,output),indent=2));return 0
    if args.command=="compare-hid-replay":
        from .capture_recorder import compare_pid5302_hid_replay
        print(json.dumps(compare_pid5302_hid_replay(args.capture,args.session_file,args.transaction_file,args.output),indent=2));return 0
    command = "Get-PnpDevice -PresentOnly | Where-Object {$_.InstanceId -match 'VID_0416'} | Select-Object Class,FriendlyName,InstanceId,Status | ConvertTo-Json -Depth 3"
    return subprocess.run(["powershell", "-NoProfile", "-Command", command]).returncode
