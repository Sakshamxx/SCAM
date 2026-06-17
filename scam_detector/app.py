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
    get_platform_stats, get_recent_scam_reports_public
)
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.enums import TA_CENTER, TA_LEFT
try:
    from groq import Groq as GroqClient
    _groq_available = True
except ImportError:
    _groq_available = False

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

# ─────────────────────────────────────────────
# Groq AI Explanation Layer
# ─────────────────────────────────────────────
_groq_client = None

def _get_groq_client():
    """Lazy-load Groq client; return None if unavailable."""
    global _groq_client
    if not _groq_available:
        return None
    if _groq_client is None:
        api_key = os.getenv("GROQ_API_KEY", "").strip()
        if api_key:
            try:
                _groq_client = GroqClient(api_key=api_key)
            except Exception as e:
                print("Groq client init error:", e)
    return _groq_client


def get_groq_fallback_explanation(risk_score, risk_level, risk_label, red_flags, matched_keywords,
                                  job_title='', company='', details=None):
    """Generate fallback explanation if Groq unavailable."""
    if risk_level == 'Scam':
        explanation = f"This job listing for '{job_title}' at '{company}' exhibits high-risk indicators, with a risk score of {risk_score}/100. Specific anomalies such as flagged keywords ({', '.join(matched_keywords[:3]) if matched_keywords else 'none detected'}) warrant extreme caution."
        recruiter_assessment = "The recruiter credentials and contact methods match patterns commonly associated with employment scams."
        safety_advice = "DO NOT pay any fees or share sensitive personal documents (PAN/Aadhaar) with this recruiter."
        recommendations = [
            "Never pay any registration fee, training fee, or document charge to secure a job.",
            "Verify the recruiter's official company email rather than generic Gmail/WhatsApp.",
            "Cross-verify the job listing on the company's official careers portal.",
            "Refuse any requests for upfront bank account details or identity documents."
        ]
    elif risk_level == 'Suspicious':
        explanation = f"The job listing for '{job_title}' at '{company}' has a moderate risk score of {risk_score}/100. While not definitively fraudulent, it contains suspicious phrases or contact channels that require validation."
        recruiter_assessment = "The recruiter signals are mixed, showing unverified email domains or non-standard application procedures."
        safety_advice = "Verify the job posting and company credentials before continuing with the application."
        recommendations = [
            "Research the company's registration status and search for employee reviews online.",
            "Ask the recruiter for official corporate identification or an official email confirmation.",
            "Do not participate in instant hiring decisions without a formal interview process."
        ]
    else:
        explanation = f"The job listing for '{job_title}' at '{company}' displays very few risk indicators, scoring {risk_score}/100. The text pattern aligns with standard, legitimate hiring practices."
        recruiter_assessment = "The hiring contact signals appear consistent with standard corporate recruiting practices."
        safety_advice = "This job appears to be safe, but always verify before sharing personal information."
        recommendations = [
            "Review the official company website to understand their business operations.",
            "Keep all communication within secure and official channels.",
            "Read the job contract carefully before accepting the offer."
        ]
        
    return {
        "explanation": explanation,
        "recommendations": recommendations,
        "safety_advice": safety_advice,
        "recruiter_assessment": recruiter_assessment,
        "is_fallback": True
    }


def get_groq_explanation(risk_score, risk_level, risk_label, red_flags, matched_keywords,
                         job_title='', company='', details=None):
    """Call Groq LLM to generate explanation. ML model is source of truth."""
    client = _get_groq_client()
    if client is None:
        return get_groq_fallback_explanation(risk_score, risk_level, risk_label, red_flags, matched_keywords, job_title, company, details)

    details = details or {}
    kw_list = ', '.join(matched_keywords[:6]) if matched_keywords else 'None detected'
    flags_list = '\n'.join(f'- {f}' for f in red_flags) if red_flags else '- No major red flags'

    prompt = f"""You are ScamShield AI, an employment fraud intelligence assistant for Indian students.

A job posting has been analyzed by our ML fraud detection engine. Your role is ONLY to explain the results — do NOT change or override the classification.

Job Details:
- Title: {job_title or 'Unknown'}
- Company: {company or 'Unknown'}
- Risk Score: {risk_score}/100
- Risk Level: {risk_level}
- Verdict: {risk_label}
- Detected Scam Keywords: {kw_list}
- Red Flags:
{flags_list}

Provide your response as a JSON object with exactly these 4 keys:
1. "explanation": A 2-3 sentence plain-English explanation of WHY this job was flagged or deemed safe.
2. "recommendations": A list of 3-4 specific safety recommendations.
3. "safety_advice": One sentence of overall safety guidance.
4. "recruiter_assessment": A brief 1-sentence assessment of recruiter trustworthiness.

Respond ONLY with valid JSON. No extra text."""

    try:
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
            max_tokens=600,
        )
        raw = response.choices[0].message.content.strip()
        if '```' in raw:
            raw = re.sub(r'```(?:json)?', '', raw).replace('```', '').strip()
        import json
        return json.loads(raw)
    except Exception as e:
        print("Groq explanation error:", e)
        return get_groq_fallback_explanation(risk_score, risk_level, risk_label, red_flags, matched_keywords, job_title, company, details)
        recommendations = [
            "Research the company's registration status and search for employee reviews online.",
            "Ask the recruiter for official corporate identification or an official email confirmation.",
            "Do not participate in instant hiring decisions without a formal interview process."
        ]
    else:
        explanation = f"The job listing for '{job_title}' at '{company}' displays very few risk indicators, scoring {risk_score}/100. The text pattern and domain align with standard, legitimate hiring practices."
        recruiter_assessment = "The hiring contact signals appear consistent with standard corporate recruiting practices."
        safety_advice = "This job appears to be safe, but always verify before sharing personal information."
        recommendations = [
            "Review the official company website to understand their business operations.",
            "Keep all communication within secure and official channels.",
            "Read the job contract carefully before accepting the offer."
        ]
        
    return {
        "explanation": explanation,
        "recommendations": recommendations,
        "safety_advice": safety_advice,
        "recruiter_assessment": recruiter_assessment,
        "is_fallback": True
    }



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
scaler = load_model('scaler.pkl')
le_location = load_model('le_location.pkl')
le_title = load_model('le_title.pkl')

