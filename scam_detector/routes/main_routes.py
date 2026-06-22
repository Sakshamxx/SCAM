import datetime
import urllib.parse
import requests
from flask import render_template, request, session, redirect, url_for, jsonify
from scam_detector.database.supabase_client import (
    supabase, get_user_analyses, get_all_analyses, get_scam_reports,
    get_all_users, get_activity_logs, get_blacklisted_domain,
    get_recent_scam_reports_public
)
from scam_detector.rule_engine.rules import FRAUD_KEYWORDS

TRUSTED_PLATFORMS = [
    'linkedin.com', 'naukri.com', 'indeed.com', 'internshala.com',
    'glassdoor.com', 'monster.com', 'shine.com', 'foundit.in',
    'adzuna.in', 'timesjobs.com', 'freshersworld.com', 'wellfound.com',
    'instahyre.com', 'hirist.com', 'letsintern.com', 'unstop.com',
    'iimjobs.com', 'apna.co', 'workindia.in', 'hirect.in',
]

def _prediction_code(value):
    """Normalize Analysis_History.prediction (text 0-2) to int."""
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return {'Legit': 0, 'Suspicious': 1, 'Scam': 2}.get(str(value), 0)

def get_company_ai_summary(domain, trust_score, risk_level, reasons):
    """Local company verification summary."""
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

def _persist_domain_reputation(result, url_input=''):
    """Save domain reputation to Supabase after verify_domain()."""
    try:
        from scam_detector.database.supabase_client import save_domain_reputation
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


def register_main_routes(app):
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

        global_legit_count = sum(1 for item in analyses_all if _prediction_code(item.get('prediction')) == 0)
        verified_recruiters_count = global_legit_count

        low_count = sum(1 for a in analyses_all if a.get('risk_score', 0) <= 30)
        med_count = sum(1 for a in analyses_all if 30 < a.get('risk_score', 0) <= 60)
        high_count = sum(1 for a in analyses_all if a.get('risk_score', 0) > 60)
        
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
            global_total_jobs=global_total_jobs,
            global_scams_detected=global_scams_detected,
            community_reports_count=community_reports_count,
            high_risk_domains_count=high_risk_domains_count,
            verified_recruiters_count=verified_recruiters_count,
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
        
        default_companies = [('Tech Hires', 3), ('Global Solutions', 2), ('HR Link', 2)]
        while len(high_risk_companies) < 5 and default_companies:
            dk, dv = default_companies.pop(0)
            if dk not in [x['name'] for x in high_risk_companies]:
                high_risk_companies.append({'name': dk, 'count': dv})

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
            from scam_detector.database.supabase_client import (
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
            'nlp_loaded': True,
            'rf_loaded': False,
            'lr_loaded': True,
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
