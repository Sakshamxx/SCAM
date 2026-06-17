"""
ScamShield — utils package
==========================
Re-exports from sub-modules for convenience.

Usage:
    from utils.scraper import scrape_job, ScrapeResult
    from utils.pdf_extractor import extract_pdf_text, ExtractionResult
"""
from utils.pdf_extractor import extract_pdf_text, ExtractionResult
from utils.scraper import scrape_job, ScrapeResult

__all__ = [
    "extract_pdf_text",
    "ExtractionResult",
    "scrape_job",
    "ScrapeResult",
]
