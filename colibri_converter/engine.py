"""
Moteur de conversion DOCX <-> PDF, hors-ligne.

Les fichiers d'entrée sont traités comme non fiables : voir SECURITY.md.
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger("colibri_converter.engine")

# --------------------------------------------------------------------------
# Garde-fous de ressources
# --------------------------------------------------------------------------

MAX_INPUT_BYTES = 512 * 1024 * 1024        # refus au-delà : pas de DoS par taille
MAX_UNCOMPRESSED_BYTES = 2 * 1024**3       # zip-bomb : total décompressé
MAX_COMPRESSION_RATIO = 200                # zip-bomb : ratio par entrée
MAX_ZIP_ENTRIES = 10_000                   # zip-bomb : nombre d'entrées
WORKER_MEMORY_LIMIT = 3 * 1024**3          # plafond RAM du parseur PDF


class ConversionError(RuntimeError):
    """Erreur de conversion irrécupérable, message destiné à l'utilisateur."""


class BackendNotFound(ConversionError):
    """LibreOffice (ou une autre dépendance native) est introuvable."""


class UntrustedBackend(ConversionError):
    """Un binaire a été trouvé à un emplacement non fiable : on refuse de l'exécuter."""


@dataclass
class ConversionResult:
    source: Path
    output: Path
    backend: str
    duration_s: float = 0.0
    warnings: list[str] = field(default_factory=list)
    ocr_applied: bool = False


# --------------------------------------------------------------------------
# Résolution durcie du binaire LibreOffice
# --------------------------------------------------------------------------

_SOFFICE_CANDIDATES = {
    "Windows": [
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ],
    "Darwin": [
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        "/opt/homebrew/bin/soffice",
        "/usr/local/bin/soffice",
    ],
    "Linux": [
        "/usr/bin/soffice",
        "/usr/bin/libreoffice",
        "/usr/lib/libreoffice/program/soffice",
        "/opt/libreoffice/program/soffice",
        "/snap/bin/libreoffice",
        "/var/lib/flatpak/exports/bin/org.libreoffice.LibreOffice",
    ],
}

# Emplacements inscriptibles par un utilisateur non privilégié : un soffice.exe
# qui s'y trouve est soit un leurre, soit une install non maîtrisée.
_UNTRUSTED_MARKERS = frozenset({
    "downloads", "téléchargements", "temp", "tmp", "temporary internet files",
    "desktop", "bureau",
})


