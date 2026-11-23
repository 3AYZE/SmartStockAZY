"""Generate SmartStockAZY's Windows application icon during release builds.

Pillow is a BUILD-ONLY dependency. The installed EXE needs no Python/Pillow.
"""
from pathlib import Path

from PIL import Image, ImageDraw


def main():
    out = Path("assets")
    out.mkdir(exist_ok=True)
    size = 256
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    dr.rounded_rectangle((9, 9, 246, 246), radius=54, fill=(17, 26, 37), outline=(60, 85, 109), width=3)
    dr.rounded_rectangle((33, 34, 223, 222), radius=36, fill=(27, 46, 66))
    # A compact market curve, readable at taskbar scale.
    pts = [(54, 174), (89, 149), (119, 158), (154, 107), (180, 116), (210, 70)]
    dr.line(pts, fill=(115, 199, 251), width=18, joint="curve")
    dr.line(pts, fill=(206, 237, 255), width=6, joint="curve")
    dr.ellipse((199, 59, 222, 82), fill=(224, 245, 255))
    im.save(out / "SmartStockAZY.ico", format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("Icon written:", out / "SmartStockAZY.ico")


if __name__ == "__main__":
    main()
