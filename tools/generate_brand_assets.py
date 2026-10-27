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
# The approved UI mockup uses a dark navy/indigo banner with a cropped
# anime-style face on the right. Keep it as a full composition rather than the
# oversized single-eye motif used by earlier builds.
W, H = 1380, 126
banner = Image.new("RGB", (W, H), "#071225")
bd = ImageDraw.Draw(banner)

# Navy-to-indigo base.
for x in range(W):
    t = x / max(1, W - 1)
    r = int(7 + 18 * t)
    g = int(18 + 20 * t)
    b = int(40 + 72 * t)
    bd.line((x, 0, x, H), fill=(r, g, b))

# Purple / electric-blue glow behind the character area.
glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
gd = ImageDraw.Draw(glow, "RGBA")
gd.ellipse((720, -170, 1160, 270), fill=(103, 62, 255, 100))
gd.ellipse((970, -150, 1450, 250), fill=(44, 119, 255, 95))
gd.ellipse((590, -140, 900, 210), fill=(151, 73, 255, 45))
glow = glow.filter(ImageFilter.GaussianBlur(54))
banner = Image.alpha_composite(banner.convert("RGBA"), glow)

# Cropped stylized anime face on the right, echoing the approved render.
art = Image.new("RGBA", (W, H), (0, 0, 0, 0))
ad = ImageDraw.Draw(art, "RGBA")

# Hair mass and layered strands.
ad.ellipse((920, -170, 1430, 250), fill=(96, 126, 216, 90))
ad.polygon(
    [(980, 0), (1110, 0), (1040, 74), (1140, 20), (1095, 115),
     (1215, 18), (1170, 125), (1325, 8), (1260, 125), (1410, 30),
     (1380, 126), (940, 126)],
    fill=(121, 158, 235, 115),
)
for x in (1000, 1055, 1115, 1190, 1265, 1340):
    ad.line((x, 0, x-55, 126), fill=(190, 210, 255, 55), width=3)

# Soft skin region.
ad.ellipse((1030, -45, 1425, 205), fill=(214, 181, 205, 78))

# Two eyes, deliberately subtle so the banner reads as a face rather than an icon.
for cx in (1140, 1305):
    ad.ellipse((cx-63, 34, cx+63, 103),
               fill=(23, 26, 58, 220),
               outline=(174, 193, 255, 135), width=2)
    ad.ellipse((cx-25, 43, cx+25, 95), fill=(110, 71, 235, 225))
    ad.ellipse((cx-11, 51, cx+11, 91), fill=(18, 12, 43, 245))
    ad.ellipse((cx-5, 47, cx+7, 59), fill=(235, 241, 255, 225))
    ad.arc((cx-70, 25, cx+70, 105), 195, 345,
           fill=(222, 229, 255, 180), width=3)

# Nose / cheek hints and a few foreground hair strands.
ad.line((1220, 67, 1208, 94), fill=(224, 193, 214, 70), width=2)
ad.arc((1160, 81, 1280, 138), 10, 165, fill=(236, 184, 206, 55), width=2)
ad.line((1090, 0, 1010, 126), fill=(210, 224, 255, 90), width=4)
ad.line((1375, 0, 1290, 126), fill=(210, 224, 255, 80), width=4)

# Dark left-side readability gradient for the title/logo area.
shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
sd = ImageDraw.Draw(shade, "RGBA")
for x in range(850):
    alpha = int(185 * (1 - x / 850))
    sd.line((x, 0, x, H), fill=(3, 9, 20, alpha))

banner = Image.alpha_composite(Image.alpha_composite(banner, art), shade)
banner_path = ASSETS / "banner.jpg"
banner.convert("RGB").save(banner_path, "JPEG", quality=93)

print(f"Generated {png_path}")
print(f"Generated {ico_path}")
print(f"Generated {banner_path}")
