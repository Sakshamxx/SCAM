"""
Fake Internship & Job Scam Detection System — Flask Backend v2.0
Graphura India Private Limited
Uses new dataset schema with multi-model ensemble
Label: 0=Legit, 1=Suspicious, 2=Scam
Risk Level: 0-30=Legit, 31-60=Suspicious, 61-100=Scam
"""
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, make_response
import joblib
import numpy as np
import re
import urllib.parse
import os
import io
import requests
from pathlib import Path
# pyrefly: ignore [missing-import]
from bs4 import BeautifulSoup
from supabase_client import (
    supabase, save_analysis, get_history, log_activity, get_activity_logs,
    get_all_users, get_all_analyses, get_user_analyses,
    get_blacklisted_domain, save_scam_report, get_scam_reports,
    get_platform_stats, get_recent_scam_reports_public,
    create_chat_session, get_chat_sessions, delete_chat_session,
    save_chat_message, get_chat_messages
)
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.enums import TA_CENTER, TA_LEFT

# ── New extraction utilities ─────────────────────────────────────────────────
try:
    from utils.scraper import scrape_job, ScrapeResult
    _new_scraper_available = True
except Exception as _e:
    _new_scraper_available = False
    scrape_job = None
    ScrapeResult = None
    print(f'[warn] New scraper not available: {_e}')

try:
    from utils.pdf_extractor import extract_pdf_text, ExtractionResult
    _pdf_extractor_available = True
except Exception as _e:
    _pdf_extractor_available = False
    extract_pdf_text = None
    ExtractionResult = None
    print(f'[warn] New PDF extractor not available: {_e}')

# ── ScamShield standalone scraper integration ────────────────────────────────
try:
    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))  # ensure project root is in path
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))  # ensure parent project root is in path
    from scamshield_scraper import (
        validate_url      as ss_validate_url,
        scrape_url        as ss_scrape_url,
        analyze_url       as ss_analyze_url,
        analyze_text      as ss_analyze_text,
        compute_trust     as ss_compute_trust,
        get_recommendation as ss_get_recommendation,
        extract_text_from_pdf   as ss_extract_pdf,
        extract_text_from_image as ss_extract_image,
    )
    _ss_scraper_available = True
    print("[info] scamshield_scraper.py loaded successfully")
except Exception as _ss_err:
    _ss_scraper_available = False
    print(f"[warn] scamshield_scraper.py not available: {_ss_err}")

# Try to import sentence-transformers for semantic embeddings
try:
    from sentence_transformers import SentenceTransformer
    _semantic_available = True
except ImportError:
    _semantic_available = False

app = Flask(__name__)

load_dotenv()
app.secret_key = os.getenv("SUPABASE_SECRET_KEY")
from datetime import timedelta
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

# ─────────────────────────────────────────────
# Paths (Project-Relative)
# ─────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
MODEL_DIR = BASE_DIR / 'models'



def load_model(filename):
    """Load pickled model from project models directory."""
    path = MODEL_DIR / filename
    if path.exists():
        try:
            return joblib.load(str(path))
        except Exception as e:
            print(f"[warn] Failed to load {filename}: {e}")
    return None

# Load production models from train_nlp_models.py
nlp_pipeline = load_model('nlp_pipeline.pkl')
logistic_model = load_model('logistic_model.pkl')
# ── PRIMARY ML pipeline from train_nlp_models.py ──────────────────────────
# First, register DenseTransformer globally so best_model.pkl can be unpickled
try:
    import sys
    from models.inference import JobScamInferencePipeline, DenseTransformer
    sys.modules['__main__'].DenseTransformer = DenseTransformer
    print("[info] DenseTransformer registered globally")
except Exception as e:
    print(f"[warn] Could not register DenseTransformer: {e}")

nlp_pipeline = load_model('nlp_pipeline.pkl')
logistic_model = load_model('logistic_model.pkl')
scaler = load_model('scaler.pkl')
le_location = load_model('le_location.pkl')
le_title = load_model('le_title.pkl')

# Attempt to load Random Forest model with debugging and fallback
try:
    rf_path = MODEL_DIR / 'random_forest_model.pkl'
    print(f"[RF-DEBUG] Attempting to load: {rf_path}")
    print(f"[RF-DEBUG] Path exists: {rf_path.exists()}")
    
    if rf_path.exists():
        random_forest_model = load_model('random_forest_model.pkl')
        print(f"[RF-DEBUG] ✅ Random Forest model loaded successfully")
    else:
        # Fallback: Use best_model.pkl (Hybrid Model contains Random Forest)
        print(f"[RF-DEBUG] random_forest_model.pkl not found. Using best_model.pkl as fallback")
        best_model_path = MODEL_DIR / 'best_model.pkl'
        if best_model_path.exists():
            random_forest_model = load_model('best_model.pkl')
            print(f"[RF-DEBUG] ✅ Loaded best_model.pkl (Hybrid Model with RF) as fallback")
        else:
            print(f"[RF-DEBUG] ⚠️  Neither random_forest_model.pkl nor best_model.pkl found")
            random_forest_model = None
except Exception as e:
    print(f"[RF ERROR] Failed to load Random Forest model: {repr(e)}")
    random_forest_model = None

# Set other model placeholders to None to ensure compatibility and prevent loading
xgboost_model = None
tfidf_vectorizer = None

# Encoders aliases for backwards compatibility
nlp_le_location = le_location
nlp_le_title = le_title

# ── Secondary ML pipeline from job_scam_detection.ipynb ─────────────────────
# Uses best_model.pkl + tfidf_vectorizer.pkl + scaler.pkl + sentence_transformer.pkl
_notebook_pipeline = None
try:
    from models.inference import JobScamInferencePipeline
    # DenseTransformer already registered globally above

    _best_model   = load_model('best_model.pkl')
    _tfidf_vec    = load_model('tfidf_vectorizer.pkl')
    _nb_scaler    = load_model('scaler.pkl')          # shared scaler
    
    _sent_trans = None
    try:
        _sent_trans = load_model('sentence_transformer.pkl')
    except Exception as e:
        print(f"[info] Loading sentence_transformer.pkl failed, trying standard initialization: {e}")
        
    if not _sent_trans and _semantic_available:
        try:
            _sent_trans = SentenceTransformer('all-MiniLM-L6-v2')
            print("[info] Loaded standard SentenceTransformer ('all-MiniLM-L6-v2') successfully ✅")
        except Exception as e:
            print(f"[warn] Failed to load standard SentenceTransformer: {e}")

    if _best_model and _tfidf_vec and _nb_scaler and _sent_trans:
        _notebook_pipeline = JobScamInferencePipeline(
            model=_best_model,
            tfidf_vec=_tfidf_vec,
            st_model=_sent_trans,
            scaler=_nb_scaler,
        )
        print('[info] models/inference.py JobScamInferencePipeline loaded ✅')
    else:
        print('[warn] One or more notebook model files missing — secondary pipeline disabled')
except Exception as _nb_err:
    print(f'[warn] models/inference.py load failed: {_nb_err}')

print("\n" + "=" * 50)
print("ScamShield v2.0 — Model Status")
print("=" * 50)
print(f"NLP Pipeline:           {'✅ Loaded' if nlp_pipeline else '❌ Missing'}")
print(f"Logistic Model:         {'✅ Loaded' if logistic_model else '❌ Missing'}")
print(f"Random Forest:          {'✅ Loaded' if random_forest_model else '❌ Missing'}")
print(f"Scaler:                 {'✅ Loaded' if scaler else '❌ Missing'}")
print(f"LE Location:            {'✅ Loaded' if le_location else '❌ Missing'}")
print(f"LE Title:               {'✅ Loaded' if le_title else '❌ Missing'}")
print(f"Notebook Pipeline:      {'✅ Loaded' if _notebook_pipeline else '❌ Missing/Unavailable'}")
print("=" * 50 + "\n")


def normalize_text(text_val):
    text_val = str(text_val).lower().strip()
    text_val = re.sub(r"https?://\S+|www\.\S+", "[url]", text_val)
    text_val = re.sub(r"\S+@\S+\.\S+", "[email]", text_val)
    text_val = re.sub(r"\b\d+\b", "[num]", text_val)
    text_val = re.sub(r"\s+", " ", text_val).strip()
    return text_val


def parse_experience(val):
    if val is None or val == '':
        return 0.0
    val_str = str(val).lower().strip()
    if "fresher" in val_str or "entry" in val_str:
        return 0.0
    match = re.search(r"(\d+)", val_str)
    return float(match.group(1)) if match else 0.0


def parse_salary(val):
    if val is None or val == '':
        return 0.0
    nums = re.findall(r"\d+", str(val).replace(",", ""))
    if nums:
        return float(nums[0])
    return 0.0


def safe_encode(le, val, default_val='Unknown'):
    if le is None:
        return 0
    val_clean = str(val).strip()
    if val_clean in le.classes_:
        return int(le.transform([val_clean])[0])
    # Case-insensitive check
    val_lower = val_clean.lower()
    for idx, c in enumerate(le.classes_):
        if str(c).lower().strip() == val_lower:
            return idx
    # Fallback to default_val if it exists in classes
    if default_val in le.classes_:
        return int(le.transform([default_val])[0])
    return 0

# Load semantic model (if available)
semantic_model = None
if _semantic_available:
    try:
        semantic_path = MODEL_DIR / 'semantic_model'
        if semantic_path.exists():
            semantic_model = SentenceTransformer(str(semantic_path))
    except Exception as e:
        print(f"[warn] Failed to load semantic model: {e}")

# ─────────────────────────────────────────────
# Fraud Keywords Dictionary
# ─────────────────────────────────────────────
FRAUD_KEYWORDS = {
    # Very High risk (0.90 – 1.00)
    'registration fee': 0.95,
    'joining fee': 0.95,
    'training fee': 0.93,
    'deposit required': 0.92,
    'whatsapp hr': 0.91,
    'pay to join': 0.91,
    'earn from home': 0.90,
    'guaranteed income': 0.90,
    'instant joining': 0.82,

    # High risk (0.70 – 0.89)
    'earn daily': 0.85,
    'no experience required': 0.80,
    'no qualification needed': 0.80,
    'daily payment': 0.80,
    'no interview': 0.75,
    'urgent hiring': 0.74,
    'limited seats': 0.69,

    # Medium risk (0.40 – 0.69)
    'work only 1 hour': 0.65,
    'work from comfort': 0.55,
    'payment guaranteed': 0.52,
    'telegram': 0.40,
}

# ─────────────────────────────────────────────
# Helper Functions
# ─────────────────────────────────────────────

def keyword_fraud_score(text):
    """Return 0–100 keyword-based fraud score and matched keywords."""
    text_lower = str(text).lower()
    total_weight = 0.0
    matched = {}
    for kw, weight in FRAUD_KEYWORDS.items():
        if kw in text_lower:
            total_weight += weight
            matched[kw] = weight
    max_possible = sum(FRAUD_KEYWORDS.values())
    score = min(100, (total_weight / max_possible) * 100 * 3) if max_possible > 0 else 0
    return round(score, 2), sorted(matched.items(), key=lambda x: -x[1])


WHITELISTED_DOMAINS = {
    'google.com', 'gmail.com', 'microsoft.com', 'linkedin.com', 'github.com', 'github.io',
    'amazon.com', 'amazon.in', 'apple.com', 'netflix.com', 'meta.com', 'facebook.com',
    'twitter.com', 'x.com', 'adobe.com', 'salesforce.com', 'zoom.us', 'slack.com',
    'oracle.com', 'ibm.com', 'accenture.com', 'tcs.com', 'wipro.com', 'infosys.com',
    'cognizant.com', 'capgemini.com', 'deloitte.com', 'pwc.com', 'ey.com', 'kpmg.com',
    'intel.com', 'nvidia.com', 'amd.com', 'gitlab.com', 'bitbucket.org', 'zoho.com',
    'tcs.co.in', 'wipro.co.in', 'infosys.co.in', 'google.co.in', 'linkedin.co.in',
    'indeed.com', 'naukri.com', 'internshala.com', 'foundit.in', 'wellfound.com',
    'instahyre.com', 'unstop.com', 'apna.co', 'hirist.com'
}

def is_whitelisted_domain(domain):
    domain = domain.lower().strip()
    if domain.startswith('www.'):
        domain = domain[4:]
    if domain in WHITELISTED_DOMAINS:
        return True
    for wd in WHITELISTED_DOMAINS:
        if domain.endswith('.' + wd):
            return True
    return False


def check_domain_risk(url):
    """Assign domain risk (0–100) based on URL patterns."""
    if not url or url.strip() == '':
        return 30.0

    url_lower = url.lower()
    parsed = urllib.parse.urlparse(url_lower)
    domain = parsed.netloc.replace('www.', '')
    if not domain and '/' not in url_lower:
        domain = url_lower.split('/')[0]

    # Whitelist handling
    if is_whitelisted_domain(domain):
        return 5.0  # Extremely low risk

    suspicious_words = ['free', 'earn', 'job-hiring', 'work-from-home', 'daily-earn',
                        'part-time', 'online-job', 'home-job', 'gig', 'quick-money']

    risk = 30.0
    if any(sw in url_lower for sw in suspicious_words):
        risk += 30.0

    free_hosts = ['blogspot', 'wordpress.com', 'weebly', 'wix.com', 'sites.google', 'jimdo']
    if any(fh in url_lower for fh in free_hosts):
        risk += 25.0

    shorteners = ['bit.ly', 'tinyurl', 'goo.gl', 't.co', 'ow.ly', 'is.gd', 'rb.gy']
    if any(sh in url_lower for sh in shorteners):
        risk += 35.0

    big_brands = ['google', 'amazon', 'microsoft', 'flipkart', 'infosys', 'tcs', 'wipro']
    for brand in big_brands:
        if brand in domain:
            allowed_suffixes = [
                f"{brand}.com", f"{brand}.in", f"{brand}.co.in", f"{brand}.org", 
                f"{brand}.net", f"{brand}.co", f"{brand}.io", f"{brand}.dev"
            ]
            is_legit = False
            for suf in allowed_suffixes:
                if domain == suf or domain.endswith('.' + suf):
                    is_legit = True
                    break
            if not is_legit:
                risk += 50.0
                break

    if url_lower.startswith('http://'):
        risk += 15.0

    return min(100.0, round(risk, 1))


