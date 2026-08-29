# Comment utiliser Colibri Converter

Convertir un Word en PDF, ou un PDF en Word. Sans compte, sans internet, sans envoyer vos documents à un site.

---

## Ce qu'il faut installer une seule fois

**Rien du tout.** Colibri Converter fait toute la conversion lui-même — pas de LibreOffice, pas d'autre programme à installer à côté.

**colibri-converter** — téléchargez l'archive dans la section *Releases* du dépôt, faites un clic droit dessus puis **Extraire tout**.

Vous obtenez un dossier contenant `colibri-converter.exe` (icône colibri turquoise) et un dossier `_internal`. Ne les séparez pas : `colibri-converter.exe` a besoin de `_internal` pour fonctionner.

> **Windows va afficher un avertissement bleu** au premier lancement (« Windows a protégé votre ordinateur »). C'est normal : le programme est gratuit et n'est pas signé par un certificat payant. Cliquez sur *Informations complémentaires*, puis *Exécuter quand même*.
>
> Avant de faire ça, vérifiez que le fichier téléchargé est bien le bon. Ouvrez PowerShell dans le dossier de téléchargement et tapez `Get-FileHash colibri-converter-windows-x64.zip`. Le résultat doit correspondre exactement au fichier `.sha256` publié à côté de l'archive.

**Astuce :** faites un clic droit sur `colibri-converter.exe` → *Envoyer vers* → *Bureau (créer un raccourci)*. Vous aurez une icône sur le bureau comme n'importe quel programme.

---

## Convertir un document

Deux façons, au choix.

**La plus rapide — glisser-déposer sur l'icône**
Prenez votre fichier Word ou PDF et lâchez-le directement sur l'icône de `colibri-converter` (ou sur le raccourci du bureau). La conversion démarre toute seule.

**La plus classique — ouvrir le programme**
Double-cliquez sur `colibri-converter`. Une fenêtre s'ouvre avec une grande zone en pointillés. Glissez-y vos fichiers, ou cliquez sur **Choisir des fichiers…**.

Dans les deux cas, vous pouvez traiter **plusieurs fichiers d'un coup**.

---

## Où se trouve le résultat ?

**À côté du fichier d'origine, dans le même dossier.**

Si vous convertissez `Bureau\Rapport.docx`, vous obtenez `Bureau\Rapport.pdf`.

Un fichier du même nom existe déjà ? Le nouveau s'appellera `Rapport (1).pdf`. **Rien n'est jamais écrasé.**

---

## Ce qui est converti

| Vous avez | Vous obtenez |
|---|---|
| `.docx` | un PDF |
| `.pdf` | un document Word `.docx` |

Un ancien `.doc`, `.odt` ou `.rtf` doit d'abord être réenregistré en `.docx` (Word ou LibreOffice savent le faire) avant d'être converti.

---

## À savoir sur la qualité du résultat

**Word → PDF : très bon sur un document courant** — texte, styles, tableaux, images, en-têtes et pieds de page sont pris en charge par le moteur intégré. Quelques mises en page avancées ne sont pas encore gérées (colonnes multiples, notes de bas de page, suivi des modifications, habillage complexe du texte autour d'une image) : dans ce cas, le programme convertit quand même et vous prévient avec un ⚠ de ce qui a été simplifié.

**PDF → Word : c'est une reconstruction, pas une restitution.** Un PDF ne contient pas de paragraphes ni de styles : seulement du texte posé à des positions précises sur la page. Le programme doit *deviner* la structure. Sur un document simple, le résultat est très bon. Sur un document complexe — plusieurs colonnes, tableaux imbriqués, mise en page travaillée — attendez-vous à des retouches.

**Un PDF scanné** (une photo ou une numérisation de papier) ne contient aucun texte, seulement une image. Le résultat sera une image dans un document Word, pas du texte modifiable.

Quand un problème est détecté, le programme l'affiche avec un ⚠ dans la fenêtre. Lisez ces messages, ils vous disent quoi vérifier.

---

## Si ça ne marche pas

**Rien ne se passe quand je glisse mon fichier**
Le format n'est pas reconnu. Seuls `.docx` et `.pdf` sont acceptés — un `.doc`, `.odt`, `.pages` ou `.txt` sera ignoré (réenregistrez-le en `.docx` d'abord).

**« Ce PDF est protégé par mot de passe »**
Le document est chiffré. Il faut le déverrouiller avant, avec le mot de passe et l'autorisation de son auteur.

**« Conversion interrompue »**
Le document est très lourd ou endommagé. Essayez de l'ouvrir dans Word ou LibreOffice pour vérifier qu'il n'est pas corrompu.

**Autre chose**
Un journal détaillé est écrit dans `%LOCALAPPDATA%\colibri-converter\colibri-converter.log`. Joignez-le si vous signalez un problème.

---

## Vos documents restent chez vous

Aucune connexion internet n'est utilisée. Rien n'est envoyé, rien n'est enregistré ailleurs que sur votre ordinateur. Vous pouvez couper le wifi et vérifier : tout fonctionne pareil.
