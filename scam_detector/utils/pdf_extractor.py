"""
ScamShield — Multi-layer PDF Text Extractor
============================================
Layer 1: pdfplumber  (fast, accurate for digital PDFs)
Layer 2: PyMuPDF/fitz (robust, handles more PDF types)
Layer 3: OCR pipeline via pdf2image + pytesseract (for scanned/image PDFs)

Usage:
    from utils.pdf_extractor import extract_pdf_text, ExtractionResult
    result = extract_pdf_text(pdf_bytes)
    if result.success:
        text = result.text   # cleaned, merged text from all pages
"""
from __future__ import annotations

import io
import logging
import re
import hashlib
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# ── Minimum characters to consider extraction successful ────────────────────
_MIN_TEXT_LENGTH = 100
# ── In-memory cache: sha256 → ExtractionResult ──────────────────────────────
_cache: dict[str, "ExtractionResult"] = {}


@dataclass
class ExtractionResult:
    success: bool
    text: str
    method: str          # 'pdfplumber' | 'pymupdf' | 'ocr_tesseract' | 'failed'
    pages: int = 0
    error: Optional[str] = None


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _clean(text: str) -> str:
    """Collapse excessive whitespace and remove control chars."""
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    text = re.sub(r'\r\n', '\n', text)
    text = re.sub(r'\n{4,}', '\n\n\n', text)
    text = re.sub(r' {3,}', ' ', text)
    return text.strip()


# ────────────────────────────────────────────────────────────────────────────
# Layer 1 — pdfplumber
# ────────────────────────────────────────────────────────────────────────────
def _try_pdfplumber(pdf_bytes: bytes) -> Optional[ExtractionResult]:
    try:
        import pdfplumber  # type: ignore
        pages_text = []
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                try:
                    t = page.extract_text() or ''
                    pages_text.append(t)
                except Exception as page_err:
                    logger.debug('[pdf_extractor] pdfplumber page extraction failed: %s', page_err)
                    continue
        
        if pages_text:
            merged  = '\n\n'.join(pages_text)
            cleaned = _clean(merged)
            if len(cleaned) >= _MIN_TEXT_LENGTH:
                logger.info('[pdf_extractor] pdfplumber succeeded (%d chars from %d pages)', len(cleaned), len(pages_text))
                return ExtractionResult(success=True, text=cleaned,
                                        method='pdfplumber', pages=len(pages_text))
            else:
                logger.debug('[pdf_extractor] pdfplumber: too short (%d chars), will try next layer', len(cleaned))
    except Exception as e:
        logger.warning('[pdf_extractor] pdfplumber failed: %s', e)
    return None


# ────────────────────────────────────────────────────────────────────────────
# Layer 2 — PyMuPDF (fitz)
# ────────────────────────────────────────────────────────────────────────────
def _try_pymupdf(pdf_bytes: bytes) -> Optional[ExtractionResult]:
    try:
        import fitz  # type: ignore  (PyMuPDF)
        doc = fitz.open(stream=pdf_bytes, filetype='pdf')
        pages_text = []
        for page in doc:
            try:
                text = page.get_text('text')  # type: ignore
                pages_text.append(text)
            except Exception as page_err:
                logger.debug('[pdf_extractor] PyMuPDF page extraction failed: %s', page_err)
                continue
        
        doc.close()
        
        if pages_text:
            merged  = '\n\n'.join(pages_text)
            cleaned = _clean(merged)
            if len(cleaned) >= _MIN_TEXT_LENGTH:
                logger.info('[pdf_extractor] PyMuPDF succeeded (%d chars from %d pages)', len(cleaned), len(pages_text))
                return ExtractionResult(success=True, text=cleaned,
                                        method='pymupdf', pages=len(pages_text))
            else:
                logger.debug('[pdf_extractor] PyMuPDF: too short (%d chars), will try next layer', len(cleaned))
    except Exception as e:
        logger.warning('[pdf_extractor] PyMuPDF failed: %s', e)
    return None


# ────────────────────────────────────────────────────────────────────────────
# Layer 3 — OCR via pdf2image + pytesseract
# ────────────────────────────────────────────────────────────────────────────
def _try_ocr_tesseract(pdf_bytes: bytes) -> Optional[ExtractionResult]:
    try:
        from pdf2image import convert_from_bytes  # type: ignore
        import pytesseract  # type: ignore

        logger.info('[pdf_extractor] Attempting OCR (tesseract)...')
        
        # Convert PDF to images with lower DPI to handle more PDFs
        try:
            images = convert_from_bytes(pdf_bytes, dpi=200, fmt='PNG')
        except Exception as img_err:
            logger.debug('[pdf_extractor] pdf2image at 200 DPI failed, trying 150 DPI: %s', img_err)
            try:
                images = convert_from_bytes(pdf_bytes, dpi=150, fmt='PNG')
            except Exception as img_err2:
                logger.debug('[pdf_extractor] pdf2image at 150 DPI also failed: %s', img_err2)
                images = []
        
        if not images:
            logger.warning('[pdf_extractor] Could not convert PDF to images')
            return None
        
        pages_text = []
        for idx, img in enumerate(images):
            try:
                text = pytesseract.image_to_string(img, lang='eng+hin', config='--psm 6')
                if text:
                    pages_text.append(text)
            except Exception as ocr_err:
                logger.debug('[pdf_extractor] OCR failed on page %d: %s', idx, ocr_err)
                continue
        
        if pages_text:
            merged  = '\n\n'.join(pages_text)
            cleaned = _clean(merged)
            if len(cleaned) >= _MIN_TEXT_LENGTH:
                logger.info('[pdf_extractor] OCR (tesseract) succeeded (%d chars from %d pages)', len(cleaned), len(pages_text))
                return ExtractionResult(success=True, text=cleaned,
                                        method='ocr_tesseract', pages=len(pages_text))
            else:
                logger.debug('[pdf_extractor] OCR produced minimal text (%d chars)', len(cleaned))
        else:
            logger.warning('[pdf_extractor] OCR produced no text from any page')
    except ImportError:
        logger.warning('[pdf_extractor] pytesseract or pdf2image not installed, OCR skipped')
    except Exception as e:
        logger.warning('[pdf_extractor] OCR failed: %s', e)
    return None


# ────────────────────────────────────────────────────────────────────────────
# Public API
# ────────────────────────────────────────────────────────────────────────────
def extract_pdf_text(pdf_bytes: bytes) -> ExtractionResult:
    """
    Try each extraction layer in order.
    Returns ExtractionResult with the best available text.
    Results are in-memory cached by SHA-256 of the PDF bytes.
    """
    cache_key = _sha256(pdf_bytes)
    if cache_key in _cache:
        logger.debug('[pdf_extractor] cache hit')
        return _cache[cache_key]

    for layer_fn in (_try_pdfplumber, _try_pymupdf, _try_ocr_tesseract):
        result = layer_fn(pdf_bytes)
        if result is not None:
            _cache[cache_key] = result
            return result

    failed = ExtractionResult(
        success=False,
        text='',
        method='failed',
        error=(
            'Could not extract text from this PDF. '
            'The document may be image-only, encrypted, or corrupt.'
        )
    )
    _cache[cache_key] = failed
    return failed
