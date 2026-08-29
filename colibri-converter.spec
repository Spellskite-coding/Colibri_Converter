# -*- mode: python ; coding: utf-8 -*-
"""
Spécification PyInstaller.

    python tools/make_icons.py                            # icônes d'abord
    pyinstaller --noconfirm --clean colibri-converter.spec

Aucun programme externe n'est requis : la conversion DOCX -> PDF est faite
par le moteur de rendu maison (colibri_converter/render/, basé sur
ReportLab), embarqué comme le reste du code Python. Les polices de
substitution (Liberation/Carlito/Caladea, vendor/fonts/) sont embarquées via
`datas` ci-dessous — sans elles, le moteur de rendu n'a plus accès à ses
polices de repli une fois figé en exécutable.
"""
import glob
import os
import sys

block_cipher = None

# Résolu explicitement en Python plutôt que via un motif glob confié à
# PyInstaller : ça garantit que chaque police manquante ferait échouer le
# build tout de suite, au lieu d'un exécutable qui démarre mais dégrade
# silencieusement au premier rendu.
_FONT_FILES = sorted(glob.glob(os.path.join("vendor", "fonts", "*.ttf")))
if not _FONT_FILES:
    raise SystemExit(
        "Aucune police trouvée dans vendor/fonts/ : le moteur de rendu en a "
        "besoin. Vérifie que le dossier vendor/fonts/ est bien présent."
    )
# Destination "fonts" (pas "vendor/fonts") : une fois figé, colibri_converter.paths.
# bundled_root() pointe directement sur la racine d'extraction PyInstaller
# (_MEIPASS), sans le dossier "vendor" intermédiaire qui n'existe qu'en
# développement. Les deux doivent s'accorder pour que fonts_dir() trouve les
# polices aussi bien en mode dev qu'une fois packagé.
FONT_DATAS = [(f, "fonts") for f in _FONT_FILES]

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
    datas=FONT_DATAS,
    hiddenimports=[
        "colibri_converter.engine", "colibri_converter.gui",
        "colibri_converter.validate", "colibri_converter.cli",
        "colibri_converter.branding", "colibri_converter.paths",
        "colibri_converter.render", "colibri_converter.render.ooxml_parser",
        "colibri_converter.render.pdf_writer", "colibri_converter.render.worker",
        "colibri_converter.render.font_resolver", "colibri_converter.render.image_extractor",
        "colibri_converter.render.isolation", "colibri_converter.render.model",
        "PySide6.QtSvg",         # rendu du logo : non détecté automatiquement
        "pdf2docx", "fitz", "docx", "defusedxml.ElementTree",
        "reportlab.pdfbase.pdfmetrics", "reportlab.pdfbase.ttfonts",
        "reportlab.platypus", "PIL", "PIL.Image",
        "multiprocessing.spawn",  # les workers isolés utilisent le mode spawn
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
