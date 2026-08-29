# Polices embarquées

Ces polices sont embarquées dans l'exécutable pour que le moteur de rendu
DOCX -> PDF (`colibri_converter/render/font_resolver.py`) produise un PDF
identique quelle que soit la machine, sans dépendre des polices installées
sur le système. Ce sont les mêmes substituts métriquement compatibles que
ceux utilisés par LibreOffice (et donc déjà éprouvés en production) :

| Fichier                | Substitut métriquement compatible de |
|-------------------------|----------------------------------------|
| `LiberationSans-*.ttf`   | Arial                                   |
| `LiberationSerif-*.ttf`  | Times New Roman                         |
| `LiberationMono-*.ttf`   | Courier New                             |
| `Carlito-*.ttf`          | Calibri                                 |
| `Caladea-*.ttf`          | Cambria                                 |

Toutes sont sous licence **SIL Open Font License 1.1** (texte complet dans
`OFL.txt`), qui autorise explicitement l'embarquement et la redistribution
avec un logiciel. Origine :

- Liberation Fonts — Red Hat, Inc. / Google (paquet Debian `fonts-liberation`)
- Carlito — tyPoland Łukasz Dziedzic (paquet Debian `fonts-crosextra-carlito`)
- Caladea — tyPoland Łukasz Dziedzic (paquet Debian `fonts-crosextra-caladea`)

Aucun nom réservé ("Liberation", "Carlito", "Caladea") n'est réutilisé pour
une police modifiée : les fichiers sont redistribués tels quels.
