"""
scamshield_scraper.py
=====================
Standalone ScamShield scraper — consolidates validator, scraper,
url_computation, extractor, explain, helpers, recommendation, and
analysis_service into a single runnable pipeline.

Usage
-----
    python scamshield_scraper.py --url  "https://example.com/job"
    python scamshield_scraper.py --text "Earn ₹50,000 daily!  WhatsApp us now."
    python scamshield_scraper.py --pdf  "/path/to/job_offer.pdf"
    python scamshield_scraper.py --image "/path/to/job_poster.png"

Requirements
------------
    pip install requests beautifulsoup4 tldextract python-whois \
                pymupdf pytesseract pillow opencv-python numpy
    # tesseract binary must be installed separately (see TESSERACT_CMD below)
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
import time
from io import BytesIO
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import numpy as np
import requests
import tldextract
import whois
from bs4 import BeautifulSoup
# cv2 / fitz / pytesseract are OCR/PDF-only — imported lazily below so a
# missing/broken install of those doesn't take down URL/text scraping.

# ──────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ──────────────────────────────────────────────────────────────────────────────

REQUEST_TIMEOUT = 10
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# Update this path if Tesseract is installed elsewhere
import os
from dotenv import load_dotenv
load_dotenv()
TESSERACT_CMD = os.getenv("TESSERACT_CMD", r"C:\Program Files\Tesseract-OCR\tesseract.exe")

MAX_CLEAN_CHARS = 5000

SUSPICIOUS_TLDS = {
    "xyz", "top", "click", "online", "site", "live",
    "shop", "buzz", "work", "loan", "win", "gq",
    "ml", "cf", "tk", "ga", "pw", "cc", "biz",
    "info", "mobi", "name", "pro", "link", "space",
    "website", "press", "rocks", "fun", "icu",
}

FREE_EMAIL_DOMAINS = ["gmail.com", "yahoo.com", "hotmail.com", "rediffmail.com"]

DOMAIN_WEIGHT  = 0.40
CONTENT_WEIGHT = 0.60


# ──────────────────────────────────────────────────────────────────────────────
# STEP 2  ─  URL VALIDATION
# ──────────────────────────────────────────────────────────────────────────────

def validate_url(url: str) -> bool:
    if not isinstance(url, str) or not url.strip():
        return False
    try:
        parsed = urlparse(url.strip())
        if parsed.scheme not in ("http", "https"):
            return False
        if not parsed.netloc:
            return False
        if "." not in parsed.netloc:
            return False
        return True
    except Exception:
        return False


# ──────────────────────────────────────────────────────────────────────────────
# STEP 3  ─  DOMAIN EXTRACTION
# ──────────────────────────────────────────────────────────────────────────────

def extract_domain_info(url: str) -> dict:
    try:
        ext       = tldextract.extract(url)
        subdomain = ext.subdomain or ""
        domain    = ext.domain    or ""
        suffix    = ext.suffix    or ""
        parts     = [p for p in [subdomain, domain, suffix] if p]
        return {
            "subdomain"  : subdomain,
            "domain"     : domain,
            "suffix"     : suffix,
            "full_domain": ".".join(parts),
        }
    except Exception:
        return {"subdomain": "", "domain": "", "suffix": "", "full_domain": ""}


# ──────────────────────────────────────────────────────────────────────────────
# STEP 4  ─  HTTPS CHECK
# ──────────────────────────────────────────────────────────────────────────────

def check_https(url: str) -> bool:
    try:
        return urlparse(url.strip()).scheme.lower() == "https"
    except Exception:
        return False


# ──────────────────────────────────────────────────────────────────────────────
# STEP 5  ─  DOMAIN AGE (WHOIS)
# ──────────────────────────────────────────────────────────────────────────────

def get_domain_age(url: str) -> dict:
    domain_info = extract_domain_info(url)
    root_domain = f"{domain_info['domain']}.{domain_info['suffix']}"
    try:
        w        = whois.whois(root_domain)
        creation = w.creation_date

        if isinstance(creation, list):
            creation = min(
                [d for d in creation if isinstance(d, datetime.datetime)],
                default=None,
            )

        if creation is None or not isinstance(creation, datetime.datetime):
            return {"creation_date": "Unknown", "domain_age_days": -1, "domain_age_risk": "UNKNOWN"}

        now = datetime.datetime.now()
        if creation.tzinfo is not None:
            creation = creation.replace(tzinfo=None)

        age_days = (now - creation).days
        risk     = "HIGH" if age_days < 30 else ("MEDIUM" if age_days < 180 else "LOW")

        return {
            "creation_date"  : creation.strftime("%Y-%m-%d"),
            "domain_age_days": age_days,
            "domain_age_risk": risk,
        }
    except Exception:
        return {"creation_date": "Unknown", "domain_age_days": -1, "domain_age_risk": "UNKNOWN"}


# ──────────────────────────────────────────────────────────────────────────────
# STEP 6  ─  SUSPICIOUS TLD
# ──────────────────────────────────────────────────────────────────────────────

def check_suspicious_tld(url: str) -> dict:
    domain_info = extract_domain_info(url)
    suffix      = domain_info.get("suffix", "").lower()
    final_tld   = suffix.split(".")[-1] if suffix else ""
    return {
        "suffix"        : suffix,
        "suspicious_tld": 1 if final_tld in SUSPICIOUS_TLDS else 0,
    }


# ──────────────────────────────────────────────────────────────────────────────
# STEP 7  ─  WEBSITE AVAILABILITY
# ──────────────────────────────────────────────────────────────────────────────

def check_website_availability(url: str) -> dict:
    try:
        start    = time.time()
        response = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        elapsed  = round((time.time() - start) * 1000, 2)
        return {
            "status_code"      : response.status_code,
            "website_reachable": 200 <= response.status_code < 400,
            "response_time_ms" : elapsed,
            "error_message"    : "",
        }
    except requests.exceptions.SSLError:
        return {"status_code": -1, "website_reachable": False, "response_time_ms": 0, "error_message": "SSL certificate error"}
    except requests.exceptions.ConnectionError:
        return {"status_code": -1, "website_reachable": False, "response_time_ms": 0, "error_message": "Connection refused or DNS failure"}
    except requests.exceptions.Timeout:
        return {"status_code": -1, "website_reachable": False, "response_time_ms": 0, "error_message": f"Request timed out after {REQUEST_TIMEOUT}s"}
    except Exception as e:
        return {"status_code": -1, "website_reachable": False, "response_time_ms": 0, "error_message": str(e)}


# ──────────────────────────────────────────────────────────────────────────────
# STEP 8  ─  WEB SCRAPING
# ──────────────────────────────────────────────────────────────────────────────

def scrape_url(url: str) -> dict:
    default = {
        "page_title": "", "meta_description": "", "body_text": "",
        "all_links": [], "emails": [], "phone_numbers": [], "scrape_success": False,
    }
    try:
        response = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        if response.status_code != 200:
            return default

        soup = BeautifulSoup(response.text, "html.parser")

        title_tag  = soup.find("title")
        page_title = title_tag.get_text(strip=True) if title_tag else ""

        meta_tag  = soup.find("meta", attrs={"name": re.compile("description", re.I)})
        meta_desc = meta_tag.get("content", "") if meta_tag else ""

        for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
            tag.decompose()
        body_text = soup.get_text(separator=" ", strip=True)

        all_links = list(set(
            a.get("href", "") for a in soup.find_all("a", href=True)
            if a.get("href", "").startswith("http")
        ))

        emails        = list(set(re.findall(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", response.text)))
        phone_numbers = list(set(re.findall(r"(?:\+91[\-\s]?)?[6-9]\d{9}|\b\d{7,12}\b", body_text)))

        return {
            "page_title"      : page_title,
            "meta_description": meta_desc,
            "body_text"       : body_text,
            "all_links"       : all_links,
            "emails"          : emails,
            "phone_numbers"   : phone_numbers,
            "scrape_success"  : True,
        }
    except Exception:
        return default


# ──────────────────────────────────────────────────────────────────────────────
# STEP 9  ─  CONTENT CLEANING
# ──────────────────────────────────────────────────────────────────────────────

def clean_scraped_text(raw_text: str) -> str:
    if not raw_text or not isinstance(raw_text, str):
        return ""
    text = raw_text.lower()
    text = re.sub(r"https?://\S+|www\.\S+", " ", text)
    text = re.sub(r"\S+@\S+\.\S+",          " ", text)
    text = re.sub(r"[^a-z\s]",              " ", text)
    text = re.sub(r"\s+",                   " ", text)
    return text.strip()[:MAX_CLEAN_CHARS]


# ──────────────────────────────────────────────────────────────────────────────
# STEP 10 ─  RULE-BASED CONTENT ANALYSIS  (lightweight, no ML model needed)
# ──────────────────────────────────────────────────────────────────────────────

_FRAUD_PHRASES = [
    "registration fee", "security deposit", "processing fee",
    "training fee", "joining fee", "investment required",
    "earn money fast", "guaranteed income", "pay upfront",
    "advance payment", "pay to work", "get rich",
    "100% profit", "wire transfer", "data entry work",
    "typing work from home",
]
_URGENCY_PHRASES = [
    "apply now", "urgent hiring", "limited seats",
    "immediate joining", "instant selection", "deadline today",
]
_CONTACT_TERMS = [
    "telegram", "whatsapp", "gmail.com", "yahoo.com",
    "hotmail.com", "call now", "wechat",
]

def analyze_text_rules(text: str) -> dict:
    """
    Rule-based scorer. Returns rule_score (0-100) and matched reasons.
    No ML model required — works standalone.
    """
    t       = text.lower()
    reasons = []
    score   = 0

    for p in _FRAUD_PHRASES:
        if p in t:
            reasons.append(f"Fraud phrase detected: '{p}'")
            score += 10

    for u in _URGENCY_PHRASES:
        if u in t:
            reasons.append(f"Urgency tactic: '{u}'")
            score += 5

    for c in _CONTACT_TERMS:
        if c in t:
            reasons.append(f"Risky contact channel: '{c}'")
            score += 5

    if re.search(r"\b[\w.+-]+@(gmail|yahoo|hotmail|rediffmail|outlook|ymail)\.com\b", text, re.I):
        reasons.append("Personal email address used for hiring")
        score += 8

    if len(re.findall(r"\b\w+\b", text)) < 50:
        reasons.append("Very short posting — low information content")
        score += 7

    anon_indicators = [
        "company name not disclosed", "client of ours",
        "undisclosed company", "anonymous client",
        "confidential company", "our client",
    ]
    if any(ind in t for ind in anon_indicators):
        reasons.append("Anonymous/undisclosed recruiter")
        score += 8

    rule_score = min(score, 100)
    if not reasons:
        reasons.append("No significant fraud indicators detected")

    return {"rule_score": rule_score, "fraud_reasons": reasons}


# ──────────────────────────────────────────────────────────────────────────────
# STEP 11 ─  DOMAIN RISK SCORE
# ──────────────────────────────────────────────────────────────────────────────

def compute_domain_risk_score(https_enabled: bool, domain_age_days: int,
                               domain_age_risk: str, suspicious_tld: int,
                               website_reachable: bool) -> dict:
    bd = {}
    bd["domain_age_score"]    = {"HIGH": 40, "MEDIUM": 20, "LOW": 0}.get(domain_age_risk, 15)
    bd["https_score"]         = 0 if https_enabled else 20
    bd["tld_score"]           = 25 if suspicious_tld else 0
    bd["availability_score"]  = 0 if website_reachable else 15

    total = min(sum(bd.values()), 100)
    level = "HIGH" if total >= 60 else ("MEDIUM" if total >= 30 else "LOW")

    return {
        "domain_risk_score"    : total,
        "domain_risk_level"    : level,
        "domain_risk_breakdown": bd,
    }


# ──────────────────────────────────────────────────────────────────────────────
# STEP 12 ─  FINAL RISK SCORE
# ──────────────────────────────────────────────────────────────────────────────

def compute_final_risk_score(domain_risk_score: int, content_risk_score: int) -> dict:
    raw   = domain_risk_score * DOMAIN_WEIGHT + content_risk_score * CONTENT_WEIGHT
    score = min(int(round(raw)), 100)
    level = "CRITICAL" if score >= 75 else ("HIGH" if score >= 50 else ("MEDIUM" if score >= 25 else "LOW"))
    return {"final_url_risk_score": score, "final_risk_level": level}


# ──────────────────────────────────────────────────────────────────────────────
# STEP 12b ─  RISK REASONS BUILDER
# ──────────────────────────────────────────────────────────────────────────────

def build_risk_reasons(domain_age_days, domain_age_risk, suspicious_tld,
                        suffix, https_enabled, website_reachable,
                        content_fraud_reasons, emails, phone_numbers) -> list:
    reasons = []

    if domain_age_risk == "HIGH" and domain_age_days >= 0:
        reasons.append(f"Newly registered domain — only {domain_age_days} days old (HIGH RISK)")
    elif domain_age_risk == "MEDIUM" and domain_age_days >= 0:
        reasons.append(f"Recently registered domain — {domain_age_days} days old (MEDIUM RISK)")
    elif domain_age_risk == "UNKNOWN":
        reasons.append("Domain age unknown — WHOIS lookup failed or privacy-protected")

    if not https_enabled:
        reasons.append("Website uses HTTP only — no SSL/TLS encryption")

    if suspicious_tld:
        reasons.append(f"Suspicious TLD detected: .{suffix} — commonly used by fraudulent sites")

    if not website_reachable:
        reasons.append("Website is currently unreachable — may have been taken down")

    suspicious_emails = [e for e in emails if any(d in e for d in FREE_EMAIL_DOMAINS)]
    if suspicious_emails:
        reasons.append(f"Recruiter uses free email service(s): {suspicious_emails[:3]}")

    if len(phone_numbers) > 2:
        reasons.append(f"Multiple phone numbers found ({len(phone_numbers)}) — unusual for legitimate postings")

    reasons.extend(content_fraud_reasons)
    return reasons


# ──────────────────────────────────────────────────────────────────────────────
# STEP 13 ─  TRUST + RECOMMENDATION
# ──────────────────────────────────────────────────────────────────────────────

def compute_trust(risk_score: float) -> dict:
    trust_score = round(100 - risk_score, 2)
    trust_level = ("High Trust" if trust_score > 60 else
                   ("Moderate Trust" if trust_score > 30 else "Low Trust"))
    return {"trust_score": trust_score, "trust_level": trust_level}


def get_recommendation(risk_level: str, risk_score: float) -> str:
    if risk_level == "LOW":
        return "Safe to Proceed"
    elif risk_level == "MEDIUM":
        return "Review Before Applying" if risk_score < 55 else "Manual Verification Required"
    else:
        return "Potential Scam Detected — Do Not Apply"


# ──────────────────────────────────────────────────────────────────────────────
# FILE EXTRACTORS  (PDF / Image)
# ──────────────────────────────────────────────────────────────────────────────

def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    import fitz  # PyMuPDF — imported here so a missing install only breaks PDF extraction
    text = []
    try:
        pdf = fitz.open(stream=BytesIO(pdf_bytes), filetype="pdf")
        for page in pdf:
            t = page.get_text()
            if t:
                text.append(t)
        pdf.close()
        return "\n".join(text)
    except Exception as e:
        raise RuntimeError(f"PDF extraction failed: {e}")


def extract_text_from_image(image_bytes: bytes) -> str:
    import cv2          # imported here so a missing/broken install only breaks image OCR
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
    try:
        np_img = np.frombuffer(image_bytes, np.uint8)
        img    = cv2.imdecode(np_img, cv2.IMREAD_COLOR)
        gray   = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray   = cv2.GaussianBlur(gray, (3, 3), 0)
        _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
        return pytesseract.image_to_string(thresh, lang="eng").strip()
    except Exception as e:
        raise RuntimeError(f"Image OCR failed: {e}")


# ──────────────────────────────────────────────────────────────────────────────
# MAIN PIPELINES
# ──────────────────────────────────────────────────────────────────────────────

def analyze_text(text: str) -> dict:
    """Full analysis for raw text input (job description, etc.)."""
    content = analyze_text_rules(text)
    rule_score   = content["rule_score"]
    fraud_reasons = content["fraud_reasons"]

    # No ML model loaded — use rule score as final content score
    trust   = compute_trust(rule_score)
    final   = compute_final_risk_score(0, rule_score)      # domain=0 for text-only

    level   = ("HIGH" if rule_score >= 70 else ("MEDIUM" if rule_score >= 40 else "LOW"))

    return {
        "source_type"   : "TEXT",
        "risk_score"    : rule_score,
        "risk_level"    : level,
        "trust_score"   : trust["trust_score"],
        "trust_level"   : trust["trust_level"],
        "fraud_reasons" : fraud_reasons,
        "recommendation": get_recommendation(level, rule_score),
    }


def analyze_url(url: str) -> dict:
    """Full URL analysis pipeline."""
    if not validate_url(url):
        return {"error": f"Invalid URL: {url}"}

    # Domain signals
    domain_info  = extract_domain_info(url)
    https        = check_https(url)
    age          = get_domain_age(url)
    tld          = check_suspicious_tld(url)
    avail        = check_website_availability(url)

    domain_risk  = compute_domain_risk_score(
        https_enabled    = https,
        domain_age_days  = age["domain_age_days"],
        domain_age_risk  = age["domain_age_risk"],
        suspicious_tld   = tld["suspicious_tld"],
        website_reachable= avail["website_reachable"],
    )

    # Content signals
    scraped      = scrape_url(url)
    clean_text   = clean_scraped_text(scraped["body_text"])
    content      = analyze_text_rules(clean_text or scraped["page_title"])

    # Final blend
    final        = compute_final_risk_score(domain_risk["domain_risk_score"], content["rule_score"])
    trust        = compute_trust(final["final_url_risk_score"])

    all_reasons  = build_risk_reasons(
        domain_age_days      = age["domain_age_days"],
        domain_age_risk      = age["domain_age_risk"],
        suspicious_tld       = tld["suspicious_tld"],
        suffix               = tld["suffix"],
        https_enabled        = https,
        website_reachable    = avail["website_reachable"],
        content_fraud_reasons= content["fraud_reasons"],
        emails               = scraped["emails"],
        phone_numbers        = scraped["phone_numbers"],
    )

    return {
        "source_type"          : "URL",
        "url"                  : url,
        "domain"               : domain_info["full_domain"],
        "https_enabled"        : https,
        "creation_date"        : age["creation_date"],
        "domain_age_days"      : age["domain_age_days"],
        "domain_age_risk"      : age["domain_age_risk"],
        "suspicious_tld"       : tld["suspicious_tld"],
        "suffix"               : tld["suffix"],
        "website_reachable"    : avail["website_reachable"],
        "status_code"          : avail["status_code"],
        "response_time_ms"     : avail["response_time_ms"],
        "page_title"           : scraped["page_title"],
        "emails"               : scraped["emails"],
        "phone_numbers"        : scraped["phone_numbers"],
        "domain_risk_score"    : domain_risk["domain_risk_score"],
        "domain_risk_level"    : domain_risk["domain_risk_level"],
        "domain_risk_breakdown": domain_risk["domain_risk_breakdown"],
        "content_rule_score"   : content["rule_score"],
        "risk_score"           : final["final_url_risk_score"],
        "risk_level"           : final["final_risk_level"],
        "trust_score"          : trust["trust_score"],
        "trust_level"          : trust["trust_level"],
        "fraud_reasons"        : all_reasons,
        "recommendation"       : get_recommendation(final["final_risk_level"], final["final_url_risk_score"]),
    }


def analyze_file(source_type: str, file_path: str) -> dict:
    """Analyze a PDF or Image file by path."""
    data = Path(file_path).read_bytes()
    if source_type == "PDF":
        text = extract_text_from_pdf(data)
    else:
        text = extract_text_from_image(data)
    result = analyze_text(text)
    result["source_type"] = source_type
    result["file_path"]   = file_path
    return result


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

def pretty_print(result: dict) -> None:
    print("\n" + "═" * 60)
    print("  🛡  SCAMSHIELD ANALYSIS REPORT")
    print("═" * 60)
    for key, value in result.items():
        if key == "fraud_reasons":
            print(f"\n  Fraud Reasons:")
            for r in value:
                print(f"    • {r}")
        elif key == "domain_risk_breakdown":
            print(f"\n  Domain Risk Breakdown:")
            for k2, v2 in value.items():
                print(f"    {k2}: {v2}")
        else:
            print(f"  {key}: {value}")
    print("═" * 60 + "\n")


def main():
    parser = argparse.ArgumentParser(description="ScamShield Scraper")
    group  = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--url",   help="Job posting URL to analyse")
    group.add_argument("--text",  help="Raw job description text")
    group.add_argument("--pdf",   help="Path to PDF job offer")
    group.add_argument("--image", help="Path to image job poster")
    parser.add_argument("--json", action="store_true", help="Output raw JSON instead of formatted report")
    args = parser.parse_args()

    if args.url:
        result = analyze_url(args.url)
    elif args.text:
        result = analyze_text(args.text)
    elif args.pdf:
        result = analyze_file("PDF", args.pdf)
    else:
        result = analyze_file("IMAGE", args.image)

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        pretty_print(result)


if __name__ == "__main__":
    main()
