# Colibri Converter — conversion souveraine DOCX ↔ PDF

Application multi-OS (Windows / macOS / Linux) de conversion bureautique **sans aucune sortie réseau** : pas de cloud, pas de télémétrie, pas d'API tierce. Le document ne quitte jamais la machine.

---

## 1. Ce qui est réellement atteignable

| Sens | Fidélité | Pourquoi |
|---|---|---|
| DOCX → PDF | **~99 %** | Rendu déterministe par le moteur LibreOffice Writer. Les écarts résiduels viennent presque toujours des polices. |
| PDF → DOCX | **60–90 %** | Un PDF ne contient ni paragraphes, ni styles, ni listes, ni tableaux — uniquement des glyphes positionnés. La reconstruction est heuristique. |
| PDF balisé → DOCX | **~90 %** | Le *StructTree* du PDF/UA fournit la sémantique manquante. |
| PDF scanné → DOCX | **variable** | OCR : dépend de la qualité de numérisation. Relecture humaine obligatoire. |

**Conséquence de conception :** puisque « sans erreurs » n'est pas garantissable dans le sens inverse, l'application *mesure* la perte (`colibri-converter/validate.py`) et la signale, plutôt que de livrer un fichier dégradé en silence. C'est la différence entre un outil fiable et un outil qui a l'air fiable.

### La cause n°1 d'écarts : les polices

Un DOCX en Calibri rendu sur une machine sans Calibri déclenche une substitution → largeurs de glyphes différentes → repagination → tout le document décale. Solution : **embarquer les polices métriquement compatibles** dans le bundle.

| Police d'origine | Substitut métrique libre |
|---|---|
| Calibri | Carlito |
| Cambria | Caladea |
| Arial / Helvetica | Liberation Sans |
| Times New Roman | Liberation Serif |
| Courier New | Liberation Mono |

Les installer dans le répertoire de polices de l'application et pointer `FONTCONFIG_PATH` (Linux) / ajouter au profil LibreOffice (Windows, macOS).

---

## 2. Architecture

```
┌─────────────────────────────────────────────┐
│  UI : PySide6 (bureau) ou CLI (scriptable)  │
├─────────────────────────────────────────────┤
│  colibri_converter.engine        — orchestration      │
│    ├─ sanitize_docx()  — retrait macros/OLE │
│    ├─ docx_to_pdf()    — LibreOffice        │
│    └─ pdf_to_docx()    — pdf2docx (+ OCR)   │
├─────────────────────────────────────────────┤
│  colibri_converter.validate      — audit de fidélité  │
│    ├─ text_similarity()                     │
│    └─ visual_similarity()  (SSIM page/page) │
├─────────────────────────────────────────────┤
│  Backends isolés : soffice, tesseract       │
│  (sous-processus, timeout, profil jetable)  │
└─────────────────────────────────────────────┘
```

**Pourquoi LibreOffice et pas une lib pure Python/Rust ?** Aucune bibliothèque native n'implémente OOXML avec une fidélité acceptable — `docx-rs`, `docx4j` sans rendu, `mammoth` (DOCX→HTML) perdent la mise en page. LibreOffice est le seul moteur libre, hors-ligne et multi-plateforme qui interprète OOXML correctement. Le prix : ~400 Mo à embarquer.

**Pourquoi pas `docx2pdf` (pip) ?** Il pilote Microsoft Word par COM/AppleScript : dépendance à une licence propriétaire, indisponible sous Linux, et non déterministe. Antinomique avec l'exigence de souveraineté.

---

## 3. Installation (développement)

```bash
python -m venv .venv && source .venv/bin/activate   # .venv\Scripts\activate sous Windows
pip install -r requirements.txt

# LibreOffice (dépendance système)
sudo apt install libreoffice-writer fonts-crosextra-carlito fonts-crosextra-caladea  # Debian/Ubuntu
brew install --cask libreoffice                                                      # macOS
winget install TheDocumentFoundation.LibreOffice                                     # Windows

# OCR (optionnel)
sudo apt install ocrmypdf tesseract-ocr-fra
```

