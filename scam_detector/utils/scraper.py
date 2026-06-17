"""
ScamShield — Universal Job Scraper
====================================
Multi-stage extraction pipeline:

Stage 1: requests + BeautifulSoup with rotating User-Agents + JSON-LD extraction
Stage 2: Playwright (Chromium headless) for JS-rendered pages with domain-specific logic
Stage 3: Raw HTML dump + generic text extraction as last resort

Platform-specific handlers for Naukri, LinkedIn, Indeed, TCS, Infosys, Deloitte,
HCL, AmEx, Adzuna, Internshala, and generic career pages.

Usage:
    from utils.scraper import scrape_job, ScrapeResult
    result = scrape_job("https://www.naukri.com/...")
    if result.success:
        print(result.data)  # dict: title, company, location, salary, description, skills, source_url
"""
from __future__ import annotations

import hashlib
import json
import logging
import random
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import urllib.parse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ── In-memory URL cache ──────────────────────────────────────────────────────
_url_cache: Dict[str, "ScrapeResult"] = {}

# ── User-Agent pool ──────────────────────────────────────────────────────────
_USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) '
    'Gecko/20100101 Firefox/125.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 14.4; rv:124.0) '
    'Gecko/20100101 Firefox/124.0',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0',
]

# ── Thresholds ───────────────────────────────────────────────────────────────
_MIN_DESC_LENGTH = 200   # characters — below this, try Playwright


@dataclass
class ScrapeResult:
    success: bool
    data: Dict = field(default_factory=dict)
    method: str = ''         # 'bs4' | 'playwright' | 'generic' | 'failed'
    error: Optional[str] = None


def _random_headers() -> Dict[str, str]:
    return {
        'User-Agent': random.choice(_USER_AGENTS),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-IN,en;q=0.9,hi;q=0.7',
        'Accept-Encoding': 'gzip, deflate, br',
        'DNT': '1',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Cache-Control': 'max-age=0',
    }


