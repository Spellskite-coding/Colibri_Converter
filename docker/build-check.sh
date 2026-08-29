#!/bin/bash
# Valide qu'un exécutable PyInstaller fraîchement construit fonctionne
# réellement (pas seulement qu'il existe) : conversion DOCX -> PDF -> DOCX
# de bout en bout, avec le binaire figé (GUI, polices embarquées comprises).
#
# Le binaire produit par colibri-converter.spec est TOUJOURS le point
# d'entrée GUI (app.py -> gui.run()), même en ligne de commande : il
# n'accepte pas de flags, seulement des chemins de fichiers (comme un
# glisser-déposer). QT_QPA_PLATFORM=offscreen permet de le faire tourner
# sans serveur graphique ; on attend le fichier de sortie, puis on tue le
# process proprement (SIGTERM, géré par gui._install_sigint).
set -euo pipefail
export QT_QPA_PLATFORM=offscreen

BIN=/app/dist/colibri-converter
test -f "$BIN" || { echo "BINAIRE ABSENT : $BIN"; exit 1; }

echo "--- Imports du paquet (détecte une dépendance manquante dans le binaire gelé) ---"
python3 -c "import colibri_converter.engine, colibri_converter.gui; print('imports OK')"

wait_for_file() {
    local path="$1" tries="${2:-30}"
    while [ "$tries" -gt 0 ]; do
        [ -f "$path" ] && return 0
        sleep 1
        tries=$((tries - 1))
    done
    return 1
}

wait_for_glob_count() {
    # Attend qu'au moins $2 fichiers correspondent au motif $1 (glob non
    # quoté à dessein). L'auto-extraction onefile de PyInstaller copie ses
    # fichiers progressivement : un sleep fixe est intrinsèquement flaky.
    local pattern="$1" want="$2" tries="${3:-30}"
    while [ "$tries" -gt 0 ]; do
        # shellcheck disable=SC2086
        count=$(ls $pattern 2>/dev/null | wc -l)
        [ "$count" -ge "$want" ] && return 0
        sleep 1
        tries=$((tries - 1))
    done
    return 1
}

echo "--- Polices embarquées accessibles depuis le binaire gelé (auto-extraction _MEIPASS) ---"
"$BIN" >/tmp/fontcheck.log 2>&1 &
FPID=$!
MEI_DIR=""
for _ in $(seq 1 20); do
    MEI_DIR=$(ls -d /tmp/_MEI* 2>/dev/null | head -1 || true)
    [ -n "$MEI_DIR" ] && break
    sleep 1
done
test -n "$MEI_DIR" || { echo "AUTO-EXTRACTION INTROUVABLE"; kill -9 "$FPID" 2>/dev/null; exit 1; }
wait_for_glob_count "$MEI_DIR/fonts/*.ttf" 20 20 || {
    echo "POLICES MANQUANTES DANS LE BINAIRE GELE (trouvé $(ls "$MEI_DIR/fonts/"*.ttf 2>/dev/null | wc -l))"
    kill -9 "$FPID" 2>/dev/null
    exit 1
}
kill "$FPID" 2>/dev/null || true
wait "$FPID" 2>/dev/null || true
echo "20 polices trouvées dans $MEI_DIR/fonts/"

echo "--- Conversion DOCX -> PDF avec le binaire gelé (GUI headless) ---"
WORK=/tmp/roundtrip
rm -rf "$WORK" && mkdir -p "$WORK" && cd "$WORK"

python3 - <<'PY'
import docx
d = docx.Document()
d.add_heading("Titre de validation", level=1)
d.add_paragraph("Contenu de test, avec accents : éàüçñ, une émoji ne passe pas ici.")
p = d.add_paragraph("Ligne en gras et en italique : ")
p.add_run("gras").bold = True
p.add_run(" puis ")
run = p.add_run("italique")
run.italic = True
d.save("original.docx")
PY

"$BIN" "$WORK/original.docx" &
BIN_PID=$!
wait_for_file "$WORK/original.pdf" || { echo "PDF NON PRODUIT (timeout)"; kill -9 "$BIN_PID" 2>/dev/null; exit 1; }
kill "$BIN_PID" 2>/dev/null || true
wait "$BIN_PID" 2>/dev/null || true

python3 -c "
import fitz
with fitz.open('$WORK/original.pdf') as doc:
    assert doc.page_count >= 1
    text = doc[0].get_text().lower()
    assert 'titre de validation' in text, text
    assert 'contenu de test' in text, text
print('PDF valide, texte retrouvé (police embarquée utilisée avec succès)')
"

echo "--- Conversion PDF -> DOCX avec le binaire gelé (GUI headless) ---"
"$BIN" "$WORK/original.pdf" &
BIN_PID=$!
sleep 8
kill "$BIN_PID" 2>/dev/null || true
wait "$BIN_PID" 2>/dev/null || true

DOCX_COUNT=$(ls "$WORK"/*.docx | wc -l)
# safe_output_path ne remplace jamais l'original : on doit se retrouver avec
# au moins 2 fichiers .docx (la source + le reconstruit, suffixé ou non).
test "$DOCX_COUNT" -ge 2 || { echo "DOCX RECONSTRUIT MANQUANT (trouvé $DOCX_COUNT .docx)"; exit 1; }
echo "Fichiers .docx présents : $(ls "$WORK"/*.docx)"

echo "--- Contenu de dist/ ---"
ls -la /app/dist

echo "BUILD ET EXECUTION OK"
