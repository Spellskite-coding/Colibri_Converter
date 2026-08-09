"""
Identité visuelle : colibri vectoriel et palette.

Le logo est un SVG écrit à la main, stocké ici sous forme de chaîne plutôt que
dans un fichier de ressources. Trois raisons :
  - aucun fichier de données à embarquer, donc rien à déclarer dans la spec
    PyInstaller ni à résoudre à l'exécution (source classique de plantage en
    binaire gelé) ;
  - une seule source de vérité pour l'interface et pour les icônes ;
  - quelques kilo-octets au lieu d'une photo, et un rendu net à toute taille,
    de l'icône 16 px à l'affichage HiDPI.
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# Palette — dérivée du plumage d'un colibri : vert émeraude irisé,
# gorge magenta, fond ardoise très clair.
# --------------------------------------------------------------------------

# Teintes pastel : saturation basse, luminosité haute. Sur une interface
# claire, des couleurs vives « brûlent » et fatiguent l'œil ; le pastel
# garde le logo lisible sans qu'il aspire toute l'attention.
MINT_LIGHT = "#A8E6D8"
MINT = "#7FD1C4"
TEAL_SOFT = "#5FB3B8"
TEAL_DEEP = "#4A93A8"
WING = "#A9C0DE"
WING_DEEP = "#8AA5C9"
BLUSH = "#F3A6C6"
BLUSH_DEEP = "#E888B0"

INK = "#4E6472"
INK_SOFT = "#7C919E"
MUTED = "#93A6B1"
LINE = "#DDE7EB"
SURFACE = "#FFFFFF"
CANVAS = "#F7FAFB"
ACCENT_BG = "#EDF7F5"
WARN_BG = "#FFF6EA"
WARN_LINE = "#F0CFA0"
WARN_INK = "#8A6636"
OK_INK = "#3E8F7C"
ERR_INK = "#C87A8E"

APP_NAME = "Colibri Converter"
TAGLINE = "Word ↔ PDF, sans quitter votre ordinateur"


# --------------------------------------------------------------------------
# Logo
# --------------------------------------------------------------------------

def colibri_svg(
    body_from: str = MINT_LIGHT,
    body_to: str = TEAL_DEEP,
    wing: str = WING,
    wing_to: str = MINT_LIGHT,
    gorget: str = BLUSH,
    eye: str = INK,
) -> str:
    """
    Colibri en vol stationnaire, de profil, bec vers la gauche.

    Le tracé est volontairement une silhouette pleine sans contour fin : à
    16 px, un détail linéaire disparaît ou produit du crénelage. Les couleurs
    sont paramétrables pour décliner le logo (filigrane, état désactivé).
    """
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">
  <defs>
    <linearGradient id="corps" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{body_from}"/>
      <stop offset="1" stop-color="{body_to}"/>
    </linearGradient>
    <linearGradient id="aile" x1="0" y1="1" x2="1" y2="0">
      <stop offset="0" stop-color="{wing}"/>
      <stop offset="1" stop-color="{wing_to}"/>
    </linearGradient>
  </defs>

  <path fill="url(#aile)" d="M120 106
    C138 86 166 56 200 34 C218 23 242 18 247 27
    C252 36 236 52 216 70 C190 96 158 120 136 130
    C122 136 110 122 120 106 Z"/>

  <path fill="url(#corps)" d="M158 178
    C172 198 192 218 214 236 C220 241 212 250 206 245
    C186 230 166 214 149 197 C142 190 152 172 158 178 Z"/>

  <path fill="url(#corps)" d="M64 106
    C62 80 84 60 110 68 C148 80 176 126 184 174
    C188 197 170 210 151 200 C112 182 74 150 64 106 Z"/>

  <path fill="{gorget}" d="M76 118
    C88 112 104 116 114 128 C119 135 116 145 108 147
    C93 150 78 139 72 128 C69 123 72 120 76 118 Z"/>

  <path fill="{eye}" d="M70 102 L10 82 C4 80 3 90 9 92 L72 118 Z"/>
  <circle cx="96" cy="100" r="8" fill="{eye}"/>
</svg>"""


COLIBRI_SVG = colibri_svg()

# Filigrane de la zone de dépôt : même tracé, presque effacé.
COLIBRI_WATERMARK = colibri_svg(
    body_from="#E4F0EE", body_to="#E4F0EE", wing="#E9F1F6",
    wing_to="#E9F1F6", gorget="#EFF4F6", eye="#E4F0EE",
)


def colibri_icon_svg() -> str:
    """
    Variante pour l'icône : pastille arrondie et sujet agrandi.
    Un logo transparent noyé dans du vide devient illisible en 16 px dans la
    barre des tâches ; le fond coloré fournit le contraste qui manque.
    """
    inner = COLIBRI_SVG
    inner = inner[inner.index("</defs>") + 7: inner.rindex("</svg>")]
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">
  <defs>
    <linearGradient id="corps" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#FFFFFF"/><stop offset="1" stop-color="{MINT_LIGHT}"/>
    </linearGradient>
    <linearGradient id="aile" x1="0" y1="1" x2="1" y2="0">
      <stop offset="0" stop-color="{WING}"/><stop offset="1" stop-color="#E8F2FA"/>
    </linearGradient>
    <linearGradient id="fond" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{MINT}"/><stop offset="1" stop-color="{TEAL_DEEP}"/>
    </linearGradient>
  </defs>
  <rect x="0" y="0" width="256" height="256" rx="56" fill="url(#fond)"/>
  <g transform="translate(6 10) scale(0.94)">{inner}</g>
</svg>"""
