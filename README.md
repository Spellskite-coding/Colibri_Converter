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
- 🪶 **Léger** — pas de moteur embarqué à télécharger deux fois, LibreOffice est réutilisé
- 🖥️ **Windows & Linux** — macOS via la ligne de commande
- 📖 **Open source** — le code est intégralement lisible, rien de caché

---

## Installation

**1. Installez [LibreOffice](https://www.libreoffice.org/download/download-libreoffice/)** (une fois, gratuit) — c'est le moteur de rendu utilisé en arrière-plan.

**2. Téléchargez Colibri Converter** depuis la page [Releases](../../releases), décompressez l'archive.

**3. Lancez `colibri-converter`**, ou glissez directement un fichier sur son icône.

C'est tout. Le fichier converti apparaît à côté de l'original.

> Premier lancement sous Windows : SmartScreen affiche un avertissement, normal pour un exécutable non signé — *Informations complémentaires* → *Exécuter quand même*. Vérifiez l'empreinte SHA-256 publiée à côté de chaque archive avant d'exécuter.
>
> 📄 Notice détaillée, pas à pas, pour utilisateur non technique : **[UTILISATION.md](UTILISATION.md)**

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

**Pourquoi LibreOffice ?** C'est le seul moteur libre, hors-ligne et multiplateforme qui interprète correctement le format OOXML — les alternatives Python pures perdent la mise en page, et `docx2pdf` pilote Microsoft Word par COM/AppleScript, donc indisponible sous Linux et non déterministe. LibreOffice n'est pas embarqué dans le binaire : il est détecté sur le poste. Ça évite de figer un moteur de plusieurs millions de lignes de C++ qu'il faudrait republier à chaque faille corrigée — vous restez patché par les mises à jour normales de The Document Foundation.

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
- neutralisation des relations pointant vers une cible externe (modèles distants, rappels réseau)
- résolution du binaire LibreOffice durcie contre le détournement de chemin
- parsing PDF confiné dans un processus isolé, avec limite mémoire et timeout

Détail complet, limites assumées et procédure de signalement : **[SECURITY.md](SECURITY.md)**

---

## Développement

```bash
git clone https://github.com/<vous>/Colibri_Converter.git
cd Colibri_Converter
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

pytest -v                    # suite complète
pytest -v -m "not needs_soffice"   # sans LibreOffice installé
```

Compiler l'exécutable :

```bash
python tools/make_icons.py
pyinstaller --noconfirm --clean colibri-converter.spec
```

Architecture, choix techniques et pièges de packaging déjà résolus : voir les commentaires de `colibri_converter/engine.py` et la CI (`.github/workflows/release.yml`), qui build et teste sur Windows et Linux avant chaque publication.

---

## Licence

**AGPL-3.0-or-later** — héritée de PyMuPDF et pdf2docx, sur lesquels repose la conversion PDF → Word. Détail et implications : **[LICENSE.md](LICENSE.md)**.

<div align="center">

*Fait avec un colibri vectoriel, pour éviter tout problème de droit d'auteur.*

</div>
