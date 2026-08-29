"""
Modèle interne (model.py) -> PDF, via ReportLab.

Une PageTemplate par section OOXML (taille de page/marges/orientation
propres), avec un callback onPage qui dessine l'en-tête et le pied de page
dans une bande dédiée. Le contenu ("story") est une liste de flowables
Platypus construite en parcourant le modèle : Paragraph pour le texte
(un seul appel par segment, le marquage <font>/<b>/<u>/<link> porte tout le
formatage caractère), Table pour les tableaux (fusions via des commandes
SPAN), Image pour les images, PageBreak/NextPageTemplate pour les sauts de
page et de section.

Simplification assumée pour la v1 : une image au milieu d'un paragraphe est
rendue comme un flowable séparé (sur sa propre ligne) plutôt que comme un
habillage de texte au pixel près — ReportLab sait techniquement le faire au
prix d'une bien plus grande complexité, pour un gain de fidélité marginal
sur l'essentiel des documents.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path
# escape() uniquement : pas de parsing XML, donc aucune surface XXE malgré
# l'alerte générique de bandit sur les imports xml.sax (B406).
from xml.sax.saxutils import escape as xml_escape  # nosec B406

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image as RLImage,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph as RLParagraph,
    Spacer,
    Table as RLTable,
    TableStyle,
)
from reportlab.platypus.flowables import Flowable, KeepTogether

from . import font_resolver, image_extractor
from .model import (
    Block,
    DocModel,
    InlineImage,
    LineBreak,
    PageBreakInline,
    Paragraph,
    Run,
    Section,
    Table,
)

log = logging.getLogger("colibri_converter.render.pdf_writer")

_ALIGN = {"left": TA_LEFT, "center": TA_CENTER, "right": TA_RIGHT, "justify": TA_JUSTIFY}

# Garde-fou : une extension EMU aberrante (document piégé ou corrompu) ne
# doit pas se traduire par une image de plusieurs mètres qui épuise la
# mémoire au rendu.
_MAX_IMAGE_DIM_PT = 3000.0
_MIN_IMAGE_DIM_PT = 4.0

_LIST_MARKER_GAP = "&nbsp;&nbsp;&nbsp;&nbsp;"
_LIST_LEVEL_INDENT_PT = 18.0


# --------------------------------------------------------------------------
# Point d'entrée
# --------------------------------------------------------------------------


def render(doc_model: DocModel, output: Path, fonts_dir: Path, *, pdfa: bool = False) -> None:
    font_resolver.register_all(fonts_dir)

    templates: list[PageTemplate] = []
    story: list = []
    for i, section in enumerate(doc_model.sections):
        template_id = f"section{i}"
        templates.append(_build_page_template(template_id, section))
        if i > 0:
            story.append(NextPageTemplate(template_id))
            story.append(PageBreak())
        max_width = section.page_width_pt - section.margin_left_pt - section.margin_right_pt
        story.extend(_blocks_to_flowables(section.blocks, max_width, pdfa=pdfa))

    if not story:
        story = [RLParagraph("&nbsp;", _base_style())]

    first = doc_model.sections[0]
    doc = _ColibriDocTemplate(
        str(output),
        pagesize=(first.page_width_pt, first.page_height_pt),
        pageTemplates=templates,
        title=doc_model.title or output.stem,
    )
    doc.build(story)


class _ColibriDocTemplate(BaseDocTemplate):
    """Ajoute les signets PDF (titres) au fil de la construction du document."""

    def afterFlowable(self, flowable) -> None:
        level = getattr(flowable, "_outline_level", None)
        text = getattr(flowable, "_outline_text", None)
        if level is None or not text:
            return
        key = f"heading-{id(flowable)}"
        self.canv.bookmarkPage(key)
        self.canv.addOutlineEntry(text, key, level=max(0, level), closed=False)


# --------------------------------------------------------------------------
# Gabarits de page (une section OOXML = une PageTemplate)
# --------------------------------------------------------------------------


def _build_page_template(template_id: str, section: Section) -> PageTemplate:
    width, height = section.page_width_pt, section.page_height_pt
    frame = Frame(
        section.margin_left_pt, section.margin_bottom_pt,
        max(1.0, width - section.margin_left_pt - section.margin_right_pt),
        max(1.0, height - section.margin_top_pt - section.margin_bottom_pt),
        id=f"{template_id}-frame",
        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
    )

    def on_page(canvas_obj, _doc, section=section) -> None:
        _draw_header_footer(canvas_obj, section)

    return PageTemplate(id=template_id, frames=[frame], onPage=on_page, pagesize=(width, height))


def _draw_header_footer(canvas_obj, section: Section) -> None:
    canvas_obj.saveState()
    try:
        max_width = section.page_width_pt - section.margin_left_pt - section.margin_right_pt
        if section.header is not None and section.header.blocks:
            band = max(section.header_distance_pt, 18.0)
            y = section.page_height_pt - band
            _draw_band(canvas_obj, section.header.blocks, section, y, band, max_width)
        if section.footer is not None and section.footer.blocks:
            band = max(section.footer_distance_pt, 18.0)
            y = max(0.0, section.footer_distance_pt - band)
            _draw_band(canvas_obj, section.footer.blocks, section, y, band, max_width)
    finally:
        canvas_obj.restoreState()


def _draw_band(
    canvas_obj, blocks: list[Block], section: Section,
    y: float, height: float, width: float,
) -> None:
    flowables = _blocks_to_flowables(blocks, width, pdfa=False)
    if not flowables:
        return
    frame = Frame(
        section.margin_left_pt, y, width, height,
        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, showBoundary=0,
    )
    try:
        frame.addFromList(list(flowables), canvas_obj)
    except Exception as exc:
        # Un en-tête/pied de page trop volumineux pour sa bande ne doit pas
        # faire échouer tout le rendu du document.
        log.debug("En-tête/pied de page tronqué : %s", exc)


# --------------------------------------------------------------------------
# Blocs (paragraphes, tableaux) -> flowables
# --------------------------------------------------------------------------


def _blocks_to_flowables(blocks: list[Block], max_width: float | None, *, pdfa: bool) -> list:
    flowables: list = []
    pending_keep: list = []
    for block in blocks:
        block_flowables = _block_to_flowables(block, max_width, pdfa=pdfa)
        wants_keep = isinstance(block, Paragraph) and block.keep_with_next
        if pending_keep:
            pending_keep.extend(block_flowables)
            if not wants_keep:
                flowables.append(KeepTogether(pending_keep))
                pending_keep = []
        elif wants_keep:
            pending_keep = list(block_flowables)
        else:
            flowables.extend(block_flowables)
    if pending_keep:
        flowables.extend(pending_keep)
    return flowables


def _block_to_flowables(block: Block, max_width: float | None, *, pdfa: bool) -> list:
    if isinstance(block, Paragraph):
        return _paragraph_to_flowables(block, pdfa=pdfa)
    if isinstance(block, Table):
        return [_table_to_flowable(block, max_width, pdfa=pdfa)]
    return []


# --------------------------------------------------------------------------
# Paragraphes
# --------------------------------------------------------------------------


def _base_style() -> ParagraphStyle:
    return ParagraphStyle(
        name="colibri-base", fontName="Liberation Sans-regular", fontSize=11, leading=13,
    )


def _paragraph_style(para: Paragraph) -> ParagraphStyle:
    base_pt = next((i.font_size_pt for i in para.items if isinstance(i, Run)), 11.0)
    leading = base_pt * (para.line_spacing or 1.15)

    left_indent = para.indent_left_pt
    first_line_indent = para.first_line_indent_pt
    if para.list_info is not None:
        level_indent = _LIST_LEVEL_INDENT_PT * (para.list_info.level + 1)
        left_indent = max(left_indent, level_indent)
        first_line_indent = -_LIST_LEVEL_INDENT_PT

    return ParagraphStyle(
        name="p",
        alignment=_ALIGN.get(para.alignment, TA_LEFT),
        leftIndent=left_indent,
        rightIndent=para.indent_right_pt,
        firstLineIndent=first_line_indent,
        spaceBefore=para.space_before_pt,
        spaceAfter=para.space_after_pt,
        leading=max(leading, base_pt + 1),
        fontName="Liberation Sans-regular",
        fontSize=base_pt,
    )


def _plain_text(para: Paragraph) -> str:
    return "".join(i.text for i in para.items if isinstance(i, Run)).strip()


def _split_items(items: list) -> list[tuple[str, object]]:
    units: list[tuple[str, object]] = []
    current: list = []
    for item in items:
        if isinstance(item, PageBreakInline):
            if current:
                units.append(("text", current))
                current = []
            units.append(("pagebreak", None))
        elif isinstance(item, InlineImage):
            if current:
                units.append(("text", current))
                current = []
            units.append(("image", item))
        else:
            current.append(item)
    if current:
        units.append(("text", current))
    return units


def _paragraph_to_flowables(para: Paragraph, *, pdfa: bool) -> list:
    style = _paragraph_style(para)
    marker = f"{xml_escape(para.list_info.marker_text)}{_LIST_MARKER_GAP}" if para.list_info else ""
    outline_text = _plain_text(para) if para.outline_level is not None else None

    flowables: list = []
    if para.page_break_before:
        flowables.append(PageBreak())

    units = _split_items(para.items)
    if not units:
        flowables.append(RLParagraph(marker or "&nbsp;", style))
    else:
        first_text_done = False
        for kind, payload in units:
            if kind == "pagebreak":
                flowables.append(PageBreak())
            elif kind == "image":
                flowables.append(_image_flowable(payload, pdfa=pdfa))
            else:
                prefix = marker if not first_text_done else ""
                xml = prefix + _runs_to_markup(payload)
                flowables.append(RLParagraph(xml or "&nbsp;", style))
                first_text_done = True

    if outline_text:
        default_target = flowables[0] if flowables else None
        target = next(
            (f for f in flowables if isinstance(f, RLParagraph)), default_target,
        )
        if target is not None:
            target._outline_level = para.outline_level
            target._outline_text = outline_text[:200]

    return flowables


def _runs_to_markup(items: list) -> str:
    parts = []
    for item in items:
        if isinstance(item, LineBreak):
            parts.append("<br/>")
        elif isinstance(item, Run):
            parts.append(_run_markup(item))
    return "".join(parts)


def _run_markup(run: Run) -> str:
    text = xml_escape(run.text).replace("\t", _LIST_MARKER_GAP)
    if not text:
        return ""
    face = font_resolver.face_name(run.font_name, bold=run.bold, italic=run.italic)
    color = f"#{run.color_hex}" if run.color_hex else "#000000"
    open_tags, close_tags = [], []
    if run.underline:
        open_tags.append("<u>")
        close_tags.insert(0, "</u>")
    if run.strike:
        open_tags.append("<strike>")
        close_tags.insert(0, "</strike>")
    if run.superscript:
        open_tags.append("<super>")
        close_tags.insert(0, "</super>")
    elif run.subscript:
        open_tags.append("<sub>")
        close_tags.insert(0, "</sub>")

    body = f'<font name="{face}" size="{run.font_size_pt:.2f}" color="{color}">{text}</font>'
    if run.hyperlink_url:
        safe_url = xml_escape(run.hyperlink_url, {'"': "&quot;"})
        body = f'<link href="{safe_url}">{body}</link>'
    return "".join(open_tags) + body + "".join(close_tags)


# --------------------------------------------------------------------------
# Images
# --------------------------------------------------------------------------


class _Placeholder(Flowable):
    """Espace réservé visible pour une image non décodable (WMF/EMF, illisible)."""

    def __init__(self, width: float, height: float, label: str) -> None:
        super().__init__()
        self.width = width
        self.height = height
        self.label = label

    def draw(self) -> None:
        c = self.canv
        c.saveState()
        c.setDash(3, 2)
        c.setStrokeColor(colors.grey)
        c.rect(0, 0, self.width, self.height)
        c.setFillColor(colors.grey)
        c.setFont("Helvetica", 8)
        c.drawCentredString(self.width / 2, self.height / 2, self.label)
        c.restoreState()


def _clamp_dim(value: float, fallback: float) -> float:
    if value <= 0:
        return fallback
    return min(max(value, _MIN_IMAGE_DIM_PT), _MAX_IMAGE_DIM_PT)


def _image_flowable(item: InlineImage, *, pdfa: bool):
    width = _clamp_dim(item.width_pt, 72.0)
    height = _clamp_dim(item.height_pt, 72.0)
    png_bytes = image_extractor.decode_png(item.image, flatten_alpha=pdfa)
    if png_bytes is None:
        return _Placeholder(width, height, "Image non prise en charge")
    try:
        return RLImage(io.BytesIO(png_bytes), width=width, height=height)
    except Exception as exc:
        log.debug("Image non rendue : %s", exc)
        return _Placeholder(width, height, "Image illisible")


# --------------------------------------------------------------------------
# Tableaux
# --------------------------------------------------------------------------


def _clamp_col_widths(col_widths: list[float], max_width: float | None) -> list[float]:
    if not col_widths or not max_width:
        return col_widths
    total = sum(col_widths)
    if total <= 0 or total <= max_width:
        return col_widths
    scale = max_width / total
    return [w * scale for w in col_widths]


def _table_to_flowable(table: Table, max_width: float | None, *, pdfa: bool):
    if not table.rows:
        return Spacer(0, 0)
    total_cols = max((sum(c.col_span for c in row.cells) for row in table.rows), default=0)
    if total_cols == 0:
        return Spacer(0, 0)

    data: list[list] = [["" for _ in range(total_cols)] for _ in table.rows]
    continuation_grid = [[False] * total_cols for _ in table.rows]
    commands: list[tuple] = [
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#B0B0B0")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]

    for r_idx, row in enumerate(table.rows):
        col_cursor = 0
        for cell in row.cells:
            span = min(cell.col_span, max(1, total_cols - col_cursor))
            for c in range(col_cursor, col_cursor + span):
                continuation_grid[r_idx][c] = cell.is_merge_continuation

            if not cell.is_merge_continuation:
                content = _blocks_to_flowables(cell.blocks, None, pdfa=pdfa)
                data[r_idx][col_cursor] = content if content else ""
                if span > 1:
                    commands.append(("SPAN", (col_cursor, r_idx), (col_cursor + span - 1, r_idx)))
                if cell.shading_hex:
                    try:
                        commands.append((
                            "BACKGROUND", (col_cursor, r_idx),
                            (col_cursor + span - 1, r_idx), colors.HexColor(f"#{cell.shading_hex}"),
                        ))
                    except ValueError:
                        pass
            col_cursor += span

    for col in range(total_cols):
        row_idx = 0
        while row_idx < len(table.rows):
            if continuation_grid[row_idx][col]:
                row_idx += 1
                continue
            end = row_idx
            while end + 1 < len(table.rows) and continuation_grid[end + 1][col]:
                end += 1
            if end > row_idx:
                commands.append(("SPAN", (col, row_idx), (col, end)))
            row_idx = end + 1

    col_widths = list(table.col_widths_pt[:total_cols])
    if len(col_widths) < total_cols:
        col_widths += [72.0] * (total_cols - len(col_widths))
    col_widths = _clamp_col_widths(col_widths, max_width)

    try:
        return RLTable(data, colWidths=col_widths, style=TableStyle(commands), splitByRow=True)
    except Exception as exc:
        log.warning("Tableau non rendu (%s), remplacé par un espace réservé.", exc)
        return _Placeholder(max(sum(col_widths), 100), 30, "Tableau non pris en charge")
