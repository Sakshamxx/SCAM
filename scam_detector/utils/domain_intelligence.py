"""
Domain Intelligence Utility for ScamShield
=========================================
Analyzes domain characteristics to assess trustworthiness:
- Domain age (WHOIS data)
- SSL certificate validity
- Suspicious TLD (.xyz, .top, .click, etc.)
- Free-hosted domains (Blogspot, Wix, WordPress free, etc.)

Returns domain risk score (0-100) as part of hybrid scam detection.
"""
import re
import socket
import ssl
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse


# Suspicious TLDs commonly used by scammers
SUSPICIOUS_TLDS = {
    '.xyz', '.top', '.click', '.site', '.download', '.stream', '.loan',
    '.trade', '.bid', '.date', '.webcam', '.science', '.accountant',
    '.faith', '.pro', '.online', '.host', '.press', '.services',
    '.tech', '.work', '.win', '.app', '.cloud', '.software',
}

# Free hosting platforms
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


def extract_domain(url: Optional[str]) -> Optional[str]:
    """
    Extract domain from URL.
    
    Args:
        url: Full URL
        
    Returns:
        Domain name (e.g., 'example.com')
    """
    if not url:
        return None
        
    try:
        url = str(url).strip()
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
            
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        
        # Remove www
        if domain.startswith('www.'):
            domain = domain[4:]
            
        return domain
    except Exception:
        return None


def get_tld(domain: Optional[str]) -> Optional[str]:
    """Get TLD from domain."""
    if not domain:
        return None
    parts = domain.split('.')
    if len(parts) >= 2:
        return '.' + parts[-1].lower()
    return None


def check_free_hosting(domain: Optional[str]) -> bool:
    """
    Check if domain is on a free hosting platform.
    
    Args:
        domain: Domain name
        
    Returns:
        True if on free hosting
    """
    if not domain:
        return False
        
    domain_lower = domain.lower()
    for pattern in FREE_HOSTING_PATTERNS:
        if re.search(pattern, domain_lower, re.IGNORECASE):
            return True
    return False


def check_suspicious_tld(domain: Optional[str]) -> bool:
    """
    Check if domain has a suspicious TLD.
    
    Args:
        domain: Domain name
        
    Returns:
        True if TLD is suspicious
    """
    if not domain:
        return False
        
    tld = get_tld(domain)
    if not tld:
        return False
        
    return tld.lower() in SUSPICIOUS_TLDS


def check_ssl_certificate(domain: Optional[str]) -> Tuple[bool, Optional[str]]:
    """
    Check if domain has a valid SSL certificate.
    
    Args:
        domain: Domain name
        
    Returns:
        Tuple of (has_valid_ssl, error_message)
    """
    if not domain:
        return False, "No domain provided"
        
    try:
        # Simple SSL check
        context = ssl.create_default_context()
        with socket.create_connection((domain, 443), timeout=5) as sock:
            with context.wrap_socket(sock, server_hostname=domain) as ssock:
                cert = ssock.getpeercert()
                if cert:
                    # Check if cert is valid
                    not_after = cert.get('notAfter')
                    if not_after:
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


def estimate_domain_age(domain: Optional[str]) -> Tuple[int, Optional[str]]:
    """
    Estimate domain age in days.
    
    NOTE: This is a simplified version. In production, use:
    - WHOIS lookup (python-whois library)
    - DNS SOA records
    - SSL certificate creation date
    
    Args:
        domain: Domain name
        
    Returns:
        Tuple of (age_days, error_message)
    """
    if not domain:
        return 0, "No domain provided"
        
    try:
        # Try to get SSL cert creation date as proxy for domain age
        context = ssl.create_default_context()
        with socket.create_connection((domain, 443), timeout=5) as sock:
            with context.wrap_socket(sock, server_hostname=domain) as ssock:
                cert = ssock.getpeercert()
                if cert:
                    not_before = cert.get('notBefore')
                    if not_before:
                        # Parse SSL cert date
                        cert_date = datetime.strptime(not_before, '%b %d %H:%M:%S %Y %Z')
                        age_days = (datetime.now() - cert_date).days
                        return max(0, age_days), None
        
        # Fallback: assume domain is new if SSL check fails
        return 0, "Could not determine domain age"
    except Exception as e:
        # Default to 0 days (very new domain)
        return 0, str(e)


def calculate_domain_age_risk(age_days: int) -> float:
    """
    Calculate risk score based on domain age.
    
    Risk Mapping (per requirements):
    - 0–6 Months:       Risk = 100
    - 6 Months–2 Years: Risk = 60
    - 2–5 Years:        Risk = 30
    - 5+ Years:         Risk = 0
    
    Args:
        age_days: Age of domain in days
        
    Returns:
        Risk score (0-100)
    """
    if age_days < 180:  # 0-6 months
        return 100.0
    elif age_days < 730:  # 6 months - 2 years
        return 60.0
    elif age_days < 1825:  # 2-5 years
        return 30.0
    else:  # 5+ years
        return 0.0


def compute_domain_intelligence_score(url: Optional[str]) -> float:
    """
    Compute comprehensive domain intelligence risk score (0-100).
    
    Factors:
    - Domain Age: 0–100 points
    - No SSL Certificate: +20 points
    - Suspicious TLD: +20 points
    - Free Hosting: +25 points
    
    Maximum normalized to 100.
    
    Args:
        url: Full URL of job posting
        
    Returns:
        Domain risk score (0-100)
    """
    domain = extract_domain(url)
    if not domain:
        return 50.0  # Neutral if can't extract domain
        
    score = 0.0
    
    # Factor 1: Domain Age (base score)
    age_days, _ = estimate_domain_age(domain)
    age_risk = calculate_domain_age_risk(age_days)
    score += age_risk
    
    # Factor 2: No SSL Certificate
    has_ssl, _ = check_ssl_certificate(domain)
    if not has_ssl:
        score += 20.0
        
    # Factor 3: Suspicious TLD
    if check_suspicious_tld(domain):
        score += 20.0
        
    # Factor 4: Free Hosting Platform
    if check_free_hosting(domain):
        score += 25.0
        
    # Normalize to 0-100
    final_score = min(100.0, max(0.0, score))
    return final_score


def get_domain_intelligence_details(url: Optional[str]) -> Dict:
    """
    Get detailed domain intelligence report.
    
    Args:
        url: Full URL of job posting
        
    Returns:
        Dictionary with domain details and risk factors
    """
    domain = extract_domain(url)
    if not domain:
        return {
            'domain': None,
            'score': 50.0,
            'risk_factors': ['Could not extract domain'],
            'has_ssl': False,
            'domain_age_days': 0,
            'is_free_hosting': False,
            'is_suspicious_tld': False,
        }
    
    age_days, _ = estimate_domain_age(domain)
    has_ssl, ssl_error = check_ssl_certificate(domain)
    is_free = check_free_hosting(domain)
    is_susp_tld = check_suspicious_tld(domain)
    
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
        'domain_age_days': age_days,
        'is_free_hosting': is_free,
        'is_suspicious_tld': is_susp_tld,
        'ssl_error': ssl_error if not has_ssl else None,
    }
