"""Generate BepisDB-style branding assets for Windows packaging.

The build creates the app icon and top banner so PyInstaller always receives
valid assets even when the repository was cloned without generated binaries.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
ASSETS.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# App icon
# ---------------------------------------------------------------------------
SIZE = 256
img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)

brown = (126, 67, 43, 255)
dark = (18, 13, 12, 255)
cream = (244, 206, 137, 255)
pink = (239, 134, 141, 255)

margin = 22
draw.rounded_rectangle(
    (margin, margin, SIZE - margin, SIZE - margin),
    radius=38,
    fill=brown,
)

draw.ellipse((62, 62, 102, 102), fill=dark)
draw.ellipse((154, 62, 194, 102), fill=dark)
draw.pieslice((54, 118, 132, 198), start=20, end=200, fill=cream)
draw.pieslice((124, 118, 202, 198), start=-20, end=160, fill=cream)
draw.ellipse((92, 126, 164, 202), fill=cream)
draw.polygon(
    [(82, 146), (114, 127), (128, 148), (142, 127),
     (174, 146), (162, 174), (128, 166), (94, 174)],
    fill=cream,
)
draw.polygon([(111, 127), (145, 127), (128, 148)], fill=pink)
draw.ellipse((121, 151, 135, 164), fill=dark)

png_path = ASSETS / "app-icon.png"
ico_path = ASSETS / "app.ico"
img.save(png_path, "PNG")
img.save(
    ico_path,
    format="ICO",
    sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
           (64, 64), (128, 128), (256, 256)],
)

# ---------------------------------------------------------------------------
# Top banner
# ---------------------------------------------------------------------------
# Keep the repository-provided banner when present. This lets custom artwork
# survive CI packaging instead of being overwritten by a generated fallback.
banner_path = ASSETS / "banner.jpg"
if banner_path.exists():
    print(f"Keeping existing {banner_path}")
else:
    W, H = 1380, 126
    banner = Image.new("RGB", (W, H), "#071225")
    bd = ImageDraw.Draw(banner)

    for x in range(W):
        t = x / max(1, W - 1)
        r = int(7 + 18 * t)
        g = int(18 + 20 * t)
        b = int(40 + 72 * t)
        bd.line((x, 0, x, H), fill=(r, g, b))

    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow, "RGBA")
    gd.ellipse((720, -170, 1160, 270), fill=(103, 62, 255, 100))
    gd.ellipse((970, -150, 1450, 250), fill=(44, 119, 255, 95))
    gd.ellipse((590, -140, 900, 210), fill=(151, 73, 255, 45))
    glow = glow.filter(ImageFilter.GaussianBlur(54))
    banner = Image.alpha_composite(banner.convert("RGBA"), glow)

    shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade, "RGBA")
    for x in range(850):
        alpha = int(185 * (1 - x / 850))
        sd.line((x, 0, x, H), fill=(3, 9, 20, alpha))

    banner = Image.alpha_composite(banner, shade)
    banner.convert("RGB").save(banner_path, "JPEG", quality=93)
    print(f"Generated fallback {banner_path}")
