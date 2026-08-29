"""
Résolution des polices OOXML -> polices TrueType embarquées.

Un .docx ne garantit jamais que la police qu'il nomme soit présente sur la
machine qui l'ouvre : Arial, Calibri, Times New Roman et Cambria sont sous
licence Microsoft et absentes par défaut de Windows minimal, de Linux et de
macOS. LibreOffice contournait ça avec ses propres substituts métriquement
compatibles (Liberation*, Carlito, Caladea). On fait exactement pareil, en
embarquant les mêmes fichiers dans le binaire (vendor/fonts/) plutôt que de
dépendre d'une police système — c'est ce qui garantit un rendu identique
quelle que soit la machine, sans rien à installer.

ReportLab ne connaît nativement que 14 polices Type1 (Helvetica/Times/
Courier + Symbol/ZapfDingbats) : sans cette résolution, tout texte Calibri
ou Cambria retomberait sur Helvetica avec des largeurs de caractère fausses,
ce qui décale la mise en page.
"""

from __future__ import annotations

import logging
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

log = logging.getLogger("colibri_converter.render.font_resolver")

# Nom de police OOXML (normalisé en minuscules) -> famille embarquée.
_SUBSTITUTIONS: dict[str, str] = {
    "arial": "Liberation Sans",
    "helvetica": "Liberation Sans",
    "verdana": "Liberation Sans",
    "tahoma": "Liberation Sans",
    "segoe ui": "Liberation Sans",
    "times new roman": "Liberation Serif",
    "times": "Liberation Serif",
    "georgia": "Liberation Serif",
    "courier new": "Liberation Mono",
    "courier": "Liberation Mono",
    "consolas": "Liberation Mono",
    "calibri": "Carlito",
    "cambria": "Caladea",
}

# Noms de famille déjà "embarqués" : si le document les nomme directement,
# inutile de passer par la table de substitution.
_CANONICAL_FAMILIES = {
    "liberation sans": "Liberation Sans",
    "liberation serif": "Liberation Serif",
    "liberation mono": "Liberation Mono",
    "carlito": "Carlito",
    "caladea": "Caladea",
}

_FALLBACK_FAMILY = "Liberation Sans"

_FAMILY_FILES: dict[str, dict[str, str]] = {
    "Liberation Sans": {
        "regular": "LiberationSans-Regular.ttf",
        "bold": "LiberationSans-Bold.ttf",
        "italic": "LiberationSans-Italic.ttf",
        "bolditalic": "LiberationSans-BoldItalic.ttf",
    },
    "Liberation Serif": {
        "regular": "LiberationSerif-Regular.ttf",
        "bold": "LiberationSerif-Bold.ttf",
        "italic": "LiberationSerif-Italic.ttf",
        "bolditalic": "LiberationSerif-BoldItalic.ttf",
    },
    "Liberation Mono": {
        "regular": "LiberationMono-Regular.ttf",
        "bold": "LiberationMono-Bold.ttf",
        "italic": "LiberationMono-Italic.ttf",
        "bolditalic": "LiberationMono-BoldItalic.ttf",
    },
    "Carlito": {
        "regular": "Carlito-Regular.ttf",
        "bold": "Carlito-Bold.ttf",
        "italic": "Carlito-Italic.ttf",
        "bolditalic": "Carlito-BoldItalic.ttf",
    },
    "Caladea": {
        "regular": "Caladea-Regular.ttf",
        "bold": "Caladea-Bold.ttf",
        "italic": "Caladea-Italic.ttf",
        "bolditalic": "Caladea-BoldItalic.ttf",
    },
}

# Familles déjà enregistrées auprès de ReportLab dans CE processus.
# pdfmetrics est un registre global du module : l'enregistrer deux fois ne
# casse rien, mais c'est un travail de parsing TTF inutile à chaque document.
_registered: set[str] = set()


def _variant_key(*, bold: bool, italic: bool) -> str:
    if bold and italic:
        return "bolditalic"
    if bold:
        return "bold"
    if italic:
        return "italic"
    return "regular"


def face_name(family: str, *, bold: bool, italic: bool) -> str:
    """Nom de fonte ReportLab pour une famille + graisse/style donnés."""
    return f"{family}-{_variant_key(bold=bold, italic=italic)}"


def register_family(fonts_dir: Path, family: str) -> None:
    """Enregistre les 4 variantes (regular/bold/italic/bolditalic) d'une famille."""
    if family in _registered:
        return
    files = _FAMILY_FILES[family]
    faces = {}
    for variant, filename in files.items():
        path = fonts_dir / filename
        name = f"{family}-{variant}"
        pdfmetrics.registerFont(TTFont(name, str(path)))
        faces[variant] = name
    pdfmetrics.registerFontFamily(
        family,
        normal=faces["regular"],
        bold=faces["bold"],
        italic=faces["italic"],
        boldItalic=faces["bolditalic"],
    )
    _registered.add(family)


def register_all(fonts_dir: Path) -> None:
    """Enregistre toutes les familles embarquées. Appelé une fois par rendu."""
    for family in _FAMILY_FILES:
        register_family(fonts_dir, family)


def resolve(font_name: str | None) -> tuple[str, bool]:
    """
    Résout un nom de police OOXML vers une famille embarquée.

    Retourne (famille, substituee) — substituee=True si le nom demandé ne
    correspondait à aucune police connue et qu'on est retombé sur le repli
    par défaut (utile pour accumuler un avertissement une seule fois par
    document plutôt que par run).
    """
    if not font_name:
        return _FALLBACK_FAMILY, False
    key = font_name.strip().lower()
    if key in _CANONICAL_FAMILIES:
        return _CANONICAL_FAMILIES[key], False
    mapped = _SUBSTITUTIONS.get(key)
    if mapped:
        return mapped, False
    return _FALLBACK_FAMILY, True