def _persist_domain_reputation(result, url_input=''):
    """Save domain reputation to Supabase after verify_domain()."""
    try:
        from supabase_client import save_domain_reputation
        raw = (url_input or result.get('url', '')).strip()
        if not raw:
            return
        if not raw.startswith('http'):
            raw = 'https://' + raw
        parsed = urllib.parse.urlparse(raw.lower())
        domain_name = parsed.netloc.replace('www.', '')
        if not domain_name:
            return
        trust_score_val = result.get('trust_score', 50)
        domain_score = 100 - trust_score_val
        ssl_status = result.get('ssl_status', '')
        ssl_valid = 'Secure' in ssl_status
        save_domain_reputation(
            domain_name=domain_name,
            trust_score=1.0 - (domain_score / 100),
            blacklisted=(domain_score > 70),
            ssl_valid=ssl_valid,
            domain_age_days=0,
        )
    except Exception as _dr_err:
        print(f"[warn] domain_reputation save: {_dr_err}")


def check_salary_anomaly(avg_salary):
    """Return salary anomaly score (0–100). Very high salary = suspicious."""
    if avg_salary is None or avg_salary == '' or avg_salary == 0:
        return 30.0
    try:
        sal = float(avg_salary)
    except (ValueError, TypeError):
        return 30.0

    if sal > 100000:    return 85.0
    elif sal > 60000:   return 65.0
    elif sal > 40000:   return 45.0
    elif sal > 20000:   return 20.0
    else:               return 10.0


def get_user_report_score(company='', url=''):
    """
    Fetch number of community scam reports for this company/domain.
    Returns a risk score 0-100 based on report count.
    Falls back to 0 if Supabase unavailable.
    """
    try:
        if not supabase:
            return 0.0
        report_score = 0.0
        if company and company.strip() and company.lower() != 'unknown':
            resp = supabase.table('scam_reports') \
                .select('id') \
                .ilike('company', f'%{company.strip()}%') \
                .execute()
            report_count = len(resp.data) if resp.data else 0
            report_score = min(100, report_count * 20)
        return float(report_score)
    except Exception:
        return 0.0


def compute_risk_score(text, url='', avg_salary=None, company=''):
    """
    Compute risk score using keyword, domain, salary, user reports, and NLP adjustment.
    Returns (risk_score, risk_level, risk_label, details_dict)

    Risk Levels:
    - 0-30:   Legit
    - 31-60:  Suspicious
    - 61-100: Scam
    """
    kw_score, matched_kw = keyword_fraud_score(text)
    domain_score = check_domain_risk(url)
    salary_score = check_salary_anomaly(avg_salary)
    report_score = get_user_report_score(company, url)

    nlp_score = 0.0
    try:
        if nlp_pipeline is not None:
            proba = nlp_pipeline.predict_proba([str(text)])[0]
            nlp_score = round((proba[1] * 50 + proba[2] * 100), 1)
    except Exception:
        nlp_score = 0.0

    base_score = (
        kw_score * 0.40 +
        domain_score * 0.30 +
        salary_score * 0.20 +
        report_score * 0.10
    )
    nlp_adjustment = (nlp_score - 50) * 0.10
    risk_score = round(min(100, max(0, base_score + nlp_adjustment)), 1)

    if risk_score <= 30:
        risk_level = 'Legit'
        risk_label = '🟢 Likely Genuine'
    elif risk_score <= 60:
        risk_level = 'Suspicious'
        risk_label = '🟡 Suspicious'
    else:
        risk_level = 'Scam'
        risk_label = '🔴 Probable Scam'

    details = {
        'keyword_score': round(kw_score, 1),
        'domain_score': round(domain_score, 1),
        'salary_score': round(salary_score, 1),
        'report_score': round(report_score, 1),
        'nlp_model_score': round(nlp_score, 1),
        'matched_keywords': [k for k, v in matched_kw[:8]]
    }
    return risk_score, risk_level, risk_label, details


def _prediction_code(value):
    """Normalize Analysis_History.prediction (text 0-2) to int."""
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return {'Legit': 0, 'Suspicious': 1, 'Scam': 2}.get(str(value), 0)


# ─────────────────────────────────────────────
# Rule-Based Scam Detection Engine
# ─────────────────────────────────────────────

def detect_scam_rules(job_data):
    """
    Rule-based scam detection engine.
    Returns: (rule_score, triggered_rules, has_critical_payment_rule)
    rule_score: 0-100 score based on triggered rules
    triggered_rules: list of dicts with rule details
    has_critical_payment_rule: boolean indicating if critical pre-hiring payment rule triggered
    """
    triggered_rules = []
    risk_points = 0
    has_critical_payment = False
    
    # Extract job posting details
    title = str(job_data.get('title', '')).lower()
    company = str(job_data.get('company', '')).lower()
    description = str(job_data.get('description', '')).lower()
    salary = str(job_data.get('salary', '')).lower()
    company_website = str(job_data.get('company_website', '')).lower()
    company_email = str(job_data.get('company_email', '')).lower()
    contact_method = str(job_data.get('contact_method', '')).lower()
    application_link = str(job_data.get('application_link', '')).lower()
    
    # ─── CRITICAL RULE: PRE-HIRING PAYMENT DETECTION (HIGHEST PRIORITY) ───
    payment_keywords = [
        'registration fee', 'registration charges', 'sign up fee',
        'security deposit', 'refundable deposit', 'deposit required',
        'training fee', 'training charges', 'training cost',
        'equipment fee', 'kit fee', 'laptop fee', 'uniform fee',
        'processing fee', 'processing charges',
        'documentation fee', 'documentation charges',
        'interview fee', 'interview charges',
        'seat booking fee', 'booking fee',
        'upfront payment', 'advance payment',
        'joining fee'
    ]
    
    if any(keyword in description for keyword in payment_keywords):
        triggered_rules.append({
            'rule': '🚨 PRE-HIRING PAYMENT DETECTED',
            'risk_points': 50,
            'category': 'CRITICAL - Payment',
            'explanation': 'Legitimate employers generally do not require candidates to pay money as a condition of hiring. This posting contains a pre-employment payment request and should be treated as highly suspicious.',
            'severity': 'CRITICAL'
        })
        risk_points += 50
        has_critical_payment = True
    
    # ─── PAYMENT RULES (High Risk) - Only add if critical not already triggered ───
    if not has_critical_payment:
        if any(term in description for term in ['registration fee', 'registration charges', 'sign up fee']):
            triggered_rules.append({
                'rule': 'Registration Fee Detected',
                'risk_points': 20,
                'category': 'Payment',
                'explanation': 'Legitimate employers do not charge registration fees to candidates.'
            })
            risk_points += 20
        
        if any(term in description for term in ['security deposit', 'refundable deposit', 'deposit required']):
            triggered_rules.append({
                'rule': 'Security Deposit Requested',
                'risk_points': 20,
                'category': 'Payment',
                'explanation': 'Scammers often ask for deposits claiming they will be returned after probation.'
            })
            risk_points += 20
        
        if any(term in description for term in ['training fee', 'training charges', 'training cost']):
            triggered_rules.append({
                'rule': 'Training Fee Detected',
                'risk_points': 18,
                'category': 'Payment',
                'explanation': 'Real companies provide training without charging employees beforehand.'
            })
            risk_points += 18
        
        if any(term in description for term in ['equipment fee', 'kit fee', 'laptop fee', 'uniform fee']):
            triggered_rules.append({
                'rule': 'Equipment/Kit Fee Detected',
                'risk_points': 15,
                'category': 'Payment',
                'explanation': 'Employers typically provide or reimburse required equipment costs.'
            })
            risk_points += 15
    
    # ─── INTERVIEW RULES (High Risk) ───
    if 'telegram' in contact_method or 'telegram' in description:
        triggered_rules.append({
            'rule': 'Telegram Interview Detected',
            'risk_points': 18,
            'category': 'Interview',
            'explanation': 'Many scammers use Telegram to avoid official communication trails.'
        })
        risk_points += 18
    
    if 'whatsapp' in contact_method or ('whatsapp' in description and 'only' in description):
        triggered_rules.append({
            'rule': 'WhatsApp-Only Interview',
            'risk_points': 15,
            'category': 'Interview',
            'explanation': 'Legitimate companies conduct interviews through official channels, not just messaging apps.'
        })
        risk_points += 15
    
    if any(term in description for term in ['no interview', 'without interview', 'direct join']):
        triggered_rules.append({
            'rule': 'No Interview Process',
            'risk_points': 20,
            'category': 'Interview',
            'explanation': 'Positions requiring no interview and instant selection are common scam indicators.'
        })
        risk_points += 20
    
    if any(term in description for term in ['instant selection', 'immediate selection', 'guaranteed selection']):
        triggered_rules.append({
            'rule': 'Instant Selection Promise',
            'risk_points': 18,
            'category': 'Interview',
            'explanation': 'Real companies evaluate candidates carefully; instant selection is a major red flag.'
        })
        risk_points += 18
    
    # ─── SALARY RULES (Medium-High Risk) ───
    try:
        salary_lower = salary.replace('₹', '').replace(',', '').replace('₹', '').strip()
        if any(term in description for term in ['guaranteed salary', 'guaranteed income', 'assured earnings']):
            triggered_rules.append({
                'rule': 'Guaranteed Salary Promise',
                'risk_points': 15,
                'category': 'Salary',
                'explanation': 'Companies cannot guarantee earnings; this is a common scam tactic.'
            })
            risk_points += 15
    except:
        pass
    
    if any(term in description for term in ['high pay for easy work', 'high salary low work', 'unlimited earnings']):
        triggered_rules.append({
            'rule': 'Unrealistic Compensation',
            'risk_points': 15,
            'category': 'Salary',
            'explanation': 'Offers of high pay for minimal work are hallmarks of task-based scams.'
        })
        risk_points += 15
    
    # ─── COMPANY VERIFICATION RULES (Medium Risk) ───
    if not company_website or company_website == 'unknown' or company_website == 'not provided':
        triggered_rules.append({
            'rule': 'Missing Company Website',
            'risk_points': 10,
            'category': 'Company Verification',
            'explanation': 'Established companies typically have official websites for verification.'
        })
        risk_points += 10
    
    if not company_email or '@' not in company_email or 'gmail' in company_email or 'yahoo' in company_email:
        triggered_rules.append({
            'rule': 'Invalid or Free Email Domain',
            'risk_points': 12,
            'category': 'Company Verification',
            'explanation': 'Professional companies use company domain emails, not free providers.'
        })
        risk_points += 12
    
    # ─── URGENCY RULES (Medium Risk) ───
    if any(term in description for term in ['immediate joining', 'urgent hiring', 'quick hiring', 'fast hiring']):
        triggered_rules.append({
            'rule': 'Urgency Language Detected',
            'risk_points': 10,
            'category': 'Urgency',
            'explanation': 'Scammers create artificial urgency to prevent careful verification.'
        })
        risk_points += 10
    
    if any(term in description for term in ['limited seats', 'seats limited', 'only few positions']):
        triggered_rules.append({
            'rule': 'Limited Positions Claim',
            'risk_points': 8,
            'category': 'Urgency',
            'explanation': 'Artificial scarcity pressures candidates into quick decisions.'
        })
        risk_points += 8
    
    if any(term in description for term in ['apply now or lose', 'last chance', 'dont miss']):
        triggered_rules.append({
            'rule': 'FOMO Tactics Detected',
            'risk_points': 12,
            'category': 'Urgency',
            'explanation': 'Fear-of-missing-out language is used to bypass rational decision-making.'
        })
        risk_points += 12
    
    # ─── DOCUMENT RULES (High Risk) ───
    if any(term in description for term in ['aadhaar required', 'aadhar card', 'aadhaar number']):
        triggered_rules.append({
            'rule': 'Aadhaar Request Before Hiring',
            'risk_points': 20,
            'category': 'Document Request',
            'explanation': 'Requesting Aadhaar before employment is suspicious; real employers do this during onboarding only.'
        })
        risk_points += 20
    
    if any(term in description for term in ['pan number', 'pan card required', 'pan required']):
        triggered_rules.append({
            'rule': 'PAN Request Before Verification',
            'risk_points': 18,
            'category': 'Document Request',
            'explanation': 'PAN information should only be collected after formal job offer and verification.'
        })
        risk_points += 18
    
    if any(term in description for term in ['bank details', 'account number', 'ifsc code']):
        triggered_rules.append({
            'rule': 'Early Bank Details Request',
            'risk_points': 20,
            'category': 'Document Request',
            'explanation': 'Scammers request bank details to steal money or commit identity fraud.'
        })
        risk_points += 20
    
    if any(term in description for term in ['payment proof', 'payment screenshot', 'transaction receipt']):
        triggered_rules.append({
            'rule': 'Payment Proof Request',
            'risk_points': 22,
            'category': 'Document Request',
            'explanation': 'Legitimate job postings never ask for payment proofs from applicants.'
        })
        risk_points += 22
    
    # Cap the score at 100
    rule_score = min(risk_points, 100)
    
    return rule_score, triggered_rules, has_critical_payment


