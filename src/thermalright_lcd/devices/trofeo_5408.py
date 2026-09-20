from .base import DeviceDefinition

DEVICE = DeviceDefinition(
    "0416:5408", "Thermalright", "Trofeo Vision 9.16 LCD",
    (1920, 462), (1920, 480), "winusb", 0, "0x09", "0x81", "bulk", 2048, True,
    transport_factory="thermalright_lcd.device_connection:GeneratedHardwareSender5408",
)