# Set other model placeholders to None to ensure compatibility and prevent loading
random_forest_model = None
xgboost_model = None
tfidf_vectorizer = None

# Encoders aliases for backwards compatibility
nlp_le_location = le_location
nlp_le_title = le_title

print("\n" + "=" * 50)
print("ScamShield v2.0 — Model Status")
print("=" * 50)
print(f"NLP Pipeline:     {'✅ Loaded' if nlp_pipeline else '❌ Missing'}")
print(f"Logistic Model:   {'✅ Loaded' if logistic_model else '❌ Missing'}")
print(f"Random Forest:    {'✅ Loaded' if random_forest_model else '❌ Missing'}")
print(f"Scaler:           {'✅ Loaded' if scaler else '❌ Missing'}")
print(f"LE Location:      {'✅ Loaded' if le_location else '❌ Missing'}")
print(f"LE Title:         {'✅ Loaded' if le_title else '❌ Missing'}")
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


def check_domain_risk(url):
    """Assign domain risk (0–100) based on URL patterns."""
    if not url or url.strip() == '':
        return 30.0

    url_lower = url.lower()
    suspicious_words = ['free', 'earn', 'job-hiring', 'work-from-home', 'daily-earn',
                        'part-time', 'online-job', 'home-job', 'gig', 'quick-money']
    trusted_domains = ['linkedin.com', 'naukri.com', 'indeed.com', 'internshala.com',
                       'glassdoor.com', 'monster.com', 'shine.com', 'foundit.in',
                       'adzuna.in', 'timesjobs.com', 'freshersworld.com']

    if any(td in url_lower for td in trusted_domains):
        return 10.0

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
    parsed = urllib.parse.urlparse(url_lower)
    domain = parsed.netloc
    for brand in big_brands:
        if brand in domain and not domain.startswith(brand + '.'):
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


@app.route('/awareness')
def awareness_page():
    return render_template('awareness.html')


@app.route('/community')
def community_page():
    recent_reports = []
    try:
        recent_reports = get_recent_scam_reports_public(limit=20)
    except Exception as e:
        print("Error fetching community reports:", e)
    return render_template('community.html', recent_reports=recent_reports)