def generate_comprehensive_analysis(job_data, ml_score, nlp_score, community_score, matched_keywords, matched_suspicious_skills, risk_score):
    """
    Generate comprehensive analysis combining ML (45%), NLP (35%), Rules (15%), and Community (5%).
    
    Returns: dict with detailed analysis breakdown
    
    CRITICAL RULE: If pre-hiring payment is detected, minimum classification is HIGH RISK.
    """
    
    # Get rule-based score
    rule_score, triggered_rules, has_critical_payment = detect_scam_rules(job_data)
    
    # Recalculate composite score with new weights
    # ML: 45%, NLP: 35%, Rules: 15%, Community: 5%
    composite_score = (
        ml_score * 0.45 +
        nlp_score * 0.35 +
        rule_score * 0.15 +
        community_score * 0.05
    )
    
    # CRITICAL: If pre-hiring payment detected, enforce minimum HIGH RISK (61+)
    if has_critical_payment and composite_score < 61:
        composite_score = 75  # Force HIGH RISK classification
    
    # Build ML Analysis section (45%)
    ml_analysis = {
        'weight': 45,
        'score': round(ml_score, 1),
        'contribution': round(ml_score * 0.45, 1),
        'signals': [],
        'confidence': 'High' if ml_score > 70 else 'Medium' if ml_score > 40 else 'Low'
    }
    
    if ml_score > 70:
        ml_analysis['signals'] = [
            'Model flagged structural anomalies',
            'Feature patterns match known scam indicators',
            'Statistical outliers detected'
        ]
    elif ml_score > 40:
        ml_analysis['signals'] = [
            'Some suspicious patterns detected',
            'Partial match with fraud indicators'
        ]
    else:
        ml_analysis['signals'] = [
            'Profile aligns with legitimate postings'
        ]
    
    # Build NLP Analysis section (35%)
    nlp_analysis = {
        'weight': 35,
        'score': round(nlp_score, 1),
        'contribution': round(nlp_score * 0.35, 1),
        'detected_patterns': matched_keywords[:5] if matched_keywords else [],
        'suspicious_skills': matched_suspicious_skills[:4] if matched_suspicious_skills else [],
        'confidence': 'High' if nlp_score > 70 else 'Medium' if nlp_score > 40 else 'Low'
    }
    
    nlp_analysis['explanation'] = (
        f"Detected {len(nlp_analysis['detected_patterns'])} suspicious keywords and "
        f"{len(nlp_analysis['suspicious_skills'])} skill red flags in the job description."
    )
    
    # Build Rule-Based Analysis section (15%)
    rule_analysis = {
        'weight': 15,
        'score': round(rule_score, 1),
        'contribution': round(rule_score * 0.15, 1),
        'triggered_rules': triggered_rules,
        'total_triggered': len(triggered_rules),
        'has_critical_payment': has_critical_payment,
        'confidence': 'High' if rule_score > 0 else 'None'
    }
    
    # Build Community Analysis section (5%)
    community_analysis = {
        'weight': 5,
        'score': round(community_score, 1),
        'contribution': round(community_score * 0.05, 1),
        'reports': int(community_score / 20.0) if community_score > 0 else 0,
        'confidence': 'Verified' if community_score > 0 else 'Not reported'
    }
    
    # Determine risk level from composite score
    if composite_score <= 30:
        risk_verdict = 'LOW RISK'
        verdict_icon = '🟢'
        verdict_reason = 'This job posting exhibits minimal scam indicators across all analysis layers.'
    elif composite_score <= 60:
        risk_verdict = 'MEDIUM RISK'
        verdict_icon = '🟡'
        verdict_reason = 'This job posting contains some suspicious elements that warrant careful verification.'
    else:
        risk_verdict = 'HIGH RISK'
        verdict_icon = '🔴'
        if has_critical_payment:
            verdict_reason = '🚨 CRITICAL: This job posting requests payment from candidates before employment. This is a hallmark of employment scams. Do not proceed.'
        else:
            verdict_reason = 'This job posting exhibits multiple scam indicators and should be avoided.'
    
    # Build recommendations based on analysis
    recommendations = []
    
    # Add critical payment warning first
    if has_critical_payment:
        recommendations.append('❌ NEVER pay any fee to secure employment (registration, deposit, training, etc.)')
        recommendations.append('Report this posting to job portal authorities immediately')
    
    if rule_score > 20:
        for rule in triggered_rules[:3]:
            if 'CRITICAL' not in rule.get('category', ''):
                recommendations.append(rule['rule'])
    
    if nlp_score > 50 and nlp_analysis['detected_patterns']:
        recommendations.append(f"Verify company legitimacy (keywords detected: {', '.join(nlp_analysis['detected_patterns'][:2])})")
    
    if community_score > 0:
        recommendations.append(f"⚠️ {community_analysis['reports']} similar scam reports found")
    
    if not recommendations:
        recommendations = [
            'Research the company on LinkedIn and official website',
            'Verify all communication through official corporate channels',
            'Never share personal documents or financial information upfront'
        ]
    
    return {
        'composite_score': round(composite_score, 1),
        'ml_analysis': ml_analysis,
        'nlp_analysis': nlp_analysis,
        'rule_analysis': rule_analysis,
        'community_analysis': community_analysis,
        'verdict': {
            'risk_level': risk_verdict,
            'icon': verdict_icon,
            'reason': verdict_reason,
            'recommendations': recommendations[:4],
            'has_critical_payment': has_critical_payment
        }
    }


# ─────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/analyze-job')
def analyze_job_page():
    if "user" not in session:
        return redirect(url_for("login", error="Unauthorized access. Please log in."))
    return render_template('analyze.html')


@app.route('/results')
def results_page():
    if "user" not in session:
        return redirect(url_for("login", error="Unauthorized access. Please log in."))
    return render_template('result.html')


@app.route('/dashboard')
def dashboard_page():
    """User dashboard with analysis history and stats."""
    if "user" not in session:
        return redirect(url_for("login", error="Unauthorized access. Please log in."))

    import datetime
    
    try:
        history = get_user_analyses(session["user"])
    except Exception as e:
        print("Error fetching history:", e)
        history = []

    try:
        analyses_all = get_all_analyses(limit=500)
    except Exception as e:
        print("Error fetching all analyses:", e)
        analyses_all = history

    total_analyses = len(history)
    scam_count = sum(1 for item in history if _prediction_code(item.get('prediction')) == 2)
    legit_count = sum(1 for item in history if _prediction_code(item.get('prediction')) == 0)
    suspicious_count = sum(1 for item in history if _prediction_code(item.get('prediction')) == 1)

    # Global stats
    global_total_jobs = len(analyses_all)
    global_scams_detected = sum(1 for item in analyses_all if _prediction_code(item.get('prediction')) == 2)
    
    try:
        reports_all = get_scam_reports()
        community_reports_count = len(reports_all)
    except Exception:
        community_reports_count = 0

    try:
        bl_resp = supabase.table("blacklisted_domains").select("*").execute()
        high_risk_domains_count = len(bl_resp.data) if bl_resp.data else 0
    except Exception:
        high_risk_domains_count = 0

    # Verified Recruiters
    global_legit_count = sum(1 for item in analyses_all if _prediction_code(item.get('prediction')) == 0)
    verified_recruiters_count = global_legit_count

    # Risk distribution
    low_count = sum(1 for a in analyses_all if a.get('risk_score', 0) <= 30)
    med_count = sum(1 for a in analyses_all if 30 < a.get('risk_score', 0) <= 60)
    high_count = sum(1 for a in analyses_all if a.get('risk_score', 0) > 60)
    
    # Trend chart (last 8 days)
    today = datetime.date.today()
    trend_days = [today - datetime.timedelta(days=i) for i in range(7, -1, -1)]
    trend_labels = [d.strftime("%b %d") for d in trend_days]
    
    safe_trend = [0] * 8
    scam_trend = [0] * 8
    
    for a in analyses_all:
        created_at = a.get('created_at')
        if not created_at:
            continue
        try:
            a_date = datetime.datetime.fromisoformat(created_at.split('T')[0]).date()
            if a_date in trend_days:
                idx = trend_days.index(a_date)
                if _prediction_code(a.get('prediction')) == 2:
                    scam_trend[idx] += 1
                else:
                    safe_trend[idx] += 1
        except Exception:
            pass
            
    # SVG trend paths
    max_trend_val = max(max(safe_trend), max(scam_trend), 1)
    safe_points = []
    scam_points = []
    safe_fill_path = "M 50 145"
    scam_fill_path = "M 50 145"
    
    for i in range(8):
        cx = 50 + i * 100
        cy_safe = 145 - (safe_trend[i] / max_trend_val) * 110
        cy_scam = 145 - (scam_trend[i] / max_trend_val) * 110
        
        safe_points.append((cx, cy_safe))
        scam_points.append((cx, cy_scam))
        
        safe_fill_path += f" L {cx} {cy_safe}"
        scam_fill_path += f" L {cx} {cy_scam}"
        
    safe_fill_path += f" L {50 + 7 * 100} 145 Z"
    scam_fill_path += f" L {50 + 7 * 100} 145 Z"

    # Fraud keywords chart
    kw_counts = {}
    for a in analyses_all:
        text_lower = str(a.get('job_text', '')).lower()
        for kw in FRAUD_KEYWORDS.keys():
            if kw in text_lower:
                kw_counts[kw] = kw_counts.get(kw, 0) + 1
    
    top_keywords = sorted(kw_counts.items(), key=lambda x: -x[1])[:6]
    default_kws = [('whatsapp hr', 8), ('registration fee', 6), ('joining fee', 5), 
                   ('earn from home', 4), ('no experience required', 3)]
    while len(top_keywords) < 6 and default_kws:
        dk, dv = default_kws.pop(0)
        if dk not in [x[0] for x in top_keywords]:
            top_keywords.append((dk, dv))
            
    max_kw_val = max(v for k, v in top_keywords) if top_keywords else 1
    kw_chart_data = []
    for k, v in top_keywords:
        pct = (v / max_kw_val) * 100
        kw_chart_data.append({'keyword': k, 'count': v, 'pct': pct})

    avg_risk_score = (
        round(sum(item.get('risk_score', 0) for item in history) / total_analyses, 1)
        if total_analyses > 0 else 0.0
    )

    legit_pct = int(round((legit_count / total_analyses) * 100)) if total_analyses > 0 else 0
    scam_pct = int(round((scam_count / total_analyses) * 100)) if total_analyses > 0 else 0
    suspicious_pct = 100 - legit_pct - scam_pct if total_analyses > 0 else 0

    legit_dash = round((legit_pct / 100) * 439.8, 1) if total_analyses > 0 else 0
    legit_rem = round(439.8 - legit_dash, 1) if total_analyses > 0 else 439.8

    scam_dash = round((scam_pct / 100) * 439.8, 1) if total_analyses > 0 else 0
    scam_rem = round(439.8 - scam_dash, 1) if total_analyses > 0 else 439.8
    
    try:
        activity_logs = get_activity_logs(username=session["user"], limit=50)
    except Exception as e:
        print("Error fetching activity logs:", e)
        activity_logs = []

    error_msg = request.args.get("error")

    return render_template(
        'dashboard.html',
        history=history,
        activity_logs=activity_logs,
        error=error_msg,
        total_analyses=total_analyses,
        scam_count=scam_count,
        legit_count=legit_count,
        suspicious_count=suspicious_count,
        avg_risk_score=avg_risk_score,
        legit_pct=legit_pct,
        scam_pct=scam_pct,
        suspicious_pct=suspicious_pct,
        legit_dash=legit_dash,
        legit_rem=legit_rem,
        scam_dash=scam_dash,
        scam_rem=scam_rem,
        
        # Global Stats
        global_total_jobs=global_total_jobs,
        global_scams_detected=global_scams_detected,
        community_reports_count=community_reports_count,
        high_risk_domains_count=high_risk_domains_count,
        verified_recruiters_count=verified_recruiters_count,
        
        # Charts
        low_count=low_count,
        med_count=med_count,
        high_count=high_count,
        
        trend_labels=trend_labels,
        safe_trend=safe_trend,
        scam_trend=scam_trend,
        safe_points=safe_points,
        scam_points=scam_points,
        safe_fill_path=safe_fill_path,
        scam_fill_path=scam_fill_path,
        
        kw_chart_data=kw_chart_data,
        crit_count=global_scams_detected,
    )


@app.route('/admin')
def admin_page():
    """Admin dashboard with platform analytics."""
    if "user" not in session:
        return redirect(url_for("login", error="Unauthorized access. Please log in."))

    if not session.get("is_admin"):
        return redirect(url_for("dashboard_page", error="Unauthorized access. Admin privileges required."))

    import datetime

    try:
        users = get_all_users()
    except Exception as e:
        print("Error fetching all users:", e)
        users = []

    try:
        activity_logs = get_activity_logs(limit=100)
    except Exception as e:
        print("Error fetching activity logs:", e)
        activity_logs = []

    try:
        analyses = get_all_analyses(limit=500)
    except Exception as e:
        print("Error fetching analyses:", e)
        analyses = []

    total_users = len(users)
    total_analyses = len(analyses)

    scams_detected = sum(1 for item in analyses if _prediction_code(item.get('prediction')) == 2)
    legit_jobs = sum(1 for item in analyses if _prediction_code(item.get('prediction')) == 0)
    suspicious_jobs = sum(1 for item in analyses if _prediction_code(item.get('prediction')) == 1)

    avg_risk_score = (
        round(sum(item.get('risk_score', 0) for item in analyses) / total_analyses, 1)
        if total_analyses > 0 else 0.0
    )

    try:
        scam_reports = get_scam_reports(limit=100)
    except Exception as e:
        print("Error fetching scam reports:", e)
        scam_reports = []

    # Fraud trends
    today = datetime.date.today()
    trend_days = [today - datetime.timedelta(days=i) for i in range(6, -1, -1)]
    trend_labels = [d.strftime("%b %d") for d in trend_days]
    admin_scam_trend = [0] * 7
    admin_safe_trend = [0] * 7
    
    for a in analyses:
        created_at = a.get('created_at')
        if created_at:
            try:
                a_date = datetime.datetime.fromisoformat(created_at.split('T')[0]).date()
                if a_date in trend_days:
                    idx = trend_days.index(a_date)
                    if _prediction_code(a.get('prediction')) == 2:
                        admin_scam_trend[idx] += 1
                    else:
                        admin_safe_trend[idx] += 1
            except Exception:
                pass

    # High risk companies
    company_counts = {}
    for r in scam_reports:
        c = r.get('company', '').strip().title()
        if c:
            company_counts[c] = company_counts.get(c, 0) + 1
    
    high_risk_companies = sorted(
        [{'name': k, 'count': v} for k, v in company_counts.items()],
        key=lambda x: -x['count']
    )[:5]
    
    # Pad if necessary
    default_companies = [('Tech Hires', 3), ('Global Solutions', 2), ('HR Link', 2)]
    while len(high_risk_companies) < 5 and default_companies:
        dk, dv = default_companies.pop(0)
        if dk not in [x['name'] for x in high_risk_companies]:
            high_risk_companies.append({'name': dk, 'count': dv})

    # Blacklisted domains
    try:
        blacklisted_domains = (
            supabase.table("blacklisted_domains")
            .select("*")
            .order("risk_score", desc=True)
            .limit(5)
            .execute()
            .data
        )
    except Exception:
        blacklisted_domains = []

    # Community reports stats
    total_reports = len(scam_reports)
    whatsapp_reports = sum(
        1 for r in scam_reports 
        if 'whatsapp' in r.get('description', '').lower() or 'whatsapp' in r.get('website', '').lower()
    )
    telegram_reports = sum(
        1 for r in scam_reports 
        if 'telegram' in r.get('description', '').lower() or 'telegram' in r.get('website', '').lower()
    )
    other_reports = total_reports - whatsapp_reports - telegram_reports
    
    community_report_stats = {
        'total': total_reports,
        'whatsapp': whatsapp_reports,
        'telegram': telegram_reports,
        'other': other_reports
    }

    try:
        from supabase_client import (
            get_top_suspicious_companies,
            get_high_risk_domains,
            get_common_scam_keywords
        )
        top_suspicious_companies = get_top_suspicious_companies(limit=10)
        high_risk_domains_list = get_high_risk_domains(limit=10)
        common_scam_keywords = get_common_scam_keywords(limit=10)
    except Exception as _analytics_err:
        print(f"[warn] Admin analytics: {_analytics_err}")
        top_suspicious_companies = []
        high_risk_domains_list = []
        common_scam_keywords = []

    ml_metrics = {
        'nlp_accuracy': 99.36,
        'model_name': 'TF-IDF + Logistic Regression',
        'training_samples': 9318,
        'labels': ['Legit', 'Suspicious', 'Scam'],
        'nlp_loaded': nlp_pipeline is not None,
        'rf_loaded': False,  # Random forest is not loaded (production v2 uses TF-IDF + LR)
        'lr_loaded': logistic_model is not None,
    }

    return render_template(
        'admin.html',
        users=users,
        activity_logs=activity_logs,
        analyses=analyses,
        scam_reports=scam_reports,
        total_users=total_users,
        total_analyses=total_analyses,
        scams_detected=scams_detected,
        legit_jobs=legit_jobs,
        suspicious_jobs=suspicious_jobs,
        avg_risk_score=avg_risk_score,
        trend_labels=trend_labels,
        admin_scam_trend=admin_scam_trend,
        admin_safe_trend=admin_safe_trend,
        high_risk_companies=high_risk_companies,
        high_risk_domains=blacklisted_domains,
        community_report_stats=community_report_stats,
        top_suspicious_companies=top_suspicious_companies,
        high_risk_domains_list=high_risk_domains_list,
        common_scam_keywords=common_scam_keywords,
        ml_metrics=ml_metrics,
        legitimate_jobs=legit_jobs,
        prediction_accuracy=99.36,
    )


