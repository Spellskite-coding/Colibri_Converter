"""colibri-converter — conversion souveraine DOCX <-> PDF, hors-ligne et auditable."""
__version__ = "0.3.0"

from .engine import convert, docx_to_pdf, pdf_to_docx, ConversionError, ConversionResult
from .validate import audit, roundtrip_audit, FidelityReport

__all__ = [
    "convert", "docx_to_pdf", "pdf_to_docx",
    "ConversionError", "ConversionResult",
    "audit", "roundtrip_audit", "FidelityReport",
]
