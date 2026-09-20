from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT = Path("captures/generated/test-media")
OUT.mkdir(parents=True, exist_ok=True)

for width, height, label in ((1920, 462, "1920x462"), (1280, 480, "1280x480")):
    for name, color, text in (("test_a", "#d40000", "DISPLAY TEST A"), ("test_b", "#00a030", "DISPLAY TEST B")):
        im = Image.new("RGB", (width, height), color)
        draw = ImageDraw.Draw(im)
        font = ImageFont.truetype(r"C:\Windows\Fonts\segoeuib.ttf", max(48, height // 6))
        box = draw.textbbox((0, 0), text, font=font)
        draw.text(((width-(box[2]-box[0]))/2, (height-(box[3]-box[1]))/2), text, font=font, fill="white", stroke_width=3, stroke_fill="black")
        draw.text((20, 20), label, font=ImageFont.truetype(r"C:\Windows\Fonts\segoeui.ttf", 28), fill="white")
        im.save(OUT / f"{name}_{label}.png")