def _bundled_root() -> Path:
    """Racine des ressources embarquées (compatible PyInstaller --onefile/--onedir)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent / "vendor"


def _registry_soffice() -> Optional[Path]:
    """Sous Windows, la base de registre est la source la plus fiable."""
    if os.name != "nt":
        return None
    try:
        import winreg
    except ImportError:
        return None

    probes = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\LibreOffice\UNO\InstallPath", None, True),
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\soffice.exe", None, False),
    ]
    for hive, subkey, value, is_dir in probes:
        for flag in (0, getattr(winreg, "KEY_WOW64_64KEY", 0), getattr(winreg, "KEY_WOW64_32KEY", 0)):
            try:
                with winreg.OpenKey(hive, subkey, 0, winreg.KEY_READ | flag) as key:
                    raw, _ = winreg.QueryValueEx(key, value)
            except OSError:
                continue
            candidate = Path(str(raw).strip('"'))
            candidate = candidate / "soffice.exe" if is_dir else candidate
            if candidate.is_file():
                return candidate
    return None


def _is_world_writable(path: Path) -> bool:
    """POSIX : un répertoire inscriptible par tous sur le chemin = vecteur de substitution."""
    if os.name == "nt":
        return False
    try:
        for parent in [path, *path.parents]:
            if parent.exists() and (parent.stat().st_mode & 0o002) and not (parent.stat().st_mode & 0o1000):
                return True
    except OSError:
        return True
    return False


def _assert_trusted(binary: Path, *, origin: str) -> Path:
    """
    Refuse d'exécuter un binaire situé à un emplacement manipulable.
    C'est la contre-mesure au détournement de résolution (PATH / CWD hijacking).
    """
    try:
        resolved = binary.resolve(strict=True)
    except OSError as exc:
        raise BackendNotFound(f"Binaire inaccessible : {binary}") from exc

    if not resolved.is_file():
        raise UntrustedBackend(f"{resolved} n'est pas un fichier régulier.")

    # Jamais le répertoire courant : c'est le scénario de substitution classique.
    try:
        if resolved.parent == Path.cwd().resolve():
            raise UntrustedBackend(
                f"Binaire trouvé dans le répertoire courant ({resolved}) : refusé."
            )
    except OSError as exc:
        # Non bloquant : si le répertoire courant est illisible, on saute
        # simplement cette comparaison plutôt que de faire échouer toute
        # la résolution du binaire pour une vérification secondaire.
        log.debug("Comparaison au répertoire courant ignorée : %s", exc)

    # Comparaison par COMPOSANT de chemin, pas par sous-chaîne : un
    # utilisateur nommé "Templeton" contient "temp" et serait bloqué à tort.
    parts = {part.lower().strip() for part in resolved.parts}
    if parts & _UNTRUSTED_MARKERS:
        raise UntrustedBackend(
            f"Binaire situé dans un dossier temporaire ou de téléchargement ({resolved}) : "
            "refusé. Installe LibreOffice normalement."
        )

    if _is_world_writable(resolved.parent):
        raise UntrustedBackend(
            f"Le dossier {resolved.parent} est inscriptible par tous : exécution refusée."
        )

    log.debug("Backend retenu (%s) : %s", origin, resolved)
    return resolved


def find_soffice() -> Path:
    """
    Résout LibreOffice par ordre de fiabilité décroissante.
    Le PATH est consulté en dernier et reste soumis à validation.
    """
    override = os.environ.get("COLIBRI_SOFFICE")
    if override:
        return _assert_trusted(Path(override), origin="COLIBRI_SOFFICE")

    bundled = _bundled_root() / "libreoffice" / "program" / (
        "soffice.exe" if os.name == "nt" else "soffice"
    )
    if bundled.is_file():
        # Embarqué dans notre propre bundle : périmètre de confiance de l'app.
        return bundled.resolve()

    from_registry = _registry_soffice()
    if from_registry:
        return _assert_trusted(from_registry, origin="registre")

    for candidate in _SOFFICE_CANDIDATES.get(platform.system(), []):
        if Path(candidate).is_file():
            return _assert_trusted(Path(candidate), origin="chemin connu")

    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return _assert_trusted(Path(found), origin="PATH")

    raise BackendNotFound(
        "LibreOffice est introuvable sur ce poste.\n"
        "Installe-le depuis https://www.libreoffice.org/download/ "
        "puis relance la conversion."
    )


def libreoffice_available() -> bool:
    """Test non bloquant, pour l'interface."""
    try:
        find_soffice()
        return True
    except ConversionError:
        return False


# --------------------------------------------------------------------------
# Exécution surveillée d'un sous-processus
# --------------------------------------------------------------------------


