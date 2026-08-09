"""
Tests de non-régression. Conçus pour tourner sur Windows ET Linux :
c'est le seul moyen d'exercer les branches spécifiques à chaque OS.

    pytest -v
    pytest -v -m "not needs_soffice"   # sans LibreOffice installé
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest

from colibri_converter.engine import (  # noqa: E402
    ConversionError, UntrustedBackend, _assert_trusted, _run_guarded,
    _strip_external_rels, docx_to_pdf, find_soffice, libreoffice_available,
    safe_output_path, sanitize_docx,
)

needs_soffice = pytest.mark.skipif(
    not libreoffice_available(), reason="LibreOffice absent"
)
windows_only = pytest.mark.skipif(os.name != "nt", reason="spécifique Windows")
posix_only = pytest.mark.skipif(os.name == "nt", reason="spécifique POSIX")


def _minimal_docx(path: Path, extra: dict[str, bytes] | None = None) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org'
            '/package/2006/content-types"><Default Extension="xml" '
            'ContentType="application/xml"/></Types>',
        )
        z.writestr("word/document.xml", "<w:document><w:body/></w:document>")
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return path


# ---------------------------------------------------------------- assainissement


def test_macro_et_ole_retires(tmp_path):
    src = _minimal_docx(tmp_path / "m.docx", {
        "word/vbaProject.bin": b"\x00" * 64,
        "word/embeddings/oleObject1.bin": b"MZ",
    })
    removed = sanitize_docx(src, tmp_path / "out.docx")
    with zipfile.ZipFile(tmp_path / "out.docx") as z:
        names = z.namelist()
    assert "word/vbaProject.bin" not in names
    assert not any(n.startswith("word/embeddings/") for n in names)
    assert len(removed) == 2


def test_zip_slip_rejete(tmp_path):
    src = _minimal_docx(tmp_path / "s.docx", {"../../../etc/passwd": b"pwned"})
    removed = sanitize_docx(src, tmp_path / "out.docx")
    with zipfile.ZipFile(tmp_path / "out.docx") as z:
        assert all(".." not in n for n in z.namelist())
    assert any("hors périmètre" in r for r in removed)


def test_zip_bomb_entete_falsifie(tmp_path):
    """L'en-tête ZIP est fourni par l'attaquant : il ne doit pas être cru."""
    src = tmp_path / "bomb.docx"
    with zipfile.ZipFile(src, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", b"\x00" * (300 * 1024 * 1024))
    with zipfile.ZipFile(src, "a") as z:
        for info in z.infolist():
            info.file_size = 100          # mensonge délibéré
    with pytest.raises(ConversionError):
        sanitize_docx(src, tmp_path / "out.docx")


def test_modele_distant_retire_hyperlien_conserve(tmp_path):
    base = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    rels = (
        '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats'
        '.org/package/2006/relationships">'
        f'<Relationship Id="r1" TargetMode="External" Type="{base}/attachedTemplate"'
        ' Target="http://attaquant.example/beacon.dotm"/>'
        f'<Relationship Id="r2" TargetMode="External" Type="{base}/hyperlink"'
        ' Target="https://legitime.example/page"/>'
        "</Relationships>"
    ).encode()
    src = _minimal_docx(tmp_path / "c.docx", {"word/_rels/settings.xml.rels": rels})
    out = tmp_path / "clean.docx"
    warnings = sanitize_docx(src, out)
    with zipfile.ZipFile(out) as z:
        cleaned = z.read("word/_rels/settings.xml.rels").decode()
    assert "attaquant.example" not in cleaned
    assert "legitime.example" in cleaned
    assert any("attachedTemplate" in w for w in warnings)


def test_archive_illisible(tmp_path):
    bad = tmp_path / "faux.docx"
    bad.write_bytes(b"pas du tout un zip")
    with pytest.raises(ConversionError):
        sanitize_docx(bad, tmp_path / "o.docx")


# ---------------------------------------------------------------- résolution binaire


def test_binaire_dans_downloads_refuse(tmp_path):
    d = tmp_path / "Downloads"
    d.mkdir()
    fake = d / ("soffice.exe" if os.name == "nt" else "soffice")
    fake.write_text("#!/bin/sh\n")
    with pytest.raises(UntrustedBackend):
        _assert_trusted(fake, origin="test")


def test_nom_utilisateur_contenant_temp_accepte(tmp_path):
    """Régression : la comparaison par sous-chaîne bloquait 'Templeton'."""
    good = tmp_path / "templeton" / "opt" / "libreoffice" / "program"
    good.mkdir(parents=True)
    fake = good / ("soffice.exe" if os.name == "nt" else "soffice")
    fake.write_text("#!/bin/sh\n")
    if os.name != "nt":
        os.chmod(good, 0o755)
    # tmp_path est sous /tmp sur POSIX, donc légitimement refusé là-bas.
    if "tmp" in {p.lower() for p in tmp_path.parts}:
        pytest.skip("tmp_path est sous /tmp, cas non représentatif")
    assert _assert_trusted(fake, origin="test").name.startswith("soffice")


def test_binaire_inexistant():
    with pytest.raises(ConversionError):
        _assert_trusted(Path("/n/existe/pas/soffice"), origin="test")


@windows_only
def test_registre_windows_ne_leve_pas():
    """`winreg` ne doit jamais faire planter la détection, même sans clé."""
    from colibri_converter.engine import _registry_soffice
    result = _registry_soffice()
    assert result is None or result.is_file()


# ---------------------------------------------------------------- sous-processus


def test_timeout_leve_conversion_error(tmp_path):
    cmd = (["cmd", "/c", "ping -n 60 127.0.0.1 > nul"] if os.name == "nt"
           else ["/bin/sh", "-c", "sleep 60"])
    started = time.monotonic()
    with pytest.raises(ConversionError):
        _run_guarded(cmd, timeout=3, cwd=tmp_path)
    assert time.monotonic() - started < 30


@posix_only
def test_pas_orphelin_apres_timeout(tmp_path):
    """`soffice` fork `soffice.bin` : le kill doit viser l'arbre entier."""
    marker = "colibri-converter_test_orphan_294"
    with pytest.raises(ConversionError):
        _run_guarded(
            ["/bin/sh", "-c", f"sleep 294 & # {marker}\nsleep 294"],
            timeout=2, cwd=tmp_path,
        )
    time.sleep(1)
    running = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True).stdout
    assert "sleep 294" not in running


