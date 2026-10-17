"""Dessine le logo de l'application (balance de la justice dorée + bulle de message) en PNG.
python scripts/creer_icone.py  →  assets/icone_1024.png, icone_256.png, icone.ico"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

S = 1024
MARINE_HAUT, MARINE_BAS = (28, 45, 84), (12, 22, 46)
OR, OR_CLAIR = (214, 175, 54), (240, 210, 110)
SORTIE = Path(__file__).resolve().parent.parent / "assets"


def degrade():
    img = Image.new("RGB", (S, S))
    d = ImageDraw.Draw(img)
    for y in range(S):
        t = y / S
        d.line([(0, y), (S, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(MARINE_HAUT, MARINE_BAS)))
    return img


def main():
    fond = degrade()
    masque = Image.new("L", (S, S), 0)
    ImageDraw.Draw(masque).rounded_rectangle([40, 40, S - 40, S - 40], radius=220, fill=255)
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    img.paste(fond, (0, 0), masque)
    d = ImageDraw.Draw(img)

    # Balance
    cx = 470
    d.rectangle([cx - 14, 250, cx + 14, 720], fill=OR)                       # mât
    d.ellipse([cx - 34, 205, cx + 34, 273], fill=OR_CLAIR)                     # pommeau
    d.rounded_rectangle([cx - 190, 290, cx + 190, 318], radius=14, fill=OR)    # fléau
    d.polygon([(cx - 130, 760), (cx + 130, 760), (cx + 70, 705), (cx - 70, 705)], fill=OR)  # socle
    d.rounded_rectangle([cx - 160, 755, cx + 160, 790], radius=12, fill=OR)
    for px in (cx - 175, cx + 175):
        d.line([(px, 312), (px - 85, 520)], fill=OR_CLAIR, width=8)            # fils
        d.line([(px, 312), (px + 85, 520)], fill=OR_CLAIR, width=8)
        d.chord([px - 105, 440, px + 105, 600], start=0, end=180, fill=OR)     # plateaux

    # Bulle de message (l'agent te parle)
    bx, by, r = 760, 735, 150
    ombre = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(ombre).ellipse([bx - r + 10, by - r + 18, bx + r + 10, by + r + 18], fill=(0, 0, 0, 110))
    img = Image.alpha_composite(img, ombre.filter(ImageFilter.GaussianBlur(18)))
    d = ImageDraw.Draw(img)
    d.ellipse([bx - r, by - r, bx + r, by + r], fill=(255, 255, 255))
    d.polygon([(bx - 110, by + 80), (bx - 165, by + 170), (bx - 40, by + 125)], fill=(255, 255, 255))
    for i, dx in enumerate((-62, 0, 62)):
        d.ellipse([bx + dx - 24, by - 24, bx + dx + 24, by + 24], fill=MARINE_HAUT if i != 1 else OR)

    SORTIE.mkdir(exist_ok=True)
    img.save(SORTIE / "icone_1024.png")
    img.resize((256, 256), Image.LANCZOS).save(SORTIE / "icone_256.png")
    img.save(SORTIE / "icone.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("Icônes écrites dans", SORTIE)


if __name__ == "__main__":
    main()
