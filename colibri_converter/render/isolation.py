"""
Isolation générique d'un worker dans un processus séparé.

Réutilisé par le parseur PDF (pdf2docx, dans engine.py) et par le moteur de
rendu DOCX -> PDF (render/pdf_writer.py) : les deux analysent du contenu de
provenance non fiable, donc les deux ont besoin d'une limite mémoire dure et
d'un timeout, dans un processus qu'on peut détruire sans laisser de restes.
Avant ce module, chaque appelant réimplémentait ce ballet spawn/terminate/
kill/join à l'identique ; le factoriser ici évite que les deux copies
divergent avec le temps.
"""

from __future__ import annotations

import logging
import multiprocessing as mp
import os
from pathlib import Path
from collections.abc import Callable

log = logging.getLogger("colibri_converter.render.isolation")

# Plafond RAM par défaut d'un worker isolé. 3 Gio est généreux pour du texte
# ou des images de taille raisonnable ; un appelant peut passer une valeur
# différente s'il a des besoins mémoire spécifiques — voir le commentaire
# dans engine.py sur pourquoi on ne mutualise pas une seule constante globale
# entre workers aux profils mémoire potentiellement différents.
DEFAULT_MEMORY_LIMIT = 3 * 1024**3


def apply_worker_limits(memory_limit: int = DEFAULT_MEMORY_LIMIT) -> None:
    """
    À appeler en tout premier dans le corps du worker (pas avant le fork/spawn
    via preexec_fn : ce n'est pas sûr dans un programme à threads).

    Plafonner l'adressage mémoire transforme une allocation aberrante (PDF
    malformé, document piégé, image bombe) en MemoryError propre au lieu d'un
    OOM killer sur toute la session hôte.
    """
    if os.name == "nt":
        return
    try:
        import resource

        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        target = (
            memory_limit
            if hard == resource.RLIM_INFINITY
            else min(memory_limit, hard)
        )
        resource.setrlimit(resource.RLIMIT_AS, (target, hard))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))  # pas de core dump : fuite de données
    except (ImportError, ValueError, OSError) as exc:
        log.debug("Limites de ressources non appliquées : %s", exc)


class WorkerFailed(RuntimeError):
    """
    Le worker isolé a échoué. `kind` vaut "timeout", "crash" ou "empty" —
    à l'appelant de traduire en ConversionError avec un message adapté à sa
    propre direction de conversion plutôt que d'exposer ce détail interne.
    """

    def __init__(self, kind: str, detail: str = "") -> None:
        self.kind = kind
        self.detail = detail
        super().__init__(f"{kind}: {detail}" if detail else kind)


def run_isolated(
    target: Callable[..., None],
    args: tuple,
    *,
    timeout: int,
    output_path: Path | None = None,
) -> None:
    """
    Lance `target(*args)` dans un processus spawn dédié, avec destruction
    garantie en cas de timeout ou de fin anormale.

    `target` DOIT être une fonction de module top-level (picklable par le
    contexte spawn) : pas de closure, pas de lambda, pas de méthode liée.

    Si `output_path` est fourni, son existence et sa non-vacuité après coup
    font partie du contrat de succès — un code de retour 0 sans fichier de
    sortie exploitable est traité comme un échec, pas comme une réussite.
    """
    ctx = mp.get_context("spawn")  # spawn : pas d'héritage d'état du parent
    proc = ctx.Process(target=target, args=args, daemon=True)
    proc.start()
    try:
        proc.join(timeout)
        if proc.is_alive():
            proc.terminate()
            proc.join(5)
            if proc.is_alive():
                proc.kill()
                proc.join(5)
            raise WorkerFailed("timeout")
        if proc.exitcode != 0:
            raise WorkerFailed("crash", str(proc.exitcode))
        if output_path is not None and (
            not output_path.is_file() or output_path.stat().st_size == 0
        ):
            raise WorkerFailed("empty")
    finally:
        # Ce bloc ne doit jamais lever : il masquerait l'exception d'origine
        # et l'appelant verrait une erreur sans rapport avec la panne réelle.
        try:
            if proc.is_alive():
                proc.kill()
            proc.join(timeout=5)
            proc.close()
        except (ValueError, OSError) as exc:
            log.debug("Nettoyage du worker incomplet : %s", exc)
