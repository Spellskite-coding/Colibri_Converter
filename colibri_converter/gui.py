"""Interface graphique : glisser-déposer, conversion, résultat."""

from __future__ import annotations

import html
import logging
import sys
from pathlib import Path

from PySide6.QtCore import QByteArray, QObject, QSize, QThread, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QFont, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QMessageBox,
    QProgressBar, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from . import __version__, branding as B
from .engine import SUPPORTED_INPUT, ConversionError, convert, libreoffice_available

log = logging.getLogger("colibri_converter.gui")

DOWNLOAD_URL = "https://www.libreoffice.org/download/download-libreoffice/"


def svg_pixmap(svg: str, size: int, ratio: float = 1.0) -> QPixmap:
    """
    Rastérise un SVG à la densité réelle de l'écran.
    Rendre à `size` puis laisser Qt agrandir donnerait un logo flou sur un
    écran HiDPI : on rend directement à la taille physique.
    """
    physical = max(1, int(size * ratio))
    pixmap = QPixmap(physical, physical)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        QSvgRenderer(QByteArray(svg.encode())).render(painter)
    finally:
        painter.end()  # sans ça le QPixmap reste verrouillé et Qt avertit
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


_ICON_CACHE: QIcon | None = None


def app_icon() -> QIcon:
    """Icône multi-tailles, construite une seule fois par session."""
    global _ICON_CACHE
    if _ICON_CACHE is None:
        icon = QIcon()
        svg = B.colibri_icon_svg()
        for size in (16, 24, 32, 48, 64, 128, 256):
            icon.addPixmap(svg_pixmap(svg, size))
        _ICON_CACHE = icon
    return _ICON_CACHE


STYLESHEET = f"""
QWidget#root {{ background: {B.CANVAS}; }}
QLabel#title {{ color: {B.INK}; font-size: 21px; font-weight: 600; }}
QLabel#tagline {{ color: {B.INK_SOFT}; font-size: 12px; }}
QLabel#status {{ color: {B.INK_SOFT}; font-size: 12px; }}
QLabel#footer {{ color: {B.MUTED}; font-size: 11px; }}

QFrame#banner {{
    background: {B.WARN_BG}; border: 1px solid {B.WARN_LINE};
    border-radius: 12px;
}}
QLabel#bannerText {{ color: {B.WARN_INK}; font-size: 12px; }}

QPushButton {{
    background: {B.SURFACE}; color: {B.INK};
    border: 1px solid {B.LINE}; border-radius: 9px;
    padding: 9px 16px; font-size: 12px;
}}
QPushButton:hover {{ background: {B.ACCENT_BG}; border-color: {B.MINT}; }}
QPushButton:pressed {{ background: {B.MINT_LIGHT}; }}
QPushButton:disabled {{ color: {B.MUTED}; background: {B.CANVAS}; }}
QPushButton#primary {{
    background: {B.MINT}; border: 1px solid {B.TEAL_SOFT}; color: #05343A;
    font-weight: 600;
}}
QPushButton#primary:hover {{ background: {B.MINT_LIGHT}; }}

QProgressBar {{
    background: {B.LINE}; border: none; border-radius: 5px;
    height: 8px; text-align: center; color: transparent;
}}
QProgressBar::chunk {{ background: {B.MINT}; border-radius: 5px; }}

QTextEdit {{
    background: {B.SURFACE}; border: 1px solid {B.LINE};
    border-radius: 12px; padding: 10px; color: {B.INK};
    selection-background-color: {B.MINT_LIGHT};
}}
"""


class Worker(QObject):
    """Exécute les conversions hors du thread graphique."""

    progress = Signal(int, int, str)
    file_done = Signal(str)
    file_failed = Signal(str)
    finished = Signal(int, int)

    def __init__(self, files: list[Path]) -> None:
        super().__init__()
        self._files = files
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        ok = failed = 0
        total = len(self._files)
        try:
            for index, src in enumerate(self._files, start=1):
                if self._cancelled:
                    break
                self.progress.emit(index, total, src.name)
                try:
                    result = convert(src)
                    # Tout ce qui vient du système de fichiers ou du document
                    # est échappé : QTextEdit interprète le HTML, et les
                    # avertissements contiennent des URL issues du document.
                    body = (
                        f'<div style="margin-bottom:6px">'
                        f'<span style="color:{B.OK_INK}">&#10003;</span> '
                        f'<b>{html.escape(src.name)}</b> &rarr; '
                        f'{html.escape(result.output.name)} '
                        f'<span style="color:{B.MUTED}">'
                        f'({result.duration_s:.1f}&nbsp;s)</span>'
                    )
                    for warning in result.warnings:
                        body += (f'<br><span style="color:{B.WARN_INK}">'
                                 f'&#9888; {html.escape(warning)}</span>')
                    self.file_done.emit(body + "</div>")
                    ok += 1
                except ConversionError as exc:
                    self.file_failed.emit(
                        f'<div style="margin-bottom:6px">'
                        f'<span style="color:{B.ERR_INK}">&#10007;</span> '
                        f'<b>{html.escape(src.name)}</b><br>'
                        f'<span style="color:{B.MUTED}">'
                        f'{html.escape(str(exc))}</span></div>'
                    )
                    failed += 1
                except Exception as exc:
                    log.exception("Erreur inattendue sur %s", src)
                    self.file_failed.emit(
                        f'<div><span style="color:{B.ERR_INK}">&#10007;</span> '
                        f'<b>{html.escape(src.name)}</b> — '
                        f'erreur interne : {html.escape(str(exc))}</div>'
                    )
                    failed += 1
        finally:
            self.finished.emit(ok, failed)