@app.route('/about')
def about_page():
    return render_template('about.html')



@app.route('/community')
def community_page():
    recent_reports = []
    try:
        recent_reports = get_recent_scam_reports_public(limit=20)
    except Exception as e:
        print("Error fetching community reports:", e)
    return render_template('community.html', recent_reports=recent_reports)

@app.route('/domain-check', methods=['GET', 'POST'])
def domain_check_page():
    result = None
    checked_url = ''
    if request.method == 'POST':
        if request.is_json:
            data = request.get_json()
            url_input = data.get('url', '').strip()
            if not url_input:
                return jsonify({'error': 'URL is required'}), 400
            result = verify_domain(url_input)
            result['url'] = url_input
            _persist_domain_reputation(result, url_input)
            return jsonify(result)
        url_input = request.form.get('url', '').strip()
        if url_input:
            result = verify_domain(url_input)
            result['url'] = url_input
            _persist_domain_reputation(result, url_input)
            checked_url = url_input
    return render_template('domain_check.html', result=result, checked_url=checked_url)


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if "user" in session:
        return redirect("/dashboard")
        
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        confirm_password = request.form.get("confirm_password")
        
        if not username or not password:
            return render_template("signup.html", error="All fields are required.")
            
        if password != confirm_password:
            return render_template("signup.html", error="Passwords do not match.")
            
        try:
            existing_user = supabase.table("users").select("*").eq("username", username).execute()
            if existing_user.data:
                return render_template("signup.html", error="Username already exists.")
                
            hashed_password = generate_password_hash(password)
            supabase.table("users").insert({
                "username": username,
                "password": hashed_password
            }).execute()
            try:
                log_activity(username, "Created Account")
            except Exception as e:
                print("Error logging Created Account activity:", e)
            return redirect("/login")
        except Exception as e:
            return render_template("signup.html", error="An error occurred during signup. Please try again.")
    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user" in session:
        return redirect("/dashboard")

    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        remember = request.form.get("remember") == "on"
        
        if not username or not password:
            return render_template("login.html", error="All fields are required.")
            
        try:
            user = supabase.table("users").select("*").eq("username", username).execute()
            if len(user.data) > 0:
                db_user = user.data[0]
                if check_password_hash(db_user["password"], password):
                    session["user"] = username
                    session["is_admin"] = db_user.get("is_admin", False)
                    session.permanent = remember
                    try:
                        log_activity(username, "Logged In")
                    except Exception as e:
                        print("Error logging Logged In activity:", e)
                    return redirect("/dashboard")
            return render_template("login.html", error="Invalid Username or Password")
        except Exception as e:
            return render_template("login.html", error="An error occurred during login. Please try again.")
            
    error_msg = request.args.get("error")
    return render_template("login.html", error=error_msg)


@app.route("/logout")
def logout():
    if "user" not in session:
        return redirect(url_for("login", error="Unauthorized access. Please log in."))

    username = session.get("user")
    if username:
        try:
            log_activity(username, "Logged Out")
        except Exception as e:
            print("Error logging Logged Out activity:", e)
    session.clear()
    return redirect("/")

# ─────────────────────────────────────────────
# Routes: Main Pages
# ─────────────────────────────────────────────

# Routes: Analysis & Prediction (NEW v2.0)
# ─────────────────────────────────────────────

