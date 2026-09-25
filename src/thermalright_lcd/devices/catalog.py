from __future__ import annotations

from dataclasses import dataclass

from .base import DeviceFamilyDefinition


DEVICE_FAMILIES = (
    DeviceFamilyDefinition("thermalright-trofeo","Thermalright",("Trofeo Vision 9.16 LCD","Trofeo Vision LCD 6.86"),((1920,462),(1280,480)),"WinUSB / HID",("0416:5408","0416:5302"),"Physically verified","docs/protocol-9.16.md; docs/protocol-6.md","ONI original research",True,"Public reviewed onboarding and physical validation exist for both models."),
    DeviceFamilyDefinition("thermalright-reference-panels","Thermalright",("ChiZhu, Trofeo HID/Bulk/LY1, ALi and SCSI panel families",),((240,240),(240,320),(320,240),(320,320),(360,360),(480,480),(640,172),(640,480),(800,480),(854,480),(960,320),(960,540),(1280,480),(1600,720),(1920,400),(1920,440),(1920,462),(1920,480)),"WinUSB / HID / SCSI",("87ad:70db","0416:5302","0416:5408","0416:5409","0416:5406","0418:5303","0418:5304","87cd:70db","0402:3922"),"Protocol implemented / community hardware needed","InfoPanel ThermalrightPanel reference sources supplied to ONI","Upstream open-source reference; no source copied verbatim",False,"Exact PM/SUB/identifier/transport detection and frame construction are implemented. Output remains fail-closed unless a matching transport adapter and exact probe response authorize the model."),
    DeviceFamilyDefinition("beadapanel","NXElec",("BeadaPanel 2/3/4/5/6/7/8/9/11 and current model families",),((320,480),(480,320),(480,480),(480,800),(800,480),(1280,480),(480,1920),(440,1920),(462,1920)),"WinUSB Panel-Link / Status-Link",("4e58:1001","4e58:1002"),"Implemented — community hardware validation required","InfoPanel GPLv3 interoperability reference; NXElec Panel-Link documentation","Clean-room protocol implementation from GPLv3 reference behavior",True,"Physical WinUSB discovery, STATUS-LINK identity validation and Panel-Link RGB565 output are wired to DisplaySession."),
    DeviceFamilyDefinition("jl-jonsbo-serial","Jungle Leopard / Jonsbo",("JL LCD family","Jonsbo DS916"),((480,960),(1920,462),(462,1920)),"USB CDC serial",("33c3:7788","33c3:f101"),"Implemented — community hardware validation required","InfoPanel GPLv3 interoperability reference","Clean-room protocol implementation from GPLv3 reference behavior",True,"Physical COM discovery plus device response is required before output."),
    DeviceFamilyDefinition("thermaltake-hid","Thermaltake / ASRock",('Thermaltake 6 inch LCD','ASRock Phantom Gaming 360 LCD'),((1480,720),(480,480)),"HID",("264a:2347","26ce:0a10"),"Implemented — community hardware validation required","InfoPanel GPLv3 interoperability reference","Clean-room protocol implementation from GPLv3 reference behavior",True,"Exact HID identity/report geometry and successful 200 handshake are required."),
    DeviceFamilyDefinition("lianli","Lian Li",('Universal Screen 8.8 inch','Universal Screen 9.2 inch','HydroShift II OLED Curve','HydroShift II LCD'),((480,1920),(464,1920),(2288,1080),(480,480)),"WinUSB encrypted bulk",("1cbe:a088","1cbe:a092","1cbe:a068","1cbe:a034"),"Implemented — community hardware validation required","InfoPanel GPLv3 interoperability reference","Clean-room protocol implementation from GPLv3 reference behavior",True,"Exact VID/PID, WinUSB interface, version and stop-media acknowledgements are required."),
    DeviceFamilyDefinition("jonsbo-vmax-ms9132","Jonsbo / VMAX",('Jonsbo DS339','VMAX 4.6 inch LCD'),((376,960),(320,960)),"Composite HID + bulk",("345f:9132",),"Detection-only","InfoPanel GPLv3 interoperability reference","Clean-room analysis only",False,"The same VID/PID represents two incompatible geometries; safe pre-output model disambiguation is not defined."),
    DeviceFamilyDefinition("turing-turzx","Turing / TURZX",("2.1–12.3 inch serial and USB revisions",),((320,480),(480,800),(480,1920)),"USB serial / model-specific USB",("1a86:5722",),"Experimental","https://github.com/mathoudebine/turing-smart-screen-python","GPL-3.0-or-later",False,"No GPL source copied. Similar enclosures use incompatible protocols, so VID/PID alone is insufficient."),
    DeviceFamilyDefinition("xuanfang","XuanFang",("3.5 inch revision B / flagship",),((320,480),),"USB serial",(),"Experimental","https://github.com/mathoudebine/turing-smart-screen-python","GPL-3.0-or-later",False,"Requires model-specific serial identity and community hardware traces."),
    DeviceFamilyDefinition("usbpcmonitor","UsbPCMonitor",("3.5 inch","5 inch","7 inch"),((320,480),(480,800),(600,1024)),"CH340 USB serial",("1a86:5722",),"Experimental","https://github.com/mathoudebine/turing-smart-screen-python; https://github.com/thomasteoh/ch340disp","GPL-3.0-or-later references",False,"Shared bridge IDs require a validated model handshake before any output."),
    DeviceFamilyDefinition("kipye-qiye","Kipye / Qiye",("Qiye Smart Display 3.5 inch",),((320,480),),"USB serial",(),"Experimental","https://github.com/mathoudebine/turing-smart-screen-python","GPL-3.0-or-later",False,"Protocol evidence exists upstream but has not been independently validated in ONI."),
    DeviceFamilyDefinition("weact-fs","WeAct Studio",("Display FS V1 0.96 inch","Display FS V1 3.5 inch"),((160,80),(320,480)),"USB 2.0 FS CDC serial",(),"Experimental","https://github.com/WeActStudio/WeActStudio.SystemMonitor","GPL-3.0",False,"Detection and safe output contract are not yet sufficiently specific."),
    DeviceFamilyDefinition("ax206","Multiple vendors",("AIDA64 / AX206 / USB2LCD photo-frame displays",),(),"USB Mass Storage BOT / vendor CDB",("1908:0102",),"Experimental","https://github.com/mathoudebine/turing-smart-screen-python/issues/475; https://github.com/mechcow/win-ax206-display","GPL-derived protocol references",False,"Exact identity is useful for diagnostics, but driver replacement, model geometry and command validation are required before writes."),
    DeviceFamilyDefinition("waveshare-guition","Waveshare / GUITION",("USB Monitor families",),(),"Vendor-specific",(),"Unsupported","https://github.com/mathoudebine/turing-smart-screen-python","GPL-3.0-or-later research index",False,"Known models require proprietary firmware or lack a safe documented protocol."),
)


