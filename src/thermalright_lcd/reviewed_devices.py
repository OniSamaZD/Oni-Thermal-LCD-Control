"""Immutable public definitions for reviewed Thermalright LCD transports.

Machine-specific instance IDs, container IDs, and device paths are discovered
read-only at runtime. They are intentionally absent from these definitions.
"""

from __future__ import annotations

from copy import deepcopy


REVIEWED_DEVICE_DEFINITIONS = {
    "0416:5408": {
        "vid_pid": "0416:5408", "interface": 0, "endpoint": "0x09", "transfer_type": "bulk",
        "host_payload_size": 4096, "response_endpoint": "0x81",
        "interface_guid": "{3876E417-E089-4BCC-BBF8-47ABA55E46FB}", "driver": "WINUSB",
        "guiSessionMaxSeconds": 3600, "guiMaxFrameWrites": 4096,
        "open_request": {"endpoint": "0x09", "transfer_type": "bulk", "payload_size": 2048, "prefix_hex": "02ff"},
        "open_response": {"endpoint": "0x81", "transfer_type": "bulk", "payload_size": 512, "prefix_hex": "03ff"},
        "readiness_mandatory_fields": {"physical_width_le_offset_24": 1920, "physical_height_le_offset_28": 480, "excluded_rows_offset_44": 18},
        "authorization_source": "public-reviewed-v1",
    },
    "0416:5302": {
        "vid_pid": "0416:5302", "interface": 1, "endpoint": "0x02", "transfer_type": "interrupt",
        "access_method": "windows-hid", "driver": "HIDUSB", "hid_interface": 0, "hid_report_id": 0,
        "hid_input_report_bytes": 37, "hid_output_report_bytes": 513, "host_payload_size": 512,
        "response_endpoint": "0x83", "interface_guid": None,
        "guiSessionMaxSeconds": 3600, "guiMaxFrameWrites": 4096,
        "open_request": {"endpoint": "0x02", "transfer_type": "interrupt", "payload_size": 512, "payload_prefix_hex": "dadbdcdd00000000000000000100000000000000"},
        "open_response": {"endpoint": "0x83", "transfer_type": "interrupt", "payload_size": 36, "payload_prefix_hex": "dadbdcdd01800000"},
        "readiness_mandatory_fields": {"command_le_offset_4": 32769, "ascii_offset_20": "AP4S122"},
        "authorization_source": "public-reviewed-v1",
    },
}


def reviewed_device_definition(device_id: str) -> dict:
    try:return deepcopy(REVIEWED_DEVICE_DEFINITIONS[device_id])
    except KeyError as exc:raise KeyError(f"unsupported device definition: {device_id}") from exc


def reviewed_lifecycle(device_id: str) -> dict:
    """Return only the reviewed initialization/readiness protocol constants."""
    if device_id == "0416:5408":
        init = bytearray(2048); init[:2] = b"\x02\xff"; init[8] = 1
        ack = bytearray(512); ack[:2] = b"\x03\xff"; ack[8] = 1
        return {"id": "0416:5408/public-reviewed-v1", "source_kind": "public-reviewed",
                "init": bytes(init), "ready": bytes(512), "ack": bytes(ack),
                "ready_validation": "reviewed-fields", "dimensions": (1920, 462)}
    if device_id == "0416:5302":
        init = bytearray(512); init[:4] = bytes.fromhex("dadbdcdd"); init[12] = 1
        return {"id": "0416:5302/public-reviewed-v1", "source_kind": "public-reviewed",
                "init": bytes(init), "ready": bytes(36), "ack": None,
                "ready_validation": "reviewed-fields", "dimensions": (1280, 480)}
    raise KeyError(f"unsupported device lifecycle: {device_id}")
