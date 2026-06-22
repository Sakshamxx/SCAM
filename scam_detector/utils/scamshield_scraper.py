"""
scamshield_job_scraper.py
=========================
Ultimate ScamShield Job Parser
Supported platforms: Naukri · Indeed · Foundit (Monster) · LinkedIn · Internshala

Each platform has a dedicated scraper class that returns a unified JobListing dict.
All scrapers feed into ScamShield's analysis pipeline automatically.

Install
-------
    pip install requests beautifulsoup4 selenium playwright \
                httpx[http2] tldextract python-whois \
                fake-useragent curl-cffi undetected-chromedriver \
                lxml cloudscraper brotli \
                pymupdf pytesseract pillow opencv-python numpy \
                rich tenacity

    # Playwright browsers
    playwright install chromium

    # Tesseract binary (Windows)
    # Download from https://github.com/UB-Mannheim/tesseract/wiki

Usage
-----
    python scamshield_job_scraper.py --platform naukri   --query "python developer" --location "bangalore" --pages 3
    python scamshield_job_scraper.py --platform indeed   --query "data analyst"      --location "mumbai"
    python scamshield_job_scraper.py --platform foundit  --query "java developer"    --location "delhi"
    python scamshield_job_scraper.py --platform linkedin --query "ml engineer"       --location "hyderabad"
    python scamshield_job_scraper.py --platform internshala --query "web development" --pages 2
    python scamshield_job_scraper.py --platform all      --query "software engineer" --location "pune"
    python scamshield_job_scraper.py --url "https://www.naukri.com/job-listings-..."   # single job URL
"""

from __future__ import annotations

# ── stdlib ──────────────────────────────────────────────────────────────────
import argparse
import datetime
import json
import logging
import random
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode, urljoin, urlparse, quote_plus

# ── HTTP / HTML ──────────────────────────────────────────────────────────────
import requests
from bs4 import BeautifulSoup, Tag
import httpx                 # HTTP/2 support
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

try:
    import cloudscraper          # Cloudflare bypass
    CLOUDSCRAPER_AVAILABLE = True
except ImportError:
    CLOUDSCRAPER_AVAILABLE = False
    logging.warning("cloudscraper not installed — falling back to standard requests.")

try:
    from fake_useragent import UserAgent  # Rotating user-agents
    FAKE_USERAGENT_AVAILABLE = True
except ImportError:
    FAKE_USERAGENT_AVAILABLE = False
    logging.warning("fake-useragent not installed — falling back to static User-Agent list.")

# ── Selenium / Playwright (JS-heavy pages) ───────────────────────────────────
try:
    import undetected_chromedriver as uc
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException, NoSuchElementException
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False
    logging.warning("undetected-chromedriver not installed — Selenium scrapers disabled.")

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logging.warning("playwright not installed — Playwright scrapers disabled.")

# ── Misc ─────────────────────────────────────────────────────────────────────
try:
    from rich.console import Console
    from rich.table import Table
    from rich import print as rprint
    console = Console()
except ImportError:
    class MockConsole:
        def print(self, *args, **kwargs):
            print(*args)
        def rule(self, *args, **kwargs):
            print("=" * 55)
    console = MockConsole()
    class Table:
        def __init__(self, *args, **kwargs): pass
        def add_column(self, *args, **kwargs): pass
        def add_row(self, *args, **kwargs): pass
    rprint = print

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("ScamShield.Scraper")

# ──────────────────────────────────────────────────────────────────────────────
# SHARED CONFIG
# ──────────────────────────────────────────────────────────────────────────────

REQUEST_TIMEOUT   = 15
MAX_RETRIES       = 3
DELAY_MIN         = 2.0    # seconds between requests (be polite)
DELAY_MAX         = 5.0

if FAKE_USERAGENT_AVAILABLE:
    try:
        ua = UserAgent()
    except Exception:
        FAKE_USERAGENT_AVAILABLE = False

if not FAKE_USERAGENT_AVAILABLE:
    class MockUserAgent:
        def __init__(self):
            self.user_agents = [
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edge/119.0.0.0"
            ]
        @property
        def random(self) -> str:
            return random.choice(self.user_agents)
    ua = MockUserAgent()

def random_headers() -> dict:
    return {
        "User-Agent"      : ua.random,
        "Accept"          : "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language" : "en-IN,en;q=0.9,hi;q=0.8",
        "Accept-Encoding" : "gzip, deflate, br",
        "Referer"         : "https://www.google.com/",
        "Connection"      : "keep-alive",
        "DNT"             : "1",
    }

def polite_delay():
    time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))


# ──────────────────────────────────────────────────────────────────────────────
# UNIFIED JOB LISTING SCHEMA
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class JobListing:
    platform        : str  = ""
    job_id          : str  = ""
    title           : str  = ""
    company         : str  = ""
    location        : str  = ""
    salary          : str  = ""
    experience      : str  = ""
    job_type        : str  = ""          # Full-time / Internship / Part-time
    posted_date     : str  = ""
    description     : str  = ""
    skills          : list = field(default_factory=list)
    apply_url       : str  = ""
    company_url     : str  = ""
    emails          : list = field(default_factory=list)
    phone_numbers   : list = field(default_factory=list)
    remote          : bool = False
    openings        : str  = ""
    scrape_success  : bool = False
    scrape_error    : str  = ""
    # ScamShield fields (populated by analyze pipeline)
    risk_score      : float = 0.0
    risk_level      : str  = ""
    trust_score     : float = 0.0
    trust_level     : str  = ""
    fraud_reasons   : list = field(default_factory=list)
    recommendation  : str  = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["page_title"] = self.title or ""
        d["raw_text"] = self.description or ""
        d["body_text"] = self.description or ""
        return d



# ──────────────────────────────────────────────────────────────────────────────
# BASE SCRAPER
# ──────────────────────────────────────────────────────────────────────────────