class DropZone(QFrame):
    """Zone de dépôt, avec le colibri en filigrane."""

    dropped = Signal(list)

    def __init__(self, ratio: float) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.setMinimumHeight(190)
        self.setObjectName("dropzone")

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(10)

        self.mark = QLabel()
        self.mark.setPixmap(svg_pixmap(B.COLIBRI_WATERMARK, 88, ratio))
        self.mark.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.title = QLabel("Déposez vos fichiers ici")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setStyleSheet(
            f"color:{B.INK}; font-size:15px; font-weight:600; background:transparent;"
        )

        subtitle = QLabel("Word → PDF   ·   PDF → Word")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet(
            f"color:{B.INK_SOFT}; font-size:12px; background:transparent;"
        )

        layout.addWidget(self.mark)
        layout.addWidget(self.title)
        layout.addWidget(subtitle)
        self._set_active(False)

    def _set_active(self, active: bool) -> None:
        border = B.MINT if active else B.LINE
        fill = B.ACCENT_BG if active else B.SURFACE
        self.setStyleSheet(
            f"#dropzone {{ border: 2px dashed {border}; border-radius: 16px; "
            f"background: {fill}; }}"
        )
        self.title.setText(
            "Relâchez pour convertir" if active else "Déposez vos fichiers ici"
        )

    @staticmethod
    def _extract(event) -> list[Path]:
        files = []
        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue  # application hors-ligne : on ignore les URL distantes
            path = Path(url.toLocalFile())
            if path.is_file() and path.suffix.lower() in SUPPORTED_INPUT:
                files.append(path)
        return files

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls() and self._extract(event):
            event.acceptProposedAction()
            self._set_active(True)

    def dragLeaveEvent(self, event) -> None:
        self._set_active(False)

    def dropEvent(self, event) -> None:
        self._set_active(False)
        files = list(dict.fromkeys(self._extract(event)))  # dédoublonne
        if files:
            event.acceptProposedAction()
            self.dropped.emit(files)