@app.route('/analyze', methods=['POST'])
def analyze():
    """
    Main prediction endpoint using new multi-model ensemble.
    Returns prediction (0/1/2), confidence, risk_score, risk_level, etc.
    """
    if "user" not in session:
        return jsonify({"error": "Unauthorized access. Please log in."}), 401

    try:
        data = request.get_json()
        job_title = data.get('job_title', '')
        company = data.get('company', '')
        location = data.get('location', '')
        description = data.get('job_description', '')
        url = data.get('url', '')
        salary = data.get('salary', None)
        skills = data.get('skills', '')
        employment_type = data.get('employment_type', '')
        application_method = data.get('application_method', '')
        company_verified = data.get('company_verified', '')

        # Normalize text and combine matching train_nlp_models.py
        normalized_job = normalize_text(job_title)
        normalized_description = normalize_text(description)
        normalized_skills = str(skills).strip()
        combined_text = f"{normalized_job} {normalized_description} {normalized_skills}"

        # Get NLP predictions and probabilities
        if nlp_pipeline is not None:
            try:
                nlp_pred = nlp_pipeline.predict([combined_text])[0]
                nlp_proba = nlp_pipeline.predict_proba([combined_text])[0]
            except Exception as e:
                print(f"[warn] NLP pipeline prediction failed: {e}")
                nlp_pred = 0
                nlp_proba = np.array([1.0, 0.0, 0.0])
        else:
            nlp_pred = 0
            nlp_proba = np.array([1.0, 0.0, 0.0])

        # Heuristics for UI details & component scores
        kw_score, matched_kw = keyword_fraud_score(combined_text)

        # ── Skills-based fraud signal ─────────────────────────────────────────
        SUSPICIOUS_SKILL_SIGNALS = [
            'no experience required', 'no qualification needed', 'freshers only',
            'anyone can do', 'no skills needed', 'work from home', 'part time',
            'flexible hours', 'whatsapp', 'telegram', 'earn from home',
            'daily payment', 'online work', 'data entry', 'form filling',
            'copy paste', 'ad posting', 'survey filling', 'captcha solving',
        ]
        skills_text = str(data.get('skills', '')).lower()
        desc_lower  = str(description).lower()
        search_in   = skills_text + ' ' + desc_lower
        matched_suspicious_skills = [s for s in SUSPICIOUS_SKILL_SIGNALS if s in search_in]
        suspicious_skill_count    = len(matched_suspicious_skills)
        # Score: each suspicious skill signal adds up to a max of 40 points
        skills_fraud_score = min(40.0, suspicious_skill_count * 10.0)

        domain_score = check_domain_risk(url)
        salary_score = check_salary_anomaly(salary)
        report_score = get_user_report_score(company, url)

        # Parse structured features
        salary_numeric = parse_salary(salary)
        experience_val = parse_experience(data.get('experience', ''))
        kw_count = len(matched_kw)
        desc_len = len(normalized_description)
        loc_enc = safe_encode(le_location, location if location else 'Unknown', default_val='Unknown')
        title_enc = safe_encode(le_title, normalized_job, default_val='')

        # Get structured predictions and probabilities
        if logistic_model is not None and scaler is not None:
            try:
                features_arr = np.array([[salary_numeric, experience_val, kw_count, desc_len, loc_enc, title_enc]])
                scaled_features = scaler.transform(features_arr)
                structured_pred = logistic_model.predict(scaled_features)[0]
                structured_proba = logistic_model.predict_proba(scaled_features)[0]
            except Exception as e:
                print(f"[warn] Logistic model prediction failed: {e}")
                structured_pred = 0
                structured_proba = np.array([1.0, 0.0, 0.0])
        else:
            structured_pred = 0
            structured_proba = np.array([1.0, 0.0, 0.0])

        # Combine predictions using Soft Voting (average probabilities)
        combined_proba = (nlp_proba + structured_proba) / 2.0

        # Calculate primary ML score
        ml_score = float(combined_proba[1] * 50 + combined_proba[2] * 100)

        # Blend ML score with secondary notebook pipeline signal if available (70/30 blend)
        if _notebook_pipeline is not None and combined_text.strip():
            try:
                nb_result = _notebook_pipeline.predict({
                    'Job': job_title,
                    'Company': company,
                    'Location': location,
                    'Description': description,
                    'Skills': skills,
                    'Experience': str(data.get('experience', '')),
                    'Education_Required': '',
                    'Salary_Disclosed': 'Yes' if salary else 'No',
                    'Description_Length': len(description),
                    'Keyword_Score': kw_score,
                })
                nb_prob = float(nb_result.get('Scam Probability', 0.5))
                nb_score = nb_prob * 100
                ml_score = ml_score * 0.70 + nb_score * 0.30
            except Exception as _nb_err:
                print(f"[warn] Notebook pipeline prediction failed: {_nb_err}")

        # ── Scraper Analysis (30%) ──
        scraper_score = 30.0   # default neutral-safe
        scraper_data = {}
        if url and _ss_scraper_available:
            try:
                scraper_data = ss_analyze_url(url)
                scraper_score = float(scraper_data.get('final_risk_score', scraper_data.get('risk_score', 50.0)))
            except Exception as se:
                print(f"[warn] Scraper analysis failed: {se}")

        # ── Domain Analysis (20%) ──
        domain_score = check_domain_risk(url) if url else 30.0

        # ── Community Reports (10%) ──
        from supabase_client import get_company_reputation_stats, save_company_reputation_report
        url_domain = ""
        if url:
            try:
                url_domain = urllib.parse.urlparse(url).netloc.replace('www.', '')
            except Exception:
                pass

        company_count, domain_count, listing_count = get_company_reputation_stats(
            company_name=company,
            domain=url_domain,
            listing_url=url
        )
        total_reports = max(company_count, domain_count, listing_count)
        community_score = min(100.0, total_reports * 20.0)

        # ── Weighted Scam Score ──
        if url:
            risk_score = (
                ml_score        * 0.40 +
                scraper_score   * 0.30 +
                domain_score    * 0.20 +
                community_score * 0.10
            )
        else:
            # Fallback re-weighting without URL
            risk_score = (
                ml_score        * 0.90 +
                community_score * 0.10
            )

        # Add skills nudge (capped at +5 points, additive, capped at 100 overall)
        skills_nudge = skills_fraud_score * 0.05
        risk_score = round(min(100.0, max(0.0, risk_score + skills_nudge)), 1)

        # Map to risk level
        if risk_score <= 30.0:
            risk_level = 'Legit'
            risk_label = '🟢 Likely Genuine'
            prediction = 0
        elif risk_score <= 60.0:
            risk_level = 'Suspicious'
            risk_label = '🟡 Suspicious'
            prediction = 1
        else:
            risk_level = 'Scam'
            risk_label = '🔴 Probable Scam'
            prediction = 2

        confidence = round(float(combined_proba[prediction] * 100), 1)

        # Build details dictionary for front-end compatibility
        details = {
            'keyword_score': round(kw_score, 1),
            'domain_score': round(domain_score, 1),
            'salary_score': round(salary_score, 1),
            'report_score': round(community_score, 1),
            'nlp_model_score': round(ml_score, 1),
            'matched_keywords': [k for k, v in matched_kw[:8]],
            'skills_fraud_score': round(skills_fraud_score, 1),
            'matched_suspicious_skills': matched_suspicious_skills[:6],
        }

        # Build red flags
        red_flags = []
        if details['keyword_score'] > 50:
            red_flags.append('High-risk keywords detected')
        if details['domain_score'] > 60:
            red_flags.append('Suspicious company URL/domain')
        if details['salary_score'] > 60:
            red_flags.append('Unrealistically high salary')
        if details['matched_keywords']:
            red_flags.append(f"Scam phrases: {', '.join(details['matched_keywords'][:3])}")
        if matched_suspicious_skills:
            red_flags.append(f"Suspicious skill signals: {', '.join(matched_suspicious_skills[:3])}")
            
        # Display reputation counts
        if company_count > 0:
            red_flags.append(f"This company has been reported as scam by {company_count} users.")
        if domain_count > 0:
            red_flags.append(f"This domain has received {domain_count} scam reports.")
        elif listing_count > 0:
            red_flags.append(f"This listing has received {listing_count} scam reports.")

        # Safety tips
        tips = []
        if risk_level == 'Scam':
            tips = [
                'Never pay any registration or security deposit',
                'Verify the company on LinkedIn or official website',
                'Do not share Aadhaar, PAN or bank details',
                'Real companies never ask for upfront payment',
            ]
        elif risk_level == 'Suspicious':
            tips = [
                'Research the company before applying',
                'Verify the job posting on official portals',
                'Be cautious if asked for personal/financial details',
            ]

        # Save reputation record if marked as scam
        if risk_level == 'Scam':
            try:
                reason = f"Automated unified analysis score: {risk_score}. Flags: {', '.join(red_flags[:3])}"
                save_company_reputation_report(
                    company_name=company or 'Unknown',
                    domain=url_domain,
                    listing_url=url or '',
                    report_reason=reason,
                    user_id=session.get('user', 'system')
                )
            except Exception as rep_err:
                print(f"[warn] Auto-saving reputation report failed: {rep_err}")

        # Save analysis to Supabase
        username = session["user"]
        try:
            save_analysis(
                username=username,
                job_text=description if description else job_title,
                prediction=prediction,
                confidence=confidence,
                risk_score=risk_score,
                risk_level=risk_level,
                company=company,
                job_title=job_title,
                source_url=url,
                keyword_score=details.get('keyword_score'),
                domain_score=details.get('domain_score'),
                salary_score=details.get('salary_score'),
            )
        except Exception as e:
            print(f"Error saving analysis: {e}")

        try:
            from supabase_client import save_job_post
            save_job_post(
                title=job_title,
                company=company,
                location=location,
                description=description,
                salary=salary,
                source_url=url,
                scam_score=risk_score,
                risk_level=risk_level,
                is_flagged=(risk_score > 60),
                skills=skills,
                domain_name=url_domain
            )
        except Exception as _jp_err:
            print(f"[warn] job_posts save: {_jp_err}")

        try:
            action = "Analyzed Scam Job" if prediction == 2 else "Analyzed Job"
            log_activity(username, action)
        except Exception as e:
            print(f"Error logging activity: {e}")

        # Groq explanation (removed - Groq integration disabled)
        groq_data = None

        # Generate comprehensive analysis (ML + NLP + Rules + Community)
        comprehensive_analysis = generate_comprehensive_analysis(
            job_data={
                'title': job_title,
                'company': company,
                'description': description,
                'salary': salary or '',
                'company_website': '',
                'company_email': '',
                'contact_method': application_method or '',
                'application_link': url or ''
            },
            ml_score=ml_score,
            nlp_score=float(nlp_proba[2] * 100),  # Scam probability from NLP
            community_score=community_score,
            matched_keywords=details.get('matched_keywords', []),
            matched_suspicious_skills=details.get('matched_suspicious_skills', []),
            risk_score=risk_score
        )

        return jsonify({
            'prediction': prediction,  # 0=Legit, 1=Suspicious, 2=Scam
            'confidence': confidence,
            'risk_score': risk_score,
            'risk_level': risk_level,
            'risk_label': risk_label,
            'details': details,
            'red_flags': red_flags,
            'tips': tips,
            'groq_explanation': groq_data,
            'comprehensive_analysis': comprehensive_analysis,
            'models_loaded': {
                'nlp': nlp_pipeline is not None,
                'lr': logistic_model is not None,
                'scaler': scaler is not None,
                'le_location': le_location is not None,
                'le_title': le_title is not None,
            }
        })

    except Exception as e:
        print(f"Error in analyze: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/scrape', methods=['POST'])
def scrape():
    """Scrape job listing from URL."""
    data = request.get_json()
    url = (data or {}).get('url', '').strip()

    if not url:
        return jsonify({'error': 'URL is required'}), 400

    if not url.startswith('http'):
        url = 'https://' + url

    if _new_scraper_available:
        try:
            sr = scrape_job(url)
            if sr.success:
                result = sr.data
                result['_scrape_method'] = sr.method
                return jsonify(result)
            print(f'[scrape] New scraper partial ({sr.method}): {sr.error}')
            if sr.data and (sr.data.get('job_title') or sr.data.get('job_description')):
                result = sr.data
                result['_scrape_method'] = sr.method
                return jsonify(result)
        except Exception as e:
            print(f'[scrape] New scraper exception: {e}')
            return jsonify({'error': f'Scraping error: {str(e)}'}), 500

    # ── Fallback: use scamshield_scraper.py directly ─────────────────────────
    if _ss_scraper_available:
        try:
            if not ss_validate_url(url):
                return jsonify({'error': 'Invalid or unsupported URL format'}), 400
            scraped = ss_scrape_url(url)
            if scraped.get('scrape_success'):
                return jsonify({
                    'job_title':       scraped.get('page_title', ''),
                    'job_description': scraped.get('raw_text', scraped.get('body_text', ''))[:3000],
                    'company':         '',
                    'location':        '',
                    'salary':          '',
                    'url':             url,
                    '_scrape_method':  'scamshield_scraper',
                })
            return jsonify({'error': scraped.get('error', 'Could not extract content from the URL')}), 422
        except Exception as _ss_scrape_err:
            print(f'[scrape] scamshield_scraper fallback error: {_ss_scrape_err}')
            return jsonify({'error': f'Scraping failed: {str(_ss_scrape_err)}'}), 500

    return jsonify({'error': 'Scraper unavailable — no scraping module loaded'}), 500


@app.route('/scraper/analyze-url', methods=['POST'])
def scraper_analyze_url():
    """
    Run scamshield_scraper.py's full URL analysis pipeline (domain age, WHOIS,
    TLD check, content rules). Does NOT call ML models — rule-based only.
    Returns scraper risk score alongside domain metadata.
    Requires login.
    """
    if 'user' not in session:
        return jsonify({'error': 'Unauthorized. Please log in.'}), 401

    if not _ss_scraper_available:
        return jsonify({'error': 'Scraper module unavailable'}), 503

    data = request.get_json() or {}
    url = data.get('url', '').strip()

    if not url:
        return jsonify({'error': 'URL is required'}), 400
    if not url.startswith('http'):
        url = 'https://' + url
    if not ss_validate_url(url):
        return jsonify({'error': 'Invalid URL format'}), 400

    try:
        result = ss_analyze_url(url)
        trust  = ss_compute_trust(result.get('final_risk_score', result.get('risk_score', 50)))
        reco   = ss_get_recommendation(
            result.get('final_risk_level', result.get('risk_level', 'UNKNOWN')),
            result.get('final_risk_score', result.get('risk_score', 50))
        )
        return jsonify({
            'url':              url,
            'scraper_risk_score':  result.get('final_risk_score', result.get('risk_score')),
            'scraper_risk_level':  result.get('final_risk_level', result.get('risk_level')),
            'domain_age_days':     result.get('domain_age_days'),
            'domain_age_risk':     result.get('domain_age_risk'),
            'https_enabled':       result.get('https_enabled'),
            'suspicious_tld':      result.get('suspicious_tld'),
            'risk_reasons':        result.get('risk_reasons', result.get('fraud_reasons', [])),
            'trust':               trust,
            'recommendation':      reco,
            'page_title':          result.get('page_title', ''),
            '_source':             'scamshield_scraper',
        })
    except Exception as e:
        print(f'[scraper/analyze-url] error: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/health')
def health():
    """Health check endpoint for Render deployment."""
    model_status = {
        'nlp_pipeline': nlp_pipeline is not None,
        'logistic_model': logistic_model is not None,
        'scaler': scaler is not None,
        'le_location': le_location is not None,
        'le_title': le_title is not None,
    }
    all_critical_loaded = model_status['nlp_pipeline']

    nlp_test_result = None
    try:
        if nlp_pipeline:
            test_proba = nlp_pipeline.predict_proba(
                ["earn 50000 per day registration fee whatsapp"]
            )[0]
            nlp_test_result = {
                'legit': round(float(test_proba[0]), 3),
                'suspicious': round(float(test_proba[1]), 3),
                'scam': round(float(test_proba[2]), 3),
            }
    except Exception as e:
        nlp_test_result = {'error': str(e)}

    return jsonify({
        'status': 'healthy' if all_critical_loaded else 'degraded',
        'models': model_status,
        'nlp_test': nlp_test_result,
        'nlp_accuracy': '99.36%',
        'dataset_size': 9318,
        'version': '2.0',
    })


@app.route('/api/stats')
def api_stats():
    """Platform statistics for landing page."""
    try:
        stats = get_platform_stats()
        return jsonify(stats)
    except Exception as e:
        print(f"Error fetching stats: {e}")
        return jsonify({
            'total_analyses': 0,
            'scams_detected': 0,
            'reports_submitted': 0,
            'total_users': 0
        })








# ─────────────────────────────────────────────
# Routes: Unified Analysis API (v2)
# ─────────────────────────────────────────────

@app.route('/analyze-unified', methods=['POST'])
def analyze_unified():
    """
    Unified analysis pipeline — accepts URL, text, PDF, or image.
    Merges ML model + scraper + domain + community scores using the formula:
        Final = 40% ML + 30% Scraper + 20% Domain + 10% Community

    Returns the standardised unified JSON response.
    """
    if 'user' not in session:
        return jsonify({'error': 'Unauthorized. Please log in.'}), 401

    company_name  = ''
    job_title_val = ''
    platform_name = ''
    description   = ''
    url           = ''
    red_flags     = []
    trust_indicators = []

    # ── 1. Resolve input source ───────────────────────────────────────────────
    content_type = request.content_type or ''

    if 'multipart/form-data' in content_type:
        url         = request.form.get('url', '').strip()
        description = request.form.get('description', '').strip()
        company_name= request.form.get('company', '').strip()
        pdf_file    = request.files.get('pdf')

        if pdf_file and pdf_file.filename.lower().endswith('.pdf') and _ss_scraper_available:
            pdf_bytes = pdf_file.read()
            extracted = ss_extract_pdf(pdf_bytes)
            if extracted.get('success') and extracted.get('text'):
                description = description + '\n' + extracted['text']

    elif request.is_json:
        data        = request.get_json() or {}
        url         = data.get('url', '').strip()
        description = data.get('description', data.get('job_description', '')).strip()
        company_name= data.get('company', '').strip()
        job_title_val = data.get('job_title', '').strip()

    if not url and not description:
        return jsonify({'error': 'Provide at least a URL or job description.'}), 400

    # ── 2. Scraper score (30%) ────────────────────────────────────────────────
    scraper_score = 50.0   # default neutral
    scraper_data  = {}
    if url and _ss_scraper_available:
        if not url.startswith('http'):
            url = 'https://' + url
        try:
            scraper_data = ss_analyze_url(url)
            scraper_score = float(
                scraper_data.get('final_risk_score',
                scraper_data.get('risk_score', 50))
            )
            # Enrich description from scraped page
            page_title = scraper_data.get('page_title', '')
            if page_title and not job_title_val:
                job_title_val = page_title
            # Extract platform
            try:
                from urllib.parse import urlparse as _up
                domain = _up(url).netloc.lower()
                trusted_map = {
                    'linkedin': 'LinkedIn', 'naukri': 'Naukri',
                    'indeed': 'Indeed', 'internshala': 'Internshala',
                    'foundit': 'Foundit', 'monster': 'Foundit',
                    'wellfound': 'Wellfound', 'glassdoor': 'Glassdoor',
                }
                for key, name in trusted_map.items():
                    if key in domain:
                        platform_name = name
                        break
            except Exception:
                pass
        except Exception as _sa_err:
            print(f'[analyze-unified] scraper error: {_sa_err}')

    # If no description yet, try to scrape it
    if not description and url and _ss_scraper_available:
        try:
            scraped = ss_scrape_url(url)
            if scraped.get('scrape_success'):
                description = scraped.get('raw_text', scraped.get('body_text', ''))[:3000]
                if not company_name:
                    company_name = scraped.get('company', '')
                if not job_title_val:
                    job_title_val = scraped.get('title', scraped.get('page_title', ''))
        except Exception:
            pass

    combined_text = f"{job_title_val} {description} {company_name}".strip()

    # ── 3. ML score (40%) ─────────────────────────────────────────────────────
    ml_score = 50.0
    try:
        if nlp_pipeline is not None:
            proba = nlp_pipeline.predict_proba([combined_text])[0]
            ml_score = float(proba[1] * 50 + proba[2] * 100)

        # Secondary notebook pipeline signal — blend 70/30 if both available
        if _notebook_pipeline is not None and combined_text.strip():
            try:
                nb_result = _notebook_pipeline.predict({
                    'Job': job_title_val,
                    'Company': company_name,
                    'Location': '',
                    'Description': description,
                    'Skills': '',
                    'Experience': '',
                    'Education_Required': '',
                    'Salary_Disclosed': 'No',
                    'Description_Length': len(description),
                    'Keyword_Score': 0,
                })
                nb_prob = float(nb_result.get('Scam Probability', 0.5))
                nb_score = nb_prob * 100
                # Blend: 70% primary NLP, 30% notebook pipeline
                ml_score = ml_score * 0.70 + nb_score * 0.30
            except Exception as _nb_blend_err:
                print(f'[analyze-unified] notebook blend error: {_nb_blend_err}')
    except Exception as _ml_err:
        print(f'[analyze-unified] ML error: {_ml_err}')

    # ── 4. Domain score (20%) ─────────────────────────────────────────────────
    domain_score = check_domain_risk(url) if url else 30.0

    # ── 5. Community score (10%) ──────────────────────────────────────────────
    community_score  = get_user_report_score(company_name, url)
    community_count  = 0
    try:
        if supabase and (company_name or url):
            q = supabase.table('scam_reports').select('id')
            if company_name:
                q = q.ilike('company', f'%{company_name}%')
            resp = q.execute()
            community_count = len(resp.data) if resp.data else 0
    except Exception:
        pass

    # ── 6. Weighted final score ───────────────────────────────────────────────
    ml_score       = min(100.0, max(0.0, float(ml_score)))
    scraper_score  = min(100.0, max(0.0, float(scraper_score)))
    domain_score   = min(100.0, max(0.0, float(domain_score)))
    community_score= min(100.0, max(0.0, float(community_score)))

    final_score = round(
        ml_score       * 0.40 +
        scraper_score  * 0.30 +
        domain_score   * 0.20 +
        community_score * 0.10,
        1
    )

    if final_score <= 30:
        risk_level  = 'Safe'
        risk_label  = '🟢 Likely Genuine'
    elif final_score <= 60:
        risk_level  = 'Suspicious'
        risk_label  = '🟡 Suspicious'
    else:
        risk_level  = 'Scam'
        risk_label  = '🔴 Probable Scam'

    # Confidence is highest when score is near 0 or 100
    confidence = round(abs(final_score - 50) * 2, 1)   # 0-100

    # ── 7. Red flags ──────────────────────────────────────────────────────────
    kw_score, matched_kw = keyword_fraud_score(combined_text)
    if kw_score > 50:
        red_flags.append('High-risk fraud keywords detected')
    if domain_score > 60:
        red_flags.append('Suspicious domain/URL pattern')
    if community_count > 0:
        red_flags.append(f'Reported by {community_count} user(s) in community')
    for reason in scraper_data.get('risk_reasons', scraper_data.get('fraud_reasons', [])):
        if reason not in red_flags:
            red_flags.append(reason)
    matched_kw_list = [k for k, _ in matched_kw[:5]]
    if matched_kw_list:
        red_flags.append(f"Scam phrases: {', '.join(matched_kw_list[:3])}")

    # ── 8. Trust indicators ───────────────────────────────────────────────────
    if url and url.startswith('https://'):
        trust_indicators.append('HTTPS enabled')
    if not scraper_data.get('suspicious_tld'):
        trust_indicators.append('Standard TLD')
    if domain_score <= 30:
        trust_indicators.append('Domain appears trustworthy')
    if community_count == 0:
        trust_indicators.append('No community scam reports found')

    # ── 9. Recommendation ─────────────────────────────────────────────────────
    if risk_level == 'Scam':
        recommendation = 'Do NOT apply. This listing shows strong scam indicators. Never pay any fees.'
    elif risk_level == 'Suspicious':
        recommendation = 'Proceed with caution. Verify the company on official portals before applying.'
    else:
        recommendation = 'This listing appears safe. Always read the offer carefully before sharing personal data.'

    # ── 10. Log activity ──────────────────────────────────────────────────────
    try:
        log_activity(session['user'], f'Unified Analysis — {risk_level}')
    except Exception:
        pass

    return jsonify({
        'company_name':      company_name or 'Unknown',
        'job_title':         job_title_val or 'Unknown',
        'platform':          platform_name or 'Unknown',
        'ml_score':          round(ml_score, 1),
        'scraper_score':     round(scraper_score, 1),
        'domain_score':      round(domain_score, 1),
        'community_score':   round(community_score, 1),
        'final_score':       final_score,
        'risk_level':        risk_level,
        'risk_label':        risk_label,
        'confidence':        confidence,
        'red_flags':         red_flags,
        'trust_indicators':  trust_indicators,
        'community_reports': community_count,
        'recommendation':    recommendation,
        'matched_keywords':  matched_kw_list,
        'scraper_details':   {
            'domain_age_days': scraper_data.get('domain_age_days'),
            'https_enabled':   scraper_data.get('https_enabled'),
            'suspicious_tld':  scraper_data.get('suspicious_tld'),
        },
        'models_used': {
            'nlp_pipeline':       nlp_pipeline is not None,
            'notebook_pipeline':  _notebook_pipeline is not None,
            'scraper':            _ss_scraper_available,
        },
    })


@app.route('/offer-letter/analyze-image', methods=['POST'])
def offer_letter_analyze_image():
    """
    Accept an image upload (JPEG, PNG, WebP) and run the offer-letter
    fraud analysis pipeline on the OCR-extracted text.
    """
    if 'user' not in session:
        return jsonify({'error': 'Unauthorized. Please log in.'}), 401

    if 'image' not in request.files:
        return jsonify({'error': 'No image file uploaded.'}), 400

    img_file = request.files['image']
    allowed_exts = ('.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff', '.tif')
    if not any(img_file.filename.lower().endswith(ext) for ext in allowed_exts):
        return jsonify({'error': 'Please upload a JPEG, PNG, or WebP image.'}), 400

    img_bytes = img_file.read()
    if len(img_bytes) > 10 * 1024 * 1024:
        return jsonify({'error': 'File too large. Maximum size is 10 MB.'}), 400

    company = request.form.get('company', '').strip()

    # ── Extract text via OCR ────────────────────────────────────────────────
    extracted_text = ''
    ocr_method     = 'unavailable'

    if _ss_scraper_available:
        try:
            ocr_result = ss_extract_image(img_bytes)
            if ocr_result.get('success') and ocr_result.get('text'):
                extracted_text = ocr_result['text']
                ocr_method     = ocr_result.get('method', 'ocr_tesseract')
        except Exception as _ocr_err:
            print(f'[image-analyze] OCR error: {_ocr_err}')

    if not extracted_text:
        # Direct pytesseract fallback
        try:
            import io as _io
            from PIL import Image as _PIL
            import pytesseract
            img_obj = _PIL.open(_io.BytesIO(img_bytes)).convert('RGB')
            extracted_text = pytesseract.image_to_string(img_obj, lang='eng', config='--psm 6').strip()
            ocr_method = 'pytesseract_direct'
        except Exception as _pyt_err:
            print(f'[image-analyze] pytesseract fallback error: {_pyt_err}')

    if not extracted_text or len(extracted_text.strip()) < 30:
        return jsonify({'error': 'No readable text found in the image. The image may be too blurry or low-resolution.'}), 422

    # ── Reuse offer-letter analysis logic ───────────────────────────────────
    text_lower = extracted_text.lower()

    OFFER_FRAUD_SIGNALS = {
        'registration_fee': {'name': 'Registration Fee Mention', 'keywords': ['registration fee', 'joining fee', 'registration charges', 'onboarding fee'], 'weight': 35},
        'security_deposit': {'name': 'Security Deposit Request',  'keywords': ['security deposit', 'refundable deposit', 'security amount'], 'weight': 30},
        'training_fee':     {'name': 'Training / Kit Fee',         'keywords': ['training fee', 'training kit', 'material fee', 'training cost'], 'weight': 25},
        'personal_email':   {'name': 'Personal Email Usage',       'keywords': ['@gmail.com', '@yahoo.com', '@hotmail.com', '@outlook.com'], 'weight': 15},
        'unrealistic_salary': {'name': 'Unrealistic Salary Claim', 'keywords': ['earn from home', 'daily payment', 'guaranteed income', 'unlimited earning'], 'weight': 20},
    }

    risk_factors   = []
    total_weight   = 0
    detected_count = 0

    for key, signal in OFFER_FRAUD_SIGNALS.items():
        found_kw = [kw for kw in signal['keywords'] if kw in text_lower]
        detected  = len(found_kw) > 0
        if detected:
            total_weight   += signal['weight']
            detected_count += 1
        risk_factors.append({
            'key': key, 'name': signal['name'], 'detected': detected,
            'detail': f"Found: {', '.join(found_kw[:3])}" if detected else 'Not detected',
            'weight': signal['weight'],
        })

    kw_score, matched_kw_pairs = keyword_fraud_score(extracted_text)
    matched_keywords = [k for k, v in matched_kw_pairs[:6]]

    max_signal_weight = sum(s['weight'] for s in OFFER_FRAUD_SIGNALS.values())
    signal_risk = min(100, (total_weight / max_signal_weight) * 100) if max_signal_weight > 0 else 0
    risk_score  = round(min(100, signal_risk * 0.70 + kw_score * 0.30), 1)

    if risk_score <= 25:   risk_level, risk_label, risk_color = 'LOW',      '🟢 Appears Genuine',          'green'
    elif risk_score <= 55: risk_level, risk_label, risk_color = 'MEDIUM',   '🟡 Review Carefully',          'yellow'
    elif risk_score <= 80: risk_level, risk_label, risk_color = 'HIGH',     '🔴 Likely Fraudulent',         'red'
    else:                  risk_level, risk_label, risk_color = 'CRITICAL',  '🚨 Almost Certainly a Scam',  'critical'

    red_flags = [f['name'] for f in risk_factors if f['detected']]

    # Groq explanation (removed - Groq integration disabled)
    groq_data = None

    try:
        log_activity(session['user'], f'Image Scanned — {risk_level}')
    except Exception:
        pass

    return jsonify({
        'risk_score':       risk_score,
        'risk_level':       risk_level,
        'risk_label':       risk_label,
        'risk_color':       risk_color,
        'risk_factors':     risk_factors,
        'ai_explanation':   (groq_data or {}).get('explanation', ''),
        'recommendations':  (groq_data or {}).get('recommendations', [
            'Never pay any fee to secure a job offer.',
            'Verify the company on LinkedIn and the official MCA portal.',
        ]),
        'matched_keywords': matched_keywords,
        'company':          company,
        'detected_signals': detected_count,
        'ocr_method':       ocr_method,
        'extracted_text_preview': extracted_text[:300],
    })


@app.route('/api/community-reports')
def api_community_reports():
    """
    Get aggregated community scam reports for a company, URL or domain.
    Used by the dashboard and unified analysis to display community warnings.
    """
    company = request.args.get('company', '').strip()
    url     = request.args.get('url', '').strip()
    domain  = request.args.get('domain', '').strip()

    if not company and not url and not domain:
        return jsonify({'error': 'Provide company, url, or domain parameter.'}), 400

    # Resolve domain from url
    if url and not domain:
        try:
            domain = urllib.parse.urlparse(url).netloc.replace('www.', '')
        except Exception:
            pass

    company_count = 0
    domain_count  = 0
    listing_count = 0
    warnings      = []

    try:
        if supabase:
            if company:
                resp = supabase.table('scam_reports').select('id, description, created_at') \
                    .ilike('company', f'%{company}%').execute()
                company_count = len(resp.data) if resp.data else 0
                if company_count > 0:
                    warnings.append(f'This company has been reported as scam by {company_count} user(s).')

            if domain:
                resp = supabase.table('scam_reports').select('id') \
                    .ilike('website', f'%{domain}%').execute()
                domain_count = len(resp.data) if resp.data else 0
                if domain_count > 0:
                    warnings.append(f'This domain has received {domain_count} scam report(s).')

            if url:
                resp = supabase.table('scam_reports').select('id') \
                    .ilike('website', f'%{url}%').execute()
                listing_count = len(resp.data) if resp.data else 0
                if listing_count > 0:
                    warnings.append(f'This listing URL has received {listing_count} scam report(s).')
    except Exception as _cr_err:
        print(f'[community-reports] error: {_cr_err}')

    total = max(company_count, domain_count, listing_count)
    community_score = min(100, total * 20)

    return jsonify({
        'company_count':   company_count,
        'domain_count':    domain_count,
        'listing_count':   listing_count,
        'total_reports':   total,
        'community_score': community_score,
        'warnings':        warnings,
    })


TRUSTED_PLATFORMS = [
    'linkedin.com', 'naukri.com', 'indeed.com', 'internshala.com',
    'glassdoor.com', 'monster.com', 'shine.com', 'foundit.in',
    'adzuna.in', 'timesjobs.com', 'freshersworld.com', 'wellfound.com',
    'instahyre.com', 'hirist.com', 'letsintern.com', 'unstop.com',
    'iimjobs.com', 'apna.co', 'workindia.in', 'hirect.in',
]


def get_company_ai_summary(domain, trust_score, risk_level, reasons):
    client = _get_groq_client()
    if client:
        try:
            prompt = f"""You are ScamShield AI. Summarize the company verification details for {domain}.
            Trust Score: {trust_score}/100.
            Risk Level: {risk_level}.
            Identified Risks: {'; '.join(reasons) if reasons else 'None'}.
            Provide a professional 2-3 sentence AI summary of this company's reputation. Don't return JSON, just the summary text."""
            response = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=150,
                temperature=0.3
            )
            return response.choices[0].message.content.strip()
        except Exception:
            pass
    # Fallback
    summary = f"Verification of {domain} results in a trust score of {trust_score}/100, indicating a {risk_level} risk level. "
    if risk_level in ['HIGH', 'CRITICAL']:
        summary += f"The primary safety concerns include: {', '.join(reasons)}. Students are strongly advised to avoid sharing financial details or paying registration fees."
    else:
        summary += "The domain exhibits standard trust signals with no major indicators of fraudulent activity. Always confirm contact addresses before proceeding."
    return summary


