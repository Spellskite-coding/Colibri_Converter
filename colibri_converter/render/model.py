"""
Modèle interne du document — la frontière entre le parseur OOXML
(ooxml_parser.py) et le moteur de rendu PDF (pdf_writer.py). Ni l'un ni
l'autre ne dépend directement de python-docx ou de ReportLab au-delà de ce
fichier : ça garde chaque côté testable isolément et remplaçable seul (un
futur parseur ODT alimenterait le même modèle, un futur backend de rendu le
consommerait de la même façon).

Toutes les longueurs sont en points (1/72 pouce), l'unité native de
ReportLab et la plus proche de l'EMU natif d'OOXML (1 pt = 12700 EMU).
"""

from __future__ import annotations

from dataclasses import dataclass, field

Alignment = str  # "left" | "center" | "right" | "justify"


@dataclass
class ImageRef:
    data: bytes
    format: str  # "png", "jpeg", "gif", "bmp", "wmf", "emf", ... (extension en minuscule)


@dataclass
class Run:
    text: str
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strike: bool = False
    superscript: bool = False
    subscript: bool = False
    font_name: str = "Liberation Sans"
    font_size_pt: float = 11.0
    color_hex: str | None = None  # "RRGGBB" ; None = couleur par défaut (encre du thème)
    hyperlink_url: str | None = None


@dataclass
class LineBreak:
    """w:br sans type, ou type="textWrapping" : retour à la ligne dans le même paragraphe."""


@dataclass
class PageBreakInline:
    """w:br type="page" : saut de page au fil du texte, pas au niveau du paragraphe."""


@dataclass
class InlineImage:
    image: ImageRef
    width_pt: float
    height_pt: float


InlineItem = Run | LineBreak | PageBreakInline | InlineImage


@dataclass
class ListInfo:
    level: int
    is_bullet: bool
    marker_text: str  # déjà résolu : "•", "1.", "a)", "iv.", ...


@dataclass
class Paragraph:
    items: list[InlineItem] = field(default_factory=list)
    alignment: Alignment = "left"
    indent_left_pt: float = 0.0
    indent_right_pt: float = 0.0
    first_line_indent_pt: float = 0.0
    space_before_pt: float = 0.0
    space_after_pt: float = 0.0
    line_spacing: float = 1.15
    list_info: ListInfo | None = None
    outline_level: int | None = None  # niveau de titre (0 = Titre 1), pour les signets PDF
    page_break_before: bool = False
    keep_with_next: bool = False


@dataclass
class TableCell:
    blocks: list[Block] = field(default_factory=list)
    col_span: int = 1
    is_merge_continuation: bool = False  # vMerge="continue" : fusionnée avec la cellule au-dessus
    shading_hex: str | None = None


@dataclass
class TableRow:
    cells: list[TableCell] = field(default_factory=list)


@dataclass
class Table:
    rows: list[TableRow] = field(default_factory=list)
    col_widths_pt: list[float] = field(default_factory=list)


Block = Paragraph | Table


@dataclass
class HeaderFooter:
    blocks: list[Block] = field(default_factory=list)


@dataclass
class Section:
    page_width_pt: float
    page_height_pt: float
    margin_top_pt: float
    margin_bottom_pt: float
    margin_left_pt: float
    margin_right_pt: float
    header_distance_pt: float
    footer_distance_pt: float
    header: HeaderFooter | None
    footer: HeaderFooter | None
    blocks: list[Block] = field(default_factory=list)
    column_count: int = 1  # >1 : non mis en page en v1, seulement signalé


@dataclass
class DocModel:
    sections: list[Section] = field(default_factory=list)
    title: str = ""
    warnings: list[str] = field(default_factory=list)
