"""
Parseur .docx -> modèle interne (model.py).

S'appuie sur python-docx pour tout ce qu'il expose proprement (paragraphes,
runs, styles, sections, tableaux), et retombe sur l'accès XML brut
(docx.oxml, via qn()) pour ce que python-docx n'expose pas :
numérotation des listes (aucune API publique), sauts de page explicites au
milieu d'un paragraphe (w:br type="page", distinct du marqueur de rendu de
Word), images ancrées/dessins (w:drawing), fusions de cellules (gridSpan/
vMerge) et niveau de titre (w:outlineLvl, indépendant de la langue du
modèle contrairement au nom du style "Heading 1"/"Titre 1").

Le document est supposé déjà assaini par engine.sanitize_docx() avant
d'arriver ici : ce module ne revalide pas les protections zip-bomb/zip-slip/
macros, seulement la structure OOXML elle-même.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from pathlib import Path

import docx
from docx.oxml.ns import qn
from docx.table import Table as DocxTable, _Cell as DocxCell
from docx.text.paragraph import Paragraph as DocxParagraph
from docx.text.run import Run as DocxRun
from docx.opc.constants import RELATIONSHIP_TYPE as _RT

from .model import (
    Block,
    DocModel,
    HeaderFooter,
    ImageRef,
    InlineImage,
    LineBreak,
    ListInfo,
    PageBreakInline,
    Paragraph,
    Run,
    Section,
    Table,
    TableCell,
    TableRow,
)

log = logging.getLogger("colibri_converter.render.ooxml_parser")

EMU_PER_PT = 12700

_ALIGN_MAP = {
    0: "left", 1: "center", 2: "right", 3: "justify", 4: "justify", 5: "justify",
}


# --------------------------------------------------------------------------
# Contexte partagé, pour éviter de faire passer 5 paramètres dans chaque
# fonction de l'arbre de parsing.
# --------------------------------------------------------------------------


@dataclass
class _Ctx:
    warnings: list[str]
    numbering: _NumberingResolver
    images: _ImageCache
    doc_default_font: str
    doc_default_size: float


def parse(path: Path) -> DocModel:
    document = docx.Document(str(path))
    warnings: list[str] = []
    numbering = _NumberingResolver(document)
    images = _ImageCache(document)
    default_font, default_size = _doc_defaults(document)
    ctx = _Ctx(
        warnings=warnings, numbering=numbering, images=images,
        doc_default_font=default_font, doc_default_size=default_size,
    )

    sections: list[Section] = []
    prev_header: HeaderFooter | None = None
    prev_footer: HeaderFooter | None = None

    for sec in document.sections:
        if sec.header.is_linked_to_previous:
            header = prev_header
        else:
            header = _parse_header_footer(sec.header, ctx)
        prev_header = header

        if sec.footer.is_linked_to_previous:
            footer = prev_footer
        else:
            footer = _parse_header_footer(sec.footer, ctx)
        prev_footer = footer

        if sec.different_first_page_header_footer:
            warnings.append(
                "En-tête/pied de page spécifique à la première page ignoré "
                "(non pris en charge) : le modèle par défaut est utilisé partout."
            )

        blocks = _parse_blocks(sec.iter_inner_content(), ctx)

        col_count = _section_column_count(sec)
        if col_count > 1:
            warnings.append(
                f"Section en {col_count} colonnes rendue sur une seule colonne."
            )

        sections.append(Section(
            page_width_pt=_pt(sec.page_width, 595.0),
            page_height_pt=_pt(sec.page_height, 842.0),
            margin_top_pt=_pt(sec.top_margin, 72.0),
            margin_bottom_pt=_pt(sec.bottom_margin, 72.0),
            margin_left_pt=_pt(sec.left_margin, 72.0),
            margin_right_pt=_pt(sec.right_margin, 72.0),
            header_distance_pt=_pt(sec.header_distance, 36.0),
            footer_distance_pt=_pt(sec.footer_distance, 36.0),
            header=header,
            footer=footer,
            blocks=blocks,
            column_count=col_count,
        ))

    if not sections:
        raise ValueError("Document sans aucune section exploitable.")

    if numbering.had_unresolvable:
        warnings.append("Certaines listes n'ont pas pu être numérotées correctement.")
    if images.unsupported_count:
        warnings.append(
            f"{images.unsupported_count} image(s) dans un format non pris en "
            "charge (WMF/EMF) remplacée(s) par un espace réservé."
        )

    return DocModel(sections=sections, warnings=warnings)


def _pt(length, default: float) -> float:
    return length.pt if length is not None else default


def _section_column_count(sec) -> int:
    try:
        cols = sec._sectPr.find(qn("w:cols"))
        if cols is None:
            return 1
        val = cols.get(qn("w:num"))
        return max(1, int(val)) if val else 1
    except Exception:
        return 1


def _doc_defaults(document) -> tuple[str, float]:
    try:
        el = document.styles.element.find(qn("w:docDefaults"))
        if el is None:
            return "Liberation Sans", 11.0
        rpr_default = el.find(qn("w:rPrDefault"))
        name, size = None, None
        if rpr_default is not None:
            rpr = rpr_default.find(qn("w:rPr"))
            if rpr is not None:
                fonts = rpr.find(qn("w:rFonts"))
                if fonts is not None:
                    name = fonts.get(qn("w:ascii")) or fonts.get(qn("w:hAnsi"))
                sz = rpr.find(qn("w:sz"))
                if sz is not None:
                    val = sz.get(qn("w:val"))
                    if val:
                        size = int(val) / 2.0  # w:sz est en demi-points
        return name or "Liberation Sans", size or 11.0
    except Exception as exc:
        log.debug("docDefaults illisible : %s", exc)
        return "Liberation Sans", 11.0


def _parse_header_footer(hf, ctx: _Ctx) -> HeaderFooter | None:
    try:
        blocks = _parse_blocks(hf.iter_inner_content(), ctx)
    except Exception as exc:
        ctx.warnings.append(f"En-tête/pied de page illisible ignoré : {exc}")
        blocks = []
    return HeaderFooter(blocks=blocks) if blocks else None


def _parse_blocks(content_iter, ctx: _Ctx) -> list[Block]:
    blocks: list[Block] = []
    for item in content_iter:
        try:
            if isinstance(item, DocxParagraph):
                blocks.append(_parse_paragraph(item, ctx))
            elif isinstance(item, DocxTable):
                blocks.append(_parse_table(item, ctx))
        except Exception as exc:
            # Un bloc illisible ne doit pas faire échouer tout le document :
            # on le signale et on continue avec le reste.
            ctx.warnings.append(f"Un élément du document n'a pas pu être converti : {exc}")
    return blocks


# --------------------------------------------------------------------------
# Paragraphes
# --------------------------------------------------------------------------


def _walk_style_chain(style):
    s = style
    seen: set[int] = set()
    while s is not None and id(s) not in seen:
        seen.add(id(s))
        yield s
        s = getattr(s, "base_style", None)


def _resolve_alignment(para: DocxParagraph) -> str:
    if para.alignment is not None:
        return _ALIGN_MAP.get(para.alignment, "left")
    for s in _walk_style_chain(para.style):
        pf = getattr(s, "paragraph_format", None)
        if pf is not None and pf.alignment is not None:
            return _ALIGN_MAP.get(pf.alignment, "left")
    return "left"


def _resolve_length_pt(direct, style, attr: str) -> float:
    if direct is not None:
        return direct.pt
    for s in _walk_style_chain(style):
        pf = getattr(s, "paragraph_format", None)
        val = getattr(pf, attr, None) if pf is not None else None
        if val is not None:
            return val.pt
    return 0.0


def _heading_level(style) -> int | None:
    for s in _walk_style_chain(style):
        el = getattr(s, "element", None)
        if el is None:
            continue
        ppr = el.find(qn("w:pPr"))
        if ppr is None:
            continue
        outline = ppr.find(qn("w:outlineLvl"))
        if outline is not None:
            val = outline.get(qn("w:val"))
            if val is not None:
                try:
                    return int(val)
                except ValueError:
                    continue
    return None


def _parse_paragraph(para: DocxParagraph, ctx: _Ctx) -> Paragraph:
    items = _parse_inline(para, ctx)
    pf = para.paragraph_format
    style = para.style

    return Paragraph(
        items=items,
        alignment=_resolve_alignment(para),
        indent_left_pt=_resolve_length_pt(pf.left_indent, style, "left_indent"),
        indent_right_pt=_resolve_length_pt(pf.right_indent, style, "right_indent"),
        first_line_indent_pt=_resolve_length_pt(pf.first_line_indent, style, "first_line_indent"),
        space_before_pt=_resolve_length_pt(pf.space_before, style, "space_before"),
        space_after_pt=_resolve_length_pt(pf.space_after, style, "space_after"),
        list_info=ctx.numbering.resolve_paragraph(para),
        outline_level=_heading_level(style),
        page_break_before=bool(pf.page_break_before),
        keep_with_next=bool(pf.keep_with_next),
    )


# --------------------------------------------------------------------------
# Runs (formatage caractère + résolution de police)
# --------------------------------------------------------------------------


def _font_bool(run: DocxRun, para_style, attr: str) -> bool:
    val = getattr(run.font, attr)
    if val is not None:
        return bool(val)
    if run.style is not None:
        for s in _walk_style_chain(run.style):
            v = getattr(s.font, attr, None)
            if v is not None:
                return bool(v)
    for s in _walk_style_chain(para_style):
        v = getattr(s.font, attr, None)
        if v is not None:
            return bool(v)
    return False


def _font_underline(run: DocxRun, para_style) -> bool:
    """
    run.font.underline peut être True/False/None ou un membre de l'enum
    WD_UNDERLINE (SINGLE, DOUBLE, WAVY...). Toute valeur "non aucune" compte
    comme souligné : le PDF ne distingue qu'un seul style de soulignement.
    """
    val = run.font.underline
    if val is not None:
        return val not in (False, 0)
    if run.style is not None:
        for s in _walk_style_chain(run.style):
            v = s.font.underline
            if v is not None:
                return v not in (False, 0)
    for s in _walk_style_chain(para_style):
        v = s.font.underline
        if v is not None:
            return v not in (False, 0)
    return False


def _font_name(run: DocxRun, para_style, default: str) -> str:
    if run.font.name:
        return run.font.name
    if run.style is not None:
        for s in _walk_style_chain(run.style):
            if s.font.name:
                return s.font.name
    for s in _walk_style_chain(para_style):
        if s.font.name:
            return s.font.name
    return default


def _font_size_pt(run: DocxRun, para_style, default: float) -> float:
    if run.font.size is not None:
        return run.font.size.pt
    if run.style is not None:
        for s in _walk_style_chain(run.style):
            if s.font.size is not None:
                return s.font.size.pt
    for s in _walk_style_chain(para_style):
        if s.font.size is not None:
            return s.font.size.pt
    return default


def _rgb_or_none(color) -> str | None:
    if color is None or color.type is None:
        return None
    try:
        rgb = color.rgb
    except (AttributeError, TypeError):
        return None
    return str(rgb) if rgb is not None else None


def _font_color(run: DocxRun, para_style) -> str | None:
    val = _rgb_or_none(run.font.color)
    if val:
        return val
    if run.style is not None:
        for s in _walk_style_chain(run.style):
            val = _rgb_or_none(s.font.color)
            if val:
                return val
    for s in _walk_style_chain(para_style):
        val = _rgb_or_none(s.font.color)
        if val:
            return val
    return None


def _run_template(run: DocxRun, para_style, ctx: _Ctx) -> Run:
    from . import font_resolver

    raw_name = _font_name(run, para_style, ctx.doc_default_font)
    resolved_family, substituted = font_resolver.resolve(raw_name)
    if substituted and f"police non prise en charge : {raw_name}" not in ctx.warnings:
        ctx.warnings.append(
            f"Police non prise en charge : {raw_name} (remplacée par {resolved_family})."
        )
    return Run(
        text="",
        bold=_font_bool(run, para_style, "bold"),
        italic=_font_bool(run, para_style, "italic"),
        underline=_font_underline(run, para_style),
        strike=(
            _font_bool(run, para_style, "strike")
            or _font_bool(run, para_style, "double_strike")
        ),
        superscript=_font_bool(run, para_style, "superscript"),
        subscript=_font_bool(run, para_style, "subscript"),
        font_name=resolved_family,
        font_size_pt=_font_size_pt(run, para_style, ctx.doc_default_size),
        color_hex=_font_color(run, para_style),
    )


def _run_items(r_el, template: Run, ctx: _Ctx, hyperlink_url: str | None) -> list:
    items: list = []
    text_buf: list[str] = []

    def flush():
        if text_buf:
            items.append(replace(template, text="".join(text_buf), hyperlink_url=hyperlink_url))
            text_buf.clear()

    for child in r_el:
        tag = child.tag
        if tag == qn("w:t"):
            text_buf.append(child.text or "")
        elif tag == qn("w:tab"):
            text_buf.append("\t")
        elif tag == qn("w:noBreakHyphen"):
            text_buf.append("-")
        elif tag == qn("w:cr"):
            flush()
            items.append(LineBreak())
        elif tag == qn("w:br"):
            flush()
            br_type = child.get(qn("w:type"))
            items.append(PageBreakInline() if br_type == "page" else LineBreak())
        elif tag == qn("w:drawing"):
            flush()
            img = ctx.images.resolve_drawing(child)
            if img is not None:
                items.append(img)

    flush()
    return items


def _hyperlink_url(hyperlink_el, part) -> str | None:
    rid = hyperlink_el.get(qn("r:id"))
    if rid:
        try:
            return part.rels[rid].target_ref
        except KeyError:
            return None
    anchor = hyperlink_el.get(qn("w:anchor"))
    return f"#{anchor}" if anchor else None


def _parse_inline(para: DocxParagraph, ctx: _Ctx) -> list:
    items: list = []
    para_style = para.style

    def handle_run(r_el, hyperlink_url):
        run_wrapper = DocxRun(r_el, para)
        template = _run_template(run_wrapper, para_style, ctx)
        items.extend(_run_items(r_el, template, ctx, hyperlink_url))

    for child in para._p:
        tag = child.tag
        if tag == qn("w:del"):
            continue  # suivi des modifications : le contenu supprimé n'est jamais rendu
        if tag == qn("w:ins"):
            for r_el in child.findall(qn("w:r")):
                handle_run(r_el, None)
            continue
        if tag == qn("w:r"):
            handle_run(child, None)
        elif tag == qn("w:hyperlink"):
            url = _hyperlink_url(child, para.part)
            for r_el in child.findall(qn("w:r")):
                handle_run(r_el, url)

    return items


# --------------------------------------------------------------------------
# Tableaux
# --------------------------------------------------------------------------


def _parse_table(table: DocxTable, ctx: _Ctx) -> Table:
    tbl = table._tbl
    grid = tbl.find(qn("w:tblGrid"))
    col_widths_pt: list[float] = []
    if grid is not None:
        for gridcol in grid.findall(qn("w:gridCol")):
            w = gridcol.get(qn("w:w"))
            col_widths_pt.append((int(w) / 20.0) if w else 72.0)  # twips -> pt

    rows_out: list[TableRow] = []
    for tr in tbl.findall(qn("w:tr")):
        cells_out: list[TableCell] = []
        for tc in tr.findall(qn("w:tc")):
            tcpr = tc.find(qn("w:tcPr"))
            gridspan = 1
            is_continuation = False
            shading_hex = None
            if tcpr is not None:
                gs_el = tcpr.find(qn("w:gridSpan"))
                if gs_el is not None:
                    try:
                        gridspan = max(1, int(gs_el.get(qn("w:val")) or 1))
                    except ValueError:
                        gridspan = 1
                vm_el = tcpr.find(qn("w:vMerge"))
                if vm_el is not None:
                    val = vm_el.get(qn("w:val"))
                    is_continuation = val is None or val == "continue"
                shd_el = tcpr.find(qn("w:shd"))
                if shd_el is not None:
                    fill = shd_el.get(qn("w:fill"))
                    if fill and fill.lower() not in ("auto", ""):
                        shading_hex = fill

            blocks: list[Block] = []
            if not is_continuation:
                cell_wrapper = DocxCell(tc, table)
                try:
                    blocks = _parse_blocks(cell_wrapper.iter_inner_content(), ctx)
                except Exception as exc:
                    ctx.warnings.append(f"Cellule de tableau illisible ignorée : {exc}")

            cells_out.append(TableCell(
                blocks=blocks, col_span=gridspan,
                is_merge_continuation=is_continuation, shading_hex=shading_hex,
            ))
        rows_out.append(TableRow(cells=cells_out))

    return Table(rows=rows_out, col_widths_pt=col_widths_pt)


# --------------------------------------------------------------------------
# Images
# --------------------------------------------------------------------------


class _ImageCache:
    """Résout un w:drawing vers les octets de l'image référencée."""

    def __init__(self, document) -> None:
        self._document = document
        self.unsupported_count = 0

    def resolve_drawing(self, drawing_el) -> InlineImage | None:
        blip = drawing_el.find(".//" + qn("a:blip"))
        if blip is None:
            return None
        rid = blip.get(qn("r:embed"))
        if not rid:
            return None
        try:
            part = self._document.part.related_parts[rid]
        except KeyError:
            return None

        content_type = (part.content_type or "").lower()
        ext = content_type.split("/")[-1].split("+")[0]
        if ext in ("x-wmf", "wmf"):
            self.unsupported_count += 1
            return None
        if ext in ("x-emf", "emf"):
            self.unsupported_count += 1
            return None

        extent = drawing_el.find(".//" + qn("wp:extent"))
        if extent is not None and extent.get("cx") and extent.get("cy"):
            width_pt = int(extent.get("cx")) / EMU_PER_PT
            height_pt = int(extent.get("cy")) / EMU_PER_PT
        else:
            width_pt = height_pt = 72.0

        return InlineImage(
            image=ImageRef(data=part.blob, format=ext or "png"),
            width_pt=width_pt, height_pt=height_pt,
        )


