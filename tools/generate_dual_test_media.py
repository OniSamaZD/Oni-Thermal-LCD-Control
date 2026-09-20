from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from thermalright_lcd.media import render_image


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "captures/generated/test-media"


def font(size: int):
    for path in (Path("C:/Windows/Fonts/seguisb.ttf"), Path("C:/Windows/Fonts/arialbd.ttf")):
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def fitted_font(draw, text: str, preferred: int, maximum_width: int):
    size=preferred
    while size>20:
        candidate=font(size);box=draw.textbbox((0,0),text,font=candidate)
        if box[2]-box[0]<=maximum_width:return candidate
        size-=4
    return font(size)


def card(size, background, accent, side, pid, label):
    image = Image.new("RGB", size, background)
    draw = ImageDraw.Draw(image)
    w, h = size
    stripe = max(24, h // 8)
    for x in range(0, w, stripe):
        if (x // stripe) % 2 == 0:
            draw.rectangle((x, 0, x + stripe - 1, stripe), fill=accent)
            draw.rectangle((x, h - stripe, x + stripe - 1, h), fill=accent)
    draw.rounded_rectangle((30, stripe + 18, w - 30, h - stripe - 18), radius=30, fill=(8, 12, 20), outline=accent, width=8)
    title = f"{side}  •  {label}"
    detail = f"NEW GENERATED MEDIA  •  PID {pid}"
    title_font = fitted_font(draw,title,max(52,h//5),w-100)
    detail_font = fitted_font(draw,detail,max(28,h//11),w-100)
    for text, y, f in ((title, h * .28, title_font), (detail, h * .61, detail_font)):
        box = draw.textbbox((0, 0), text, font=f)
        draw.text(((w - (box[2] - box[0])) / 2, y), text, font=f, fill=accent)
    return image


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    specs = {
        "pid5408": ((1920, 462), (18, 0, 48), (0, 255, 255), "LEFT / 9.16", "5408", "CYAN"),
        "pid5302": ((1280, 480), (0, 45, 95), (255, 224, 0), "RIGHT / 6-INCH", "5302", "YELLOW"),
        "gui-pid5408": ((1920, 462), (15, 45, 20), (255, 40, 210), "GUI LEFT / 9.16", "5408", "MAGENTA"),
        "gui-pid5302": ((1280, 480), (55, 18, 0), (80, 255, 70), "GUI RIGHT / 6-INCH", "5302", "GREEN"),
    }
    for name, (size, bg, accent, side, pid, label) in specs.items():
        image = card(size, bg, accent, side, pid, label)
        base=f"gui-test-{name[4:]}" if name.startswith("gui-") else f"dual-generated-{name}"
        png = OUT / f"{base}.png"
        jpg = OUT / f"{base}.jpg"
        image.save(png, "PNG")
        prepared = render_image(image, size, quality=95)
        jpg.write_bytes(prepared.jpeg)
        print(f"{name}: {png} / {jpg} / {len(prepared.jpeg)} JPEG bytes")


if __name__ == "__main__":
    main()