def _hardened_env() -> dict[str, str]:
    """Environnement des backends : aucune sortie réseau possible, pas d'accélération GPU."""
    env = dict(os.environ)
    for var in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
                "ALL_PROXY", "all_proxy", "FTP_PROXY", "ftp_proxy"):
        env.pop(var, None)
    env["no_proxy"] = "*"
    env["NO_PROXY"] = "*"
    env["SAL_DISABLE_OPENCL"] = "1"          # OpenCL = source classique de crash headless
    env["SAL_DISABLE_OPENGL"] = "1"
    env.setdefault("SAL_USE_VCLPLUGIN", "svp")  # rendu offscreen : pas de dépendance X11
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _kill_tree(proc: subprocess.Popen) -> None:
    """
    Détruit le processus ET sa descendance.
    Indispensable : `soffice` n'est qu'un lanceur, le travail est fait par
    `soffice.bin`. Un simple kill() laisse un orphelin qui verrouille le profil
    et fuit en mémoire jusqu'au redémarrage de la session.
    """
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True, timeout=15, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        else:
            pgid = os.getpgid(proc.pid)
            os.killpg(pgid, signal.SIGTERM)
            # Attente active brève plutôt que proc.wait() : wait() se bloque
            # si le tube stdout est plein et que le processus écrit encore.
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and proc.poll() is None:
                time.sleep(0.05)
            if proc.poll() is None:
                os.killpg(pgid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("Nettoyage du processus %s incomplet : %s", proc.pid, exc)
    finally:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and proc.poll() is None:
            time.sleep(0.05)
        if proc.poll() is None:
            log.error("Processus %s toujours vivant après kill.", proc.pid)


def _run_guarded(cmd: list[str], *, timeout: int, cwd: Path) -> tuple[int, str, str]:
    """
    Lance un backend natif sans shell, avec timeout et destruction d'arbre.
    `cwd` est un répertoire temporaire contrôlé : évite qu'une bibliothèque
    native charge une dépendance depuis un dossier utilisateur.
    """
    kwargs: dict = {
        "cwd": str(cwd),
        "env": _hardened_env(),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "errors": "replace",
        "shell": False,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    else:
        kwargs["start_new_session"] = True  # groupe de processus dédié pour killpg

    proc = subprocess.Popen(cmd, **kwargs)
    try:
        out, err = proc.communicate(timeout=timeout)
        return proc.returncode, out or "", err or ""
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        # Drainage obligatoire : si le backend a rempli le tube stdout, le
        # processus reste bloqué en écriture et n'est jamais récolté.
        try:
            proc.communicate(timeout=10)
        except (subprocess.TimeoutExpired, ValueError, OSError):
            log.warning("Tubes du processus %s non drainés.", proc.pid)
        raise ConversionError(
            f"Conversion interrompue après {timeout}s. "
            "Document trop lourd, ou fichier malformé."
        )
    except BaseException:
        _kill_tree(proc)
        try:
            proc.communicate(timeout=10)
        except Exception as exc:
            # Best-effort : le processus est déjà tué, ce drainage ne sert
            # qu'à éviter un tube bloqué. Son échec ne doit rien changer
            # à l'exception d'origine qui remonte juste après.
            log.debug("Drainage des tubes après kill incomplet : %s", exc)
        raise
    finally:
        for stream in (proc.stdout, proc.stderr):
            if stream and not stream.closed:
                stream.close()


# --------------------------------------------------------------------------
# Validation d'entrée
# --------------------------------------------------------------------------


def _check_input(source: Path) -> Path:
    source = Path(source).expanduser()
    try:
        source = source.resolve(strict=True)
    except OSError as exc:
        raise ConversionError(f"Fichier introuvable : {source}") from exc
    if not source.is_file():
        raise ConversionError(f"Ce n'est pas un fichier : {source}")
    size = source.stat().st_size
    if size == 0:
        raise ConversionError(f"Fichier vide : {source.name}")
    if size > MAX_INPUT_BYTES:
        raise ConversionError(
            f"Fichier trop volumineux ({size / 1024**2:.0f} Mo, "
            f"limite {MAX_INPUT_BYTES / 1024**2:.0f} Mo)."
        )
    return source


def safe_output_path(source: Path, target_ext: str, outdir: Optional[Path] = None) -> Path:
    """
    Chemin de sortie à côté du fichier source (ou dans outdir), sans jamais
    écraser un fichier existant. On n'utilise PAS le répertoire courant :
    en glisser-déposer sur une icône, il est imprévisible et parfois non
    inscriptible.
    """
    source = Path(source)
    directory = Path(outdir).expanduser().resolve() if outdir else source.parent
    directory.mkdir(parents=True, exist_ok=True)

    candidate = directory / f"{source.stem}{target_ext}"
    counter = 1
    while candidate.exists():
        candidate = directory / f"{source.stem} ({counter}){target_ext}"
        counter += 1
        if counter > 999:
            raise ConversionError("Trop de fichiers homonymes dans le dossier de sortie.")
    return candidate


# --------------------------------------------------------------------------
# Assainissement DOCX (macros, OLE, zip-bomb, zip-slip)
# --------------------------------------------------------------------------

# Types de relation dont une cible externe déclenche une connexion sortante
# ou un chargement de contenu actif au rendu. Les hyperliens sont conservés :
# ils ne sont suivis que sur clic, et les retirer dégraderait le document.
# Toujours neutralisés : une cible externe de ce type déclenche un
# chargement de contenu actif ou une exécution au rendu.
_RISKY_REL_TYPES = (
    "attachedTemplate", "oleObject", "package", "subDocument",
    "frame", "externalLink",
)

# Médias liés : neutralisés UNIQUEMENT si la cible est distante. Une image
# liée vers un fichier du disque est légitime et fréquente ; la supprimer
# faisait disparaître les illustrations du document converti.
_MEDIA_REL_TYPES = ("image", "audio", "video", "media")
_REMOTE_SCHEMES = ("http://", "https://", "ftp://", "ftps://", "//")

_RISKY_PARTS = ("word/vbaProject.bin", "word/vbaData.xml")
_RISKY_PREFIXES = ("word/embeddings/", "word/activeX/", "customUI/")


def _strip_external_rels(archive: zipfile.ZipFile, item, name: str) -> tuple[bytes, list[str]]:
    """
    Retire des fichiers .rels les relations pointant vers une cible EXTERNE
    et de type actif. C'est ce qui neutralise réellement le rappel réseau :
    LibreOffice ouvre ces cibles en direct, sans passer par un proxy, donc
    l'assainissement de l'environnement ne suffit pas.
    """
    import xml.etree.ElementTree as ET

    # Un .rels légitime pèse quelques kilo-octets. Au-delà, on refuse de
    # parser : ElementTree reste sensible à l'expansion d'entités.
    if item.file_size > 1024 * 1024:
        raise ConversionError(f"Fichier de relations anormalement volumineux : {name}")

    limit = 1024 * 1024
    with archive.open(item) as handle:
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        # L'en-tête mentait sur la taille : on refuse plutôt que de renvoyer
        # un contenu tronqué, qui corromprait le document réécrit.
        raise ConversionError(f"Fichier de relations tronqué ou piégé : {name}")

    # xml.etree est sensible à l'expansion d'entités (« billion laughs ») et à
    # l'expansion quadratique. Un .rels légitime n'a ni DTD ni entité : leur
    # présence suffit à rejeter le document, sans avoir à parser.
    head = raw[:4096].upper()
    if b"<!DOCTYPE" in head or b"<!ENTITY" in raw.upper():
        raise ConversionError(
            f"Déclaration XML interdite dans {name} (DTD ou entité). "
            "Conversion refusée."
        )

    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return raw, [f"Relations illisibles, conservées telles quelles : {name}"]

    stripped: list[str] = []
    for child in list(root):
        if child.get("TargetMode") != "External":
            continue
        rel_type = (child.get("Type") or "").rsplit("/", 1)[-1]
        target = child.get("Target") or ""

        remote = target.lower().startswith(_REMOTE_SCHEMES)
        if rel_type in _RISKY_REL_TYPES or (rel_type in _MEDIA_REL_TYPES and remote):
            root.remove(child)
            stripped.append(
                f"Référence externe neutralisée ({rel_type}) : {target[:80]}"
            )

    if not stripped:
        return raw, []
    return ET.tostring(root, encoding="UTF-8", xml_declaration=True), stripped


def _copy_bounded(reader, writer, remaining: int, name: str) -> int:
    """
    Copie par blocs en comptant les octets réellement produits.
    Ne fait jamais confiance à `file_size` de l'en-tête ZIP : ce champ est
    fourni par l'archive, donc par l'attaquant.
    """
    written = 0
    while True:
        chunk = reader.read(512 * 1024)
        if not chunk:
            return written
        written += len(chunk)
        if written > remaining:
            raise ConversionError(
                f"Archive suspecte : {name} dépasse le volume décompressé "
                "autorisé. Conversion refusée."
            )
        writer.write(chunk)


def sanitize_docx(source: Path, destination: Path) -> list[str]:
    """
    Réécrit le DOCX en retirant tout composant actif, et refuse les archives
    piégées. Retourne la liste des éléments neutralisés.
    """
    removed: list[str] = []
    total_uncompressed = 0

    try:
        with zipfile.ZipFile(source) as zin:
            entries = zin.infolist()
            if len(entries) > MAX_ZIP_ENTRIES:
                raise ConversionError(
                    f"Archive suspecte : {len(entries)} entrées "
                    f"(limite {MAX_ZIP_ENTRIES}). Conversion refusée."
                )

            with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as zout:
                for item in entries:
                    name = item.filename

                    # Zip-slip : un DOCX est un ZIP, donc un format d'archive hostile.
                    if name.startswith(("/", "\\")) or ".." in Path(name).parts or ":" in name:
                        removed.append(f"Entrée d'archive hors périmètre ignorée : {name}")
                        continue

                    if item.is_dir():
                        continue  # inutile en OOXML, et piégeux à réécrire

                    if name in _RISKY_PARTS or name.startswith(_RISKY_PREFIXES):
                        removed.append(f"Composant actif retiré : {name}")
                        continue

                    # Pré-filtre sur l'en-tête : élimine les cas grossiers
                    # sans décompresser. Ne remplace pas le comptage réel.
                    if item.compress_size > 0:
                        ratio = item.file_size / item.compress_size
                        if ratio > MAX_COMPRESSION_RATIO and item.file_size > 10 * 1024**2:
                            raise ConversionError(
                                f"Archive suspecte : taux de compression {ratio:.0f}:1 "
                                f"sur {name}. Conversion refusée."
                            )

                    # En-tête normalisé : une méthode de compression exotique
                    # ou chiffrée dans l'archive source ferait échouer l'écriture.
                    clean = zipfile.ZipInfo(name, date_time=item.date_time)
                    clean.compress_type = zipfile.ZIP_DEFLATED
                    clean.external_attr = item.external_attr

                    if name.endswith(".rels"):
                        payload, stripped = _strip_external_rels(zin, item, name)
                        removed += stripped
                        total_uncompressed += len(payload)
                        if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
                            raise ConversionError(
                                "Archive suspecte : volume décompressé excessif."
                            )
                        zout.writestr(clean, payload)
                        continue

                    # Comptage réel des octets décompressés, jamais l'en-tête.
                    budget = MAX_UNCOMPRESSED_BYTES - total_uncompressed
                    with zin.open(item) as reader, zout.open(clean, "w") as writer:
                        total_uncompressed += _copy_bounded(reader, writer, budget, name)

    except zipfile.BadZipFile as exc:
        raise ConversionError(
            f"{Path(source).name} n'est pas un .docx valide (archive illisible)."
        ) from exc

    return removed


# --------------------------------------------------------------------------
# DOCX -> PDF
# --------------------------------------------------------------------------

# Pas d'espace dans le JSON : le parseur de ligne de commande de LibreOffice
# sous Windows découpe mal les options contenant des espaces.
_PDF_FILTER_TAGGED = (
    'pdf:writer_pdf_Export:{'
    '"UseTaggedPDF":{"type":"boolean","value":"true"},'
    '"EmbedStandardFonts":{"type":"boolean","value":"true"},'
    '"ExportBookmarks":{"type":"boolean","value":"true"},'
    '"ExportNotes":{"type":"boolean","value":"false"},'
    '"ReduceImageResolution":{"type":"boolean","value":"false"}'
    '}'
)
_PDF_FILTER_PDFA = (
    'pdf:writer_pdf_Export:{'
    '"UseTaggedPDF":{"type":"boolean","value":"true"},'
    '"SelectPdfVersion":{"type":"long","value":"2"},'
    '"EmbedStandardFonts":{"type":"boolean","value":"true"}'
    '}'
)


def _pdf_is_tagged(path: Path) -> bool:
    """
    Un PDF balisé porte /MarkInfo (avec /Marked true) et un /StructTreeRoot.
    Certaines versions de LibreOffice (7.3, celle qu'apt installe encore sur
    Ubuntu 22.04) ignorent silencieusement les options d'export étendues
    passées via `--convert-to` — le filtre demande un PDF balisé, LibreOffice
    en produit un non balisé sans lever la moindre erreur. Sans cette
    vérification, l'application affirmerait un succès complet alors que la
    structure attendue est absente.
    """
    try:
        head = path.read_bytes()
    except OSError:
        return False
    return b"/StructTreeRoot" in head and b"/MarkInfo" in head


def docx_to_pdf(
    source: Path,
    output: Optional[Path] = None,
    *,
    pdfa: bool = False,
    timeout: int = 180,
    sanitize: bool = True,
) -> ConversionResult:
    """Convertit un document bureautique en PDF via LibreOffice headless."""
    source = _check_input(source)
    suffix = source.suffix.lower()
    if not suffix:
        raise ConversionError(
            f"{source.name} n'a pas d'extension : format indéterminable."
        )
    if suffix == ".pdf":
        raise ConversionError("Le fichier est déjà un PDF.")

    soffice = find_soffice()
    output = Path(output) if output else safe_output_path(source, ".pdf")
    warnings: list[str] = []
    started = time.monotonic()

    with tempfile.TemporaryDirectory(prefix="pdfconv_") as tmp:
        tmp_path = Path(tmp)
        # Nom neutralisé : le nom d'origine peut contenir des séquences
        # interprétées par le lanceur natif.
        work_src = tmp_path / f"input{suffix}"

        if sanitize and suffix == ".docx":
            warnings += sanitize_docx(source, work_src)
        else:
            shutil.copy2(source, work_src)

        # Profil jetable : permet le parallélisme (LibreOffice verrouille le
        # profil partagé) et garantit qu'aucun état ne survit à la conversion.
        profile_dir = tmp_path / "profile"
        profile_dir.mkdir()

        cmd = [
            str(soffice),
            f"-env:UserInstallation={profile_dir.as_uri()}",
            "--headless", "--norestore", "--nolockcheck",
            "--nodefault", "--nologo", "--nofirststartwizard",
            "--convert-to", _PDF_FILTER_PDFA if pdfa else _PDF_FILTER_TAGGED,
            "--outdir", str(tmp_path),
            str(work_src),
        ]

        code, out, err = _run_guarded(cmd, timeout=timeout, cwd=tmp_path)
        produced = tmp_path / "input.pdf"

        if not produced.is_file() or produced.stat().st_size == 0:
            detail = (err or out or "aucune sortie").strip()[-800:]
            raise ConversionError(
                f"LibreOffice n'a pas produit de PDF (code {code}).\n"
                f"Le document est peut-être protégé ou corrompu.\n{detail}"
            )

        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(produced), str(output))

    if not pdfa and not _pdf_is_tagged(output):
        warnings.append(
            "PDF produit sans balisage structurel : cette version de "
            "LibreOffice ignore les options d'export étendues. Une "
            "conversion ultérieure PDF -> Word sera moins fidèle. Mettre à "
            "jour LibreOffice résout généralement ce point."
        )

    return ConversionResult(
        source=source, output=output,
        backend=f"LibreOffice ({soffice.name})",
        duration_s=time.monotonic() - started,
        warnings=warnings,
    )


# --------------------------------------------------------------------------
# PDF -> DOCX
# --------------------------------------------------------------------------


def _apply_worker_limits() -> None:
    """
    Exécuté au démarrage du processus fils. Plafonner l'adressage mémoire
    transforme une allocation aberrante (PDF malformé, décompression piégée)
    en MemoryError propre au lieu d'un OOM killer sur toute la session.
    Posé DANS le fils : `preexec_fn` n'est pas sûr dans un programme à threads.
    """
    if os.name == "nt":
        return
    try:
        import resource
        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        target = WORKER_MEMORY_LIMIT if hard == resource.RLIM_INFINITY else min(WORKER_MEMORY_LIMIT, hard)
        resource.setrlimit(resource.RLIMIT_AS, (target, hard))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))  # pas de core dump : fuite de données
    except (ImportError, ValueError, OSError) as exc:
        log.debug("Limites de ressources non appliquées : %s", exc)


