"""Generate the deterministic multi-resolution Windows application icon."""

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "assets" / "oni-thermal-lcd.ico"
PREVIEW = ROOT / "assets" / "oni-thermal-lcd-icon.png"


def render(size: int) -> Image.Image:
    scale = size / 256
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    def box(coords, radius, fill, outline=None, width=1):
        draw.rounded_rectangle(
            tuple(round(value * scale) for value in coords),
            radius=round(radius * scale), fill=fill, outline=outline,
            width=max(1, round(width * scale)),
        )

    # ONI mask mark using the same navy glass and electric-cyan palette as the UI.
    box((8, 8, 248, 248), 52, "#050b14", "#155070", 5)
    box((25, 25, 231, 231), 40, "#081725", "#0d3047", 3)
    points = ((53, 70), (81, 29), (93, 82), (128, 61), (163, 82),
              (175, 29), (203, 70), (187, 162), (128, 218), (69, 162))
    draw.polygon(
        [(round(x * scale), round(y * scale)) for x, y in points],
        fill="#0b2940", outline="#16b8ff",
    )
    width = max(1, round(7 * scale))
    cyan = "#6fe7ff"
    draw.line([(round(x * scale), round(y * scale)) for x, y in ((74, 105), (111, 121))], fill=cyan, width=width)
    draw.line([(round(x * scale), round(y * scale)) for x, y in ((182, 105), (145, 121))], fill=cyan, width=width)
    draw.line([(128 * scale, 84 * scale), (128 * scale, 184 * scale)], fill=cyan, width=max(1, round(5 * scale)))
    draw.line(
        [(91 * scale, 157 * scale), (128 * scale, 194 * scale), (165 * scale, 157 * scale)],
        fill="#16b8ff", width=max(1, round(5 * scale)), joint="curve",
    )
    return image


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    master = render(256)
    master.save(PREVIEW, optimize=True)
    master.save(
        OUTPUT,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
               (128, 128), (256, 256)],
    )
    print(OUTPUT)


if __name__ == "__main__":
    main()
