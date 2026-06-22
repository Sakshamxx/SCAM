"""
Domain Intelligence Utility for ScamShield v3.0
================================================
WHOIS-primary domain analysis with SSL fallback.

Risk Scoring:
  Domain Age:
    0–6 months   → 100
    6m–2 years   → 60
    2–5 years    → 30
    5+ years     → 0
  Additional Signals:
    No SSL       → +20
    Suspicious TLD → +20
    Free hosting → +25
  Normalized to max 100.

Returns domain risk score (0–100) as part of hybrid scam detection.
"""
import re
import socket
import ssl
from datetime import datetime
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse

# WHOIS support (python-whois)
try:
    import whois as _whois_lib
    _whois_available = True
except ImportError:
    _whois_available = False

# ── Constants ──────────────────────────────────────────────────────────────────

SUSPICIOUS_TLDS = {
    '.xyz', '.top', '.click', '.site', '.download', '.stream', '.loan',
    '.trade', '.bid', '.date', '.webcam', '.science', '.accountant',
    '.faith', '.pro', '.online', '.host', '.press', '.services',
    '.tech', '.work', '.win', '.app', '.cloud', '.software',
}

FREE_HOSTING_PATTERNS = [
    r'\.blogspot\.com',
    r'\.wordpress\.com',
    r'\.wix\.com',
    r'\.weebly\.com',
    r'\.squarespace\.com',
    r'\.github\.io',
    r'\.netlify\.com',
    r'\.vercel\.app',
    r'\.herokuapp\.com',
    r'\.tumblr\.com',
    r'\.simdif\.com',
    r'\.freewebs\.com',
    r'\.yolasite\.com',
    r'\.jimdo\.com',
]

# ── Helpers ────────────────────────────────────────────────────────────────────

def extract_domain(url: Optional[str]) -> Optional[str]:
    """Extract clean domain from URL."""
    if not url:
        return None
    try:
        url = str(url).strip()
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if domain.startswith('www.'):
            domain = domain[4:]
        return domain or None
    except Exception:
        return None


def get_tld(domain: Optional[str]) -> Optional[str]:
    if not domain:
        return None
    parts = domain.split('.')
    if len(parts) >= 2:
        return '.' + parts[-1].lower()
    return None


def check_free_hosting(domain: Optional[str]) -> bool:
    if not domain:
        return False
    domain_lower = domain.lower()
    for pattern in FREE_HOSTING_PATTERNS:
        if re.search(pattern, domain_lower, re.IGNORECASE):
            return True
    return False


def check_suspicious_tld(domain: Optional[str]) -> bool:
    if not domain:
        return False
    tld = get_tld(domain)
    return bool(tld and tld.lower() in SUSPICIOUS_TLDS)


# ── SSL Check ──────────────────────────────────────────────────────────────────

def check_ssl_certificate(domain: Optional[str]) -> Tuple[bool, Optional[str]]:
    """Check if domain has a valid SSL certificate. Returns (has_ssl, error)."""
    if not domain:
        return False, "No domain provided"
    try:
        context = ssl.create_default_context()
        with socket.create_connection((domain, 443), timeout=5) as sock:
            with context.wrap_socket(sock, server_hostname=domain) as ssock:
                cert = ssock.getpeercert()
                if cert:
                    return True, None
        return True, None
    except ssl.SSLError as e:
        return False, f"SSL Error: {str(e)}"
    except socket.timeout:
        return False, "SSL check timeout"
    except ConnectionRefusedError:
        return False, "Connection refused"
    except Exception as e:
        return False, str(e)


# ── WHOIS Age Estimation ───────────────────────────────────────────────────────

def _parse_whois_date(val) -> Optional[datetime]:
    """Parse a WHOIS date field which may be a list, datetime, or string."""
    if val is None:
        return None
    if isinstance(val, list):
        val = val[0]
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        for fmt in ('%Y-%m-%d', '%d-%b-%Y', '%Y-%m-%dT%H:%M:%SZ', '%d %b %Y'):
            try:
                return datetime.strptime(val.strip(), fmt)
            except ValueError:
                pass
    return None


def get_domain_age_via_whois(domain: str) -> Tuple[int, Optional[str]]:
    """
    Query WHOIS for domain creation date and return age in days.
    Returns (age_days, error_message).
    """
    if not _whois_available:
        return 0, "python-whois not installed"
    try:
        w = _whois_lib.whois(domain)
        creation_date = _parse_whois_date(getattr(w, 'creation_date', None))
        if creation_date:
            # Make timezone-naive if needed
            if hasattr(creation_date, 'tzinfo') and creation_date.tzinfo is not None:
                from datetime import timezone
                now = datetime.now(timezone.utc)
            else:
                now = datetime.now()
            age_days = (now - creation_date).days
            return max(0, age_days), None
        return 0, "WHOIS creation_date not found"
    except Exception as e:
        return 0, f"WHOIS error: {str(e)}"


