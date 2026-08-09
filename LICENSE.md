# Licence

Colibri Converter est distribué sous **GNU Affero General Public License v3.0
ou ultérieure (AGPL-3.0-or-later)**.

Le texte intégral doit accompagner le dépôt. Récupérez-le une fois pour toutes :

    curl -o LICENSE https://www.gnu.org/licenses/agpl-3.0.txt

## Pourquoi l'AGPL et pas MIT

Ce n'est pas un choix, c'est une contrainte héritée. Le moteur de
reconstruction PDF → DOCX repose sur **pdf2docx**, lui-même bâti sur
**PyMuPDF**, tous deux sous AGPL-3.0. Toute œuvre distribuée qui les
incorpore — y compris un binaire PyInstaller — doit être publiée sous la
même licence.

Publier ce projet sous MIT tout en embarquant PyMuPDF serait une violation
de licence, pas une simplification.

## Ce que l'AGPL implique concrètement

- Le code source doit rester accessible à quiconque reçoit le binaire.
  Un dépôt GitHub public suffit.
- Toute modification redistribuée doit l'être sous AGPL-3.0.
- La clause « réseau » (article 13) impose de fournir les sources aux
  utilisateurs d'un service en ligne bâti sur ce code. Elle ne concerne
  pas une application de bureau hors-ligne comme celle-ci.
- Un usage strictement privé n'impose aucune obligation.

## Si l'AGPL ne convient pas

Deux issues :

1. **Licence commerciale PyMuPDF** auprès d'Artifex, qui lève l'obligation
   de réciprocité.
2. **Retirer la dépendance** : remplacer pdf2docx/PyMuPDF par
   `pypdfium2` (BSD-3) et `pdfplumber` (MIT), au prix d'une reconstruction
   de tableaux à réécrire entièrement. Le sens DOCX → PDF, lui, ne dépend
   que de LibreOffice (MPL-2.0) et resterait publiable sous MIT.

## Composants tiers

| Composant | Licence | Redistribué ? |
|---|---|---|
| LibreOffice | MPL-2.0 | non — dépendance détectée sur le poste |
| PyMuPDF | AGPL-3.0 | oui |
| pdf2docx | AGPL-3.0 | oui |
| PySide6 (Qt) | LGPL-3.0 | oui |
| python-docx | MIT | oui |
