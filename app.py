#!/usr/bin/env python3
"""Point d'entrée graphique (cible PyInstaller)."""

from __future__ import annotations

import logging
import multiprocessing
import os
import sys
import tempfile
import traceback
from pathlib import Path


def _log_file() -> Path:
    """Journal dans le dossier de données utilisateur, jamais à côté du binaire."""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Logs"
    else:
        base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    directory = base / "colibri-converter"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        return directory / "colibri-converter.log"
    except OSError:
        return Path(tempfile.gettempdir()) / "colibri-converter.log"


def _setup_logging() -> Path:
    path = _log_file()
    handlers: list[logging.Handler] = []
    try:
        from logging.handlers import RotatingFileHandler
        # Rotation : un journal non borné finit par saturer le disque.
        handlers.append(RotatingFileHandler(
            path, maxBytes=1024 * 1024, backupCount=2, encoding="utf-8"
        ))
    except OSError:
        pass
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler(sys.stderr))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )
    return path


def _install_excepthook(log_path: Path) -> None:
    def hook(exc_type, exc_value, exc_tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logging.critical(
            "Exception non gérée\n%s",
            "".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
        )
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox
            if QApplication.instance() is not None:
                QMessageBox.critical(
                    None, "colibri-converter — erreur inattendue",
                    f"{exc_type.__name__} : {exc_value}\n\nDétails : {log_path}",
                )
        except Exception:
            pass

    sys.excepthook = hook


def main() -> int:
    log_path = _setup_logging()
    _install_excepthook(log_path)
    logging.info("Démarrage — Python %s sur %s", sys.version.split()[0], sys.platform)

    try:
        from colibri_converter.gui import run
    except ImportError as exc:
        logging.critical("Dépendance graphique manquante : %s", exc)
        # sys.stderr vaut None dans un binaire PyInstaller --windowed :
        # print() y lèverait AttributeError et masquerait la cause réelle.
        if sys.stderr is not None:
            print(
                "Interface graphique indisponible (PySide6 absent).\n"
                "Utilisez la ligne de commande : python -m colibri_converter.cli <fichier>",
                file=sys.stderr,
            )
        return 3

    return run(sys.argv)


if __name__ == "__main__":
    # OBLIGATOIRE avant toute autre initialisation : sans cet appel, un binaire
    # PyInstaller relance l'application entière à chaque `spawn` d'un worker,
    # ce qui produit une bombe à fork sous Windows.
    multiprocessing.freeze_support()
    sys.exit(main())
