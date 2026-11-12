"""
Génère l'icône de BioCentral dans assets/ : icon.png (1024 px), icon.ico
(Windows, 16 à 256 px) et icon.icns (macOS). À relancer seulement si l'on
veut changer le dessin :  python outils/generer_icone.py   (nécessite Pillow)

Dessin : carré arrondi bleu, avec une carte de contrôle stylisée (moyenne et
limites ±2 s, tracé de points) — le cœur du logiciel en un coup d'œil.
"""
from pathlib import Path

from PIL import Image, ImageDraw

ASSETS = Path(__file__).resolve().parent.parent / "assets"
TAILLE = 1024


def dessiner() -> Image.Image:
    s = TAILLE
    image = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    fond = Image.new("RGBA", (s, s))
    d = ImageDraw.Draw(fond)
    haut, bas = (0x1A, 0x6F, 0xC4), (0x0C, 0x44, 0x7C)   # dégradé vertical bleu
    for y in range(s):
        t = y / (s - 1)
        d.line([(0, y), (s, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(haut, bas)) + (255,))
    masque = Image.new("L", (s, s), 0)
    ImageDraw.Draw(masque).rounded_rectangle([40, 40, s - 40, s - 40], radius=210, fill=255)
    image.paste(fond, (0, 0), masque)

    d = ImageDraw.Draw(image)
    gauche, droite = 170, s - 170
    centre = s // 2 + 20
    ecart = 150
    # limites ±2 s en pointillés, moyenne en trait plein
    for y, couleur in ((centre - ecart, (255, 196, 92, 255)), (centre + ecart, (255, 196, 92, 255))):
        x = gauche
        while x < droite:
            d.line([(x, y), (min(x + 46, droite), y)], fill=couleur, width=16)
            x += 80
    d.line([(gauche, centre), (droite, centre)], fill=(255, 255, 255, 170), width=12)
    # série de points (le dernier au-delà de +2 s, en rouge)
    valeurs = [0.2, -0.6, 0.5, -0.2, 0.9, -0.9, 0.3, 1.25]
    pas = (droite - gauche) / (len(valeurs) - 1)
    points = [(gauche + i * pas, centre - v * ecart) for i, v in enumerate(valeurs)]
    d.line(points, fill=(255, 255, 255, 255), width=20, joint="curve")
    for i, (x, y) in enumerate(points):
        rayon = 34
        couleur = (235, 80, 80, 255) if i == len(points) - 1 else (255, 255, 255, 255)
        d.ellipse([x - rayon, y - rayon, x + rayon, y + rayon], fill=couleur, outline=(12, 68, 124, 255), width=10)
    return image


def main():
    ASSETS.mkdir(exist_ok=True)
    image = dessiner()
    image.save(ASSETS / "icon.png")
    image.save(ASSETS / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    image.save(ASSETS / "icon.icns")
    print("Icônes écrites dans", ASSETS)


if __name__ == "__main__":
    main()
