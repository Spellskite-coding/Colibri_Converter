"""
Point d'entrée du worker isolé : parse le .docx puis rend le PDF, dans un
processus séparé (voir isolation.py). Le parsing OOXML est désormais fait en
Python dans le processus de rendu (python-docx/lxml) : c'est une surface
d'attaque sur fichier hostile qui a besoin de la même isolation mémoire/
timeout que le worker pdf2docx existant, plutôt que de bénéficier
"gratuitement" de la frontière de processus qu'offrait `soffice` avant.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ..paths import fonts_dir
from . import ooxml_parser, pdf_writer
from .isolation import WorkerFailed, apply_worker_limits, run_isolated

log = logging.getLogger("colibri_converter.render.worker")


def _worker(src: str, dst: str, warnings_path: str, pdfa: bool) -> None:
    apply_worker_limits()
    model = ooxml_parser.parse(Path(src))
    pdf_writer.render(model, Path(dst), fonts_dir(), pdfa=pdfa)
    Path(warnings_path).write_text(json.dumps(model.warnings), encoding="utf-8")


def render_docx_isolated(src: Path, dst: Path, *, pdfa: bool, timeout: int) -> list[str]:
    """
    Rend `src` (.docx) en PDF vers `dst`, dans un processus isolé.

    Retourne les avertissements accumulés pendant le parsing/rendu (formats
    non pris en charge, listes non résolues, images manquantes...). Lève
    TimeoutError ou RuntimeError en cas d'échec — à l'appelant (engine.py)
    de traduire en ConversionError avec un message adapté.
    """
    warnings_path = dst.with_suffix(dst.suffix + ".warnings.json")
    try:
        run_isolated(
            _worker, (str(src), str(dst), str(warnings_path), pdfa),
            timeout=timeout, output_path=dst,
        )
    except WorkerFailed as exc:
        if exc.kind == "timeout":
            raise TimeoutError(f"Rendu interrompu après {timeout}s.") from None
        if exc.kind == "crash":
            raise RuntimeError(f"Échec du rendu (code {exc.detail}).") from None
        raise RuntimeError("Le rendu n'a produit aucun contenu exploitable.") from None

    warnings: list[str] = []
    if warnings_path.is_file():
        try:
            warnings = json.loads(warnings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.debug("Avertissements du worker illisibles : %s", exc)
        finally:
            warnings_path.unlink(missing_ok=True)
    return warnings