## 4. Utilisation

```bash
# Conversion simple
python -m colibri_converter.cli rapport.docx -o ./out

# Lot complet + contrôle de fidélité + seuil bloquant (usage CI)
python -m colibri_converter.cli ./corpus -o ./out --audit --fail-under 0.95 -j 4

# PDF -> DOCX avec OCR forcé
python -m colibri_converter.cli scan.pdf -o ./out --ocr always --ocr-lang fra

# Archivage long terme
python -m colibri_converter.cli contrat.docx -o ./out --pdfa
```

En bibliothèque :

```python
from colibri_converter import convert, audit

res = convert("rapport.docx", "rapport.pdf", pdfa=True)
print(res.warnings)
print(audit("rapport.docx", "rapport.pdf").summary())
```

---

## 5. Packaging multi-OS

| Cible | Outil | Sortie |
|---|---|---|
| Windows | PyInstaller + Inno Setup / WiX | `.exe`, `.msi` signé Authenticode |
| macOS | PyInstaller + `codesign` + `notarytool` | `.app` dans un `.dmg`, notarisé |
| Linux | PyInstaller + AppImage, ou Flatpak | `.AppImage`, `.flatpak` |

**LibreOffice n'est pas embarqué.** C'est un choix délibéré : redistribuer un moteur C++ de plusieurs millions de lignes dans un binaire figé oblige à republier à chaque CVE. En le détectant sur le poste, l'utilisateur reste patché par les mises à jour de The Document Foundation, et l'archive tombe de ~500 Mo à ~60 Mo.

Au premier lancement, si LibreOffice est absent, l'application affiche un bandeau avec un lien vers la page officielle et un bouton « Revérifier » — pas besoin de relancer le programme.

```bash
pyinstaller --noconfirm --clean colibri-converter.spec
```

La CI (`.github/workflows/release.yml`) builde Windows + Linux, lance `ruff` et `bandit`, génère les empreintes SHA-256 et publie la Release sur tag `v*`.

> **Deux pièges de packaging déjà traités :**
> `multiprocessing.freeze_support()` est appelé en tout premier dans `app.py` — sans lui, un binaire PyInstaller relance l'application entière à chaque `spawn`, ce qui produit une bombe à fork sous Windows.
> La CI builde sur `ubuntu-22.04` et non `ubuntu-latest` : PyInstaller lie la glibc de la machine de build, donc compiler sur une version récente casse les distributions plus anciennes.

**macOS :** non publié en binaire. Gatekeeper bloque tout `.app` non notarisé, et le contournement se durcit à chaque version. Les utilisateurs macOS passent par le CLI (`pip install -e .`).

---

## 6. Durcissement (déjà implémenté ou à câbler)

Le pipeline traite des documents potentiellement hostiles. Points d'attention :

**Implémenté**
- `sanitize_docx()` retire `vbaProject.bin`, ActiveX et objets OLE embarqués avant rendu, et rejette les entrées ZIP en *zip-slip* (`../`, chemins absolus).
- Purge des variables de proxy + `no_proxy=*` dans l'environnement des backends : neutralise les modèles distants (`attachedTemplate`), les images liées et le tracking pixel dans un DOCX ou PDF.
- Profil LibreOffice jetable par conversion (`-env:UserInstallation`) : évite le verrou de profil partagé *et* toute persistance entre documents.
- Parsing PDF confiné dans un processus fils avec `timeout` + `kill` : PyMuPDF et Tesseract ont un historique de CVE mémoire sur fichiers malformés.

**À ajouter selon ton niveau d'exigence**
- Confinement OS des sous-processus : `seccomp`/`bubblewrap` ou AppArmor (Linux), *Job Objects* + *AppContainer* (Windows), `sandbox-exec` (macOS). Limiter RAM et CPU pour contrer les zip-bombs et PDF récursifs.
- Blocage réseau au niveau applicatif (règle de pare-feu locale sur le binaire) plutôt qu'au niveau des variables d'environnement — plus robuste, et démontrable en audit.
- `MacroSecurityLevel=3` (très élevé) dans le `registrymodifications.xcu` du profil LibreOffice, en défense en profondeur derrière `sanitize_docx()`.
- Builds reproductibles + SBOM CycloneDX + signature des artefacts : `cyclonedx-py requirements -i requirements.txt -o sbom.json`.
- Suppression des métadonnées de sortie (auteur, chemins, historique de révision) — fuite d'information classique lors de la diffusion externe de PDF.