def _clean_text(text: str) -> str:
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _extract_salary_number(text: str) -> Optional[int]:
    patterns = [
        r'₹\s*(\d[\d,]+)',
        r'Rs\.?\s*(\d[\d,]+)',
        r'INR\s*(\d[\d,]+)',
        r'(\d[\d,]+)\s*(?:per month|/month|p\.m\.|pm)',
        r'stipend[^\d]*(\d[\d,]+)',
        r'(\d+)k\s*(?:per month|/month|pm)',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            num_str = m.group(1).replace(',', '')
            try:
                num = int(num_str)
                if 'k' in pat:
                    num *= 1000
                if 1000 <= num <= 1_000_000:
                    return num
            except ValueError:
                pass
    return None


def _extract_jsonld(soup: BeautifulSoup, url: str) -> Optional[Dict]:
    """Extract structured job data from JSON-LD if available."""
    try:
        script_tags = soup.find_all('script', type='application/ld+json')
        for script in script_tags:
            try:
                data = json.loads(script.string)
                # Check if it's a JobPosting
                if isinstance(data, dict) and data.get('@type') == 'JobPosting':
                    result = _empty_job()
                    result['source_url'] = url
                    result['job_title'] = data.get('title', '')
                    result['company'] = data.get('hiringOrganization', {}).get('name', '') if isinstance(data.get('hiringOrganization'), dict) else str(data.get('hiringOrganization', ''))
                    
                    job_location = data.get('jobLocation', {})
                    if isinstance(job_location, dict):
                        loc = job_location.get('address', {})
                        if isinstance(loc, dict):
                            result['location'] = loc.get('addressLocality', '')
                    
                    result['job_description'] = data.get('description', '') or data.get('jobDescription', '')
                    
                    # Extract salary
                    base_salary = data.get('baseSalary', {})
                    if isinstance(base_salary, dict):
                        salary_info = base_salary.get('currency', '') + ' ' + str(base_salary.get('value', {}).get('minValue', '')) if base_salary.get('value') else ''
                        result['salary'] = salary_info.strip()
                    
                    if result.get('job_title') or result.get('job_description'):
                        result['salary_num'] = _extract_salary_number(result.get('salary', '') + ' ' + result.get('job_description', ''))
                        logger.info('[scraper/jsonld] extracted structured job data')
                        return result
            except (json.JSONDecodeError, TypeError, AttributeError):
                continue
    except Exception as e:
        logger.debug('[scraper/jsonld] extraction failed: %s', e)
    return None


def _empty_job() -> Dict:
    return {
        'job_title': '', 'company': '', 'location': '',
        'salary': '', 'salary_num': None, 'job_description': '',
        'skills': [], 'source_url': '', 'experience': None, 'error': None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Platform-specific BS4 extractors
# ─────────────────────────────────────────────────────────────────────────────

def _extract_naukri(soup: BeautifulSoup, url: str) -> Dict:
    d = _empty_job()
    d['source_url'] = url

    title = soup.find('h1', class_=re.compile(r'jd-header|title|heading', re.I))
    if not title:
        title = soup.find('h1')
    d['job_title'] = _clean_text(title.get_text()) if title else ''

    company = soup.find('a', class_=re.compile(r'comp-name|company', re.I)) or \
              soup.find('div', class_=re.compile(r'comp-name|company', re.I))
    d['company'] = _clean_text(company.get_text()) if company else ''

    loc = soup.find('a', class_=re.compile(r'loc\b', re.I)) or \
          soup.find('span', class_=re.compile(r'location', re.I))
    d['location'] = _clean_text(loc.get_text()) if loc else ''

    sal = soup.find('span', class_=re.compile(r'salary', re.I))
    d['salary'] = _clean_text(sal.get_text()) if sal else ''

    desc = soup.find('section', class_=re.compile(r'job-desc|description', re.I)) or \
           soup.find('div', class_=re.compile(r'dang-inner-html|job-desc', re.I))
    if not desc:
        desc = soup.find('div', id=re.compile(r'job-desc', re.I))
    d['job_description'] = desc.get_text(separator='\n', strip=True)[:4000] if desc else ''

    # Skills tags
    skill_tags = soup.find_all('a', class_=re.compile(r'tag|skill', re.I))
    d['skills'] = [s.get_text(strip=True) for s in skill_tags[:15]]

    d['salary_num'] = _extract_salary_number(d['salary'] + ' ' + d['job_description'])
    return d


def _extract_internshala(soup: BeautifulSoup, url: str) -> Dict:
    d = _empty_job()
    d['source_url'] = url

    title = soup.find('h1', class_=re.compile(r'profile|heading|title', re.I)) or soup.find('h1')
    d['job_title'] = _clean_text(title.get_text()) if title else ''

    company = soup.find('a', class_=re.compile(r'company|org', re.I)) or \
              soup.find('div', class_=re.compile(r'company', re.I))
    d['company'] = _clean_text(company.get_text()) if company else ''

    loc = soup.find('p', class_=re.compile(r'location|city', re.I)) or \
          soup.find('span', string=re.compile(r'Remote|Work from home|Delhi|Mumbai|Bangalore', re.I))
    d['location'] = _clean_text(loc.get_text()) if loc else ''

    stipend = soup.find('span', class_=re.compile(r'stipend|salary', re.I))
    d['salary'] = _clean_text(stipend.get_text()) if stipend else ''

    desc = soup.find('div', class_=re.compile(r'internship-details|about|description|detail', re.I))
    d['job_description'] = desc.get_text(separator='\n', strip=True)[:4000] if desc else ''
    d['salary_num'] = _extract_salary_number(d['salary'] + ' ' + d['job_description'])
    return d


def _extract_linkedin(soup: BeautifulSoup, url: str) -> Dict:
    d = _empty_job()
    d['source_url'] = url

    title = soup.find('h1', class_=re.compile(r'top-card|title', re.I)) or soup.find('h1')
    d['job_title'] = _clean_text(title.get_text()) if title else ''

    company = soup.find('a', class_=re.compile(r'topcard__org|company', re.I)) or \
              soup.find('span', class_=re.compile(r'company', re.I))
    d['company'] = _clean_text(company.get_text()) if company else ''

    loc = soup.find('span', class_=re.compile(r'topcard__flavor--bullet|location', re.I))
    d['location'] = _clean_text(loc.get_text()) if loc else ''

    desc = soup.find('div', class_=re.compile(r'description|show-more-less', re.I))
    d['job_description'] = desc.get_text(separator='\n', strip=True)[:4000] if desc else ''
    d['salary_num'] = _extract_salary_number(d['job_description'])
    return d


def _extract_indeed(soup: BeautifulSoup, url: str) -> Dict:
    d = _empty_job()
    d['source_url'] = url

    title = soup.find('h1', class_=re.compile(r'jobsearch|title', re.I)) or soup.find('h1')
    d['job_title'] = _clean_text(title.get_text()) if title else ''

    company = soup.find('div', class_=re.compile(r'company', re.I))
    d['company'] = _clean_text(company.get_text()) if company else ''

    loc = soup.find('div', class_=re.compile(r'location|companyLocation', re.I))
    d['location'] = _clean_text(loc.get_text()) if loc else ''

    sal = soup.find('span', class_=re.compile(r'salary', re.I))
    d['salary'] = _clean_text(sal.get_text()) if sal else ''

    desc = soup.find('div', id=re.compile(r'jobDescriptionText', re.I)) or \
           soup.find('div', class_=re.compile(r'jobsearch-jobDescriptionText', re.I))
    d['job_description'] = desc.get_text(separator='\n', strip=True)[:4000] if desc else ''
    d['salary_num'] = _extract_salary_number(d['salary'] + ' ' + d['job_description'])
    return d


def _extract_adzuna(soup: BeautifulSoup, url: str) -> Dict:
    d = _empty_job()
    d['source_url'] = url

    title = soup.find('h1') or soup.find('h2')
    d['job_title'] = _clean_text(title.get_text()) if title else ''

    company = soup.find(class_=re.compile(r'advertiser|company|employer', re.I))
    d['company'] = _clean_text(company.get_text()) if company else ''

    loc = soup.find(class_=re.compile(r'location|area', re.I))
    d['location'] = _clean_text(loc.get_text()) if loc else ''

    sal = soup.find(class_=re.compile(r'salary|pay', re.I))
    d['salary'] = _clean_text(sal.get_text()) if sal else ''

    desc = soup.find(class_=re.compile(r'adp-body|job-description|description', re.I))
    if not desc:
        desc = soup.find('section')
    d['job_description'] = desc.get_text(separator='\n', strip=True)[:4000] if desc else ''
    d['salary_num'] = _extract_salary_number(d['salary'] + ' ' + d['job_description'])
    return d


def _extract_tcs(soup: BeautifulSoup, url: str) -> Dict:
    """TCS Careers page extractor."""
    d = _empty_job()
    d['source_url'] = url
    d['company'] = 'TCS'
    
    # Title
    title = soup.find('h1', class_=re.compile(r'job-title|title', re.I))
    if not title:
        title = soup.find(re.compile(r'h[1-2]'))
    d['job_title'] = _clean_text(title.get_text()) if title else ''
    
    # Location
    loc = soup.find(class_=re.compile(r'location|city|place', re.I))
    d['location'] = _clean_text(loc.get_text()) if loc else ''
    
    # Description
    desc = soup.find(class_=re.compile(r'job-desc|description|details|content', re.I))
    if not desc:
        desc = soup.find('div', class_=re.compile(r'prose|body|main', re.I))
    d['job_description'] = desc.get_text(separator='\n', strip=True)[:4000] if desc else ''
    
    # Salary
    sal = soup.find(string=re.compile(r'salary|ctc|lpa|per annum', re.I))
    if sal:
        d['salary'] = _clean_text(sal.parent.get_text() if sal.parent else sal)
    
    d['salary_num'] = _extract_salary_number(d['salary'] + ' ' + d['job_description'])
    return d


def _extract_infosys(soup: BeautifulSoup, url: str) -> Dict:
    """Infosys Careers page extractor."""
    d = _empty_job()
    d['source_url'] = url
    d['company'] = 'Infosys'
    
    # Title
    title = soup.find('h1')
    d['job_title'] = _clean_text(title.get_text()) if title else ''
    
    # Location
    loc = soup.find(string=re.compile(r'Location|city|place', re.I))
    if loc and loc.parent:
        d['location'] = _clean_text(loc.parent.get_text())
    
    # Description
    desc = soup.find(class_=re.compile(r'description|details|content|prose', re.I))
    if not desc:
        desc = soup.find('div', id=re.compile(r'desc|content', re.I))
    d['job_description'] = desc.get_text(separator='\n', strip=True)[:4000] if desc else ''
    
    # Salary/CTC
    sal = soup.find(string=re.compile(r'CTC|Salary|ctc', re.I))
    if sal and sal.parent:
        d['salary'] = _clean_text(sal.parent.get_text())
    
    d['salary_num'] = _extract_salary_number(d['salary'] + ' ' + d['job_description'])
    return d


def _extract_deloitte(soup: BeautifulSoup, url: str) -> Dict:
    """Deloitte Careers page extractor."""
    d = _empty_job()
    d['source_url'] = url
    d['company'] = 'Deloitte'
    
    # Title
    title = soup.find('h1')
    d['job_title'] = _clean_text(title.get_text()) if title else ''
    
    # Location/Locations
    loc = soup.find(string=re.compile(r'Location|Job Location|country', re.I))
    if loc and loc.parent:
        d['location'] = _clean_text(loc.parent.get_text())
    
    # Description
    desc = soup.find(class_=re.compile(r'description|overview|details|content', re.I))
    if not desc:
        desc = soup.find('div', class_=re.compile(r'prose|richtext', re.I))
    d['job_description'] = desc.get_text(separator='\n', strip=True)[:4000] if desc else ''
    
    d['salary_num'] = _extract_salary_number(d['job_description'])
    return d


def _extract_hcl(soup: BeautifulSoup, url: str) -> Dict:
    """HCL Careers page extractor."""
    d = _empty_job()
    d['source_url'] = url
    d['company'] = 'HCL'
    
    # Title
    title = soup.find('h1', class_=re.compile(r'job-title|title', re.I))
    if not title:
        title = soup.find('h1')
    d['job_title'] = _clean_text(title.get_text()) if title else ''
    
    # Location
    loc = soup.find(string=re.compile(r'Location|Job Location|city', re.I))
    if loc and loc.parent:
        d['location'] = _clean_text(loc.parent.get_text())
    
    # Description
    desc = soup.find(class_=re.compile(r'description|overview|details|content', re.I))
    if not desc:
        desc = soup.find('div', id=re.compile(r'desc|content|details', re.I))
    d['job_description'] = desc.get_text(separator='\n', strip=True)[:4000] if desc else ''
    
    d['salary_num'] = _extract_salary_number(d['job_description'])
    return d


def _extract_amex(soup: BeautifulSoup, url: str) -> Dict:
    """American Express Careers page extractor."""
    d = _empty_job()
    d['source_url'] = url
    d['company'] = 'American Express'
    
    # Title
    title = soup.find('h1') or soup.find('h2', class_=re.compile(r'title|heading', re.I))
    d['job_title'] = _clean_text(title.get_text()) if title else ''
    
    # Location
    loc = soup.find(string=re.compile(r'Location|Work Location', re.I))
    if loc and loc.parent:
        d['location'] = _clean_text(loc.parent.get_text())
    
    # Description
    desc = soup.find(class_=re.compile(r'description|overview|details|content|prose', re.I))
    if not desc:
        desc = soup.find('div', class_=re.compile(r'body|main', re.I))
    d['job_description'] = desc.get_text(separator='\n', strip=True)[:4000] if desc else ''
    
    d['salary_num'] = _extract_salary_number(d['job_description'])
    return d


def _extract_generic(soup: BeautifulSoup, url: str) -> Dict:
    """Generic fallback extractor for any career page."""
    d = _empty_job()
    d['source_url'] = url
    parsed = urllib.parse.urlparse(url)

    # Title
    og = soup.find('meta', property='og:title')
    if og:
        d['job_title'] = og.get('content', '').strip()
    elif soup.find('h1'):
        d['job_title'] = _clean_text(soup.find('h1').get_text())  # type: ignore
    elif soup.title:
        d['job_title'] = soup.title.get_text(strip=True)

    # Company
    og_site = soup.find('meta', property='og:site_name')
    if og_site:
        d['company'] = og_site.get('content', '').strip()
    else:
        d['company'] = parsed.netloc.replace('www.', '').split('.')[0].title()

    # Location
    for tag in soup.find_all(['span', 'div', 'p'],
                              string=re.compile(r'Remote|Work from home|Delhi|Mumbai|Bangalore|Hyderabad', re.I)):
        d['location'] = _clean_text(tag.get_text())
        break

    # Salary
    for tag in soup.find_all(string=re.compile(r'₹|LPA|lakh|per month|stipend|salary', re.I)):
        parent = tag.parent
        if parent:
            txt = parent.get_text(strip=True)
            if len(txt) < 120:
                d['salary'] = txt
                break

    # Description — try structured first, then body fallback
    og_desc = soup.find('meta', property='og:description')
    best_desc = ''
    for tag_name in ['article', 'main', 'section', 'div']:
        content = soup.find(tag_name, class_=re.compile(r'job|description|content|detail|body', re.I))
        if content:
            t = content.get_text(separator='\n', strip=True)
            if len(t) > len(best_desc):
                best_desc = t[:4000]
    if not best_desc and og_desc:
        best_desc = og_desc.get('content', '').strip()
    if not best_desc:
        body = soup.find('body')
        best_desc = body.get_text(separator='\n', strip=True)[:4000] if body else ''
    d['job_description'] = best_desc
    d['salary_num'] = _extract_salary_number(d['salary'] + ' ' + d['job_description'])
    return d


# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 — requests + BeautifulSoup + JSON-LD extraction
# ─────────────────────────────────────────────────────────────────────────────
def _scrape_bs4(url: str) -> Optional[Dict]:
    """Returns a job dict or None if quality is too low."""
    for attempt in range(2):
        try:
            session = requests.Session()
            session.headers.update(_random_headers())
            if attempt > 0:
                time.sleep(1.5)
            resp = session.get(url, timeout=12, allow_redirects=True)
            resp.raise_for_status()
        except requests.exceptions.Timeout:
            logger.warning('[scraper/bs4] timeout attempt %d', attempt + 1)
            continue
        except requests.exceptions.HTTPError as e:
            logger.warning('[scraper/bs4] HTTP error: %s', e)
            return None
        except requests.exceptions.ConnectionError as e:
            logger.warning('[scraper/bs4] connection error: %s', e)
            return None
        except Exception as e:
            logger.warning('[scraper/bs4] error: %s', e)
            return None

        soup = BeautifulSoup(resp.text, 'html.parser')
        url_lower = url.lower()

        # Try JSON-LD first
        jsonld_data = _extract_jsonld(soup, url)
        if jsonld_data and len(jsonld_data.get('job_description', '')) >= _MIN_DESC_LENGTH:
            logger.info('[scraper/bs4] JSON-LD extraction successful')
            return jsonld_data

        # Platform-specific extractors
        if 'naukri.com' in url_lower:
            data = _extract_naukri(soup, url)
        elif 'tcs.com' in url_lower or 'tcscareer' in url_lower:
            data = _extract_tcs(soup, url)
        elif 'infosys.com' in url_lower or 'infosyscareers' in url_lower:
            data = _extract_infosys(soup, url)
        elif 'deloitte.com' in url_lower or 'delozpita' in url_lower:
            data = _extract_deloitte(soup, url)
        elif 'hcl.com' in url_lower or 'hclcareers' in url_lower:
            data = _extract_hcl(soup, url)
        elif 'americanexpress.com' in url_lower or 'amex' in url_lower:
            data = _extract_amex(soup, url)
        elif 'internshala.com' in url_lower:
            data = _extract_internshala(soup, url)
        elif 'linkedin.com' in url_lower:
            data = _extract_linkedin(soup, url)
        elif 'indeed.com' in url_lower:
            data = _extract_indeed(soup, url)
        elif 'adzuna' in url_lower:
            data = _extract_adzuna(soup, url)
        else:
            # Use JSON-LD data if we got it, else generic
            data = jsonld_data or _extract_generic(soup, url)

        desc_len = len(data.get('job_description', ''))
        logger.info('[scraper/bs4] extracted %d chars of description', desc_len)

        if desc_len >= _MIN_DESC_LENGTH:
            return data
        # Short text — return anyway but caller will try Playwright
        return data if data.get('job_title') or data.get('job_description') else None

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 — Playwright (Chromium headless) with JSON-LD and domain-specific logic
# ─────────────────────────────────────────────────────────────────────────────
def _scrape_playwright(url: str) -> Optional[Dict]:
    """
    Launch a headless Chromium instance, wait for JS rendering,
    scroll the page, then extract visible text and JSON-LD.
    Falls back gracefully if Playwright is not installed.
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        logger.warning('[scraper/playwright] playwright not installed — skipping')
        return None

    data = _empty_job()
    data['source_url'] = url

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(
                viewport={'width': random.randint(1280, 1920), 'height': random.randint(800, 1080)},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0 Safari/537.36',
                locale='en-IN',
                extra_http_headers={
                    'Accept-Language': 'en-IN,en;q=0.9',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                },
            )
            page = ctx.new_page()

            # Block images/fonts to speed things up
            page.route('**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf,eot}',
                       lambda route: route.abort())

            try:
                page.goto(url, wait_until='networkidle', timeout=25000)
            except Exception:
                # Still continue even if networkidle times out
                pass

            # Scroll aggressively to trigger lazy-loading
            page.evaluate("""
                () => new Promise(resolve => {
                    let totalHeight = 0;
                    const dist = 400;
                    const timer = setInterval(() => {
                        window.scrollBy(0, dist);
                        totalHeight += dist;
                        if (totalHeight >= document.body.scrollHeight) {
                            clearInterval(timer);
                            resolve();
                        }
                    }, 100);
                    setTimeout(() => {
                        clearInterval(timer);
                        resolve();
                    }, 5000);
                })
            """)
            page.wait_for_timeout(1000)

            # Extract JSON-LD from rendered DOM
            jsonld_text = page.inner_text('script[type="application/ld+json"]') or ''
            url_lower = url.lower()

            if jsonld_text:
                try:
                    jsonld_data = json.loads(jsonld_text)
                    if isinstance(jsonld_data, dict) and jsonld_data.get('@type') == 'JobPosting':
                        data['job_title'] = jsonld_data.get('title', '')
                        data['company'] = jsonld_data.get('hiringOrganization', {}).get('name', '') if isinstance(jsonld_data.get('hiringOrganization'), dict) else str(jsonld_data.get('hiringOrganization', ''))
                        job_location = jsonld_data.get('jobLocation', {})
                        if isinstance(job_location, dict):
                            loc = job_location.get('address', {})
                            if isinstance(loc, dict):
                                data['location'] = loc.get('addressLocality', '')
                        data['job_description'] = (jsonld_data.get('description', '') or jsonld_data.get('jobDescription', ''))[:5000]
                        base_salary = jsonld_data.get('baseSalary', {})
                        if isinstance(base_salary, dict):
                            if base_salary.get('value'):
                                data['salary'] = f"{base_salary.get('currency', '')} {base_salary.get('value', {}).get('minValue', '')}"
                except (json.JSONDecodeError, TypeError, AttributeError):
                    pass

            # If JSON-LD didn't provide enough, use DOM extraction
            if len(data.get('job_description', '')) < _MIN_DESC_LENGTH:
                if 'naukri.com' in url_lower:
                    data['job_title'] = page.inner_text('h1, [class*="jd-header"]') or data.get('job_title', '')
                    data['job_description'] = page.inner_text('[class*="jobDescriptionSection"], [class*="dang-inner-html"], [class*="job-desc"]') or ''
                    data['company'] = page.inner_text('[class*="comp-name"]') or ''
                    data['location'] = page.inner_text('[class*="loc"]') or ''
                    data['salary'] = page.inner_text('[class*="salary"]') or ''
                elif 'tcs.com' in url_lower or 'tcscareer' in url_lower:
                    data['job_title'] = page.inner_text('h1, [class*="job-title"]') or data.get('job_title', '')
                    data['job_description'] = page.inner_text('[class*="job-desc"], [class*="description"], [class*="details"]') or ''
                    data['company'] = 'TCS'
                    data['location'] = page.inner_text('[class*="location"], [class*="city"]') or ''
                elif 'infosys.com' in url_lower or 'infosyscareers' in url_lower:
                    data['job_title'] = page.inner_text('h1, h2') or data.get('job_title', '')
                    data['job_description'] = page.inner_text('[class*="description"], [class*="details"], [class*="content"]') or ''
                    data['company'] = 'Infosys'
                    data['location'] = page.inner_text('[class*="location"], [class*="city"]') or ''
                elif 'deloitte.com' in url_lower:
                    data['job_title'] = page.inner_text('h1, h2') or data.get('job_title', '')
                    data['job_description'] = page.inner_text('[class*="description"], [class*="prose"], [class*="content"]') or ''
                    data['company'] = 'Deloitte'
                    data['location'] = page.inner_text('[class*="location"], [class*="city"]') or ''
                elif 'hcl.com' in url_lower or 'hclcareers' in url_lower:
                    data['job_title'] = page.inner_text('h1, h2') or data.get('job_title', '')
                    data['job_description'] = page.inner_text('[class*="description"], [class*="details"]') or ''
                    data['company'] = 'HCL'
                    data['location'] = page.inner_text('[class*="location"]') or ''
                elif 'americanexpress.com' in url_lower or 'amex' in url_lower:
                    data['job_title'] = page.inner_text('h1, h2') or data.get('job_title', '')
                    data['job_description'] = page.inner_text('[class*="description"], [class*="prose"], [class*="content"]') or ''
                    data['company'] = 'American Express'
                    data['location'] = page.inner_text('[class*="location"]') or ''
                elif 'internshala.com' in url_lower:
                    data['job_title'] = page.inner_text('h1') or page.title()
                    data['job_description'] = page.inner_text('[class*="internship-details"], [class*="about"]') or ''
                    data['company'] = page.inner_text('[class*="company"]') or ''
                elif 'linkedin.com' in url_lower:
                    data['job_title'] = page.inner_text('.top-card-layout__title, h1') or ''
                    data['company'] = page.inner_text('.topcard__org-name-link, [class*="company"]') or ''
                    data['location'] = page.inner_text('.topcard__flavor--bullet') or ''
                    data['job_description'] = page.inner_text('.show-more-less-html__markup, [class*="description"]') or ''
                elif 'indeed.com' in url_lower:
                    data['job_title'] = page.inner_text('[class*="jobsearch"] h1, h1') or ''
                    data['company'] = page.inner_text('[class*="company"]') or ''
                    data['location'] = page.inner_text('[class*="location"]') or ''
                    data['job_description'] = page.inner_text('#jobDescriptionText, [class*="jobDescriptionText"]') or ''

            # Fallback: grab all visible text from body
            if len(data.get('job_description', '')) < _MIN_DESC_LENGTH:
                full_text = page.inner_text('body') or ''
                data['job_description'] = _clean_text(full_text)[:5000]

            if not data.get('job_title'):
                data['job_title'] = page.title()

            # Clean all fields
            for key in ('job_title', 'company', 'location', 'salary', 'job_description'):
                if key in data:
                    data[key] = _clean_text(str(data.get(key, '')))[:5000 if key == 'job_description' else 200]

            data['salary_num'] = _extract_salary_number(
                data.get('salary', '') + ' ' + data.get('job_description', '')
            )

            browser.close()

        logger.info('[scraper/playwright] extracted %d chars', len(data.get('job_description', '')))
        return data

    except Exception as e:
        logger.warning('[scraper/playwright] failed: %s', e)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────
def scrape_job(url: str) -> ScrapeResult:
    """
    Full multi-stage scraper.
    Returns ScrapeResult.success + data dict.
    """
    if not url or not url.strip():
        return ScrapeResult(success=False, error='URL is required')

    if not url.startswith('http'):
        url = 'https://' + url

    # Cache check
    cache_key = hashlib.md5(url.encode()).hexdigest()
    if cache_key in _url_cache:
        logger.debug('[scraper] cache hit for %s', url)
        return _url_cache[cache_key]

    # ── Stage 1: BS4 ────────────────────────────────────────────────────────
    data = _scrape_bs4(url)

    if data and len(data.get('job_description', '')) >= _MIN_DESC_LENGTH:
        result = ScrapeResult(success=True, data=data, method='bs4')
        _url_cache[cache_key] = result
        return result

    logger.info('[scraper] BS4 quality low — trying Playwright for %s', url)

    # ── Stage 2: Playwright ──────────────────────────────────────────────────
    pw_data = _scrape_playwright(url)

    if pw_data and (len(pw_data.get('job_description', '')) >= _MIN_DESC_LENGTH
                    or pw_data.get('job_title')):
        result = ScrapeResult(success=True, data=pw_data, method='playwright')
        _url_cache[cache_key] = result
        return result

    # ── Stage 3: Use whatever we have ───────────────────────────────────────
    best = pw_data or data
    if best:
        # If we at least got a title or some description, still return partial
        has_content = bool(best.get('job_title') or best.get('job_description'))
        result = ScrapeResult(
            success=has_content,
            data=best,
            method='generic',
            error=None if has_content else 'Could not extract job details from this URL'
        )
    else:
        result = ScrapeResult(
            success=False,
            data=_empty_job(),
            method='failed',
            error='Failed to scrape this URL after multiple attempts. '
                  'The site may block automated requests.'
        )

    _url_cache[cache_key] = result
    return result