class MainWindow(QWidget):
    def __init__(self, initial: list[Path] | None = None) -> None:
        super().__init__()
        self.setObjectName("root")
        self.setWindowTitle(B.APP_NAME)
        self.setWindowIcon(app_icon())
        self.setMinimumSize(660, 620)
        self.setStyleSheet(STYLESHEET)

        ratio = self.devicePixelRatioF() or 1.0
        self._thread: QThread | None = None
        self._worker: Worker | None = None
        self._closing = False

        root = QVBoxLayout(self)
        root.setSpacing(14)
        root.setContentsMargins(24, 22, 24, 20)

        root.addLayout(self._build_header(ratio))
        root.addWidget(self._build_banner())

        self.dropzone = DropZone(ratio)
        self.dropzone.dropped.connect(self.start)
        root.addWidget(self.dropzone)

        actions = QHBoxLayout()
        browse = QPushButton("Choisir des fichiers…")
        browse.setObjectName("primary")
        browse.clicked.connect(self.browse)
        actions.addWidget(browse)
        actions.addStretch()
        root.addLayout(actions)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        root.addWidget(self.progress)

        self.status = QLabel("Prêt.")
        self.status.setObjectName("status")
        root.addWidget(self.status)

        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.document().setMaximumBlockCount(5000)  # borne la mémoire
        root.addWidget(self.output, stretch=1)

        footer = QLabel(
            "Le fichier converti est enregistré à côté de l'original. "
            "Aucune donnée ne quitte votre ordinateur."
        )
        footer.setObjectName("footer")
        footer.setWordWrap(True)
        root.addWidget(footer)

        self.refresh_backend()
        if initial:
            self.start(initial)

    # -- Construction --------------------------------------------------------

    def _build_header(self, ratio: float) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setSpacing(14)

        logo = QLabel()
        logo.setPixmap(svg_pixmap(B.COLIBRI_SVG, 58, ratio))
        logo.setFixedSize(QSize(58, 58))
        header.addWidget(logo)

        text = QVBoxLayout()
        text.setSpacing(2)
        title = QLabel(B.APP_NAME)
        title.setObjectName("title")
        tagline = QLabel(B.TAGLINE)
        tagline.setObjectName("tagline")
        text.addWidget(title)
        text.addWidget(tagline)
        header.addLayout(text)
        header.addStretch()

        version = QLabel(f"v{__version__}")
        version.setObjectName("footer")
        header.addWidget(version, alignment=Qt.AlignmentFlag.AlignBottom)
        return header

    def _build_banner(self) -> QFrame:
        self.banner = QFrame()
        self.banner.setObjectName("banner")
        layout = QVBoxLayout(self.banner)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(9)

        message = QLabel(
            "<b>LibreOffice est nécessaire</b><br>"
            "Il fournit le moteur de conversion. Installez-le, puis cliquez "
            "sur « Revérifier » — inutile de relancer l'application."
        )
        message.setObjectName("bannerText")
        message.setWordWrap(True)
        layout.addWidget(message)

        buttons = QHBoxLayout()
        download = QPushButton("Ouvrir la page de téléchargement")
        download.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(DOWNLOAD_URL)))
        recheck = QPushButton("Revérifier")
        recheck.clicked.connect(self.refresh_backend)
        buttons.addWidget(download)
        buttons.addWidget(recheck)
        buttons.addStretch()
        layout.addLayout(buttons)
        return self.banner

    # -- Backend -------------------------------------------------------------

    def refresh_backend(self) -> bool:
        available = libreoffice_available()
        self.banner.setVisible(not available)
        self.dropzone.setEnabled(available)
        self.status.setText("Prêt." if available else "En attente de LibreOffice.")
        return available

    # -- Conversion ----------------------------------------------------------

    def browse(self) -> None:
        patterns = " ".join(f"*{e}" for e in sorted(SUPPORTED_INPUT))
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Fichiers à convertir", "", f"Documents ({patterns})"
        )
        if paths:
            self.start([Path(p) for p in paths])

    def start(self, files: list[Path]) -> None:
        if not files:
            return
        if self._thread is not None:
            QMessageBox.information(
                self, "Conversion en cours",
                "Attendez la fin de la conversion en cours."
            )
            return
        if not self.refresh_backend():
            return

        self.output.clear()
        self.progress.setVisible(True)
        self.progress.setRange(0, len(files))
        self.progress.setValue(0)

        self._thread = QThread(self)
        self._worker = Worker(files)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        # Destruction pilotée par la fin du THREAD : un deleteLater mis en file
        # dans une boucle qu'on va fermer ne serait jamais traité.
        self._thread.finished.connect(self._worker.deleteLater)
        self._worker.progress.connect(self._on_progress)
        self._worker.file_done.connect(self.output.append)
        self._worker.file_failed.connect(self.output.append)
        self._worker.finished.connect(self._on_finished)
        self._thread.start()

    def _on_progress(self, index: int, total: int, name: str) -> None:
        self.progress.setValue(index - 1)
        self.status.setText(f"Conversion {index}/{total} — {name}")

    def _on_finished(self, ok: int, failed: int) -> None:
        self.progress.setValue(self.progress.maximum())
        self.status.setText(
            f"Terminé — {ok} réussie(s)" + (f", {failed} en échec" if failed else "")
        )
        self._teardown()
        if self._closing:
            self.close()

    def _teardown(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            if not self._thread.wait(10_000):
                log.error("Thread de conversion non terminé dans les délais.")
            self._thread.deleteLater()
        self._thread = None
        self._worker = None

    def closeEvent(self, event) -> None:
        if self._worker is None:
            event.accept()
            return
        # Un backend natif ne s'interrompt pas. Détruire le QThread ici
        # provoquerait un abandon du processus : on diffère la fermeture.
        self._closing = True
        self._worker.cancel()
        self.status.setText("Fermeture après le fichier en cours…")
        event.ignore()


def run(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    initial = [
        Path(a) for a in argv[1:]
        if not a.startswith("-") and Path(a).is_file()
        and Path(a).suffix.lower() in SUPPORTED_INPUT
    ]
    app = QApplication.instance() or QApplication(argv)
    app.setApplicationName(B.APP_NAME)
    app.setWindowIcon(app_icon())
    font = QFont()
    font.setPointSize(10)
    app.setFont(font)

    window = MainWindow(initial)
    window.show()
    return app.exec()
