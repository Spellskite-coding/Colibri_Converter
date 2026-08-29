# Modèle de menace

**Hypothèse de départ : le document d'entrée est hostile.** Un convertisseur reçoit par définition des fichiers d'origine inconnue, et DOCX comme PDF sont des formats conteneurs riches, historiquement porteurs de vecteurs d'exécution.

Point important sur le langage : Python est memory-safe, donc **le débordement de tampon n'est pas atteignable depuis le code de colibri-converter**. Le risque mémoire réel vient des dépendances natives — PyMuPDF (C++), lxml (C, utilisé sous python-docx), Tesseract (C++, optionnel). La stratégie n'est donc pas d'éviter le bug dans ces composants, mais de faire en sorte qu'il ne coûte rien : **confinement dans un processus jetable**.

Depuis le retrait de LibreOffice, **les deux sens de conversion parsent désormais du contenu non fiable en Python, dans le même processus applicatif** (python-docx/lxml pour DOCX -> PDF, PyMuPDF pour PDF -> DOCX) plutôt que de déléguer à un programme externe qui offrait une frontière de processus gratuite. Les deux tournent donc dans un worker isolé (`render/isolation.py`), pas seulement le sens PDF -> DOCX comme avant.

## Contre-mesures implémentées

| Menace | Vecteur concret | Contre-mesure | Emplacement |
|---|---|---|---|
| Injection de commande | Nom de fichier contenant des métacaractères | `shell=False`, arguments en liste, nom de travail neutralisé en `input.<ext>` avant appel d'un backend externe (OCR) | `_run_guarded()` |
| Exécution de code | Macro VBA, ActiveX, objet OLE embarqué | Retrait des parties actives avant tout rendu | `sanitize_docx()` |
| Exfiltration / balise réseau | `attachedTemplate` distant, image liée, pixel de tracking | Suppression des relations OOXML `TargetMode="External"` de type actif, dans les `.rels`, avant même que le moteur de rendu n'ouvre le document. Les hyperliens sont conservés (suivis sur clic uniquement) | `_strip_external_rels()` |
| Zip-slip | Entrée d'archive en `../../..` ou chemin absolu | Rejet des entrées hors périmètre | `sanitize_docx()` |
| Zip-bomb | Ratio de compression extrême, volume décompressé massif | Comptage des octets **réellement décompressés**, avec interruption au dépassement. Les champs `file_size` de l'en-tête ZIP ne sont utilisés que comme pré-filtre : ils sont fournis par l'archive, donc par l'attaquant | `_copy_bounded()` |
| Corruption mémoire native | DOCX ou PDF malformé exploitant une CVE de lxml/PyMuPDF | Parsing dans un processus `spawn` séparé pour les deux sens de conversion, plafond `RLIMIT_AS`, `RLIMIT_CORE=0` | `render/isolation.py`, `render/worker.py`, `_pdf2docx_worker()` |
| Déni de service | Document conçu pour boucler ou saturer la RAM | Timeout sur chaque worker isolé, taille d'entrée plafonnée, limite mémoire du worker | `MAX_INPUT_BYTES`, `render/isolation.run_isolated()` |
| Écrasement de données | Sortie qui remplace un fichier existant | Suffixe incrémental, jamais d'écrasement ; écriture à côté de la source, jamais dans le CWD (imprévisible en glisser-déposer) | `safe_output_path()` |
| Fuite d'information | Core dump contenant le document, journal non borné | `RLIMIT_CORE=0`, journal en rotation (1 Mo × 3) dans le dossier de données utilisateur | `apply_worker_limits()`, `app.py` |
| Détournement de binaire (OCR) | `ocrmypdf` malveillant déposé dans le CWD ou un dossier du `PATH` inscriptible | Validation du chemin résolu, refus si CWD / dossier temporaire / world-writable | `_assert_trusted()`, `_ocrmypdf()` |