# --------------------------------------------------------------------------
# Numérotation des listes
# --------------------------------------------------------------------------


class _NumberingResolver:
    def __init__(self, document) -> None:
        self._num_to_abstract: dict[str, str] = {}
        self._levels: dict[str, dict[int, tuple[str, str, int]]] = {}
        self._counters: dict[tuple[str, int], int] = {}
        self.had_unresolvable = False

        # On NE PASSE PAS par document.part.numbering_part : cette property de
        # python-docx, si le document n'a aucune partie de numérotation (cas
        # d'un .docx sans la moindre liste), tente d'en *créer* une via
        # NumberingPart.new() — qui lève NotImplementedError sur python-docx
        # 1.1.2 (et pollue le document sur les versions plus récentes). On
        # résout donc la relation directement et on traite son absence comme
        # « pas de numérotation », sans jamais déclencher de création.
        try:
            numbering_part = document.part.part_related_by(_RT.NUMBERING)
        except KeyError:
            return
        root = numbering_part.element

        for num_el in root.findall(qn("w:num")):
            num_id = num_el.get(qn("w:numId"))
            abstract_el = num_el.find(qn("w:abstractNumId"))
            if num_id is not None and abstract_el is not None:
                self._num_to_abstract[num_id] = abstract_el.get(qn("w:val"))

        for abstract_el in root.findall(qn("w:abstractNum")):
            abstract_id = abstract_el.get(qn("w:abstractNumId"))
            levels: dict[int, tuple[str, str, int]] = {}
            for lvl_el in abstract_el.findall(qn("w:lvl")):
                try:
                    ilvl = int(lvl_el.get(qn("w:ilvl")))
                except (TypeError, ValueError):
                    continue
                fmt_el = lvl_el.find(qn("w:numFmt"))
                text_el = lvl_el.find(qn("w:lvlText"))
                start_el = lvl_el.find(qn("w:start"))
                num_fmt = fmt_el.get(qn("w:val")) if fmt_el is not None else "decimal"
                lvl_text = text_el.get(qn("w:val")) if text_el is not None else "%1."
                try:
                    start = int(start_el.get(qn("w:val"))) if start_el is not None else 1
                except (TypeError, ValueError):
                    start = 1
                levels[ilvl] = (num_fmt or "decimal", lvl_text or "%1.", start)
            if abstract_id is not None:
                self._levels[abstract_id] = levels

    @staticmethod
    def _direct_numpr(para: DocxParagraph):
        ppr = para._p.pPr
        return ppr.find(qn("w:numPr")) if ppr is not None else None

    def resolve_paragraph(self, para: DocxParagraph) -> ListInfo | None:
        numpr = self._direct_numpr(para)
        if numpr is None:
            # La numérotation d'un style de liste ("List Bullet"/"List Number")
            # vit dans la définition du style lui-même, pas sur chaque
            # paragraphe : Word ne la recopie pas à chaque instance.
            for s in _walk_style_chain(para.style):
                style_ppr = getattr(s, "element", None)
                style_ppr = style_ppr.find(qn("w:pPr")) if style_ppr is not None else None
                found = style_ppr.find(qn("w:numPr")) if style_ppr is not None else None
                if found is not None:
                    numpr = found
                    break
        if numpr is None:
            return None
        numid_el = numpr.find(qn("w:numId"))
        if numid_el is None:
            return None
        num_id = numid_el.get(qn("w:val"))
        if not num_id or num_id == "0":
            return None  # numId=0 : convention OOXML pour "numérotation supprimée"

        ilvl_el = numpr.find(qn("w:ilvl"))
        try:
            ilvl = int(ilvl_el.get(qn("w:val"))) if ilvl_el is not None else 0
        except (TypeError, ValueError):
            ilvl = 0

        abstract_id = self._num_to_abstract.get(num_id)
        levels = self._levels.get(abstract_id, {}) if abstract_id else {}
        entry = levels.get(ilvl)
        if entry is None:
            self.had_unresolvable = True
            return ListInfo(level=ilvl, is_bullet=True, marker_text="•")

        num_fmt, lvl_text, start = entry
        if num_fmt == "bullet":
            return ListInfo(level=ilvl, is_bullet=True, marker_text="•")

        key = (num_id, ilvl)
        current = self._counters.get(key, start - 1) + 1
        self._counters[key] = current
        # Un niveau qui avance remet à zéro tous les niveaux plus profonds
        # de la même liste (convention Word : 1.a, 1.b, 2.a et non 2.c).
        for existing_key in [k for k in self._counters if k[0] == num_id and k[1] > ilvl]:
            del self._counters[existing_key]

        marker = _format_number(current, num_fmt)
        placeholder = f"%{ilvl + 1}"
        rendered = (
            lvl_text.replace(placeholder, marker) if placeholder in lvl_text else f"{marker}."
        )
        return ListInfo(level=ilvl, is_bullet=False, marker_text=rendered)


def _format_number(n: int, fmt: str) -> str:
    if fmt == "lowerLetter":
        return _to_alpha(n).lower()
    if fmt == "upperLetter":
        return _to_alpha(n).upper()
    if fmt == "lowerRoman":
        return _to_roman(n).lower()
    if fmt == "upperRoman":
        return _to_roman(n).upper()
    return str(n)  # decimal et tout format inconnu : repli numérique simple


def _to_alpha(n: int) -> str:
    s = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        s = chr(65 + rem) + s
    return s


def _to_roman(n: int) -> str:
    values = [
        (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
        (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
    ]
    s = ""
    for value, symbol in values:
        while n >= value:
            s += symbol
            n -= value
    return s
