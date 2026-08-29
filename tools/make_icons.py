#!/usr/bin/env python3
"""
Génère les icônes à partir du SVG de `branding.py`.

    python tools/make_icons.py

Produit `build/icons/colibri.ico` (Windows), `.icns` (macOS) et des PNG.

La rastérisation passe par QtSvg plutôt que par cairosvg : PySide6 est déjà
une dépendance du projet, alors que cairo exige des bibliothèques natives
pénibles à installer sur les runners Windows.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Aucun serveur d'affichage sur un runner de CI : sans ceci, Qt échoue au
# démarrage avec « could not connect to display ».
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QByteArray, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

from colibri_converter.branding import COLIBRI_SVG, colibri_icon_svg  # noqa: E402

SIZES = (16, 24, 32, 48, 64, 128, 256, 512)
OUTPUT = ROOT / "build" / "icons"


def rasterize(svg: str, size: int, destination: Path) -> Path:
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        QSvgRenderer(QByteArray(svg.encode())).render(painter)
    finally:
        painter.end()
    if not image.save(str(destination), "PNG"):
        raise RuntimeError(f"Écriture impossible : {destination}")
    return destination


def main() -> int:
    QGuiApplication(sys.argv)  # requis avant tout rendu Qt
    OUTPUT.mkdir(parents=True, exist_ok=True)

    icon_svg = colibri_icon_svg()
    pngs = [rasterize(icon_svg, s, OUTPUT / f"icon_{s}.png") for s in SIZES]
    rasterize(COLIBRI_SVG, 512, OUTPUT / "logo.png")
    (OUTPUT / "colibri.svg").write_text(COLIBRI_SVG, encoding="utf-8")

    try:
        from PIL import Image
    except ImportError:
        print("Pillow absent : PNG produits, mais pas de .ico", file=sys.stderr)
        return 1

    # Un .ico multi-résolutions : Windows pioche la taille adaptée selon le
    # contexte (barre des tâches, explorateur, alt-tab). Un .ico à taille
    # unique donne une icône floue partout ailleurs.
    with Image.open(pngs[-2]) as base:
        base.save(
            OUTPUT / "colibri.ico",
            format="ICO",
            sizes=[(s, s) for s in SIZES if s <= 256],
        )
    print(f"Icônes générées dans {OUTPUT}")

    if sys.platform == "darwin":
        iconset = OUTPUT / "colibri.iconset"
        iconset.mkdir(exist_ok=True)
        for size in (16, 32, 128, 256, 512):
            rasterize(icon_svg, size, iconset / f"icon_{size}x{size}.png")
            rasterize(icon_svg, size * 2, iconset / f"icon_{size}x{size}@2x.png")
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset),
             "-o", str(OUTPUT / "colibri.icns")],
            check=False,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