@dataclass(frozen=True, slots=True)
class CatalogClassification:
    family_ids: tuple[str, ...]
    support_status: str
    selected_adapter: str | None
    output_authorized: bool
    reason: str


@dataclass(frozen=True, slots=True)
class CatalogModel:
    key: str
    manufacturer: str
    family: str
    model: str
    resolutions: tuple[tuple[int, int], ...]
    identifiers: tuple[str, ...]
    connection_type: str
    status: str
    output_enabled: bool
    notes: str
    family_level: bool = False


def catalog_models() -> tuple[CatalogModel, ...]:
    """Model-level UI catalog derived from the same runtime protocol records."""
    from .community_panels import BEADA_MODEL_NAMES, BEADA_MODEL_SIZES, MODELS as community
    from .thermalright_reference import MODELS as thermalright

    rows = [
        CatalogModel("trofeo-vision-916", "Thermalright", "Trofeo Vision", "Trofeo Vision 9.16 LCD", ((1920, 462),), ("0416:5408",), "WinUSB", "Verified", True, "Physically validated by the ONI project."),
        CatalogModel("trofeo-vision-686", "Thermalright", "Trofeo Vision", "Trofeo Vision 6.86 LCD", ((1280, 480),), ("0416:5302",), "HID", "Verified", True, "Physically validated by the ONI project."),
    ]
    for model_id, size in sorted(BEADA_MODEL_SIZES.items()):
        rows.append(CatalogModel(f"beada-{model_id}", "NXElec", "BeadaPanel", f"BeadaPanel {BEADA_MODEL_NAMES[model_id]}", (size,), ("4e58:1001", "4e58:1002"), "WinUSB Panel-Link / Status-Link", "Experimental", True, "Exact STATUS-LINK model byte and resolution must match before output."))
    for key in ("jl", "jonsbo-ds916", "thermaltake-6", "asrock-pg360", "lianli-88", "lianli-92", "lianli-oled", "lianli-lcd"):
        model=community[key];family="JL LCD Device Family" if key=="jl" else model.name;resolutions=() if not all(model.render_size) else (model.render_size,)
        rows.append(CatalogModel(key,model.manufacturer,"Community Panels",family,resolutions,(model.vid_pid,),model.transport.upper(),"Experimental",True,"Exact physical identity and protocol handshake are required before output.",key=="jl"))
    verified_keys={"trofeo-vision-916","trofeo-vision-686"};enabled_ids={"87ad:70db","0416:5409","0416:5406","87cd:70db","0402:3922"}
    for model in thermalright.values():
        if model.key in verified_keys:continue
        enabled=model.vid_pid in enabled_ids and model.transport in {"winusb","scsi"}
        status="Experimental" if enabled else "Unsupported / Incomplete"
        notes="Exact protocol probe selects this model before the dynamic DisplaySession is registered." if enabled else "A complete safe physical discovery and output binding is not currently available for this model."
        rows.append(CatalogModel(model.key,"Thermalright","Thermalright Reference Panels",model.name,(model.render_size,),(model.vid_pid,),model.transport.upper(),status,enabled,notes))
    rows.extend((
        CatalogModel("thermalright-0418-5303","Thermalright","Thermalright Reference Panels","0418:5303 Device Family",(),("0418:5303",),"Model-specific","Unsupported / Incomplete",False,"Safe framing and output binding are not sufficiently defined.",True),
        CatalogModel("thermalright-0418-5304","Thermalright","Thermalright Reference Panels","0418:5304 Device Family",(),("0418:5304",),"Model-specific","Unsupported / Incomplete",False,"Safe framing and output binding are not sufficiently defined.",True),
    ))
    for family in DEVICE_FAMILIES:
        if family.output_enabled or family.family_id in {"thermalright-trofeo","thermalright-reference-panels","beadapanel","jl-jonsbo-serial","thermaltake-hid","lianli"}:continue
        for index,name in enumerate(family.models):
            family_level="famil" in name.casefold() or "revision" in name.casefold() or "2.1–12.3" in name
            label=name if not family_level else f"{name} Device Family"
            rows.append(CatalogModel(f"{family.family_id}-{index}",family.manufacturer,family.manufacturer,label,family.resolutions,family.identifiers,family.connection_type,"Unsupported / Incomplete",False,family.notes,family_level))
    return tuple(rows)