class BaseScraper:
    PLATFORM = "base"

    def __init__(self):
        if CLOUDSCRAPER_AVAILABLE:
            try:
                self.session = cloudscraper.create_scraper(
                    browser={"browser": "chrome", "platform": "windows", "mobile": False}
                )
            except Exception as e:
                log.warning(f"Failed to create cloudscraper session: {e}. Falling back to requests.Session().")
                self.session = requests.Session()
        else:
            self.session = requests.Session()
        self.session.headers.update(random_headers())

    def get(self, url: str, **kwargs) -> Optional[requests.Response]:
        try:
            polite_delay()
            resp = self.session.get(url, timeout=REQUEST_TIMEOUT, **kwargs)
            resp.raise_for_status()
            return resp
        except Exception as e:
            log.warning(f"GET failed for {url}: {e}")
            return None

    def soup(self, url: str, **kwargs) -> Optional[BeautifulSoup]:
        resp = self.get(url, **kwargs)
        if resp:
            return BeautifulSoup(resp.text, "lxml")
        return None

    def search(self, query: str, location: str = "", pages: int = 1) -> list[JobListing]:
        raise NotImplementedError

    def parse_job_page(self, url: str) -> JobListing:
        raise NotImplementedError

    @staticmethod
    def _clean(text: str) -> str:
        if not text:
            return ""
        return re.sub(r"\s+", " ", text.strip())

    @staticmethod
    def _extract_emails(text: str) -> list:
        return list(set(re.findall(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", text)))

    @staticmethod
    def _extract_phones(text: str) -> list:
        return list(set(re.findall(r"(?:\+91[\-\s]?)?[6-9]\d{9}|\b\d{7,12}\b", text)))


# ──────────────────────────────────────────────────────────────────────────────
# 1. NAUKRI SCRAPER
# ──────────────────────────────────────────────────────────────────────────────

class NaukriScraper(BaseScraper):
    """
    Scrapes Naukri.com job listings.
    Strategy: REST API endpoint that Naukri's own frontend calls.
    Falls back to HTML parsing if API changes.
    """
    PLATFORM   = "naukri"
    SEARCH_API = "https://www.naukri.com/jobapi/v3/search"
    BASE_URL   = "https://www.naukri.com"

    def __init__(self):
        super().__init__()
        self.session.headers.update({
            "appid"       : "109",
            "systemid"    : "109",
            "Referer"     : "https://www.naukri.com/",
            "Content-Type": "application/json",
        })

    def search(self, query: str, location: str = "", pages: int = 1) -> list[JobListing]:
        results = []
        for page in range(1, pages + 1):
            params = {
                "noOfResults" : 20,
                "urlType"     : "search_by_keyword",
                "searchType"  : "adv",
                "keyword"     : query,
                "location"    : location,
                "pageNo"      : page,
                "sort"        : "r",          # relevance
                "wfhType"     : "",
                "jobAge"      : 30,
            }
            url  = f"{self.SEARCH_API}?{urlencode(params)}"
            resp = self.get(url)
            if not resp:
                continue
            try:
                data = resp.json()
                jobs = data.get("jobDetails", [])
                for job in jobs:
                    listing = self._parse_api_result(job)
                    results.append(listing)
            except Exception as e:
                log.warning(f"Naukri API parse error page {page}: {e}")
                # Fallback: HTML scrape
                html_url = f"{self.BASE_URL}/{query.replace(' ', '-')}-jobs-in-{location.replace(' ', '-')}"
                results.extend(self._html_search(html_url))
            log.info(f"Naukri page {page}: {len(results)} total listings so far")
        return results

    def _parse_api_result(self, job: dict) -> JobListing:
        listing            = JobListing(platform=self.PLATFORM)
        listing.job_id     = str(job.get("jobId", ""))
        listing.title      = self._clean(job.get("title", ""))
        listing.company    = self._clean(job.get("companyName", ""))
        listing.location   = ", ".join(job.get("placeholders", [{}])[0].get("label", "").split(",")[:2]) \
                             if job.get("placeholders") else ""
        listing.experience = job.get("experienceText", "")
        listing.salary     = job.get("salaryDetail", "")
        listing.posted_date= job.get("footerPlaceholderLabel", "")
        listing.apply_url  = f"https://www.naukri.com{job.get('jdURL', '')}"
        listing.skills     = job.get("tagsAndSkills", "").split(",") if job.get("tagsAndSkills") else []
        listing.skills     = [s.strip() for s in listing.skills if s.strip()]
        listing.description= self._clean(job.get("jobDescription", ""))
        listing.remote     = "work from home" in listing.title.lower() or \
                             "remote" in listing.title.lower()
        listing.scrape_success = True
        return listing

    def _html_search(self, url: str) -> list[JobListing]:
        """Fallback HTML parser for Naukri search pages."""
        results = []
        page    = self.soup(url)
        if not page:
            return results
        cards = page.select("article.jobTuple, div.jobTupleHeader")
        for card in cards:
            listing         = JobListing(platform=self.PLATFORM, scrape_success=True)
            title_tag       = card.select_one("a.title")
            company_tag     = card.select_one("a.subTitle")
            location_tag    = card.select_one("li.location span")
            exp_tag         = card.select_one("li.experience span")
            salary_tag      = card.select_one("li.salary span")
            listing.title   = self._clean(title_tag.text if title_tag else "")
            listing.company = self._clean(company_tag.text if company_tag else "")
            listing.location= self._clean(location_tag.text if location_tag else "")
            listing.experience = self._clean(exp_tag.text if exp_tag else "")
            listing.salary  = self._clean(salary_tag.text if salary_tag else "")
            listing.apply_url = title_tag["href"] if title_tag and title_tag.get("href") else ""
            results.append(listing)
        return results

    def parse_job_page(self, url: str) -> JobListing:
        """Parse a single Naukri job detail page."""
        listing          = JobListing(platform=self.PLATFORM, apply_url=url)
        page             = self.soup(url)
        if not page:
            listing.scrape_error = "Failed to fetch page"
            return listing
        try:
            listing.title      = self._clean(page.select_one("h1.jd-header-title, .job-tittle h1")
                                             .get_text() if page.select_one("h1.jd-header-title, .job-tittle h1") else "")
            listing.company    = self._clean(page.select_one("a.jd-header-comp-name, .comp-name")
                                             .get_text() if page.select_one("a.jd-header-comp-name, .comp-name") else "")
            exp_tag            = page.select_one("div.exp-wrap span.exp, .exp")
            listing.experience = self._clean(exp_tag.get_text() if exp_tag else "")
            sal_tag            = page.select_one("div.sal-wrap span.ni-job-tuple-icon, .salary")
            listing.salary     = self._clean(sal_tag.get_text() if sal_tag else "")
            loc_tag            = page.select_one("div.loc-wrap a, .location")
            listing.location   = self._clean(loc_tag.get_text() if loc_tag else "")
            desc_tag           = page.select_one("section.job-desc, div.job-description")
            listing.description= self._clean(desc_tag.get_text(separator=" ") if desc_tag else "")
            skills_tags        = page.select("a.chip-list__chip, li.tag-li")
            listing.skills     = [self._clean(s.get_text()) for s in skills_tags]
            listing.emails     = self._extract_emails(page.get_text())
            listing.phone_numbers = self._extract_phones(listing.description)
            listing.scrape_success = True
        except Exception as e:
            listing.scrape_error = str(e)
        return listing


# ──────────────────────────────────────────────────────────────────────────────
# 2. INDEED SCRAPER
# ──────────────────────────────────────────────────────────────────────────────

class IndeedScraper(BaseScraper):
    """
    Scrapes Indeed India (in.indeed.com).
    Strategy: HTML scraping with cloudscraper (handles JS challenge).
    Playwright fallback for heavy bot-detection pages.
    """
    PLATFORM = "indeed"
    BASE_URL = "https://in.indeed.com"

    def search(self, query: str, location: str = "", pages: int = 1) -> list[JobListing]:
        results = []
        for page in range(pages):
            params  = {"q": query, "l": location, "start": page * 10, "fromage": 30}
            url     = f"{self.BASE_URL}/jobs?{urlencode(params)}"
            bs      = self.soup(url)
            if not bs:
                log.warning(f"Indeed: page {page+1} blocked — trying Playwright")
                bs = self._playwright_fetch(url)
            if not bs:
                continue
            cards = bs.select("div.job_seen_beacon, div.resultContent, li.css-5lfssm")
            for card in cards:
                listing = self._parse_card(card)
                results.append(listing)
            log.info(f"Indeed page {page+1}: {len(results)} total")
        return results

    def _parse_card(self, card: Tag) -> JobListing:
        listing          = JobListing(platform=self.PLATFORM)
        try:
            title_tag        = card.select_one("h2.jobTitle a, a.jcs-JobTitle")
            company_tag      = card.select_one("span.companyName, [data-testid='company-name']")
            location_tag     = card.select_one("div.companyLocation, [data-testid='text-location']")
            salary_tag       = card.select_one("div.salary-snippet-container, div.metadata.salary-snippet-container")
            date_tag         = card.select_one("span.date, [data-testid='myJobsStateDate']")
            snippet_tag      = card.select_one("div.job-snippet, div.summary")

            listing.title    = self._clean(title_tag.get_text() if title_tag else "")
            listing.company  = self._clean(company_tag.get_text() if company_tag else "")
            listing.location = self._clean(location_tag.get_text() if location_tag else "")
            listing.salary   = self._clean(salary_tag.get_text() if salary_tag else "Not disclosed")
            listing.posted_date = self._clean(date_tag.get_text() if date_tag else "")
            listing.description = self._clean(snippet_tag.get_text() if snippet_tag else "")

            href = title_tag["href"] if title_tag and title_tag.get("href") else ""
            listing.apply_url = urljoin(self.BASE_URL, href)

            jk = re.search(r"jk=([a-f0-9]+)", listing.apply_url)
            listing.job_id = jk.group(1) if jk else ""
            listing.scrape_success = True
        except Exception as e:
            listing.scrape_error = str(e)
        return listing

    def parse_job_page(self, url: str) -> JobListing:
        listing = JobListing(platform=self.PLATFORM, apply_url=url)
        bs = self.soup(url) or self._playwright_fetch(url)
        if not bs:
            listing.scrape_error = "Failed to fetch page"
            return listing
        try:
            listing.title   = self._clean(bs.select_one("h1.jobsearch-JobInfoHeader-title, h1[data-testid]")
                                          .get_text() if bs.select_one("h1.jobsearch-JobInfoHeader-title, h1[data-testid]") else "")
            listing.company = self._clean(bs.select_one("div[data-company-name], [data-testid='inlineHeader-companyName']")
                                          .get_text() if bs.select_one("div[data-company-name], [data-testid='inlineHeader-companyName']") else "")
            listing.location= self._clean(bs.select_one("div[data-testid='job-location'], div.jobsearch-JobInfoHeader-subtitle")
                                          .get_text() if bs.select_one("div[data-testid='job-location'], div.jobsearch-JobInfoHeader-subtitle") else "")
            desc_tag        = bs.select_one("div#jobDescriptionText, div.jobsearch-jobDescriptionText")
            listing.description = self._clean(desc_tag.get_text(separator=" ") if desc_tag else "")
            listing.emails  = self._extract_emails(bs.get_text())
            listing.phone_numbers = self._extract_phones(listing.description)
            listing.scrape_success = True
        except Exception as e:
            listing.scrape_error = str(e)
        return listing

    def _playwright_fetch(self, url: str) -> Optional[BeautifulSoup]:
        if not PLAYWRIGHT_AVAILABLE:
            return None
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                ctx     = browser.new_context(user_agent=ua.random)
                page    = ctx.new_page()
                page.goto(url, timeout=30000, wait_until="domcontentloaded")
                page.wait_for_timeout(3000)
                html    = page.content()
                browser.close()
            return BeautifulSoup(html, "lxml")
        except Exception as e:
            log.warning(f"Playwright fetch failed: {e}")
            return None


# ──────────────────────────────────────────────────────────────────────────────
# 3. FOUNDIT (Monster India) SCRAPER
# ──────────────────────────────────────────────────────────────────────────────

class FounditScraper(BaseScraper):
    """
    Scrapes Foundit.in (formerly Monster India).
    Strategy: JSON API + HTML fallback.
    """
    PLATFORM   = "foundit"
    SEARCH_API = "https://www.foundit.in/middleware/jobsearch/v2/search"
    BASE_URL   = "https://www.foundit.in"

    def search(self, query: str, location: str = "", pages: int = 1) -> list[JobListing]:
        results = []
        for page in range(1, pages + 1):
            params = {
                "query"       : query,
                "locations"   : location,
                "start"       : (page - 1) * 15,
                "limit"       : 15,
                "sort"        : 1,
                "isMobile"    : False,
            }
            resp = self.get(self.SEARCH_API, params=params)
            if not resp:
                continue
            try:
                data = resp.json()
                for job in data.get("jobSearchResponse", {}).get("data", {}).get("jobs", []):
                    results.append(self._parse_api_result(job))
            except Exception as e:
                log.warning(f"Foundit API parse error: {e}")
                # HTML fallback
                slug = quote_plus(query)
                loc  = quote_plus(location) if location else "india"
                html_url = f"{self.BASE_URL}/in/search/jobs?query={slug}&locations={loc}&start={(page-1)*15}"
                results.extend(self._html_search(html_url))
            log.info(f"Foundit page {page}: {len(results)} total")
        return results

    def _parse_api_result(self, job: dict) -> JobListing:
        listing              = JobListing(platform=self.PLATFORM)
        listing.job_id       = str(job.get("jobId", ""))
        listing.title        = self._clean(job.get("title", ""))
        listing.company      = self._clean(job.get("company", {}).get("name", "") if isinstance(job.get("company"), dict) else str(job.get("company", "")))
        listing.location     = ", ".join(job.get("locations", []))
        listing.experience   = job.get("experience", {}).get("label", "") if isinstance(job.get("experience"), dict) else ""
        listing.salary       = job.get("salary", {}).get("label", "Not disclosed") if isinstance(job.get("salary"), dict) else "Not disclosed"
        listing.posted_date  = job.get("freshness", "")
        listing.description  = self._clean(job.get("jobDescription", ""))
        listing.skills       = job.get("keySkills", []) if isinstance(job.get("keySkills"), list) else []
        listing.apply_url    = f"{self.BASE_URL}/in/job/{listing.job_id}"
        listing.remote       = job.get("workFromHome", False)
        listing.scrape_success = True
        return listing

    def _html_search(self, url: str) -> list[JobListing]:
        results = []
        bs = self.soup(url)
        if not bs:
            return results
        for card in bs.select("div.card-panel, div.jobTupleHeader, article.srpResultCardContainer"):
            listing = JobListing(platform=self.PLATFORM, scrape_success=True)
            t       = card.select_one("h3.jobTitle a, a.job-tittle")
            c       = card.select_one("span.companyDesig a, a.company-name")
            l       = card.select_one("li.location span, span.location")
            listing.title   = self._clean(t.get_text() if t else "")
            listing.company = self._clean(c.get_text() if c else "")
            listing.location= self._clean(l.get_text() if l else "")
            listing.apply_url = urljoin(self.BASE_URL, t["href"]) if t and t.get("href") else ""
            results.append(listing)
        return results

    def parse_job_page(self, url: str) -> JobListing:
        listing = JobListing(platform=self.PLATFORM, apply_url=url)
        bs = self.soup(url)
        if not bs:
            listing.scrape_error = "Failed to fetch page"
            return listing
        try:
            listing.title   = self._clean(bs.select_one("h1.jd-header-title, h1.jobTitle").get_text()
                                          if bs.select_one("h1.jd-header-title, h1.jobTitle") else "")
            listing.company = self._clean(bs.select_one("a.company-name, span.companyDesig a").get_text()
                                          if bs.select_one("a.company-name, span.companyDesig a") else "")
            desc            = bs.select_one("div.jdesc, div.job-description, section.job-description")
            listing.description = self._clean(desc.get_text(separator=" ") if desc else "")
            listing.emails  = self._extract_emails(bs.get_text())
            listing.phone_numbers = self._extract_phones(listing.description)
            listing.scrape_success = True
        except Exception as e:
            listing.scrape_error = str(e)
        return listing


# ──────────────────────────────────────────────────────────────────────────────
# 4. LINKEDIN SCRAPER
# ──────────────────────────────────────────────────────────────────────────────

class LinkedInScraper(BaseScraper):
    """
    Scrapes LinkedIn public job listings (no login required for search).
    Strategy: Public job search endpoint + Playwright for JS-rendered detail pages.
    NOTE: LinkedIn aggressively blocks bots. Playwright with stealth is the
          most reliable approach. Respect robots.txt in production.
    """
    PLATFORM   = "linkedin"
    SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    JOB_URL    = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"

    def search(self, query: str, location: str = "", pages: int = 1) -> list[JobListing]:
        results = []
        for page in range(pages):
            params = {
                "keywords"   : query,
                "location"   : location or "India",
                "f_TPR"      : "r2592000",   # last 30 days
                "start"      : page * 25,
            }
            url  = f"{self.SEARCH_URL}?{urlencode(params)}"
            resp = self.get(url)
            if not resp:
                log.warning(f"LinkedIn page {page+1} blocked — trying Playwright")
                bs   = self._playwright_job_search(query, location, page)
            else:
                bs   = BeautifulSoup(resp.text, "lxml")

            if not bs:
                continue

            cards = bs.select("li div.base-card, li.jobs-search__results-list")
            for card in cards:
                listing = self._parse_card(card)
                if listing.scrape_success:
                    results.append(listing)
            log.info(f"LinkedIn page {page+1}: {len(results)} total")
        return results

    def _parse_card(self, card: Tag) -> JobListing:
        listing = JobListing(platform=self.PLATFORM)
        try:
            title_tag   = card.select_one("h3.base-search-card__title, h3.base-card__full-link")
            company_tag = card.select_one("h4.base-search-card__subtitle a, a.hidden-nested-link")
            location_tag= card.select_one("span.job-search-card__location")
            date_tag    = card.select_one("time")
            link_tag    = card.select_one("a.base-card__full-link")

            listing.title   = self._clean(title_tag.get_text() if title_tag else "")
            listing.company = self._clean(company_tag.get_text() if company_tag else "")
            listing.location= self._clean(location_tag.get_text() if location_tag else "")
            listing.posted_date = date_tag.get("datetime", "") if date_tag else ""
            listing.apply_url = link_tag["href"].split("?")[0] if link_tag else ""

            jid = re.search(r"-(\d+)$", listing.apply_url.rstrip("/"))
            listing.job_id = jid.group(1) if jid else ""
            listing.scrape_success = True
        except Exception as e:
            listing.scrape_error = str(e)
        return listing

    def parse_job_page(self, url: str) -> JobListing:
        listing = JobListing(platform=self.PLATFORM, apply_url=url)
        jid     = re.search(r"-(\d+)/?$", url.rstrip("/"))
        if jid:
            api_url = self.JOB_URL.format(job_id=jid.group(1))
            bs = self.soup(api_url)
        else:
            bs = None

        if not bs:
            bs = self._playwright_fetch(url)
        if not bs:
            listing.scrape_error = "Failed to fetch page"
            return listing

        try:
            listing.title   = self._clean(bs.select_one("h2.top-card-layout__title, h1.job-details-jobs-unified-top-card__job-title")
                                          .get_text() if bs.select_one("h2.top-card-layout__title, h1.job-details-jobs-unified-top-card__job-title") else "")
            listing.company = self._clean(bs.select_one("a.topcard__org-name-link, a[data-tracking-control-name='public_jobs_topcard-org-name']")
                                          .get_text() if bs.select_one("a.topcard__org-name-link") else "")
            listing.location= self._clean(bs.select_one("span.topcard__flavor--bullet, span.job-details-jobs-unified-top-card__bullet")
                                          .get_text() if bs.select_one("span.topcard__flavor--bullet") else "")
            desc            = bs.select_one("div.show-more-less-html__markup, section.description__text")
            listing.description = self._clean(desc.get_text(separator=" ") if desc else "")

            meta_spans = bs.select("span.job-criteria__text")
            for i, span in enumerate(meta_spans):
                text = self._clean(span.get_text())
                header = bs.select("h3.job-criteria__subheader")
                if i < len(header):
                    h = self._clean(header[i].get_text()).lower()
                    if "seniority" in h:
                        listing.experience = text
                    elif "employment" in h:
                        listing.job_type   = text

            listing.emails  = self._extract_emails(bs.get_text())
            listing.phone_numbers = self._extract_phones(listing.description)
            listing.scrape_success = True
        except Exception as e:
            listing.scrape_error = str(e)
        return listing

    def _playwright_job_search(self, query: str, location: str, page: int) -> Optional[BeautifulSoup]:
        if not PLAYWRIGHT_AVAILABLE:
            return None
        try:
            url = f"https://www.linkedin.com/jobs/search/?keywords={quote_plus(query)}&location={quote_plus(location or 'India')}&start={page*25}"
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                ctx     = browser.new_context(user_agent=ua.random)
                pg      = ctx.new_page()
                pg.goto(url, timeout=30000, wait_until="networkidle")
                pg.wait_for_timeout(3000)
                html    = pg.content()
                browser.close()
            return BeautifulSoup(html, "lxml")
        except Exception as e:
            log.warning(f"LinkedIn Playwright search failed: {e}")
            return None

    def _playwright_fetch(self, url: str) -> Optional[BeautifulSoup]:
        if not PLAYWRIGHT_AVAILABLE:
            return None
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                ctx     = browser.new_context(user_agent=ua.random)
                pg      = ctx.new_page()
                pg.goto(url, timeout=30000, wait_until="networkidle")
                pg.wait_for_timeout(4000)
                html    = pg.content()
                browser.close()
            return BeautifulSoup(html, "lxml")
        except Exception as e:
            log.warning(f"LinkedIn Playwright detail fetch failed: {e}")
            return None


# ──────────────────────────────────────────────────────────────────────────────
# 5. INTERNSHALA SCRAPER
# ──────────────────────────────────────────────────────────────────────────────

class IntershalaScraper(BaseScraper):
    """
    Scrapes Internshala.com — internships and fresher jobs.
    Strategy: HTML scraping (site is server-rendered, very scrapable).
    """
    PLATFORM = "internshala"
    BASE_URL = "https://internshala.com"

    def search(self, query: str, location: str = "", pages: int = 1) -> list[JobListing]:
        results = []
        # Internshala uses slug-based URLs
        slug_q  = query.lower().replace(" ", "-")
        slug_l  = location.lower().replace(" ", "-") if location else ""

        for page in range(1, pages + 1):
            if slug_l:
                url = f"{self.BASE_URL}/internships/{slug_q}-internship-in-{slug_l}/page-{page}"
            else:
                url = f"{self.BASE_URL}/internships/{slug_q}-internship/page-{page}"

            bs = self.soup(url)
            if not bs:
                # Try jobs endpoint
                url = f"{self.BASE_URL}/jobs/{slug_q}-jobs-in-{slug_l or 'india'}/page-{page}"
                bs  = self.soup(url)
            if not bs:
                continue

            cards = bs.select("div.individual_internship, div.internship-listing-card, .internship_meta")
            for card in cards:
                listing = self._parse_card(card)
                results.append(listing)
            log.info(f"Internshala page {page}: {len(results)} total")
        return results

    def _parse_card(self, card: Tag) -> JobListing:
        listing = JobListing(platform=self.PLATFORM, job_type="Internship")
        try:
            title_tag    = card.select_one("h3.job-internship-name a, .profile a, h3 a")
            company_tag  = card.select_one("p.company-name a, .company-name")
            location_tag = card.select_one("p.location-name span, .location_link, a.location_link")
            stipend_tag  = card.select_one("span.stipend, .stipend")
            duration_tag = card.select_one("div.internship-other-details span.item_body, .other-detail span")
            date_tag     = card.select_one("div.posted-on span")

            listing.title   = self._clean(title_tag.get_text() if title_tag else "")
            listing.company = self._clean(company_tag.get_text() if company_tag else "")
            listing.location= self._clean(location_tag.get_text() if location_tag else "Work from Home")
            listing.salary  = self._clean(stipend_tag.get_text() if stipend_tag else "Unpaid")
            listing.experience = self._clean(duration_tag.get_text() if duration_tag else "")
            listing.posted_date = self._clean(date_tag.get_text() if date_tag else "")
            listing.remote  = "work from home" in listing.location.lower()

            href = title_tag["href"] if title_tag and title_tag.get("href") else ""
            listing.apply_url = urljoin(self.BASE_URL, href)
            jid = re.search(r"/(\d+)", href)
            listing.job_id = jid.group(1) if jid else ""
            listing.scrape_success = True
        except Exception as e:
            listing.scrape_error = str(e)
        return listing

    def parse_job_page(self, url: str) -> JobListing:
        listing = JobListing(platform=self.PLATFORM, apply_url=url)
        bs = self.soup(url)
        if not bs:
            listing.scrape_error = "Failed to fetch page"
            return listing
        try:
            listing.title   = self._clean(bs.select_one("h1.profile, h1.heading_4_5").get_text()
                                          if bs.select_one("h1.profile, h1.heading_4_5") else "")
            listing.company = self._clean(bs.select_one("div.company_name a, h2.company-name").get_text()
                                          if bs.select_one("div.company_name a, h2.company-name") else "")
            listing.location= self._clean(bs.select_one("a.location_link").get_text()
                                          if bs.select_one("a.location_link") else "Work from Home")
            listing.salary  = self._clean(bs.select_one("span.stipend, .salary-insight").get_text()
                                          if bs.select_one("span.stipend, .salary-insight") else "")
            desc            = bs.select_one("div.internship-details-container, div#about_company, div.section-container")
            listing.description = self._clean(desc.get_text(separator=" ") if desc else "")
            skills_tags     = bs.select("div.skills_section .round_tabs_container a, span.individual_skill")
            listing.skills  = [self._clean(s.get_text()) for s in skills_tags]
            openings_tag    = bs.select_one(".number_of_openings strong, .detail-row .ic-16-people + div span")
            listing.openings = self._clean(openings_tag.get_text() if openings_tag else "")
            listing.emails  = self._extract_emails(bs.get_text())
            listing.phone_numbers = self._extract_phones(listing.description)
            listing.scrape_success = True
        except Exception as e:
            listing.scrape_error = str(e)
        return listing


# ──────────────────────────────────────────────────────────────────────────────
# SCAMSHIELD ANALYSIS ENGINE (inline, no external ML needed)
# ──────────────────────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────────────────────
# PLATFORM ROUTER
# ──────────────────────────────────────────────────────────────────────────────

class WellfoundScraper(BaseScraper):
    PLATFORM = "wellfound"

    def search(self, query: str, location: str = "", pages: int = 1) -> list[JobListing]:
        return []

    def parse_job_page(self, url: str) -> JobListing:
        listing = JobListing(platform=self.PLATFORM, apply_url=url)
        html = ""
        try:
            resp = self.get(url)
            if resp:
                html = resp.text
        except Exception as e:
            log.warning(f"[WellfoundScraper] requests fetch failed: {e}")

        if (not html or len(html) < 500) and PLAYWRIGHT_AVAILABLE:
            try:
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(headless=True)
                    ctx     = browser.new_context(user_agent=ua.random)
                    page    = ctx.new_page()
                    page.goto(url, timeout=30000, wait_until="domcontentloaded")
                    page.wait_for_timeout(3000)
                    html    = page.content()
                    browser.close()
            except Exception as e:
                log.warning(f"[WellfoundScraper] Playwright fetch failed: {e}")

        if not html:
            listing.scrape_error = "Failed to fetch Wellfound page"
            return listing

        try:
            soup = BeautifulSoup(html, "lxml")
            title_tag = soup.select_one("h1[class*='title'], h1")
            company_tag = soup.select_one("a[class*='companyLink'], div[class*='company'] a, h2[class*='companyName']")
            location_tag = soup.select_one("span[class*='location']")
            desc_tag = soup.select_one("div[class*='jobDescription'], div[class*='description']")

            listing.title = self._clean(title_tag.get_text() if title_tag else "")
            listing.company = self._clean(company_tag.get_text() if company_tag else "")
            listing.location = self._clean(location_tag.get_text() if location_tag else "")
            
            if desc_tag:
                listing.description = self._clean(desc_tag.get_text(separator=" "))
            else:
                body = soup.find("body")
                listing.description = self._clean(body.get_text(separator=" ") if body else soup.get_text(separator=" "))[:6000]

            listing.emails = self._extract_emails(soup.get_text())
            listing.phone_numbers = self._extract_phones(listing.description)
            listing.scrape_success = True
        except Exception as e:
            listing.scrape_error = str(e)
        return listing


class GenericScraper(BaseScraper):
    PLATFORM = "generic"

    def search(self, query: str, location: str = "", pages: int = 1) -> list[JobListing]:
        return []

    def parse_job_page(self, url: str) -> JobListing:
        listing = JobListing(platform=self.PLATFORM, apply_url=url)
        html = ""
        try:
            resp = self.get(url)
            if resp:
                html = resp.text
        except Exception as e:
            log.warning(f"[GenericScraper] requests fetch failed: {e}")

        if (not html or len(html) < 500) and PLAYWRIGHT_AVAILABLE:
            try:
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(headless=True)
                    ctx     = browser.new_context(user_agent=ua.random)
                    page    = ctx.new_page()
                    page.goto(url, timeout=30000, wait_until="domcontentloaded")
                    page.wait_for_timeout(3000)
                    html    = page.content()
                    browser.close()
            except Exception as e:
                log.warning(f"[GenericScraper] Playwright fetch failed: {e}")

        if not html:
            listing.scrape_error = "Could not fetch career page content"
            return listing

        try:
            soup = BeautifulSoup(html, "lxml")
            for script in soup(["script", "style"]):
                script.decompose()
            body_text = soup.get_text(separator=" ", strip=True)
            title_tag = soup.find("title")
            page_title = title_tag.get_text(strip=True) if title_tag else ""
            
            company_guess = ""
            try:
                domain = urlparse(url).netloc.lower().replace("www.", "")
                parts = domain.split(".")
                if len(parts) >= 2:
                    company_guess = parts[0].capitalize()
            except Exception:
                pass

            listing.title = page_title or "Job Opportunity"
            listing.company = company_guess
            listing.description = body_text[:6000]
            listing.emails = self._extract_emails(body_text)
            listing.phone_numbers = self._extract_phones(body_text)
            listing.remote = "remote" in body_text.lower()
            listing.scrape_success = True
        except Exception as e:
            listing.scrape_error = str(e)
        return listing


SCRAPERS: dict[str, type[BaseScraper]] = {
    "naukri"     : NaukriScraper,
    "indeed"     : IndeedScraper,
    "foundit"    : FounditScraper,
    "linkedin"   : LinkedInScraper,
    "internshala": IntershalaScraper,
    "wellfound"  : WellfoundScraper,
    "generic"    : GenericScraper,
}

def detect_platform(url: str) -> Optional[str]:
    domain = urlparse(url).netloc.lower()
    if "naukri"      in domain: return "naukri"
    if "indeed"      in domain: return "indeed"
    if "foundit"     in domain: return "foundit"
    if "monster"     in domain: return "foundit"
    if "linkedin"    in domain: return "linkedin"
    if "internshala" in domain: return "internshala"
    if "wellfound"   in domain: return "wellfound"
    if "angel.co"    in domain: return "wellfound"
    return "generic"

_FRAUD_PHRASES  = ["registration fee","security deposit","processing fee","training fee",
                   "joining fee","investment required","earn money fast","guaranteed income",
                   "pay upfront","advance payment","pay to work","get rich","100% profit",
                   "wire transfer","data entry work","typing work from home"]
_URGENCY_PHRASES= ["apply now","urgent hiring","limited seats","immediate joining",
                   "instant selection","deadline today"]
_CONTACT_TERMS  = ["telegram","whatsapp","gmail.com","yahoo.com","hotmail.com","call now","wechat"]
_FREE_EMAILS    = ["gmail.com","yahoo.com","hotmail.com","rediffmail.com","outlook.com"]

def analyze_listing(listing: JobListing) -> JobListing:
    """Run ScamShield rule-based analysis on a JobListing and populate risk fields."""
    text    = f"{listing.title} {listing.company} {listing.description} {' '.join(listing.skills)}".lower()
    reasons = []
    score   = 0

    for p in _FRAUD_PHRASES:
        if p in text:
            reasons.append(f"Fraud phrase: '{p}'")
            score += 10

    for u in _URGENCY_PHRASES:
        if u in text:
            reasons.append(f"Urgency tactic: '{u}'")
            score += 5

    for c in _CONTACT_TERMS:
        if c in text:
            reasons.append(f"Risky contact channel: '{c}'")
            score += 5

    sus_emails = [e for e in listing.emails if any(d in e for d in _FREE_EMAILS)]
    if sus_emails:
        reasons.append(f"Personal email used: {sus_emails[:2]}")
        score += 8

    if len(listing.phone_numbers) > 2:
        reasons.append(f"Multiple phone numbers: {len(listing.phone_numbers)}")
        score += 5

    if listing.salary and re.search(r"\d{5,}", listing.salary.replace(",", "")):
        if any(w in listing.salary.lower() for w in ["lakh", "lac"]):
            pass   # normal
        else:
            reasons.append("Unusually high salary figure — verify authenticity")
            score += 5

    anon = ["company name not disclosed","undisclosed company","anonymous client","our client"]
    if any(a in text for a in anon):
        reasons.append("Anonymous/undisclosed company")
        score += 8

    if listing.description and len(listing.description.split()) < 30:
        reasons.append("Very short job description")
        score += 7

    score = min(score, 100)
    level = "HIGH" if score >= 70 else ("MEDIUM" if score >= 40 else "LOW")

    trust_score = round(100 - score, 2)
    trust_level = ("High Trust" if trust_score > 60 else ("Moderate Trust" if trust_score > 30 else "Low Trust"))

    rec = ("Safe to Proceed" if level == "LOW" else
           ("Review Before Applying" if level == "MEDIUM" and score < 55 else
            ("Manual Verification Required" if level == "MEDIUM" else
             "Potential Scam Detected — Do Not Apply")))

    if not reasons:
        reasons.append("No significant fraud indicators detected")

    listing.risk_score    = float(score)
    listing.risk_level    = level
    listing.trust_score   = trust_score
    listing.trust_level   = trust_level
    listing.fraud_reasons = reasons
    listing.recommendation= rec
    return listing


# ──────────────────────────────────────────────────────────────────────────────
# PLATFORM ROUTER
# ──────────────────────────────────────────────────────────────────────────────

SCRAPERS: dict[str, type[BaseScraper]] = {
    "naukri"     : NaukriScraper,
    "indeed"     : IndeedScraper,
    "foundit"    : FounditScraper,
    "linkedin"   : LinkedInScraper,
    "internshala": IntershalaScraper,
}

def detect_platform(url: str) -> Optional[str]:
    domain = urlparse(url).netloc.lower()
    if "naukri"      in domain: return "naukri"
    if "indeed"      in domain: return "indeed"
    if "foundit"     in domain: return "foundit"
    if "monster"     in domain: return "foundit"
    if "linkedin"    in domain: return "linkedin"
    if "internshala" in domain: return "internshala"
    if "wellfound"   in domain: return "linkedin"   # Wellfound uses LinkedIn-style structure
    if "angel.co"    in domain: return "linkedin"
    return None


# ──────────────────────────────────────────────────────────────────────────────
# FLASK APP ADAPTER LAYER
# Functions expected by app.py — thin wrappers over existing scraper logic.
# ──────────────────────────────────────────────────────────────────────────────

def validate_url(url: str) -> bool:
    """Return True if url is a valid http/https URL with a host."""
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def scrape_url(url: str) -> dict:
    """
    Scrape a single job URL using the appropriate platform scraper.
    Returns a dict with JobListing fields + scrape_success / error.
    Falls back to generic requests fetch if platform unknown.
    """
    platform = detect_platform(url)
    if platform and platform in SCRAPERS:
        try:
            scraper  = SCRAPERS[platform]()
            listing  = scraper.parse_job_page(url)
            return listing.to_dict()
        except Exception as e:
            log.warning(f"[scrape_url] platform scraper failed: {e}")

    # Generic fallback — basic requests + BeautifulSoup
    try:
        import requests as _req
        from bs4 import BeautifulSoup as _BS
        resp = _req.get(url, headers=random_headers(), timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = _BS(resp.text, "lxml")
        body_text = soup.get_text(separator=" ", strip=True)[:5000]
        title_tag = soup.find("title")
        page_title = title_tag.get_text(strip=True) if title_tag else ""
        return {
            "platform": "generic",
            "job_id": "",
            "title": page_title,
            "company": "",
            "location": "",
            "salary": "",
            "experience": "",
            "job_type": "",
            "posted_date": "",
            "description": body_text,
            "skills": [],
            "apply_url": url,
            "company_url": "",
            "emails": BaseScraper._extract_emails(body_text),
            "phone_numbers": BaseScraper._extract_phones(body_text),
            "remote": False,
            "openings": "",
            "scrape_success": True,
            "scrape_error": "",
            "risk_score": 0.0,
            "risk_level": "",
            "trust_score": 0.0,
            "trust_level": "",
            "fraud_reasons": [],
            "recommendation": "",
            # Extra keys expected by app.py fallback handler
            "page_title": page_title,
            "raw_text": body_text,
            "body_text": body_text,
        }
    except Exception as e:
        return {
            "scrape_success": False,
            "scrape_error": str(e),
            "error": str(e),
            "page_title": "",
            "raw_text": "",
            "body_text": "",
        }


def analyze_url(url: str) -> dict:
    """
    Full URL risk analysis: scrape the page, run rule-based scam analysis,
    add domain-level signals (HTTPS, domain patterns, RDAP age lookup).

    Returns a dict compatible with what app.py's /scraper/analyze-url expects.
    """
    result: dict = {
        "url": url,
        "final_risk_score": 50,
        "final_risk_level": "MEDIUM",
        "risk_score": 50,
        "risk_level": "MEDIUM",
        "domain_age_days": None,
        "domain_age_risk": 50,
        "https_enabled": url.startswith("https://"),
        "suspicious_tld": False,
        "risk_reasons": [],
        "fraud_reasons": [],
        "page_title": "",
    }

    try:
        scraped = scrape_url(url)
        listing = JobListing(
            platform  = scraped.get("platform", "generic"),
            title     = scraped.get("title", scraped.get("page_title", "")),
            company   = scraped.get("company", ""),
            location  = scraped.get("location", ""),
            salary    = scraped.get("salary", ""),
            description = scraped.get("description", scraped.get("raw_text", "")),
            skills    = scraped.get("skills", []),
            emails    = scraped.get("emails", []),
            phone_numbers = scraped.get("phone_numbers", []),
            scrape_success = scraped.get("scrape_success", False),
        )
        listing = analyze_listing(listing)

        # Domain-level signals
        parsed  = urlparse(url)
        domain  = parsed.netloc.lower()
        reasons = list(listing.fraud_reasons)
        risk_score = listing.risk_score

        if not url.startswith("https://"):
            reasons.append("No HTTPS — site lacks SSL encryption")
            risk_score = min(100, risk_score + 15)

        suspicious_tlds = [".xyz", ".tk", ".ml", ".ga", ".cf", ".click", ".loan", ".work"]
        if any(domain.endswith(t) for t in suspicious_tlds):
            reasons.append(f"Suspicious top-level domain ({domain.split('.')[-1]})")
            result["suspicious_tld"] = True
            risk_score = min(100, risk_score + 20)

        shorteners = ["bit.ly", "tinyurl", "goo.gl", "t.co", "ow.ly", "is.gd", "rb.gy"]
        if any(s in domain for s in shorteners):
            reasons.append("URL shortener — hides real destination")
            risk_score = min(100, risk_score + 30)

        # RDAP domain age
        domain_age_days = None
        try:
            import requests as _req
            rdap_resp = _req.get(
                f"https://rdap.org/domain/{domain.replace('www.', '')}",
                timeout=5, allow_redirects=True
            )
            if rdap_resp.status_code == 200:
                events = rdap_resp.json().get("events", [])
                for ev in events:
                    if ev.get("eventAction") in ("registration", "creation"):
                        from datetime import datetime, timezone
                        reg_date = ev.get("eventDate", "")
                        if reg_date:
                            reg_dt = datetime.fromisoformat(reg_date.replace("Z", "+00:00"))
                            age_days = (datetime.now(timezone.utc) - reg_dt).days
                            domain_age_days = age_days
                            if age_days < 90:
                                reasons.append(f"Very new domain ({age_days} days old)")
                                risk_score = min(100, risk_score + 20)
                            elif age_days < 365:
                                reasons.append(f"Relatively new domain ({age_days} days old)")
                                risk_score = min(100, risk_score + 10)
                        break
        except Exception:
            pass

        risk_score = round(float(risk_score), 1)
        risk_level = "HIGH" if risk_score >= 70 else ("MEDIUM" if risk_score >= 40 else "LOW")

        result.update({
            "final_risk_score": risk_score,
            "final_risk_level": risk_level,
            "risk_score": risk_score,
            "risk_level": risk_level,
            "domain_age_days": domain_age_days,
            "domain_age_risk": min(100, max(0, 100 - (domain_age_days or 0) // 10)) if domain_age_days else 50,
            "https_enabled": url.startswith("https://"),
            "risk_reasons": reasons,
            "fraud_reasons": reasons,
            "page_title": listing.title or "",
        })

    except Exception as e:
        log.warning(f"[analyze_url] error: {e}")
        result["error"] = str(e)

    return result


def analyze_text(text: str) -> dict:
    """
    Run rule-based scam analysis on raw text (no URL needed).
    Returns dict: risk_score (0-100), risk_level, fraud_phrases, urgency_phrases, score.
    """
    text_lower = str(text).lower()
    found_fraud   = [p for p in _FRAUD_PHRASES   if p in text_lower]
    found_urgency = [p for p in _URGENCY_PHRASES if p in text_lower]
    found_contact = [c for c in _CONTACT_TERMS   if c in text_lower]
    found_emails  = re.findall(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", text)
    sus_emails    = [e for e in found_emails if any(d in e for d in _FREE_EMAILS)]

    score = 0
    score += len(found_fraud)   * 10
    score += len(found_urgency) * 5
    score += len(found_contact) * 5
    score += len(sus_emails)    * 8
    score = min(100, score)

    risk_level = "HIGH" if score >= 70 else ("MEDIUM" if score >= 40 else "LOW")
    return {
        "risk_score":     round(float(score), 1),
        "risk_level":     risk_level,
        "fraud_phrases":  found_fraud,
        "urgency_phrases": found_urgency,
        "contact_signals": found_contact,
        "suspicious_emails": sus_emails,
        "recommendation": (
            "Potential Scam Detected — Do Not Apply" if score >= 70 else
            ("Manual Verification Required" if score >= 55 else
             ("Review Before Applying" if score >= 40 else "Safe to Proceed"))
        ),
    }


def compute_trust(risk_score: float) -> dict:
    """
    Convert a 0–100 risk score into a trust metadata dict.
    Mirrors the structure app.py uses from scraper_analyze_url.
    """
    risk_score = float(risk_score)
    trust_score = round(100 - risk_score, 1)
    if trust_score >= 75:
        trust_level, trust_label = "HIGH", "High Trust"
    elif trust_score >= 50:
        trust_level, trust_label = "MEDIUM", "Moderate Trust"
    elif trust_score >= 25:
        trust_level, trust_label = "LOW", "Low Trust"
    else:
        trust_level, trust_label = "CRITICAL", "Very Low Trust"

    return {
        "trust_score": trust_score,
        "trust_level": trust_level,
        "trust_label": trust_label,
        "risk_score":  risk_score,
    }


def get_recommendation(risk_level: str, risk_score: float = 50) -> str:
    """Return human-readable recommendation string based on risk level and score."""
    risk_level = str(risk_level).upper()
    score = float(risk_score)
    if risk_level in ("CRITICAL", "HIGH") or score >= 70:
        return "Potential Scam Detected — Do Not Apply"
    if risk_level == "MEDIUM" or score >= 55:
        return "Manual Verification Required"
    if score >= 40:
        return "Review Before Applying"
    return "Safe to Proceed"


def extract_text_from_pdf(pdf_input) -> dict:
    """
    Extract text from a PDF file.
    Accepts: bytes (file content) or str/Path (file path).
    Returns dict: success, text, method, pages, error.
    """
    try:
        # Resolve input to bytes
        if isinstance(pdf_input, (str, Path)):
            with open(pdf_input, "rb") as f:
                pdf_bytes = f.read()
        elif hasattr(pdf_input, "read"):
            pdf_bytes = pdf_input.read()
        else:
            pdf_bytes = bytes(pdf_input)
    except Exception as e:
        return {"success": False, "text": "", "method": "failed", "pages": 0, "error": str(e)}

    # Try pdfplumber → PyMuPDF → OCR in order
    # Layer 1: pdfplumber
    try:
        import pdfplumber
        import io as _io
        with pdfplumber.open(_io.BytesIO(pdf_bytes)) as pdf:
            pages_text = []
            for page in pdf.pages:
                try:
                    t = page.extract_text() or ""
                    pages_text.append(t)
                except Exception:
                    continue
        text = "\n\n".join(pages_text).strip()
        if len(text) >= 100:
            return {"success": True, "text": text, "method": "pdfplumber", "pages": len(pages_text), "error": None}
    except Exception:
        pass

    # Layer 2: PyMuPDF
    try:
        import fitz
        import io as _io
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        pages_text = [page.get_text("text") for page in doc]
        doc.close()
        text = "\n\n".join(pages_text).strip()
        if len(text) >= 100:
            return {"success": True, "text": text, "method": "pymupdf", "pages": len(pages_text), "error": None}
    except Exception:
        pass

    # Layer 3: OCR
    try:
        import io as _io
        from pdf2image import convert_from_bytes
        import pytesseract
        images = convert_from_bytes(pdf_bytes, dpi=200, fmt="PNG")
        pages_text = []
        for img in images:
            try:
                t = pytesseract.image_to_string(img, lang="eng", config="--psm 6")
                pages_text.append(t)
            except Exception:
                continue
        text = "\n\n".join(pages_text).strip()
        if len(text) >= 50:
            return {"success": True, "text": text, "method": "ocr_tesseract", "pages": len(pages_text), "error": None}
    except Exception:
        pass

    return {
        "success": False, "text": "", "method": "failed", "pages": 0,
        "error": "Could not extract text from PDF (tried pdfplumber, PyMuPDF, OCR)."
    }


def extract_text_from_image(image_input) -> dict:
    """
    Extract text from an image (JPEG, PNG, WebP, TIFF, BMP) using Tesseract OCR.
    Accepts: bytes, file-like object, or str/Path to file.
    Returns dict: success, text, method, error.
    """
    try:
        import io as _io
        from PIL import Image as _PilImage
        import pytesseract

        # Resolve input to PIL Image
        if isinstance(image_input, (str, Path)):
            img = _PilImage.open(image_input)
        elif hasattr(image_input, "read"):
            img = _PilImage.open(image_input)
        elif isinstance(image_input, (bytes, bytearray)):
            img = _PilImage.open(_io.BytesIO(image_input))
        else:
            img = _PilImage.fromarray(image_input)

        # Convert to RGB if needed (handles RGBA / palette)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        text = pytesseract.image_to_string(img, lang="eng+hin", config="--psm 6")
        text = text.strip()

        if text:
            return {"success": True, "text": text, "method": "ocr_tesseract", "error": None}
        return {"success": False, "text": "", "method": "ocr_tesseract", "error": "OCR returned no text from image"}

    except ImportError as e:
        return {"success": False, "text": "", "method": "failed", "error": f"OCR dependencies missing: {e}"}
    except Exception as e:
        return {"success": False, "text": "", "method": "failed", "error": str(e)}

def scrape_and_analyze(platform: str, query: str = "", location: str = "",
                        pages: int = 1, url: str = "") -> list[JobListing]:
    results = []

    if url:
        plat = detect_platform(url)
        if not plat:
            log.error(f"Cannot detect platform for URL: {url}")
            return []
        scraper = SCRAPERS[plat]()
        listing = scraper.parse_job_page(url)
        listing = analyze_listing(listing)
        results.append(listing)

    elif platform == "all":
        for name, cls in SCRAPERS.items():
            log.info(f"Scraping {name}...")
            try:
                scraper  = cls()
                listings = scraper.search(query, location, pages)
                for l in listings:
                    results.append(analyze_listing(l))
            except Exception as e:
                log.error(f"{name} scraper failed: {e}")
    else:
        cls     = SCRAPERS.get(platform)
        if not cls:
            log.error(f"Unknown platform: {platform}. Choose: {list(SCRAPERS.keys())}")
            return []
        scraper  = cls()
        listings = scraper.search(query, location, pages)
        for l in listings:
            results.append(analyze_listing(l))

    return results


# ──────────────────────────────────────────────────────────────────────────────
# OUTPUT HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def print_table(listings: list[JobListing]) -> None:
    table = Table(title="ScamShield Job Analysis", show_lines=True)
    table.add_column("#",          style="dim",    width=3)
    table.add_column("Platform",   style="cyan",   width=10)
    table.add_column("Title",      style="bold",   width=28)
    table.add_column("Company",    width=22)
    table.add_column("Location",   width=16)
    table.add_column("Salary",     width=16)
    table.add_column("Risk",       width=8)
    table.add_column("Score",      width=6)
    table.add_column("Recommend",  width=30)

    risk_colors = {"LOW": "green", "MEDIUM": "yellow", "HIGH": "red", "CRITICAL": "bright_red"}

    for i, l in enumerate(listings, 1):
        col = risk_colors.get(l.risk_level, "white")
        table.add_row(
            str(i),
            l.platform,
            l.title[:27],
            l.company[:21],
            l.location[:15],
            l.salary[:15] if l.salary else "N/A",
            f"[{col}]{l.risk_level}[/{col}]",
            str(int(l.risk_score)),
            l.recommendation[:29],
        )
    console.print(table)


def save_json(listings: list[JobListing], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump([l.to_dict() for l in listings], f, indent=2, ensure_ascii=False, default=str)
    log.info(f"Saved {len(listings)} listings → {path}")


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="ScamShield Ultimate Job Parser",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scamshield_job_scraper.py --platform naukri    --query "python developer" --location "bangalore" --pages 3
  python scamshield_job_scraper.py --platform indeed    --query "data analyst"     --location "mumbai"
  python scamshield_job_scraper.py --platform foundit   --query "java developer"   --location "delhi"
  python scamshield_job_scraper.py --platform linkedin  --query "ml engineer"      --location "hyderabad"
  python scamshield_job_scraper.py --platform internshala --query "web development" --pages 2
  python scamshield_job_scraper.py --platform all       --query "software engineer" --location "pune"
  python scamshield_job_scraper.py --url "https://www.naukri.com/job-listings-..."
        """
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--platform", choices=[*SCRAPERS.keys(), "all"],
                       help="Target platform to scrape")
    group.add_argument("--url",      help="Single job URL to analyse")

    parser.add_argument("--query",    default="software developer", help="Job search query")
    parser.add_argument("--location", default="",                   help="City / location filter")
    parser.add_argument("--pages",    type=int, default=1,          help="Number of result pages")
    parser.add_argument("--out",      default="",                   help="Save results to JSON file")
    parser.add_argument("--no-table", action="store_true",          help="Skip rich table output")

    args = parser.parse_args()

    console.rule("[bold cyan]ScamShield Job Scraper[/bold cyan]")

    listings = scrape_and_analyze(
        platform = args.platform if hasattr(args, "platform") and args.platform else "",
        query    = args.query,
        location = args.location,
        pages    = args.pages,
        url      = args.url if args.url else "",
    )

    if not listings:
        console.print("[red]No listings found.[/red]")
        sys.exit(1)

    console.print(f"\n[green]✓ Scraped {len(listings)} listings[/green]")

    if not args.no_table:
        print_table(listings)

    # Always print high-risk findings
    high_risk = [l for l in listings if l.risk_level in ("HIGH", "CRITICAL")]
    if high_risk:
        console.rule("[red]⚠ HIGH RISK LISTINGS[/red]")
        for l in high_risk:
            console.print(f"\n[bold red]{l.title}[/bold red] @ {l.company} ({l.platform})")
            console.print(f"  URL    : {l.apply_url}")
            console.print(f"  Score  : {l.risk_score} | {l.risk_level}")
            for r in l.fraud_reasons:
                console.print(f"  • {r}")

    if args.out:
        save_json(listings, args.out)
    else:
        # Auto-save
        ts   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        name = f"scamshield_{args.platform if hasattr(args,'platform') and args.platform else 'url'}_{ts}.json"
        save_json(listings, name)


if __name__ == "__main__":
    main()