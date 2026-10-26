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
W, H = 1380, 126
banner = Image.new("RGB", (W, H), "#071225")
bd = ImageDraw.Draw(banner)

# Navy -> indigo gradient.
for x in range(W):
    t = x / max(1, W - 1)
    r = int(7 + 13 * t)
    g = int(18 + 16 * t)
    b = int(40 + 46 * t)
    bd.line((x, 0, x, H), fill=(r, g, b))

# Soft purple/blue glow fields.
glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
gd = ImageDraw.Draw(glow, "RGBA")
gd.ellipse((720, -140, 1120, 260), fill=(94, 59, 255, 105))
gd.ellipse((970, -120, 1390, 230), fill=(44, 112, 255, 95))
gd.ellipse((560, -120, 850, 190), fill=(129, 61, 255, 60))
glow = glow.filter(ImageFilter.GaussianBlur(52))
banner = Image.alpha_composite(banner.convert("RGBA"), glow)

# Stylized blue/purple eye motif on the right to match the approved mockup.
art = Image.new("RGBA", (W, H), (0, 0, 0, 0))
ad = ImageDraw.Draw(art, "RGBA")
for offset, alpha in ((0, 70), (18, 55), (36, 40)):
    ad.arc((930-offset, -80-offset, 1450+offset, 250+offset),
           190, 345, fill=(170, 195, 255, alpha), width=4)
    ad.arc((850-offset, -110-offset, 1320+offset, 210+offset),
           205, 350, fill=(120, 150, 255, alpha), width=3)

ad.ellipse((1050, 28, 1275, 103),
           fill=(18, 25, 54, 210),
           outline=(160, 190, 255, 145), width=2)
ad.ellipse((1132, 38, 1206, 112), fill=(102, 73, 235, 210))
ad.ellipse((1152, 55, 1190, 96), fill=(16, 12, 43, 240))
ad.ellipse((1160, 48, 1176, 64), fill=(225, 235, 255, 220))
ad.arc((1048, 25, 1280, 112), 195, 345,
       fill=(210, 222, 255, 180), width=3)
ad.arc((1048, -5, 1280, 98), 15, 165,
       fill=(150, 175, 255, 140), width=2)

# Darken the left side so the title remains readable.
shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
sd = ImageDraw.Draw(shade, "RGBA")
for x in range(800):
    alpha = int(150 * (1 - x / 800))
    sd.line((x, 0, x, H), fill=(3, 9, 20, alpha))

banner = Image.alpha_composite(Image.alpha_composite(banner, art), shade)
banner_path = ASSETS / "banner.jpg"
banner.convert("RGB").save(banner_path, "JPEG", quality=92)

print(f"Generated {png_path}")
print(f"Generated {ico_path}")
print(f"Generated {banner_path}")
