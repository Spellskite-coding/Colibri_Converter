<div align="center">

# 🐦 Colibri Converter

**Convertissez vos documents Word et PDF sans jamais quitter votre ordinateur.**

Pas de cloud. Pas de compte. Pas de limite de taille. Pas de données qui partent on ne sait où.

[Télécharger](#-installation) · [Comment ça marche](#-comment-ça-marche) · [Fidélité annoncée](#-ce-que-vous-pouvez-vraiment-attendre) · [Contribuer](#-développement)

</div>

---

## Pourquoi Colibri Converter

Les convertisseurs DOCX ↔ PDF en ligne ont un point commun gênant : votre document transite par leur serveur. Pour un CV, une facture, un contrat, un rapport interne — ce n'est pas toujours acceptable.

Colibri Converter fait la même chose, **entièrement en local**. Vous glissez un fichier sur l'icône, le résultat apparaît à côté quelques secondes plus tard. Aucune connexion sortante n'est établie — vous pouvez couper le Wi-Fi et vérifier.

- 🔒 **100 % hors-ligne** — le document ne quitte jamais la machine
- 🖱️ **Glisser-déposer** — aucune ligne de commande à connaître
- 📦 **Un seul fichier** — l'exécutable est autonome, aucune installation
- 🖥️ **Windows & Linux** — macOS via la ligne de commande
- 📖 **Open source** — le code est intégralement lisible, rien de caché

---

## Installation

Dans tous les cas, une seule dépendance externe est nécessaire : **[LibreOffice](https://www.libreoffice.org/download/download-libreoffice/)**, gratuit, qui fournit le moteur de conversion utilisé en arrière-plan. Colibri Converter ne l'embarque pas — il le détecte sur votre poste — pour rester patché par les mises à jour normales de The Document Foundation plutôt que de figer un moteur qu'il faudrait republier à chaque faille corrigée.

### 🪟 Windows

1. **Installez LibreOffice** : téléchargez-le sur [libreoffice.org](https://www.libreoffice.org/download/download-libreoffice/) et suivez l'installeur — options par défaut, rien à personnaliser.

2. **Téléchargez Colibri Converter** depuis la page [Releases](../../releases) : prenez `colibri-converter-windows-x64.zip`.

3. **Décompressez l'archive** — clic droit → *Extraire tout*. Vous obtenez un seul fichier, `colibri-converter.exe`. Placez-le où vous voulez : Bureau, `Documents`, une clé USB — il est autonome et ne dépend d'aucun dossier voisin.

4. **Premier lancement** : double-cliquez sur `colibri-converter.exe`.

   > Windows affiche **SmartScreen** (« Windows a protégé votre ordinateur ») : normal pour un exécutable non signé par un certificat payant. Cliquez sur *Informations complémentaires*, puis *Exécuter quand même*.
   >
   > Avant cette étape, vérifiez l'intégrité du fichier téléchargé. Dans PowerShell, à l'endroit où se trouve l'archive :
   > ```powershell
   > Get-FileHash colibri-converter-windows-x64.zip
   > ```
   > Le résultat doit correspondre exactement au fichier `.sha256` publié à côté de l'archive sur la page Releases.

5. Le démarrage prend 2 à 5 secondes la première fois — l'exécutable s'extrait dans un dossier temporaire (`%TEMP%`) avant de se lancer. C'est normal, et plus rapide aux lancements suivants.

**Glisser-déposer** : une fois l'exe placé où vous le souhaitez, glissez directement un `.docx` ou un `.pdf` dessus pour lancer la conversion sans même ouvrir la fenêtre.

> **Antivirus.** Un exécutable « fichier unique » comme celui-ci ressemble, dans sa structure, à ce que font certains malwares (auto-extraction puis lancement) — c'est une heuristique commune à Defender et aux antivirus tiers, pas une détection de contenu réel. Si le vôtre le signale, vous pouvez vérifier l'empreinte SHA-256 ci-dessus, consulter le code source (public) ou soumettre le fichier à [VirusTotal](https://www.virustotal.com/).

### 🐧 Linux

1. **Installez LibreOffice**, généralement déjà présent sur la plupart des distributions. Sinon :
   ```bash
   sudo apt install libreoffice-writer      # Debian / Ubuntu
   sudo dnf install libreoffice-writer      # Fedora
   ```

2. **Téléchargez** `colibri-converter-linux-x64.tar.gz` depuis la page [Releases](../../releases), puis décompressez :
   ```bash
   tar -xzf colibri-converter-linux-x64.tar.gz
   ```
   Vous obtenez un seul exécutable, `colibri-converter`.

3. **Rendez-le exécutable** — c'est l'étape que Windows fait automatiquement mais que Linux exige explicitement, par sécurité :
   ```bash
   chmod +x colibri-converter
   ```

4. **Lancez-le** :
   ```bash
   ./colibri-converter
   ```
   ou double-cliquez dessus depuis votre gestionnaire de fichiers (Nautilus, Dolphin…) si l'exécution graphique est activée.

   Vérification d'intégrité avant tout, si vous le souhaitez :
   ```bash
   sha256sum colibri-converter-linux-x64.tar.gz
   ```
   à comparer au fichier `.sha256` publié à côté de l'archive.

**Rendre l'exécutable accessible depuis n'importe où**, si vous voulez le lancer sans y penser :
```bash
mv colibri-converter ~/.local/bin/          # doit être dans votre PATH
```
puis lancez `colibri-converter` depuis n'importe quel terminal.

### 🍎 macOS

Non distribué en binaire : Gatekeeper bloque tout exécutable non notarisé, et le contournement se durcit à chaque version macOS — publier un `.app` non notarisé serait plus frustrant qu'utile. Passez par la ligne de commande :
```bash
brew install --cask libreoffice
git clone https://github.com/<vous>/Colibri_Converter.git
cd Colibri_Converter
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
colibri-converter mon_fichier.docx
```

---

## Comment ça marche

```
┌──────────────────────────────────────────────┐
│   Interface : glisser-déposer (PySide6)       │
│   ou ligne de commande, pour l'automatisation │
├──────────────────────────────────────────────┤
│   Moteur                                      │
│     • assainissement (macros, OLE retirés)    │
│     • DOCX → PDF   via LibreOffice headless   │
│     • PDF  → DOCX  via pdf2docx (+ OCR)       │
├──────────────────────────────────────────────┤
│   Audit de fidélité (optionnel, --audit)      │
│     • similarité texte                        │
│     • similarité visuelle, page à page        │
├──────────────────────────────────────────────┤
│   Sous-processus isolés, avec timeout         │
│   et limite mémoire                           │
└──────────────────────────────────────────────┘
```

**Pourquoi LibreOffice ?** C'est le seul moteur libre, hors-ligne et multiplateforme qui interprète correctement le format OOXML — les alternatives Python pures perdent la mise en page, et `docx2pdf` pilote Microsoft Word par COM/AppleScript, donc indisponible sous Linux et non déterministe.

---

## Ce que vous pouvez vraiment attendre

La conversion de documents n'est pas symétrique, et on préfère vous le dire plutôt que vous laisser le découvrir avec un fichier abîmé.

| Sens | Fidélité | Pourquoi |
|---|:---:|---|
| **Word → PDF** | ~99 % | Rendu déterministe par LibreOffice. Les écarts résiduels viennent presque toujours d'une police absente sur la machine. |
| **PDF balisé → Word** | ~90 % | Un PDF « accessible » (PDF/UA) embarque une structure logique exploitable. |
| **PDF → Word** | 60–90 % | Un PDF ordinaire ne contient ni paragraphes ni styles — seulement des glyphes positionnés sur une page. La reconstruction est une reconstruction, pas une lecture. |
| **PDF scanné → Word** | variable | Aucun texte natif : la qualité dépend entièrement de la numérisation et de l'OCR. Relecture toujours recommandée. |

Sur un document texte simple, la conversion PDF → Word est en général excellente. Sur une mise en page à colonnes, avec tableaux imbriqués ou notes de bas de page, attendez des retouches.

**Plutôt que de vous laisser deviner**, l'application peut mesurer elle-même l'écart entre le fichier d'origine et le résultat :

```bash
colibri-converter rapport.pdf --audit
```

```
Verdict : CONFORME
  Fidélité textuelle : 97.40 %
  Pages : 12 -> 12
```

Un score bas ne veut pas dire que l'outil a mal fait son travail — souvent, ça signifie que le PDF source ne contenait tout simplement pas l'information nécessaire pour reconstruire un document fidèle. Le score existe pour vous le dire *avant* que vous ne l'envoyiez à quelqu'un.

---

## En ligne de commande

Pour l'automatisation, les scripts, ou simplement si vous préférez :

```bash
# Un fichier
colibri-converter rapport.docx -o ./sortie

# Un dossier entier, en parallèle
colibri-converter ./documents -o ./sortie -j 4

# Avec contrôle de fidélité et seuil bloquant (utile en CI)
colibri-converter ./corpus -o ./sortie --audit --fail-under 0.95

# PDF scanné, OCR forcé
colibri-converter scan.pdf -o ./sortie --ocr always --ocr-lang fra

# Archivage long terme (PDF/A)
colibri-converter contrat.docx -o ./sortie --pdfa
```

En bibliothèque Python :

```python
from colibri_converter import convert, audit

resultat = convert("rapport.docx", "rapport.pdf", pdfa=True)
print(resultat.warnings)
print(audit("rapport.docx", "rapport.pdf").summary())
```

---

## Sécurité

Un convertisseur reçoit par définition des fichiers d'origine inconnue. Colibri Converter part du principe que **le document d'entrée est hostile** :

- macros VBA, ActiveX et objets OLE retirés avant tout rendu
- protection contre les zip-bombs et le zip-slip (le DOCX est une archive ZIP)
- neutralisation des relations pointant vers une cible externe distante (modèles distants, rappels réseau) — les médias liés localement sont conservés
- résolution du binaire LibreOffice durcie contre le détournement de chemin
- parsing PDF confiné dans un processus isolé, avec limite mémoire et timeout

Détail complet, limites assumées et procédure de signalement : **[SECURITY.md](SECURITY.md)**

---

## Développement

```bash
git clone https://github.com/<vous>/Colibri_Converter.git
cd Colibri_Converter
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

pytest -v                    # suite complète
pytest -v -m "not needs_soffice"   # sans LibreOffice installé
```

Compiler l'exécutable :

```bash
python tools/make_icons.py
pyinstaller --noconfirm --clean colibri-converter.spec
```

Par défaut, le build produit un **exécutable unique** (`ONEFILE=1`, la valeur par défaut). Pour revenir à un dossier classique — démarrage instantané, mais non déplaçable hors de son dossier :

```bash
ONEFILE=0 pyinstaller --noconfirm --clean colibri-converter.spec
```

Architecture, choix techniques et pièges de packaging déjà résolus : voir les commentaires de `colibri_converter/engine.py` et la CI (`.github/workflows/release.yml`), qui build et teste sur Windows et Linux avant chaque publication.

---

## Licence

**AGPL-3.0-or-later** — héritée de PyMuPDF et pdf2docx, sur lesquels repose la conversion PDF → Word. Détail et implications : **[LICENSE.md](LICENSE.md)**.

<div align="center">

*Fait avec un colibri vectoriel, pour éviter tout problème de droit d'auteur.*

</div>