def get_domain_age_via_ssl(domain: str) -> Tuple[int, Optional[str]]:
    """
    Fallback: estimate domain age from SSL certificate notBefore date.
    Returns (age_days, error_message).
    """
    try:
        context = ssl.create_default_context()
        with socket.create_connection((domain, 443), timeout=5) as sock:
            with context.wrap_socket(sock, server_hostname=domain) as ssock:
                cert = ssock.getpeercert()
                if cert:
                    not_before = cert.get('notBefore')
                    if not_before:
                        cert_date = datetime.strptime(not_before, '%b %d %H:%M:%S %Y %Z')
                        age_days = (datetime.now() - cert_date).days
                        return max(0, age_days), None
        return 0, "SSL cert notBefore not found"
    except Exception as e:
        return 0, str(e)


def estimate_domain_age(domain: Optional[str]) -> Tuple[int, Optional[str]]:
    """
    Get domain age in days. Tries WHOIS first, falls back to SSL cert date.
    Returns (age_days, method_used_or_error).
    """
    if not domain:
        return 0, "No domain provided"

    # Primary: WHOIS
    age_days, err = get_domain_age_via_whois(domain)
    if age_days > 0:
        return age_days, f"WHOIS (creation_date)"

    # Fallback: SSL cert date
    age_days_ssl, err_ssl = get_domain_age_via_ssl(domain)
    if age_days_ssl > 0:
        return age_days_ssl, f"SSL cert (fallback)"

    return 0, err or err_ssl


# ── Risk Calculation ───────────────────────────────────────────────────────────

def calculate_domain_age_risk(age_days: int) -> float:
    """
    Risk score from domain age.
    0–6 months   → 100
    6m–2 years   → 60
    2–5 years    → 30
    5+ years     → 0
    """
    if age_days < 180:
        return 100.0
    elif age_days < 730:
        return 60.0
    elif age_days < 1825:
        return 30.0
    else:
        return 0.0


def compute_domain_intelligence_score(url: Optional[str]) -> float:
    """
    Compute composite domain risk score (0–100).
    Factors: Age (base) + No SSL (+20) + Suspicious TLD (+20) + Free hosting (+25).
    """
    domain = extract_domain(url)
    if not domain:
        return 50.0  # neutral if can't extract

    score = 0.0

    # Factor 1: Domain Age (primary: WHOIS, fallback: SSL)
    age_days, _ = estimate_domain_age(domain)
    score += calculate_domain_age_risk(age_days)

    # Factor 2: No SSL
    has_ssl, _ = check_ssl_certificate(domain)
    if not has_ssl:
        score += 20.0

    # Factor 3: Suspicious TLD
    if check_suspicious_tld(domain):
        score += 20.0

    # Factor 4: Free hosting
    if check_free_hosting(domain):
        score += 25.0

    return round(min(100.0, max(0.0, score)), 1)


def get_domain_intelligence_details(url: Optional[str]) -> Dict:
    """
    Full domain intelligence report as a dict.
    """
    domain = extract_domain(url)
    if not domain:
        return {
            'domain': None,
            'score': 50.0,
            'risk_factors': ['Could not extract domain'],
            'has_ssl': False,
            'domain_age_days': 0,
            'domain_age_source': 'unavailable',
            'is_free_hosting': False,
            'is_suspicious_tld': False,
            'registrar': None,
            'whois_available': _whois_available,
        }

    age_days, age_source  = estimate_domain_age(domain)
    has_ssl, ssl_error     = check_ssl_certificate(domain)
    is_free                = check_free_hosting(domain)
    is_susp_tld            = check_suspicious_tld(domain)

    # Try to get registrar info
    registrar = None
    expiry_date = None
    try:
        if _whois_available:
            w = _whois_lib.whois(domain)
            registrar = getattr(w, 'registrar', None)
            if isinstance(registrar, list):
                registrar = registrar[0]
            expiry_raw = _parse_whois_date(getattr(w, 'expiration_date', None))
            if expiry_raw:
                expiry_date = expiry_raw.strftime('%Y-%m-%d')
    except Exception:
        pass

    # Build risk factors
    risk_factors = []
    if age_days < 180:
        risk_factors.append(f"Very new domain (only {age_days} days old)")
    elif age_days < 730:
        risk_factors.append(f"Relatively new domain ({age_days // 30} months old)")

    if not has_ssl:
        risk_factors.append("No valid SSL certificate")
    if is_susp_tld:
        risk_factors.append(f"Suspicious TLD: {get_tld(domain)}")
    if is_free:
        risk_factors.append("Free hosting platform (WordPress, Blogspot, etc.)")

    score = compute_domain_intelligence_score(url)

    return {
        'domain': domain,
        'score': score,
        'risk_factors': risk_factors,
        'has_ssl': has_ssl,
        'ssl_error': ssl_error if not has_ssl else None,
        'domain_age_days': age_days,
        'domain_age_source': age_source,
        'is_free_hosting': is_free,
        'is_suspicious_tld': is_susp_tld,
        'registrar': registrar,
        'expiry_date': expiry_date,
        'whois_available': _whois_available,
    }
