"""Generate BepisDB-style branding assets for Windows packaging.

The icon is intentionally generated during the build so PyInstaller always gets
valid PNG/ICO files, including a multi-resolution ICO for Windows Explorer.
"""
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
ASSETS.mkdir(parents=True, exist_ok=True)

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

# Bepis-style face.
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

print(f"Generated {png_path}")
print(f"Generated {ico_path}")