def _pdf2docx_worker(src: str, dst: str, pages: Optional[tuple[int, int]]) -> None:
    """
    Processus fils dédié. Le parsing PDF est la principale surface d'attaque
    du programme (PyMuPDF est du C++). Un crash ici ne touche pas l'application,
    et la mort du processus libère intégralement la mémoire — ce qui rend
    toute fuite du parseur sans conséquence sur la durée de vie de l'app.
    """
    _apply_worker_limits()
    from pdf2docx import Converter

    cv = Converter(src)
    try:
        if pages:
            cv.convert(dst, start=pages[0] - 1, end=pages[1])
        else:
            cv.convert(dst)
    finally:
        cv.close()


def _pdf2docx_isolated(src: Path, dst: Path, pages, timeout: int) -> None:
    import multiprocessing as mp

    ctx = mp.get_context("spawn")  # spawn : pas d'héritage d'état du parent
    proc = ctx.Process(target=_pdf2docx_worker, args=(str(src), str(dst), pages), daemon=True)
    proc.start()
    try:
        proc.join(timeout)
        if proc.is_alive():
            proc.terminate()
            proc.join(5)
            if proc.is_alive():
                proc.kill()
                proc.join(5)
            raise ConversionError(
                f"Reconstruction interrompue après {timeout}s. "
                "PDF trop complexe ou malformé."
            )
        if proc.exitcode != 0:
            raise ConversionError(
                "Échec de la reconstruction du document "
                f"(code {proc.exitcode}). Le PDF est probablement chiffré, "
                "corrompu, ou d'une structure non prise en charge."
            )
        if not dst.is_file() or dst.stat().st_size == 0:
            raise ConversionError("La reconstruction n'a produit aucun contenu exploitable.")
    finally:
        # Ce bloc ne doit jamais lever : il masquerait l'exception d'origine
        # et l'utilisateur verrait un message sans rapport avec la panne.
        try:
            if proc.is_alive():
                proc.kill()
            proc.join(timeout=5)
            proc.close()
        except (ValueError, OSError) as exc:
            log.debug("Nettoyage du worker incomplet : %s", exc)