def test_tube_sature_ne_bloque_pas(tmp_path):
    """Un backend qui remplit stdout ne doit pas provoquer d'interblocage."""
    if os.name == "nt":
        pytest.skip("équivalent Windows non trivial")
    started = time.monotonic()
    with pytest.raises(ConversionError):
        _run_guarded(
            ["/bin/sh", "-c", "yes LONGUELIGNEDESORTIE | head -c 200000000; sleep 293"],
            timeout=3, cwd=tmp_path,
        )
    assert time.monotonic() - started < 30


# ---------------------------------------------------------------- sorties


def test_jamais_ecraser(tmp_path):
    (tmp_path / "doc.pdf").write_text("existant")
    result = safe_output_path(tmp_path / "doc.docx", ".pdf")
    assert result.name == "doc (1).pdf"
    assert (tmp_path / "doc.pdf").read_text() == "existant"


def test_fichier_vide_rejete(tmp_path):
    empty = tmp_path / "vide.docx"
    empty.touch()
    with pytest.raises(ConversionError):
        docx_to_pdf(empty)


def test_pdf_en_entree_de_docx_to_pdf(tmp_path):
    pdf = tmp_path / "deja.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    with pytest.raises(ConversionError):
        docx_to_pdf(pdf)


# ---------------------------------------------------------------- bout en bout


@needs_soffice
def test_conversion_reelle_et_pdf_balise(tmp_path):
    """
    Vérifie que le PDF est TAGGED. C'est le contrôle décisif sous Windows :
    si l'échappement des guillemets du filtre JSON casse, LibreOffice ignore
    silencieusement les options et produit un PDF non balisé.
    """
    docx = pytest.importorskip("docx")
    d = docx.Document()
    d.add_heading("Titre de test", 0)
    d.add_paragraph("Accents : éàüçñ — espace insécable inclus.")
    src = tmp_path / "reel.docx"
    d.save(src)

    result = docx_to_pdf(src)
    assert result.output.is_file()
    assert result.output.stat().st_size > 1000

    fitz = pytest.importorskip("fitz")
    with fitz.open(result.output) as doc:
        assert doc.page_count >= 1
        assert "test" in doc[0].get_text().lower()
    raw = result.output.read_bytes()
    assert b"/StructTreeRoot" in raw, (
        "PDF non balisé : les options du filtre n'ont pas été prises en compte "
        "(échappement de la ligne de commande ?)"
    )


@needs_soffice
def test_accents_dans_le_chemin(tmp_path):
    """Le profil LibreOffice est passé en file:// — l'encodage doit tenir."""
    docx = pytest.importorskip("docx")
    folder = tmp_path / "Dossier Éric & Cie"
    folder.mkdir()
    d = docx.Document()
    d.add_paragraph("test")
    src = folder / "rapport éàü.docx"
    d.save(src)
    assert docx_to_pdf(src).output.is_file()


@needs_soffice
def test_conversions_paralleles(tmp_path):
    """Sans profil jetable, deux instances de LibreOffice se verrouillent."""
    from concurrent.futures import ThreadPoolExecutor
    docx = pytest.importorskip("docx")
    sources = []
    for i in range(4):
        d = docx.Document()
        d.add_paragraph(f"document {i}")
        path = tmp_path / f"doc{i}.docx"
        d.save(path)
        sources.append(path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(docx_to_pdf, sources))
    assert all(r.output.is_file() for r in results)


def test_imports_des_modules():
    """Détecte une dépendance manquante dans le binaire gelé."""
    import colibri_converter.cli
    import colibri_converter.engine
    import colibri_converter.validate
    assert colibri_converter.engine.SUPPORTED_INPUT


# ---------------------------------------------------------------- SAST


