"""colibri_converter.cli — interface ligne de commande (scriptable, CI-friendly)."""

from __future__ import annotations

import argparse
import logging
import multiprocessing
import sys
from pathlib import Path

from .engine import SUPPORTED_INPUT, ConversionError, convert, safe_output_path
from .validate import audit


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="colibri-converter",
        description="Conversion souveraine DOCX <-> PDF, 100%% hors-ligne.",
    )
    p.add_argument("inputs", nargs="+", type=Path, help="Fichiers ou dossiers à convertir")
    p.add_argument("-o", "--outdir", type=Path, default=Path.cwd(), help="Dossier de sortie")
    p.add_argument(
        "--pdfa", action="store_true",
        help="Mode archivage best-effort (polices embarquées, transparence "
             "aplatie) — pas une conformité PDF/A ISO 19005 vérifiée",
    )
    p.add_argument("--ocr", choices=("auto", "always", "never"), default="auto")
    p.add_argument("--ocr-lang", default="fra+eng")
    p.add_argument("--no-sanitize", action="store_true",
                   help="Ne pas retirer macros/OLE du DOCX source (déconseillé)")
    p.add_argument("--audit", action="store_true", help="Contrôle de fidélité après conversion")
    p.add_argument("--fail-under", type=float, default=None, metavar="RATIO",
                   help="Code retour non nul si la fidélité est sous ce seuil (ex: 0.95)")
    p.add_argument("--overwrite", action="store_true",
                   help="Écraser les fichiers de sortie existants")
    p.add_argument("-j", "--jobs", type=int, default=1, help="Conversions en parallèle")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


MAX_BATCH = 5000


def _collect(inputs: list[Path]) -> list[Path]:
    exts = SUPPORTED_INPUT
    files: list[Path] = []
    for item in inputs:
        if item.is_dir():
            for found in item.rglob("*"):
                if found.is_file() and found.suffix.lower() in exts:
                    files.append(found)
                    if len(files) >= MAX_BATCH:
                        print(f"[!] Limite de {MAX_BATCH} fichiers atteinte.",
                              file=sys.stderr)
                        return sorted(files)
        elif item.is_file():
            files.append(item)
        else:
            print(f"[!] Introuvable : {item}", file=sys.stderr)
    return sorted(set(files))


def _target(src: Path, outdir: Path, overwrite: bool) -> Path:
    ext = ".docx" if src.suffix.lower() == ".pdf" else ".pdf"
    if overwrite:
        return outdir / (src.stem + ext)
    # Par défaut, jamais d'écrasement : même règle que l'interface graphique.
    return safe_output_path(src, ext, outdir)


def _one(src: Path, args) -> tuple[Path, bool, str]:
    dst = _target(src, args.outdir, args.overwrite)
    try:
        kwargs = {}
        if src.suffix.lower() == ".pdf":
            kwargs.update(ocr=args.ocr, ocr_lang=args.ocr_lang)
        else:
            kwargs.update(pdfa=args.pdfa, sanitize=not args.no_sanitize)

        result = convert(src, dst, **kwargs)
        lines = [f"OK  {src.name} -> {dst.name}  ({result.duration_s:.1f}s, {result.backend})"]
        lines += [f"    [!] {w}" for w in result.warnings]

        if args.audit:
            report = audit(src, dst)
            lines.append("    " + report.summary().replace("\n", "\n    "))
            if args.fail_under is not None:
                score = report.text_similarity or 0.0
                if score < args.fail_under:
                    return dst, False, "\n".join(lines)

        return dst, True, "\n".join(lines)

    except ConversionError as exc:
        return dst, False, f"KO  {src.name} : {exc}"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    args.jobs = max(1, min(args.jobs, 16))  # 0 ou négatif ferait échouer le pool
    files = _collect(args.inputs)
    if not files:
        print("Aucun fichier convertible.", file=sys.stderr)
        return 2

    args.outdir.mkdir(parents=True, exist_ok=True)
    failures = 0

    if args.jobs > 1:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(max_workers=args.jobs) as pool:
            for _, ok, msg in pool.map(_one, files, [args] * len(files)):
                print(msg)
                failures += not ok
    else:
        for src in files:
            _, ok, msg = _one(src, args)
            print(msg)
            failures += not ok

    print(f"\n{len(files) - failures}/{len(files)} conversion(s) réussie(s).")
    return 1 if failures else 0


if __name__ == "__main__":
    multiprocessing.freeze_support()  # obligatoire pour les builds PyInstaller
    sys.exit(main())