def _text_density(pdf: Path) -> Optional[int]:
    """Caractères extractibles par page. 0 => PDF image-only (scan)."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return None

    doc = None
    try:
        doc = fitz.open(pdf)
        if doc.is_encrypted and not doc.authenticate(""):
            raise ConversionError(
                "Ce PDF est protégé par mot de passe. Déchiffre-le en amont, "
                "avec les autorisations appropriées."
            )
        if doc.page_count == 0:
            return 0
        sampled = min(doc.page_count, 20)  # échantillon : évite de parser 5000 pages
        total = sum(len(doc[i].get_text("text").strip()) for i in range(sampled))
        return total // sampled
    except ConversionError:
        raise
    except Exception as exc:
        log.warning("Analyse de densité impossible : %s", exc)
        return None
    finally:
        if doc is not None:
            doc.close()  # libération explicite du handle natif


def _ocrmypdf() -> Path:
    found = shutil.which("ocrmypdf")
    if not found:
        raise BackendNotFound("ocrmypdf introuvable (requiert ocrmypdf + tesseract).")
    return _assert_trusted(Path(found), origin="PATH")


def pdf_to_docx(
    source: Path,
    output: Optional[Path] = None,
    *,
    ocr: str = "auto",
    ocr_lang: str = "fra+eng",
    pages: Optional[tuple[int, int]] = None,
    timeout: int = 600,
) -> ConversionResult:
    """Reconstruit un .docx à partir d'un PDF (heuristique de mise en page)."""
    source = _check_input(source)
    output = Path(output) if output else safe_output_path(source, ".docx")
    started = time.monotonic()
    warnings: list[str] = []
    ocr_applied = False

    with tempfile.TemporaryDirectory(prefix="pdfconv_") as tmp:
        tmp_path = Path(tmp)
        working = tmp_path / "input.pdf"
        shutil.copy2(source, working)

        density = _text_density(working)
        if density is None:
            warnings.append("Analyse de la couche texte impossible.")
        elif ocr == "always" or (ocr == "auto" and density < 25):
            try:
                ocred = tmp_path / "ocr.pdf"
                code, _, err = _run_guarded(
                    [str(_ocrmypdf()), "--quiet", "--skip-text",
                     "--language", ocr_lang, "--optimize", "0",
                     str(working), str(ocred)],
                    timeout=timeout, cwd=tmp_path,
                )
                if code == 0 and ocred.is_file():
                    working, ocr_applied = ocred, True
                    warnings.append(
                        "Document scanné : OCR appliqué. "
                        "Relecture humaine indispensable."
                    )
                else:
                    warnings.append(f"OCR en échec : {(err or '').strip()[-200:]}")
            except ConversionError as exc:
                warnings.append(
                    f"Document scanné mais OCR indisponible ({exc}). "
                    "Le résultat contiendra surtout des images."
                )

        staging = tmp_path / "out.docx"
        _pdf2docx_isolated(working, staging, pages, timeout)

        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staging), str(output))

    if not ocr_applied and density is not None and density < 25:
        warnings.append("Peu de texte détecté : la mise en page sera approximative.")

    return ConversionResult(
        source=source, output=output,
        backend="pdf2docx" + (" + OCR" if ocr_applied else ""),
        duration_s=time.monotonic() - started,
        warnings=warnings, ocr_applied=ocr_applied,
    )


# --------------------------------------------------------------------------

SUPPORTED_INPUT = {".docx", ".doc", ".odt", ".rtf", ".pdf"}


def convert(source: Path, output: Optional[Path] = None, **kwargs) -> ConversionResult:
    """Aiguillage sur l'extension source."""
    ext = Path(source).suffix.lower()
    if ext == ".pdf":
        return pdf_to_docx(source, output, **kwargs)
    if ext in SUPPORTED_INPUT:
        return docx_to_pdf(source, output, **kwargs)
    raise ConversionError(
        f"Format non pris en charge : {ext or '(sans extension)'}. "
        f"Attendu : {', '.join(sorted(SUPPORTED_INPUT))}"
    )