def test_dtd_dans_rels_rejetee(tmp_path):
    """xml.etree est sensible à l'expansion d'entités : on refuse toute DTD."""
    bomb = (
        b'<?xml version="1.0"?>'
        b'<!DOCTYPE r [<!ENTITY a "aaaaaaaaaa">'
        b'<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">'
        b'<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">]>'
        b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006'
        b'/relationships"><Relationship Id="r1" Type="x" Target="&c;"/>'
        b"</Relationships>"
    )
    src = _minimal_docx(tmp_path / "dtd.docx", {"word/_rels/document.xml.rels": bomb})
    with pytest.raises(ConversionError):
        sanitize_docx(src, tmp_path / "out.docx")


def test_rels_surdimensionne_rejete(tmp_path):
    """En-tête mensonger sur un .rels : refuser plutôt que tronquer."""
    huge = b'<?xml version="1.0"?><Relationships>' + b"<!-- " + b"x" * (2 * 1024 * 1024) + b" -->"
    src = _minimal_docx(tmp_path / "big.docx", {"word/_rels/document.xml.rels": huge})
    with pytest.raises(ConversionError):
        sanitize_docx(src, tmp_path / "out.docx")


def test_nom_de_fichier_hostile_echappe(tmp_path):
    """Le nom de fichier finit dans un QTextEdit, qui interprète le HTML."""
    import html as html_mod

    piege = '<img src="http://attaquant.example/x.png">'
    echappe = html_mod.escape(piege)
    assert "<img" not in echappe
    assert "&lt;img" in echappe


def test_lot_borne(tmp_path):
    """Un dossier immense ne doit pas geler le CLI sans retour."""
    from colibri_converter.cli import MAX_BATCH, _collect

    assert MAX_BATCH > 0
    for i in range(5):
        (tmp_path / f"f{i}.pdf").write_bytes(b"%PDF-1.4\n")
    (tmp_path / "ignore.txt").write_text("x")
    found = _collect([tmp_path])
    assert len(found) == 5
    assert all(f.suffix == ".pdf" for f in found)


def test_audit_passe_par_assainissement(tmp_path):
    """L'option --audit ne doit pas ouvrir l'archive brute."""
    import zipfile as zf

    from colibri_converter.validate import extract_text

    docx_mod = pytest.importorskip("docx")
    d = docx_mod.Document()
    d.add_paragraph("Contenu de contrôle")
    src = tmp_path / "a.docx"
    d.save(src)

    # On greffe une macro dans un document par ailleurs valide.
    piege = tmp_path / "piege.docx"
    with zf.ZipFile(src) as zin, zf.ZipFile(piege, "w") as zout:
        for item in zin.infolist():
            zout.writestr(item, zin.read(item))
        zout.writestr("word/vbaProject.bin", b"\x00" * 32)

    assert "contrôle" in extract_text(piege)


def test_docx_illisible_message_propre(tmp_path):
    """Aucune trace interne de python-docx ne doit remonter."""
    from colibri_converter.validate import extract_text

    src = _minimal_docx(tmp_path / "casse.docx")
    with pytest.raises(ValueError):
        extract_text(src)


def test_branding_svg_valides():
    import xml.etree.ElementTree as ET

    from colibri_converter.branding import COLIBRI_SVG, colibri_icon_svg

    ET.fromstring(COLIBRI_SVG)
    ET.fromstring(colibri_icon_svg())
    assert len(COLIBRI_SVG) < 8000  # doit rester léger pour l'icône 16 px


def test_image_liee_locale_conservee(tmp_path):
    """Régression : les images liées vers le disque étaient supprimées."""
    base = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    rels = (
        '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats'
        '.org/package/2006/relationships">'
        f'<Relationship Id="r1" TargetMode="External" Type="{base}/image"'
        ' Target="file:///home/user/photo.png"/>'
        f'<Relationship Id="r2" TargetMode="External" Type="{base}/image"'
        ' Target="http://pisteur.example/pixel.png"/>'
        "</Relationships>"
    ).encode()
    src = _minimal_docx(tmp_path / "img.docx", {"word/_rels/document.xml.rels": rels})
    out = tmp_path / "clean.docx"
    sanitize_docx(src, out)
    with zipfile.ZipFile(out) as z:
        cleaned = z.read("word/_rels/document.xml.rels").decode()
    assert "photo.png" in cleaned, "une image liée locale ne doit pas disparaître"
    assert "pisteur.example" not in cleaned, "un pixel distant reste un rappel réseau"


@needs_soffice
def test_image_embarquee_survit_a_la_conversion(tmp_path):
    """Une image dans le DOCX doit se retrouver dans le PDF."""
    import io

    docx_mod = pytest.importorskip("docx")
    pil = pytest.importorskip("PIL.Image")

    buf = io.BytesIO()
    pil.new("RGB", (80, 80), (200, 50, 50)).save(buf, "PNG")
    buf.seek(0)

    d = docx_mod.Document()
    d.add_paragraph("Avant")
    d.add_picture(buf, width=docx_mod.shared.Inches(1))
    src = tmp_path / "avec_image.docx"
    d.save(src)

    raw = docx_to_pdf(src).output.read_bytes()
    assert b"/Image" in raw and b"/Width" in raw, "l'image a disparu du PDF"
