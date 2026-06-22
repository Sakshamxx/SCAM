import re
from database.supabase_client import supabase

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
