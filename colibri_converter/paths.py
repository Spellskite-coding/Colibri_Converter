"""Résolution de chemins compatible PyInstaller (--onefile et --onedir).

Partagé entre engine.py et render/worker.py : les deux ont besoin de
localiser des ressources embarquées (polices) aussi bien en développement
(dossier vendor/ à la racine du dépôt) qu'une fois figés en exécutable par
PyInstaller (sys._MEIPASS en mode --onefile, dossier de l'exécutable en
--onedir).
"""

from __future__ import annotations

import sys
from pathlib import Path


def bundled_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent / "vendor"


def fonts_dir() -> Path:
    return bundled_root() / "fonts"
