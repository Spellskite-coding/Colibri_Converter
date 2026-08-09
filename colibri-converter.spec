# -*- mode: python ; coding: utf-8 -*-
"""
Spécification PyInstaller.

    python tools/make_icons.py                            # icônes d'abord
    pyinstaller --noconfirm --clean colibri-converter.spec

LibreOffice n'est PAS embarqué : il est détecté sur le poste. Cela évite de
redistribuer un moteur C++ figé qu'il faudrait repatcher à chaque CVE.
"""
import os
import sys

block_cipher = None

# L'icône est produite depuis le SVG de branding.py. Absente, le build reste
# fonctionnel : on n'échoue pas pour un détail cosmétique.
_ico = "colibri.icns" if sys.platform == "darwin" else "colibri.ico"
_path = os.path.join("build", "icons", _ico)
ICON = _path if os.path.exists(_path) else None

# Fichier unique par défaut : un exécutable déplaçable n'importe où, sans
# dossier compagnon. Prix à payer : 2 à 5 s de démarrage, le temps que le
# contenu s'extraie dans un dossier temporaire.
# ONEFILE=0 dans l'environnement pour revenir au mode dossier (démarrage
# instantané, mais l'exécutable ne fonctionne plus hors de son dossier).
ONEFILE = os.environ.get("ONEFILE", "1") != "0"

# Modules lourds jamais utilisés : les exclure divise le poids par deux.
EXCLUDES = [
    "tkinter", "matplotlib", "IPython", "pytest", "setuptools", "pip",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
    "PySide6.QtMultimedia", "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtNetwork",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtSql",
    "PySide6.QtTest", "PySide6.QtBluetooth", "PySide6.QtPositioning",
    # QtSvg est volontairement absent de cette liste : le logo en dépend.
    "scipy", "pandas",
]

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        "colibri_converter.engine", "colibri_converter.gui",
        "colibri_converter.validate", "colibri_converter.cli",
        "colibri_converter.branding",
        "PySide6.QtSvg",         # rendu du logo : non détecté automatiquement
        "pdf2docx", "fitz", "docx", "defusedxml.ElementTree",
        "multiprocessing.spawn",  # le worker PDF utilise le mode spawn
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDES,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

_common = dict(
    name="colibri-converter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX déclenche des faux positifs antivirus
    console=False,      # pas de console noire au lancement
    disable_windowed_traceback=False,
    argv_emulation=(sys.platform == "darwin"),  # glisser-déposer sur l'icône
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON,
)

if ONEFILE:
    exe = EXE(
        pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
        exclude_binaries=False,
        runtime_tmpdir=None,
        **_common,
    )
    coll = exe          # rien à collecter : l'exécutable contient déjà tout
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **_common)
    coll = COLLECT(
        exe, a.binaries, a.zipfiles, a.datas,
        strip=False, upx=False, name="colibri-converter",
    )

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Colibri Converter.app",
        icon=ICON,
        bundle_identifier="dev.colibri-converter.app",
        info_plist={
            "NSHighResolutionCapable": True,
            "CFBundleDocumentTypes": [{
                "CFBundleTypeName": "Document",
                "CFBundleTypeRole": "Viewer",
                "LSItemContentTypes": [
                    "com.adobe.pdf",
                    "org.openxmlformats.wordprocessingml.document",
                ],
            }],
        },
    )