| Interblocage de tube | Backend saturant `stdout` (>64 Ko) puis figé | Drainage des tubes après destruction du processus ; attente active bornée au lieu de `wait()`, qui se bloque sur tube plein | `_run_guarded()`, `_kill_tree()` |
| Épuisement mémoire de l'audit | Comparaison de deux documents volumineux | Bascule sur une similarité par multiensemble de mots (linéaire) au-delà de 120 000 caractères : `difflib` est quadratique en mémoire | `text_similarity()` |

| Injection HTML | Nom de fichier ou URL externe piégée affichée dans le journal de l'interface, que QTextEdit interprète comme du HTML | Échappement systématique de tout ce qui provient du système de fichiers ou du document | `Worker.run()` |
| Expansion d'entités XML | `.rels` contenant une DTD (« billion laughs », expansion quadratique) | Rejet de toute déclaration `<!DOCTYPE>` ou `<!ENTITY>` avant parsing ; `xml.etree` y est sensible | `_strip_external_rels()` |
| Contournement par l'audit | `--audit` ouvrait le `.docx` source avec python-docx, sans plafond de décompression | L'extraction de texte passe désormais par `sanitize_docx()` | `extract_text()` |
| Déni de service par lot | Dossier de plusieurs centaines de milliers de fichiers | Plafond de 5 000 fichiers par lot, avec message explicite | `_collect()` |

## Stabilité mémoire

Les fuites du parseur PDF sont structurellement sans conséquence : le worker meurt à la fin de chaque conversion et le système récupère l'intégralité de son espace d'adressage. C'est ce qui permet à l'application de tourner indéfiniment sans dérive. Côté application : `fitz.Document` fermé dans un `finally`, `Converter.close()` garanti, streams du sous-processus fermés systématiquement, thread Qt joint avec délai borné avant destruction.

## Limites assumées

- **Pas de confinement OS.** Les processus workers ne sont ni sous seccomp/bubblewrap, ni sous Job Object, ni sous `sandbox-exec` — seulement isolés par `spawn` + plafond mémoire + timeout. Une CVE lxml/PyMuPDF exploitable donne l'exécution avec les droits de l'utilisateur, dans le worker isolé. Pour un usage en environnement sensible, encadrer l'appel avec le mécanisme de confinement de l'OS.
- **Binaires non signés.** Les Releases GitHub ne sont pas signées : SmartScreen avertira. Les empreintes SHA-256 sont publiées avec chaque artefact — vérifiez-les.
- **Surface native résiduelle.** PyMuPDF (C++) reste utilisé pour le sens PDF -> DOCX. Côté DOCX -> PDF, le moteur de rendu maison (`render/`) est en Python pur au-dessus de python-docx, ReportLab et Pillow — mais python-docx s'appuie sur `lxml` (C) pour parser le XML, ce qui reste une dépendance native même si elle n'a pas besoin d'être détectée/installée séparément (elle est embarquée comme le reste des dépendances Python). `render/ooxml_parser.py` ne parse jamais de XML lui-même : il ne fait que parcourir l'arbre déjà construit par python-docx, dont le parseur interne (`docx/oxml/parser.py`) est configuré avec `resolve_entities=False` — vérifié directement dans la source de la version épinglée (1.1.2) — ce qui neutralise nativement les bombes d'entités (« billion laughs ») dans `word/document.xml`, `styles.xml` et `numbering.xml`, sans qu'on ait eu à ajouter de pré-filtre équivalent à celui de `_strip_external_rels()`.
- **Pas de vérification de contenu.** Le fichier converti n'est pas analysé antivirus. Ce n'est pas un outil de désinfection.
- **Pas de PDF/A ni de PDF balisé au sens strict.** Le mode `--pdfa` est du best-effort (polices embarquées, transparence aplatie) et n'est **pas** une conformité ISO 19005 vérifiée. Le moteur de rendu ne produit pas non plus de structure `/StructTreeRoot` (accessibilité) — voir README pour le détail.

## Signaler une vulnérabilité

Ouvrez un *security advisory* privé sur le dépôt. Ce projet est maintenu au mieux, sans engagement de délai.