@app.route('/threat-intel')
def threat_intel_page():
    scam_reports = []
    try:
        scam_reports = get_scam_reports(limit=10)
    except Exception as e:
        print("Error fetching threat intel data:", e)
    return render_template('threat_intel.html', scam_reports=scam_reports)


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
        prediction = int(np.argmax(combined_proba))

        # Map prediction to risk level and labels
        prediction_map = {0: 'Legit', 1: 'Suspicious', 2: 'Scam'}
        risk_level = prediction_map.get(prediction, 'Legit')

        # Calibrate risk score based on the predicted class range
        risk_score_raw = combined_proba[1] * 50 + combined_proba[2] * 100
        if risk_level == 'Legit':
            risk_score = min(30.0, risk_score_raw)
            risk_label = '🟢 Likely Genuine'
        elif risk_level == 'Suspicious':
            risk_score = max(31.0, min(60.0, risk_score_raw))
            risk_label = '🟡 Suspicious'
        else:
            risk_score = max(61.0, risk_score_raw)
            risk_label = '🔴 Probable Scam'

        # Skills signal nudge (5% weight, additive, capped so it never flips risk level alone)
        skills_nudge = skills_fraud_score * 0.05
        risk_score   = round(min(100, risk_score + skills_nudge), 1)
        confidence = round(float(combined_proba[prediction] * 100), 1)

        # Build details dictionary for front-end compatibility
        details = {
            'keyword_score': round(kw_score, 1),
            'domain_score': round(domain_score, 1),
            'salary_score': round(salary_score, 1),
            'report_score': round(report_score, 1),
            'nlp_model_score': round((nlp_proba[1] * 50 + nlp_proba[2] * 100), 1),
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
                domain_name=url.split('/')[2] if url and '/' in url else ''
            )
        except Exception as _jp_err:
            print(f"[warn] job_posts save: {_jp_err}")

        try:
            action = "Analyzed Scam Job" if prediction == 2 else "Analyzed Job"
            log_activity(username, action)
        except Exception as e:
            print(f"Error logging activity: {e}")

        # Groq explanation
        groq_data = None
        try:
            groq_data = get_groq_explanation(
                risk_score=risk_score,
                risk_level=risk_level,
                risk_label=risk_label,
                red_flags=red_flags,
                matched_keywords=details.get('matched_keywords', []),
                job_title=job_title,
                company=company,
                details=details
            )
        except Exception as e:
            print(f"Groq explanation error: {e}")

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
                if brand in domain and not domain.startswith(brand + '.'):
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
    Accept a PDF upload, extract text with multi-layer PDF extractor
    (pdfplumber → PyMuPDF → OCR Tesseract fallback),
    run ML pipeline + Groq explanation, return JSON results.
    """
    if 'user' not in session:
        return jsonify({'error': 'Unauthorized. Please log in.'}), 401

    if 'pdf' not in request.files:
        return jsonify({'error': 'No PDF file uploaded.'}), 400

    pdf_file = request.files['pdf']
    if not pdf_file.filename.lower().endswith('.pdf'):
        return jsonify({'error': 'Please upload a PDF file.'}), 400

    # Read file bytes and enforce 5 MB limit
    pdf_bytes = pdf_file.read()
    if len(pdf_bytes) > 5 * 1024 * 1024:
        return jsonify({'error': 'File too large. Maximum size is 5 MB.'}), 400

    company          = request.form.get('company', '').strip()
    recruiter_email  = request.form.get('recruiter_email', '').strip()

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

    if not extracted_text or len(extracted_text.strip()) < 50:
        return jsonify({'error': 'No readable text found in the PDF. The document may be corrupted or empty.'}), 422

    text_lower = extracted_text.lower()

    # ── 2. Offer-letter specific risk factors ────────────────────────────────
    OFFER_FRAUD_SIGNALS = {
        'registration_fee': {
            'name': 'Registration Fee Mention',
            'keywords': ['registration fee', 'joining fee', 'registration charges', 'onboarding fee', 'enrolment fee'],
            'weight': 35,
        },
        'security_deposit': {
            'name': 'Security Deposit Request',
            'keywords': ['security deposit', 'refundable deposit', 'security amount', 'caution deposit'],
            'weight': 30,
        },
        'training_fee': {
            'name': 'Training / Kit Fee',
            'keywords': ['training fee', 'training kit', 'kit charge', 'material fee', 'training cost'],
            'weight': 25,
        },
        'personal_email': {
            'name': 'Personal Email Usage',
            'keywords': ['@gmail.com', '@yahoo.com', '@hotmail.com', '@outlook.com', '@rediffmail.com'],
            'weight': 15,
        },
        'unrealistic_salary': {
            'name': 'Unrealistic Salary Claim',
            'keywords': ['earn from home', 'daily payment', 'weekly payment guaranteed', 'guaranteed income',
                         'earn per day', 'unlimited earning'],
            'weight': 20,
        },
    }

    # If recruiter_email provided, check it directly
    if recruiter_email:
        personal_domains = ['gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com', 'rediffmail.com']
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

    # ── 3. Combine with ML keyword score on extracted text ───────────────────
    kw_score, matched_kw_pairs = keyword_fraud_score(extracted_text)
    matched_keywords = [k for k, v in matched_kw_pairs[:6]]

    # Weighted risk: offer signals (70%) + keyword ML (30%)
    max_signal_weight = sum(s['weight'] for s in OFFER_FRAUD_SIGNALS.values())
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

    # ── 4. Groq explanation ──────────────────────────────────────────────────
    groq_data = None
    try:
        groq_data = get_groq_explanation(
            risk_score=risk_score,
            risk_level=risk_level,
            risk_label=risk_label,
            red_flags=red_flags,
            matched_keywords=matched_keywords,
            job_title='Offer Letter',
            company=company or 'Unknown',
            details={
                'keyword_score': round(kw_score, 1),
                'domain_score': 0,
                'salary_score': 0,
                'nlp_model_score': 0,
            }
        )
    except Exception as e:
        print('Groq offer letter error:', e)

    ai_explanation = (groq_data or {}).get('explanation', '')
    recommendations = (groq_data or {}).get('recommendations', [
        'Never pay any fee to secure a job offer.',
        'Verify the company on LinkedIn and the official MCA portal.',
        'Contact the company directly using contact info from their official website.',
    ])

    # ── 5. Log activity ──────────────────────────────────────────────────────
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
    app.run(debug=True, port=5001)
