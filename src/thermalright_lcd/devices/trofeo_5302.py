from .base import DeviceDefinition

DEVICE = DeviceDefinition(
    "0416:5302", "Thermalright", "Trofeo Vision LCD 6.86",
    (1280, 480), (1280, 480), "windows-hid", 1, "0x02", "0x83", "interrupt", 512, False,
    transport_factory="thermalright_lcd.device_connection:GeneratedHardwareSender5302",
)