def classify_catalog_descriptor(vid: int, pid: int, *, interface: int | None = None, endpoints: set[int] | None = None, transport: str = "") -> CatalogClassification | None:
    """Classify public descriptors without opening a handle or authorizing writes."""
    endpoint_set=set(endpoints or ())
    if (vid,pid) in {(0x4E58,0x1001),(0x4E58,0x1002)}:
        exact=interface==0 and {0x01,0x02,0x82}.issubset(endpoint_set)
        return CatalogClassification(("beadapanel",),"Protocol verified / community test needed","beadapanel" if exact else None,False,"exact Panel-Link/Status-Link descriptor shape" if exact else "Beada VID/PID observed but required interface/endpoints are incomplete")
    if (vid,pid)==(0x1908,0x0102):
        exact={0x01,0x81}.issubset(endpoint_set)
        return CatalogClassification(("ax206",),"Experimental","ax206-diagnostic" if exact else None,False,"mass-storage bulk endpoints observed; output remains disabled" if exact else "AX206 identity observed but bulk endpoint evidence is incomplete")
    if (vid,pid)==(0x1A86,0x5722):
        return CatalogClassification(("turing-turzx","usbpcmonitor"),"Experimental",None,False,"shared CH340 bridge identity is ambiguous; a read-only model handshake is required")
    thermalright_ids={(0x87AD,0x70DB),(0x0416,0x5409),(0x0416,0x5406),(0x0418,0x5303),(0x0418,0x5304),(0x87CD,0x70DB),(0x0402,0x3922)}
    if (vid,pid) in thermalright_ids:
        return CatalogClassification(("thermalright-reference-panels",),"Protocol implemented / community hardware needed",None,False,"recognized Thermalright reference identity; exact init/poll response and a matching transport adapter are required before output")
    return None


def identify_catalog_device(vid: int, pid: int, *, interface: int, endpoints: set[int]) -> DeviceFamilyDefinition | None:
    """Read-only, exact descriptor match; never authorizes output."""
    if (vid,pid) in {(0x4E58,0x1001),(0x4E58,0x1002)} and interface==0 and {0x01,0x02,0x82}.issubset(endpoints):
        return next(item for item in DEVICE_FAMILIES if item.family_id=="beadapanel")
    return None
