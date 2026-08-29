"""Décodage des images du DOCX pour insertion dans le PDF."""

from __future__ import annotations

import io
import logging

from PIL import Image, UnidentifiedImageError

from .model import ImageRef

log = logging.getLogger("colibri_converter.render.image_extractor")


def decode_png(image: ImageRef, *, flatten_alpha: bool = False) -> bytes | None:
    """
    Décode une image vers des octets PNG, ou None si illisible.

    On repasse systématiquement par Pillow et on renormalise en PNG plutôt
    que d'injecter les octets bruts dans le PDF : ça homogénéise la gestion
    de la transparence et des espaces colorimétriques exotiques (CMYK,
    palette indexée) que ReportLab ne décode pas nativement lui-même.

    `flatten_alpha` aplatit la transparence sur fond blanc : utilisé en mode
    PDF/A best-effort, où la transparence n'est pas censée être présente.
    """
    try:
        with Image.open(io.BytesIO(image.data)) as im:
            im.load()
            if im.mode == "CMYK":
                im = im.convert("RGB")
            elif im.mode not in ("RGB", "RGBA", "L", "LA"):
                im = im.convert("RGBA" if "transparency" in im.info else "RGB")

            if flatten_alpha and im.mode in ("RGBA", "LA"):
                background = Image.new("RGB", im.size, (255, 255, 255))
                background.paste(im, mask=im.split()[-1])
                im = background

            buf = io.BytesIO()
            im.save(buf, format="PNG")
            return buf.getvalue()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        log.debug("Image illisible (%s) : %s", image.format, exc)
        return None