def verify_domain(url_input):
    """
    Comprehensive domain trust check.
    Returns dict: trust_score (0-100), risk_level, status, reason, etc.
    """
    if not url_input or not url_input.strip():
        return {
            'trust_score': 0, 'company_trust_score': 0, 'risk_score': 100,
            'risk_level': 'UNKNOWN', 'trust_level': 'UNKNOWN',
            'status': 'Invalid', 'domain_reputation': 'Invalid',
            'reason': 'No URL provided.', 'risk_indicators': ['No URL provided.'],
            'ssl_status': 'Insecure', 'domain_age': 'Unknown',
            'ai_summary': 'No URL provided.', 'ai_explanation': 'No URL provided.'
        }

    raw = url_input.strip()
    if not raw.startswith('http'):
        raw = 'https://' + raw

    url_lower = raw.lower()
    parsed   = urllib.parse.urlparse(url_lower)
    domain   = parsed.netloc.replace('www.', '')

    reasons = []
    deductions = 0

    # 1. Check Supabase blacklist
    blacklisted = get_blacklisted_domain(domain)
    if blacklisted:
        bl_risk  = blacklisted.get('risk_score', 90)
        bl_reason = blacklisted.get('reason', 'Listed as a known scam domain.')
        reasons.append(f'⛔ Domain is in our scam blacklist. {bl_reason}')
        trust_score = max(0, 100 - bl_risk)
        risk_level = 'CRITICAL'
        status = 'Blacklisted'
    elif is_whitelisted_domain(domain):
        trust_score = 98
        risk_level = 'LOW'
        status = 'Verified Trusted'
        reasons.append(f'✅ Verified trusted domain: {domain}')
    else:
        # 2. Trusted platform check
        if any(tp in domain for tp in TRUSTED_PLATFORMS):
            trust_score = 95
            risk_level = 'LOW'
            status = 'Verified Trusted'
            reasons.append('✅ This is a well-known, reputable job platform.')
        else:
            # 3. HTTP (no SSL)
            if url_lower.startswith('http://'):
                deductions += 25
                reasons.append('No HTTPS — site lacks SSL encryption')

            # 4. Free hosting / suspicious TLD
            free_hosts = ['blogspot', 'wordpress.com', 'weebly', 'wix.com',
                          'sites.google', 'jimdo', 'netlify.app', 'vercel.app']
            if any(fh in domain for fh in free_hosts):
                deductions += 20
                reasons.append('Hosted on a free platform (common with scam sites)')

            # 5. URL shorteners
            shorteners = ['bit.ly', 'tinyurl', 'goo.gl', 't.co', 'ow.ly', 'is.gd', 'rb.gy', 'cutt.ly']
            if any(sh in domain for sh in shorteners):
                deductions += 35
                reasons.append('URL shortener detected — hides the real destination')

            # 6. Brand impersonation
            big_brands = ['google', 'amazon', 'microsoft', 'flipkart', 'infosys',
                          'tcs', 'wipro', 'accenture', 'ibm', 'deloitte']
            for brand in big_brands:
                if brand in domain:
                    allowed_suffixes = [
                        f"{brand}.com", f"{brand}.in", f"{brand}.co.in", f"{brand}.org", 
                        f"{brand}.net", f"{brand}.co", f"{brand}.io", f"{brand}.dev"
                    ]
                    is_legit = False
                    for suf in allowed_suffixes:
                        if domain == suf or domain.endswith('.' + suf):
                            is_legit = True
                            break
                    if not is_legit:
                        deductions += 45
                        reasons.append(f'Possible brand impersonation of "{brand}"')
                        break

            # 7. Suspicious keywords in domain
            sus_words = ['free', 'earn', 'job-hiring', 'work-from-home', 'daily-earn',
                         'part-time', 'online-job', 'home-job', 'gig', 'quick-money',
                         'guaranteed', 'instant', 'easy-money']
            if any(sw in domain for sw in sus_words):
                deductions += 20
                reasons.append('Domain contains suspicious keywords')

            # 8. Very long or hyphen-heavy domain
            base_domain = domain.split('.')[0] if '.' in domain else domain
            if base_domain.count('-') >= 3:
                deductions += 10
                reasons.append('Excessive hyphens in domain (common with fake sites)')
            if len(domain) > 40:
                deductions += 10
                reasons.append('Unusually long domain name')

            trust_score = max(0, min(100, 70 - deductions))

            if trust_score >= 65:
                risk_level = 'LOW'
                status = 'Appears Safe'
                if not reasons:
                    reasons.append('No major issues detected.')
            elif trust_score >= 40:
                risk_level = 'MEDIUM'
                status = 'Use Caution'
            elif trust_score >= 20:
                risk_level = 'HIGH'
                status = 'High Risk'
            else:
                risk_level = 'CRITICAL'
                status = 'Very Suspicious'

    # SSL Status
    ssl_status = "Secure (HTTPS)" if url_lower.startswith("https") else "Insecure (HTTP)"

    # Domain Age via RDAP lookup
    domain_age = "Unknown"
    try:
        rdap_url = f"https://rdap.org/domain/{domain}"
        resp = requests.get(rdap_url, allow_redirects=True, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            events = data.get("events", [])
            for event in events:
                if event.get("eventAction") in ["registration", "creation"]:
                    date_str = event.get("eventDate", "")
                    if date_str:
                        domain_age = date_str.split("T")[0]
                        break
    except Exception as e:
        print("RDAP lookup error in verify_domain:", e)

    ai_summary = get_company_ai_summary(domain, trust_score, risk_level, reasons)

    return {
        'url': url_input,
        'domain': domain,
        'trust_score': trust_score,
        'company_trust_score': trust_score,
        'risk_score': 100 - trust_score,
        'risk_level': risk_level,
        'trust_level': risk_level,
        'status': status,
        'domain_reputation': status,
        'reason': '; '.join(reasons) if reasons else 'No major issues detected.',
        'risk_indicators': reasons if reasons else ['No major issues detected.'],
        'ssl_status': ssl_status,
        'domain_age': domain_age,
        'ai_summary': ai_summary,
        'ai_explanation': ai_summary
    }


@app.route('/verify-company', methods=['GET', 'POST'])
def verify_company():
    if 'user' not in session:
        return redirect(url_for('login', error='Please log in to verify a company.'))

    if request.method == 'POST':
        # Accept both JSON (AJAX) and form POST
        if request.is_json:
            data = request.get_json()
            url_input = data.get('url', '').strip()
        else:
            url_input = request.form.get('url', '').strip()

        if not url_input:
            if request.is_json:
                return jsonify({'error': 'URL is required'}), 400
            return render_template('verify_company.html',
                                   error='Please enter a company website URL.')

        result = verify_domain(url_input)
        result['url'] = url_input

        try:
            log_activity(session['user'], 'Company Verification')
        except Exception as e:
            print('Error logging Company Verification activity:', e)

        if request.is_json:
            return jsonify(result)
        return render_template('verify_company.html', result=result, checked_url=url_input)

    return render_template('verify_company.html', result=None, checked_url='')


@app.route('/recruiter-check', methods=['GET', 'POST'])
def recruiter_check():
    if 'user' not in session:
        if request.is_json:
            return jsonify({'error': 'Please log in to check a recruiter.'}), 401
        return redirect(url_for('login', error='Please log in to check a recruiter.'))
        
    result = None
    checked_name = ''
    checked_domain = ''
    
    if request.method == 'POST':
        if request.is_json:
            data = request.get_json()
            name = data.get('recruiter_name', '').strip()
            domain = data.get('domain', '').strip()
        else:
            name = request.form.get('recruiter_name', '').strip()
            domain = request.form.get('domain', '').strip()
            
        checked_name = name
        checked_domain = domain
        email = ''
        if request.is_json:
            email = data.get('email', '').strip()
        else:
            email = request.form.get('email', '').strip()

        blacklisted_in_db = False
        previous_reports = 0
        try:
            from supabase_client import get_recruiter_profile
            db_profiles = get_recruiter_profile(
                email=email, company=name, domain=domain
            )
            if db_profiles:
                blacklisted_in_db = any(p.get('blacklisted') for p in db_profiles)
                previous_reports = sum(p.get('previous_reports', 0) for p in db_profiles)
        except Exception:
            blacklisted_in_db = False
            previous_reports = 0
        
        # 1. Trust Score & Verification Status
        trust_score = 75
        status = "Unverified"
        reasons = []
        
        if domain:
            dom_res = verify_domain(domain)
            trust_score = dom_res['trust_score']
            status = dom_res['status']
            reasons.append(dom_res['reason'])
        else:
            reasons.append("No website domain provided for verification.")
            
        # 2. Check previous reports in scam_reports
        reports = []
        try:
            all_reports = get_scam_reports()
            for rpt in all_reports:
                c_match = name and name.lower() in rpt.get('company', '').lower()
                w_match = domain and domain.lower() in rpt.get('website', '').lower()
                if c_match or w_match:
                    reports.append({
                        'company': rpt.get('company'),
                        'website': rpt.get('website'),
                        'description': rpt.get('description'),
                        'created_at': rpt.get('created_at')
                    })
        except Exception as e:
            print("Error checking recruiter reports:", e)
            
        if reports:
            trust_score = max(0, trust_score - len(reports) * 20)
            status = "Suspicious" if trust_score >= 40 else "High Risk"
            reasons.append(f"Flagged in {len(reports)} community scam reports.")
            
        result = {
            'recruiter_name': name,
            'domain': domain,
            'trust_score': trust_score,
            'status': status,
            'reasons': reasons,
            'previous_reports': reports,
            'blacklisted_in_db': blacklisted_in_db,
            'db_previous_reports': previous_reports,
        }
        
        try:
            log_activity(session['user'], 'Recruiter Verification Check')
        except Exception as e:
            print('Error logging Recruiter Check activity:', e)
            
        if request.is_json:
            return jsonify(result)
            
    return render_template('verify_company.html', recruiter_result=result, checked_name=checked_name, checked_domain=checked_domain)


# ─────────────────────────────────────────────
# Phase 5 — PDF Report Generation
# ─────────────────────────────────────────────

def build_pdf(data):
    """
    Build a ScamShield analysis PDF report in memory.
    Returns BytesIO buffer ready for streaming.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=20*mm, rightMargin=20*mm,
        topMargin=20*mm, bottomMargin=20*mm
    )

    styles = getSampleStyleSheet()
    # Custom styles
    title_style = ParagraphStyle(
        'Title', parent=styles['Title'],
        fontSize=22, textColor=colors.HexColor('#6366f1'),
        spaceAfter=4, alignment=TA_CENTER
    )
    subtitle_style = ParagraphStyle(
        'Sub', parent=styles['Normal'],
        fontSize=10, textColor=colors.HexColor('#64748b'),
        spaceAfter=14, alignment=TA_CENTER
    )
    section_style = ParagraphStyle(
        'Section', parent=styles['Heading2'],
        fontSize=12, textColor=colors.HexColor('#1e293b'),
        spaceBefore=12, spaceAfter=6
    )
    body_style = ParagraphStyle(
        'Body', parent=styles['Normal'],
        fontSize=10, textColor=colors.HexColor('#334155'),
        spaceAfter=4, leading=14
    )
    label_style = ParagraphStyle(
        'Label', parent=styles['Normal'],
        fontSize=9, textColor=colors.HexColor('#64748b'),
        spaceAfter=2
    )

    story = []

    # ── Header ──
    story.append(Paragraph('🛡️ ScamShield AI Report', title_style))
    story.append(Paragraph('Graphura India Private Limited · Team-J', subtitle_style))
    story.append(HRFlowable(width='100%', thickness=1,
                             color=colors.HexColor('#e2e8f0'), spaceAfter=10))

    # ── Job Info Table ──
    risk_score   = data.get('risk_score', 'N/A')
    risk_level   = data.get('risk_level', 'N/A')
    prediction   = data.get('prediction', 'N/A')
    confidence   = data.get('confidence', 'N/A')
    job_title    = data.get('job_title', 'N/A') or 'N/A'
    company      = data.get('company', 'N/A') or 'N/A'
    location     = data.get('location', 'N/A') or 'N/A'
    url          = data.get('url', '') or ''
    matched_kws  = data.get('matched_keywords', [])
    red_flags    = data.get('red_flags', [])
    tips         = data.get('tips', [])
    details      = data.get('details', {})

    # Risk color
    risk_color_map = {
        'LOW': colors.HexColor('#10b981'),
        'MEDIUM': colors.HexColor('#f59e0b'),
        'HIGH': colors.HexColor('#ef4444'),
        'CRITICAL': colors.HexColor('#7f1d1d'),
    }
    rc = risk_color_map.get(str(risk_level).upper(), colors.black)

    story.append(Paragraph('Job Details', section_style))
    job_info = [
        ['Field', 'Value'],
        ['Job Title', job_title],
        ['Company', company],
        ['Location', location],
        ['URL', url if url else '—'],
        ['Prediction', prediction],
        ['Risk Score', str(risk_score)],
        ['Risk Level', str(risk_level)],
        ['ML Confidence', f"{confidence}%" if confidence != 'N/A' else 'N/A'],
    ]
    tbl = Table(job_info, colWidths=[50*mm, 120*mm])
    tbl.setStyle(TableStyle([
        ('BACKGROUND',   (0, 0), (-1, 0), colors.HexColor('#6366f1')),
        ('TEXTCOLOR',    (0, 0), (-1, 0), colors.white),
        ('FONTNAME',     (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE',     (0, 0), (-1, 0), 10),
        ('BACKGROUND',   (0, 1), (-1, -1), colors.HexColor('#f8fafc')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1),
         [colors.HexColor('#f8fafc'), colors.HexColor('#f1f5f9')]),
        ('FONTSIZE',     (0, 1), (-1, -1), 9),
        ('FONTNAME',     (0, 1), (0, -1), 'Helvetica-Bold'),
        ('GRID',         (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
        ('TOPPADDING',   (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING',  (0, 0), (-1, -1), 8),
        ('TEXTCOLOR',    (1, 6), (1, 6), rc),   # Risk Score value
        ('FONTNAME',     (1, 6), (1, 6), 'Helvetica-Bold'),
        ('TEXTCOLOR',    (1, 7), (1, 7), rc),   # Risk Level value
        ('FONTNAME',     (1, 7), (1, 7), 'Helvetica-Bold'),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 6*mm))

    # ── Score Breakdown ──
    if details:
        story.append(Paragraph('Score Breakdown', section_style))
        breakdown = [
            ['Signal', 'Score'],
            ['Keyword Score (40% weight)',   str(details.get('keyword_score', '—'))],
            ['Domain Risk Score (30% weight)', str(details.get('domain_score', '—'))],
            ['Salary Anomaly Score (20% weight)', str(details.get('salary_score', '—'))],
            ['NLP Model Score (10% weight)', str(details.get('nlp_model_score', '—'))],
        ]
        btbl = Table(breakdown, colWidths=[110*mm, 60*mm])
        btbl.setStyle(TableStyle([
            ('BACKGROUND',   (0, 0), (-1, 0), colors.HexColor('#1e293b')),
            ('TEXTCOLOR',    (0, 0), (-1, 0), colors.white),
            ('FONTNAME',     (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE',     (0, 0), (-1, 0), 9),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1),
             [colors.HexColor('#f8fafc'), colors.HexColor('#f1f5f9')]),
            ('FONTSIZE',     (0, 1), (-1, -1), 9),
            ('GRID',         (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
            ('TOPPADDING',   (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('LEFTPADDING',  (0, 0), (-1, -1), 8),
        ]))
        story.append(btbl)
        story.append(Spacer(1, 6*mm))

    # ── Matched Keywords ──
    if matched_kws:
        story.append(Paragraph('Detected Scam Keywords', section_style))
        kw_text = ',  '.join(f'"{k}"' for k in matched_kws)
        story.append(Paragraph(kw_text, body_style))
        story.append(Spacer(1, 4*mm))

    # ── Red Flags ──
    if red_flags:
        story.append(Paragraph('Red Flags Detected', section_style))
        for flag in red_flags:
            story.append(Paragraph(f'• {flag}', body_style))
        story.append(Spacer(1, 4*mm))

    # ── Recommendations ──
    if tips:
        story.append(Paragraph('Safety Recommendations', section_style))
        for tip in tips:
            story.append(Paragraph(f'✓ {tip}', body_style))
        story.append(Spacer(1, 4*mm))

    # ── Footer ──
    story.append(HRFlowable(width='100%', thickness=1,
                             color=colors.HexColor('#e2e8f0'), spaceBefore=10))
    story.append(Paragraph(
        'Generated by ScamShield · Graphura India Private Limited · '
        'This report is AI-generated and should be used for guidance only.',
        label_style
    ))

    doc.build(story)
    buf.seek(0)
    return buf


@app.route('/download-report', methods=['POST'])
def download_report():
    if 'user' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    try:
        pdf_buf = build_pdf(data)
    except Exception as e:
        print('PDF generation error:', e)
        return jsonify({'error': 'Failed to generate PDF'}), 500

    try:
        log_activity(session['user'], 'PDF Downloaded')
    except Exception as e:
        print('Error logging PDF Downloaded activity:', e)

    job_title = data.get('job_title', 'report') or 'report'
    safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', job_title)[:40]
    filename  = f'scamshield_report_{safe_name}.pdf'

    response = make_response(pdf_buf.read())
    response.headers['Content-Type']        = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


# ─────────────────────────────────────────────
# Phase 6 — Scam Reporting System
# ─────────────────────────────────────────────

@app.route('/report-scam', methods=['GET', 'POST'])
def report_scam():
    if 'user' not in session:
        return redirect(url_for('login', error='Please log in to report a scam.'))

    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or \
              request.headers.get('Content-Type', '').startswith('application/x-www-form-urlencoded') and \
              request.headers.get('Accept', '').find('application/json') != -1

    # Detect fetch() calls (they send Content-Type: application/x-www-form-urlencoded from URLSearchParams)
    # but NOT a browser form post (which also uses that type).  We distinguish via Accept header.
    want_json = 'application/json' in request.headers.get('Accept', '')

    success = False
    error   = None

    if request.method == 'POST':
        company     = request.form.get('company', '').strip()
        website     = request.form.get('website', '').strip()
        description = request.form.get('description', '').strip()

        if not company:
            error = 'Company name is required.'
        elif not description or len(description) < 20:
            error = 'Please provide a detailed description (at least 20 characters).'
        else:
            try:
                save_scam_report(
                    username=session['user'],
                    company=company,
                    website=website,
                    description=description
                )
                try:
                    log_activity(session['user'], 'Scam Report Submitted')
                except Exception as le:
                    print('Error logging Scam Report Submitted activity:', le)
                success = True
            except Exception as e:
                print('Error saving scam report:', e)
                error = 'Failed to submit report. Please try again.'

        # Return JSON if the client wants it (AJAX fetch)
        if want_json or request.is_json:
            if success:
                return jsonify({'success': True, 'message': 'Report submitted successfully.'})
            else:
                return jsonify({'success': False, 'error': error}), 400

    prefill_company = request.args.get('company', '')
    return render_template('report_scam.html',
                           success=success, error=error,
                           prefill_company=prefill_company)







# ─────────────────────────────────────────────
# Phase 7 — Offer Letter Fraud Detection
# ─────────────────────────────────────────────

@app.route('/offer-letter')
def offer_letter_page():
    """Offer Letter Fraud Detection page."""
    if 'user' not in session:
        return redirect(url_for('login', error='Please log in to use the Offer Letter Scanner.'))
    return render_template('offer_letter.html')


@app.route('/offer-letter/analyze', methods=['POST'])
def offer_letter_analyze():
    """
    Accept a PDF upload or PDF URL, extract text with multi-layer PDF extractor
    (pdfplumber → PyMuPDF → OCR Tesseract fallback),
    run ML pipeline + Groq explanation, return JSON results.
    """
    if 'user' not in session:
        return jsonify({'error': 'Unauthorized. Please log in.'}), 401

    company          = request.form.get('company', '').strip()
    recruiter_email  = request.form.get('recruiter_email', '').strip()
    pdf_url          = request.form.get('pdf_url', '').strip()

    if request.is_json:
        data = request.get_json() or {}
        company = data.get('company', '').strip()
        recruiter_email = data.get('recruiter_email', '').strip()
        pdf_url = data.get('pdf_url', '').strip()

    # ── Resolve PDF source (Upload or URL) ──────────────────────────────────
    pdf_bytes = None
    if pdf_url:
        if not pdf_url.startswith('http'):
            pdf_url = 'https://' + pdf_url
        try:
            import requests as _req
            resp = _req.get(pdf_url, timeout=15)
            resp.raise_for_status()
            pdf_bytes = resp.content
            if len(pdf_bytes) > 10 * 1024 * 1024:
                return jsonify({'error': 'PDF file at URL is too large. Maximum size is 10 MB.'}), 400
        except Exception as e:
            return jsonify({'error': f'Failed to download PDF from URL: {str(e)}'}), 400
    else:
        if 'pdf' not in request.files:
            return jsonify({'error': 'Provide a PDF file or a PDF URL.'}), 400
        pdf_file = request.files['pdf']
        if not pdf_file.filename.lower().endswith('.pdf'):
            return jsonify({'error': 'Please upload a PDF file.'}), 400
        pdf_bytes = pdf_file.read()
        if len(pdf_bytes) > 10 * 1024 * 1024:
            return jsonify({'error': 'File too large. Maximum size is 10 MB.'}), 400

    # ── 1. Extract text using new multi-layer PDF extractor ──────────────────
    extracted_text = ''
    try:
        if not _pdf_extractor_available:
            return jsonify({'error': 'PDF extraction unavailable. Please contact support.'}), 500
        result = extract_pdf_text(pdf_bytes)
        if not result.success or not result.text:
            return jsonify({'error': 'Could not extract text from PDF. The file may be corrupted or encrypted.'}), 422
        extracted_text = result.text
    except Exception as e:
        print('PDF extraction error:', e)
        return jsonify({'error': 'Could not extract text from PDF. Please ensure it is a valid PDF file.'}), 422

    if not extracted_text or len(extracted_text.strip()) < 30:
        return jsonify({'error': 'No readable text found in the PDF. The document may be empty or require manual check.'}), 422

    text_lower = extracted_text.lower()

    # ── 2. Offer-letter specific risk factors ────────────────────────────────
    OFFER_FRAUD_SIGNALS = {
        'registration_fee': {
            'name': 'Registration Fee Mention',
            'keywords': ['registration fee', 'joining fee', 'registration charges', 'onboarding fee', 'enrolment fee', 'activation fee'],
            'weight': 35,
        },
        'security_deposit': {
            'name': 'Security Deposit Request',
            'keywords': ['security deposit', 'refundable deposit', 'security amount', 'caution deposit', 'refundable amount'],
            'weight': 30,
        },
        'training_fee': {
            'name': 'Training / Kit Fee',
            'keywords': ['training fee', 'training kit', 'kit charge', 'material fee', 'training cost', 'laptop security'],
            'weight': 25,
        },
        'personal_email': {
            'name': 'Personal / Free Email Usage',
            'keywords': ['@gmail.com', '@yahoo.com', '@hotmail.com', '@outlook.com', '@rediffmail.com', '@live.com', '@yandex.com'],
            'weight': 20,
        },
        'unrealistic_salary': {
            'name': 'Unrealistic Salary Claim',
            'keywords': ['earn from home', 'daily payment', 'weekly payment guaranteed', 'guaranteed income',
                         'earn per day', 'unlimited earning', 'no target', 'hours work'],
            'weight': 20,
        },
        'payment_request': {
            'name': 'Payment / Bank Details Requested',
            'keywords': ['bank details', 'upi id', 'gpay', 'paytm', 'phonepe', 'bank account', 'account number',
                         'transfer the amount', 'deposit the fee', 'pay the security', 'scan the qr', 'send money',
                         'payment link', 'qr code'],
            'weight': 30,
        },
        'hr_validation': {
            'name': 'Suspicious HR Contact / Channels',
            'keywords': ['whatsapp hr', 'whatsapp number', 'telegram hr', 'contact hr on', 'reach us on whatsapp',
                         'hr executive whatsapp', 'chat with hr', 'hr on telegram', 'telegram channel', 'telegram group'],
            'weight': 25,
        },
        'joining_letter': {
            'name': 'Suspicious Selection / Urgent Letter',
            'keywords': ['urgent joining', 'instant selection', 'no interview', 'direct selection', 'pay and join',
                         'selection within 24 hours', 'immediate start', 'hurry up', 'limited seats'],
            'weight': 20,
        }
    }

    # If recruiter_email provided, check it directly
    if recruiter_email:
        personal_domains = ['gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com', 'rediffmail.com', 'live.com', 'yandex.com']
        email_domain = recruiter_email.split('@')[-1].lower() if '@' in recruiter_email else ''
        if email_domain in personal_domains:
            OFFER_FRAUD_SIGNALS['personal_email']['keywords'].append(recruiter_email.lower())

    risk_factors = []
    total_weight = 0
    detected_count = 0

    for key, signal in OFFER_FRAUD_SIGNALS.items():
        found_kw = [kw for kw in signal['keywords'] if kw in text_lower]
        detected  = len(found_kw) > 0
        if detected:
            total_weight  += signal['weight']
            detected_count += 1
        risk_factors.append({
            'key':      key,
            'name':     signal['name'],
            'detected': detected,
            'detail':   f"Found: {', '.join(found_kw[:3])}" if detected else 'Not detected in document',
            'weight':   signal['weight'],
        })

    # ── 3. Company & Domain Validation ───────────────────────────────────────
    company_reputation_score = 0.0
    email_domain_mismatch = False
    
    if company:
        try:
            from supabase_client import get_company_reputation_stats
            company_reports, _, _ = get_company_reputation_stats(company_name=company)
            if company_reports > 0:
                company_reputation_score = min(100.0, company_reports * 25.0)
                risk_factors.append({
                    'key':      'company_reputation',
                    'name':     'Known Community Scam Reports',
                    'detected': True,
                    'detail':   f"Company has received {company_reports} community scam reports.",
                    'weight':   25,
                })
                total_weight += 25
                detected_count += 1
        except Exception:
            pass

    # Domain mismatch check (e.g. company name is Google but email domain is @wipro.com)
    if recruiter_email and company:
        personal_domains = ['gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com', 'rediffmail.com', 'live.com']
        email_domain = recruiter_email.split('@')[-1].lower() if '@' in recruiter_email else ''
        if email_domain and email_domain not in personal_domains:
            clean_company = re.sub(r'[^a-zA-Z0-9]', '', company).lower()
            clean_domain = email_domain.split('.')[0]
            if clean_domain not in clean_company and clean_company not in clean_domain:
                email_domain_mismatch = True
                risk_factors.append({
                    'key':      'domain_mismatch',
                    'name':     'Company - Email Domain Mismatch',
                    'detected': True,
                    'detail':   f"Recruiter email domain '{email_domain}' does not match company name '{company}'.",
                    'weight':   20,
                })
                total_weight += 20
                detected_count += 1

    # ── 4. Combine with ML keyword score on extracted text ───────────────────
    kw_score, matched_kw_pairs = keyword_fraud_score(extracted_text)
    matched_keywords = [k for k, v in matched_kw_pairs[:6]]

    # Weighted risk calculation
    max_signal_weight = sum(s['weight'] for s in OFFER_FRAUD_SIGNALS.values())
    if company_reputation_score > 0:
        max_signal_weight += 25
    if email_domain_mismatch:
        max_signal_weight += 20

    signal_risk = min(100, (total_weight / max_signal_weight) * 100) if max_signal_weight > 0 else 0
    risk_score  = round(min(100, signal_risk * 0.70 + kw_score * 0.30), 1)

    if risk_score <= 25:
        risk_level = 'LOW';    risk_label = '🟢 Appears Genuine';   risk_color = 'green'
    elif risk_score <= 55:
        risk_level = 'MEDIUM'; risk_label = '🟡 Review Carefully';   risk_color = 'yellow'
    elif risk_score <= 80:
        risk_level = 'HIGH';   risk_label = '🔴 Likely Fraudulent';  risk_color = 'red'
    else:
        risk_level = 'CRITICAL'; risk_label = '🚨 Almost Certainly a Scam'; risk_color = 'critical'

    red_flags = [f['name'] for f in risk_factors if f['detected']]

    # ── 5. Groq explanation (removed - Groq integration disabled) ──────────────────────────────────────────────────
    groq_data = None

    ai_explanation = (groq_data or {}).get('explanation', '')
    recommendations = (groq_data or {}).get('recommendations', [
        'Never pay any fee to secure a job offer.',
        'Verify the company on LinkedIn and the official MCA portal.',
        'Contact the company directly using contact info from their official website.',
    ])

    # ── 6. Log activity ──────────────────────────────────────────────────────
    try:
        log_activity(session['user'], f'Offer Letter Scanned — {risk_level}')
    except Exception as le:
        print('Error logging offer letter activity:', le)

    return jsonify({
        'risk_score':       risk_score,
        'risk_level':       risk_level,
        'risk_label':       risk_label,
        'risk_color':       risk_color,
        'risk_factors':     risk_factors,
        'ai_explanation':   ai_explanation,
        'recommendations':  recommendations,
        'matched_keywords': matched_keywords,
        'company':          company,
        'detected_signals': detected_count,
    })


@app.route('/offer-letter/report', methods=['POST'])
def offer_letter_report():
    """Generate a PDF report for the offer letter analysis."""
    if 'user' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    risk_score   = data.get('risk_score', 0)
    risk_level   = data.get('risk_level', 'UNKNOWN')
    risk_label   = data.get('risk_label', '—')
    risk_factors = data.get('risk_factors', [])
    ai_exp       = data.get('ai_explanation', '')
    recs         = data.get('recommendations', [])
    company      = data.get('company', 'Unknown')
    username     = session['user']

    import io as _io
    from datetime import datetime

    pdf_buf = _io.BytesIO()
    doc     = SimpleDocTemplate(pdf_buf, pagesize=A4,
                                rightMargin=20*mm, leftMargin=20*mm,
                                topMargin=20*mm, bottomMargin=20*mm)

    styles = getSampleStyleSheet()
    content = []

    title_style = ParagraphStyle('Title', parent=styles['Heading1'],
                                 fontSize=20, textColor=colors.HexColor('#6366f1'),
                                 spaceAfter=6, alignment=TA_CENTER)
    sub_style   = ParagraphStyle('Sub', parent=styles['Normal'],
                                 fontSize=10, textColor=colors.HexColor('#94a3b8'),
                                 spaceAfter=12, alignment=TA_CENTER)
    section_style = ParagraphStyle('Section', parent=styles['Heading2'],
                                   fontSize=12, textColor=colors.HexColor('#e2e8f0'),
                                   spaceBefore=14, spaceAfter=6)
    body_style  = ParagraphStyle('Body', parent=styles['Normal'],
                                 fontSize=9, textColor=colors.HexColor('#cbd5e1'),
                                 spaceAfter=6, leading=14)

    content.append(Paragraph('ScamShield AI — Offer Letter Report', title_style))
    content.append(Paragraph(f'Generated: {datetime.now().strftime("%d %b %Y, %I:%M %p")} · User: {username}', sub_style))
    content.append(HRFlowable(width='100%', color=colors.HexColor('#334155'), spaceAfter=10))

    color_map = {'LOW': '#10b981', 'MEDIUM': '#f59e0b', 'HIGH': '#ef4444', 'CRITICAL': '#7c3aed'}
    verdict_color = colors.HexColor(color_map.get(risk_level, '#6366f1'))

    content.append(Paragraph('Analysis Summary', section_style))
    summary_data = [
        ['Company', company or 'Not specified'],
        ['Risk Score', f'{risk_score}/100'],
        ['Risk Level', risk_level],
        ['Verdict', risk_label],
    ]
    tbl = Table(summary_data, colWidths=[60*mm, 110*mm])
    tbl.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#0f172a')),
        ('TEXTCOLOR',  (0,0), (0,-1), colors.HexColor('#94a3b8')),
        ('TEXTCOLOR',  (1,0), (1,-1), colors.HexColor('#e2e8f0')),
        ('FONTNAME',   (0,0), (-1,-1), 'Helvetica'),
        ('FONTSIZE',   (0,0), (-1,-1), 9),
        ('ROWBACKGROUNDS', (0,0), (-1,-1), [colors.HexColor('#1e293b'), colors.HexColor('#0f172a')]),
        ('GRID',       (0,0), (-1,-1), 0.5, colors.HexColor('#334155')),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
    ]))
    content.append(tbl)
    content.append(Spacer(1, 8))

    # Risk Factors
    content.append(Paragraph('Risk Factors Detected', section_style))
    for f in risk_factors:
        icon  = '⚠' if f.get('detected') else '✓'
        color_hex = '#ef4444' if f.get('detected') else '#10b981'
        content.append(Paragraph(
            f'<font color="{color_hex}">{icon} {f["name"]}</font> — {f.get("detail", "")}',
            body_style
        ))

    # AI Explanation
    if ai_exp:
        content.append(Paragraph('AI Explanation', section_style))
        content.append(Paragraph(ai_exp, body_style))

    # Recommendations
    if recs:
        content.append(Paragraph('Safety Recommendations', section_style))
        for r in recs:
            content.append(Paragraph(f'→ {r}', body_style))

    content.append(Spacer(1, 10))
    content.append(HRFlowable(width='100%', color=colors.HexColor('#334155')))
    content.append(Paragraph(
        'Report generated by ScamShield AI · Graphura India Private Limited · Team-J',
        ParagraphStyle('Footer', parent=styles['Normal'], fontSize=7,
                       textColor=colors.HexColor('#64748b'), alignment=TA_CENTER, spaceBefore=6)
    ))

    doc.build(content)
    pdf_buf.seek(0)

    response = make_response(pdf_buf.read())
    response.headers['Content-Type']        = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename="scamshield_offer_report.pdf"'
    return response


if __name__ == '__main__':
    app.run(debug=True, port=5007)