---

## 7. Corpus de non-régression

`validate.roundtrip_audit()` enchaîne DOCX → PDF → DOCX → PDF et compare le premier et le dernier rendu en SSIM. À brancher en CI sur un corpus versionné couvrant : tableaux imbriqués, listes multi-niveaux, sauts de section, en-têtes/pieds différenciés, notes de bas de page, images flottantes, champs de fusion, texte RTL, formules. C'est le seul moyen de détecter une régression lors d'une montée de version de LibreOffice.

---

## Licence

Voir `LICENSE.md`. Le projet est sous **AGPL-3.0-or-later** : ce n'est pas un choix mais une contrainte héritée de PyMuPDF et pdf2docx, tous deux AGPL. Récupérez le texte intégral avant de publier :

```bash
curl -o LICENSE https://www.gnu.org/licenses/agpl-3.0.txt
```

## Licence des composants

LibreOffice est sous MPL-2.0 (redistribution possible, y compris en bundle). PyMuPDF est en **AGPL-3.0** : en distribution commerciale fermée, il faut soit une licence commerciale Artifex, soit remplacer PyMuPDF/pdf2docx par `pypdfium2` (BSD) + `pdfplumber` (MIT), au prix d'une reconstruction de tableaux nettement plus artisanale. À arbitrer tôt : c'est structurant.

---

## 8. État de validation

Les tests de `tests/` couvrent l'assainissement, la résolution de binaire, la gestion des sous-processus et la conversion de bout en bout. Ils tournent en CI sur **Windows et Linux avant tout build** — un échec bloque la publication.

**Ce qui n'a jamais été exécuté sous Windows au moment de la rédaction :** la lecture du registre, la branche `taskkill /F /T`, les `creationflags`, l'encodage `file://` du profil LibreOffice, et l'échappement de la ligne de commande du filtre PDF. Le premier passage de CI est donc le vrai test — attendez-le avant de publier une Release.

Le contrôle le plus important est `test_conversion_reelle_et_pdf_balise` : il vérifie la présence de `/StructTreeRoot` dans le PDF produit. Si l'échappement des guillemets du filtre JSON casse sous Windows, LibreOffice ignore les options **sans lever d'erreur** et produit un PDF non balisé — une panne silencieuse qui dégraderait toutes les conversions PDF → DOCX ultérieures.

```bash
pytest -v                            # tout
pytest -v -m "not needs_soffice"     # sans LibreOffice
```


---

## 9. Identité visuelle

Le logo est un **SVG écrit à la main** (`colibri_converter/branding.py`), pas une image bitmap. Ce choix est technique autant qu'esthétique :

- **Aucune question de licence.** Une photo animalière trouvée en ligne est presque toujours sous copyright ; l'embarquer dans un binaire open source expose le dépôt à un retrait.
- **Aucun fichier de ressources.** Le SVG est une chaîne Python, donc rien à déclarer dans la spec PyInstaller ni à résoudre à l'exécution — c'est une cause classique de plantage en binaire gelé.
- **Une seule source de vérité** pour l'interface, l'icône Windows, l'icône macOS et le filigrane.
- **Net à toute taille**, de l'icône 16 px de la barre des tâches à un écran HiDPI.

```bash
python tools/make_icons.py     # produit build/icons/colibri.ico, .icns et les PNG
```

La CI lance cette commande avant PyInstaller. Si l'icône manque, le build continue sans échouer : un détail cosmétique ne doit pas bloquer une publication.

La palette pastel (menthe, pervenche, rose poudré) est définie dans `branding.py` et pilote à la fois le logo et la feuille de style Qt : changer une constante suffit à décliner tout le thème.
