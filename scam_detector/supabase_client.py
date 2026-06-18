from supabase import create_client
from dotenv import load_dotenv
import os

load_dotenv()

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_ANON_KEY")

print(f"[Startup] SUPABASE_URL = {supabase_url}")
print(f"[Startup] SUPABASE_KEY exists = {bool(supabase_key)}")

supabase = None
try:
    if not supabase_url or not supabase_key:
        raise ValueError(f"Missing Supabase credentials: URL={bool(supabase_url)}, KEY={bool(supabase_key)}")
    
    supabase = create_client(supabase_url, supabase_key)
    print("[Startup] ✓ Supabase client initialized successfully")
except Exception as e:
    print(f"[Startup] ⚠ Supabase initialization failed: {e}")
    print("[Startup] ⚠ Application will continue without Supabase")
    supabase = None

# ─────────────────────────────────────────────
# Analysis History (New Schema v2.0)
# ─────────────────────────────────────────────

def save_analysis(username, job_text, prediction, confidence, risk_score, risk_level, 
                  company='', job_title='', source_url='',
                  keyword_score=None, domain_score=None, salary_score=None,
                  application_method='', company_verified='',
                  **_ignored):
    """
    Save an analysis record matching Analysis_History schema.
    prediction stored as text: '0'=Legit, '1'=Suspicious, '2'=Scam
    """
    if not supabase:
        print(f"[Warning] Supabase unavailable: Analysis not saved for {username}")
        return None
    
    try:
        row = {
            "user_id": username,
            "job_text": job_text[:2000] if job_text else '',
            "prediction": str(prediction),
            "confidence": confidence,
            "risk_score": risk_score,
            "risk_level": risk_level,
            "company": company or '',
        }
        if job_title:
            row["job_title"] = str(job_title)[:500]
        if source_url:
            row["source_url"] = str(source_url)[:500]
        if keyword_score is not None:
            row["keyword_score"] = float(keyword_score)
        if domain_score is not None:
            row["domain_score"] = float(domain_score)
        if salary_score is not None:
            row["salary_score"] = float(salary_score)
        response = supabase.table("Analysis_History").insert(row).execute()
        return response
    except Exception as e:
        print(f"Error saving analysis: {e}")
        raise


def get_history(user_id):
    """Fetch analysis history for a specific user (legacy alias)."""
    if not supabase:
        print(f"[Warning] Supabase unavailable: Cannot fetch history for {user_id}")
        return []
    
    try:
        response = (
            supabase
            .table("Analysis_History")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        return response.data
    except Exception as e:
        print(f"Error fetching history: {e}")
        return []


def get_user_analyses(username):
    """Fetch all analyses belonging to the given username."""
    if not supabase:
        print(f"[Warning] Supabase unavailable: Cannot fetch analyses for {username}")
        return []
    
    try:
        response = (
            supabase
            .table("Analysis_History")
            .select("*")
            .eq("user_id", username)
            .order("created_at", desc=True)
            .execute()
        )
        return response.data
    except Exception as e:
        print(f"Error fetching user analyses: {e}")
        return []


def get_all_analyses(limit=None):
    """Fetch all analyses across all users (admin use)."""
    if not supabase:
        print("[Warning] Supabase unavailable: Cannot fetch all analyses")
        return []
    
    try:
        query = (
            supabase
            .table("Analysis_History")
            .select("*")
            .order("created_at", desc=True)
        )
        if limit:
            query = query.limit(limit)
        response = query.execute()
        return response.data
    except Exception as e:
        print(f"Error fetching all analyses: {e}")
        return []


# ─────────────────────────────────────────────
# Users
# ─────────────────────────────────────────────

def get_all_users():
    """Fetch all registered users (admin use). Excludes password hash."""
    if not supabase:
        print("[Warning] Supabase unavailable: Cannot fetch users")
        return []
    
    try:
        response = (
            supabase
            .table("users")
            .select("id, username, is_admin, created_at")
            .order("created_at", desc=True)
            .execute()
        )
        return response.data
    except Exception as e:
        print(f"Error fetching all users: {e}")
        return []


# ─────────────────────────────────────────────
# Activity Logs
# ─────────────────────────────────────────────

def log_activity(username, action):
    """Log a user action."""
    if not supabase:
        print(f"[Warning] Supabase unavailable: Activity not logged for {username}")
        return None
    
    try:
        response = (
            supabase
            .table("activity_logs")
            .insert({
                "username": username,
                "action": action
            })
            .execute()
        )
        return response.data
    except Exception as e:
        print(f"Error logging activity: {e}")
        raise


def get_activity_logs(username=None, limit=None):
    """
    Fetch activity logs.
    - If username is given, returns only that user's logs.
    - If limit is given, returns at most that many records.
    """
    query = (
        supabase
        .table("activity_logs")
        .select("*")
        .order("created_at", desc=True)
    )
    if username:
        query = query.eq("username", username)
    if limit:
        query = query.limit(limit)
    response = query.execute()
    return response.data


# ─────────────────────────────────────────────
# Blacklisted Domains  (Phase 4)
# ─────────────────────────────────────────────

def get_blacklisted_domain(domain):
    """
    Check if the given domain (or a containing string) exists in the
    blacklisted_domains table.  Returns the first matching record or None.

    Supabase does not support full ILIKE on foreign queries via the Python
    client's .like() method easily, so we fetch all records and filter
    in Python for safety and simplicity.
    """
    try:
        response = (
            supabase
            .table("blacklisted_domains")
            .select("*")
            .execute()
        )
        domain_lower = domain.lower()
        for record in response.data:
            stored = record.get("domain", "").lower()
            if stored and (stored in domain_lower or domain_lower in stored):
                return record
    except Exception as e:
        print("Error querying blacklisted_domains:", e)
    return None


# ─────────────────────────────────────────────
# Scam Reports  (Phase 6)
# ─────────────────────────────────────────────

def save_scam_report(username, company, website, description):
    """Save a community-submitted scam report."""
    response = (
        supabase
        .table("scam_reports")
        .insert({
            "username": username,
            "company": company,
            "website": website,
            "description": description
        })
        .execute()
    )
    return response.data


def get_scam_reports(limit=None):
    """Fetch scam reports (admin use), newest first."""
    if not supabase:
        print("[Warning] Supabase unavailable: Cannot fetch scam reports (admin)")
        return []
    
    query = (
        supabase
        .table("scam_reports")
        .select("*")
        .order("created_at", desc=True)
    )
    if limit:
        query = query.limit(limit)
    response = query.execute()
    return response.data


# ─────────────────────────────────────────────
# Platform Statistics  (Phase 3 — Live Stats)
# ─────────────────────────────────────────────

def get_platform_stats():
    """
    Return aggregate platform statistics for the landing page live counters.
    Returns dict: total_analyses, scams_detected, reports_submitted, total_users.
    """
    stats = {
        'total_analyses': 0,
        'scams_detected': 0,
        'reports_submitted': 0,
        'total_users': 0,
    }
    
    if not supabase:
        print("[Warning] Supabase unavailable: Returning empty platform stats")
        return stats
    
    try:
        analyses = supabase.table("Analysis_History").select("prediction").execute()
        stats['total_analyses'] = len(analyses.data)
        stats['scams_detected'] = sum(
            1 for a in analyses.data if str(a.get('prediction')) == '2'
        )
    except Exception as e:
        print("Error fetching analysis stats:", e)

    try:
        reports = supabase.table("scam_reports").select("id").execute()
        stats['reports_submitted'] = len(reports.data)
    except Exception as e:
        print("Error fetching reports stats:", e)

    try:
        users = supabase.table("users").select("id").execute()
        stats['total_users'] = len(users.data)
    except Exception as e:
        print("Error fetching user stats:", e)

    return stats


def get_recent_scam_reports_public(limit=10):
    """
    Fetch recent community scam reports for the public community feed.
    Excludes sensitive username info; shows company, website, partial description, date.
    """
    try:
        query = (
            supabase
            .table("scam_reports")
            .select("company, website, description, created_at")
            .order("created_at", desc=True)
            .limit(limit)
        )
        response = query.execute()
        return response.data
    except Exception as e:
        print("Error fetching public scam reports:", e)
        return []


# ─────────────────────────────────────────────
# Job Posts, Recruiter Profiles, Domain Reputation, Analytics
# ─────────────────────────────────────────────

def save_job_post(title, company, location, description, salary,
                  source_url, scam_score, risk_level, is_flagged,
                  skills='', domain_name=''):
    """Save analyzed job post to job_posts table."""
    if not supabase:
        return None
    try:
        data = {
            'title': str(title or '')[:500],
            'company_name': str(company or '')[:200],
            'location': str(location or '')[:200],
            'description': str(description or '')[:5000],
            'skills': str(skills or '')[:500],
            'salary': float(salary) if salary else None,
            'source_url': str(source_url or '')[:500],
            'domain_name': str(domain_name or '')[:200],
            'scam_score': float(scam_score or 0),
            'risk_level': str(risk_level or 'Unknown'),
            'is_flagged': bool(is_flagged),
        }
        resp = supabase.table('job_posts').insert(data).execute()
        return resp.data
    except Exception as e:
        print(f"[warn] save_job_post failed: {e}")
        return None


def get_recruiter_profile(email='', company='', domain=''):
    """Look up recruiter profile by email, company, or domain."""
    if not supabase:
        return []
    try:
        query = supabase.table('recruiter_profiles').select('*')
        if email:
            query = query.ilike('email', f'%{email}%')
        elif company:
            query = query.ilike('company', f'%{company}%')
        elif domain:
            query = query.ilike('domain_name', f'%{domain}%')
        resp = query.limit(5).execute()
        return resp.data or []
    except Exception as e:
        print(f"[warn] get_recruiter_profile failed: {e}")
        return []


def save_recruiter_profile(name, email, company, domain='',
                           linkedin_url='', verified=False):
    """Save or update recruiter profile."""
    if not supabase:
        return None
    try:
        data = {
            'recruiter_name': str(name or '')[:200],
            'email': str(email or '')[:200],
            'company': str(company or '')[:200],
            'domain_name': str(domain or '')[:200],
            'linkedin_url': str(linkedin_url or '')[:500],
            'verified': bool(verified),
        }
        resp = supabase.table('recruiter_profiles').insert(data).execute()
        return resp.data
    except Exception as e:
        print(f"[warn] save_recruiter_profile failed: {e}")
        return None


def get_domain_reputation(domain_name):
    """Get domain reputation from database."""
    if not supabase:
        return None
    try:
        resp = supabase.table('domain_reputation') \
            .select('*') \
            .eq('domain_name', domain_name.lower().strip()) \
            .limit(1) \
            .execute()
        return resp.data[0] if resp.data else None
    except Exception as e:
        print(f"[warn] get_domain_reputation failed: {e}")
        return None


def save_domain_reputation(domain_name, trust_score, blacklisted,
                           ssl_valid=True, domain_age_days=0):
    """Save or update domain reputation."""
    if not supabase:
        return None
    try:
        from datetime import datetime, timezone
        data = {
            'domain_name': domain_name.lower().strip(),
            'trust_score': float(trust_score),
            'blacklisted': bool(blacklisted),
            'ssl_valid': bool(ssl_valid),
            'domain_age_days': int(domain_age_days),
            'whois_checked_at': datetime.now(timezone.utc).isoformat(),
        }
        resp = supabase.table('domain_reputation') \
            .upsert(data, on_conflict='domain_name').execute()
        return resp.data
    except Exception as e:
        print(f"[warn] save_domain_reputation failed: {e}")
        return None


def get_flagged_keywords():
    """Fetch all flagged keywords from database."""
    if not supabase:
        return []
    try:
        resp = supabase.table('flagged_keywords') \
            .select('keyword, fraud_weight') \
            .order('fraud_weight', desc=True) \
            .execute()
        return resp.data or []
    except Exception as e:
        print(f"[warn] get_flagged_keywords failed: {e}")
        return []


def get_top_suspicious_companies(limit=10):
    """SQL analytics: top companies by average scam score."""
    if not supabase:
        return []
    try:
        from collections import defaultdict
        resp = supabase.table('job_posts') \
            .select('company_name, scam_score') \
            .order('scam_score', desc=True) \
            .limit(limit * 5) \
            .execute()
        if not resp.data:
            return []
        scores = defaultdict(list)
        for row in resp.data:
            if row.get('company_name'):
                scores[row['company_name']].append(row.get('scam_score', 0))
        result = [
            {'company_name': k, 'avg_score': round(sum(v) / len(v), 1),
             'count': len(v)}
            for k, v in scores.items()
        ]
        return sorted(result, key=lambda x: x['avg_score'], reverse=True)[:limit]
    except Exception as e:
        print(f"[warn] get_top_suspicious_companies failed: {e}")
        return []


def get_high_risk_domains(limit=10):
    """SQL analytics: domains with trust_score < 0.3."""
    if not supabase:
        return []
    try:
        resp = supabase.table('domain_reputation') \
            .select('domain_name, trust_score, blacklisted') \
            .lt('trust_score', 0.3) \
            .order('trust_score') \
            .limit(limit) \
            .execute()
        return resp.data or []
    except Exception as e:
        print(f"[warn] get_high_risk_domains failed: {e}")
        return []


def get_common_scam_keywords(limit=10):
    """SQL analytics: most weighted scam keywords."""
    if not supabase:
        return []
    try:
        resp = supabase.table('flagged_keywords') \
            .select('keyword, fraud_weight') \
            .order('fraud_weight', desc=True) \
            .limit(limit) \
            .execute()
        return resp.data or []
    except Exception as e:
        print(f"[warn] get_common_scam_keywords failed: {e}")
        return []


def save_company_reputation_report(company_name, domain, listing_url, report_reason, user_id):
    """
    Saves a scam listing reputation record to Supabase.
    Attempts to insert into 'company_reputation' table, falling back to 'scam_reports' if missing.
    """
    if not supabase:
        return None
    
    # Try inserting into company_reputation first
    try:
        data = {
            "company_name": company_name or "Unknown",
            "domain": domain or "",
            "listing_url": listing_url or "",
            "report_reason": report_reason or "Automated detection",
            "user_id": user_id or "system"
        }
        resp = supabase.table("company_reputation").insert(data).execute()
        return resp.data
    except Exception as e:
        print(f"[warn] Failed to insert into company_reputation, trying fallback to scam_reports: {e}")
        # Fallback to scam_reports
        try:
            fallback_data = {
                "username": user_id or "system",
                "company": company_name or "Unknown",
                "website": listing_url or domain or "",
                "description": report_reason or "Automated detection"
            }
            resp = supabase.table("scam_reports").insert(fallback_data).execute()
            return resp.data
        except Exception as fe:
            print(f"[error] Fallback to scam_reports also failed: {fe}")
            return None


def get_company_reputation_stats(company_name="", domain="", listing_url=""):
    """
    Fetch report counts from 'company_reputation' and 'scam_reports' for a company/domain/url.
    Returns: (company_count, domain_count, listing_count)
    """
    company_count = 0
    domain_count = 0
    listing_count = 0
    
    if not supabase:
        return 0, 0, 0

    # Clean inputs
    company_name = company_name.strip() if company_name else ""
    domain = domain.strip() if domain else ""
    listing_url = listing_url.strip() if listing_url else ""

    # Parse domain from URL if URL is given but domain isn't
    if listing_url and not domain:
        try:
            from urllib.parse import urlparse
            domain = urlparse(listing_url).netloc.replace("www.", "")
        except Exception:
            pass

    # Query new company_reputation table
    try:
        # 1. Company reports
        if company_name and company_name.lower() != 'unknown' and company_name != "":
            res = supabase.table("company_reputation").select("id").ilike("company_name", f"%{company_name}%").execute()
            company_count += len(res.data) if res.data else 0
        
        # 2. Domain reports
        if domain:
            res = supabase.table("company_reputation").select("id").ilike("domain", f"%{domain}%").execute()
            domain_count += len(res.data) if res.data else 0
            
        # 3. Listing URL reports
        if listing_url:
            res = supabase.table("company_reputation").select("id").ilike("listing_url", f"%{listing_url}%").execute()
            listing_count += len(res.data) if res.data else 0
    except Exception as e:
        print(f"[warn] Failed to query company_reputation stats: {e}")

    # Query existing scam_reports table for legacy/backup reports
    try:
        if company_name and company_name.lower() != 'unknown' and company_name != "":
            res = supabase.table("scam_reports").select("id").ilike("company", f"%{company_name}%").execute()
            company_count += len(res.data) if res.data else 0
            
        if domain:
            res = supabase.table("scam_reports").select("id").ilike("website", f"%{domain}%").execute()
            domain_count += len(res.data) if res.data else 0
            
        if listing_url:
            res = supabase.table("scam_reports").select("id").ilike("website", f"%{listing_url}%").execute()
            listing_count += len(res.data) if res.data else 0
    except Exception as e:
        print(f"[warn] Failed to query scam_reports stats: {e}")

    return company_count, domain_count, listing_count


# In-memory fallbacks if Supabase is offline or tables do not exist
_fallback_sessions = {}
_fallback_messages = {}

def create_chat_session(user_id, title="New Conversation"):
    import uuid
    from datetime import datetime
    session_id = str(uuid.uuid4())
    now_str = datetime.utcnow().isoformat()
    
    if supabase:
        try:
            resp = supabase.table("ai_chat_sessions").insert({
                "user_id": user_id,
                "title": title
            }).execute()
            if resp.data:
                return resp.data[0]
        except Exception as e:
            print(f"[warn] Failed to create_chat_session in Supabase: {e}. Falling back to memory.")
            
    sess = {
        "id": session_id,
        "user_id": user_id,
        "title": title,
        "created_at": now_str,
        "updated_at": now_str
    }
    _fallback_sessions[session_id] = sess
    _fallback_messages[session_id] = []
    return sess

def get_chat_sessions(user_id):
    if supabase:
        try:
            resp = supabase.table("ai_chat_sessions")\
                           .select("*")\
                           .eq("user_id", user_id)\
                           .order("updated_at", desc=True)\
                           .execute()
            if resp.data is not None:
                return resp.data
        except Exception as e:
            print(f"[warn] Failed to get_chat_sessions from Supabase: {e}. Falling back to memory.")
            
    return sorted(
        [s for s in _fallback_sessions.values() if s["user_id"] == user_id],
        key=lambda x: x["updated_at"],
        reverse=True
    )

def delete_chat_session(session_id):
    if supabase:
        try:
            supabase.table("ai_chat_sessions")\
                           .delete()\
                           .eq("id", session_id)\
                           .execute()
            return True
        except Exception as e:
            print(f"[warn] Failed to delete_chat_session in Supabase: {e}. Falling back to memory.")
            
    if session_id in _fallback_sessions:
        del _fallback_sessions[session_id]
    if session_id in _fallback_messages:
        del _fallback_messages[session_id]
    return True

def save_chat_message(session_id, role, content, documents=None):
    from datetime import datetime
    now_str = datetime.utcnow().isoformat()
    msg_data = {
        "session_id": session_id,
        "role": role,
        "content": content,
        "documents": documents or []
    }
    if supabase:
        try:
            resp = supabase.table("ai_chat_messages").insert(msg_data).execute()
            try:
                supabase.table("ai_chat_sessions")\
                        .update({"updated_at": now_str})\
                        .eq("id", session_id)\
                        .execute()
            except Exception:
                pass
            if resp.data:
                return resp.data[0]
        except Exception as e:
            print(f"[warn] Failed to save_chat_message in Supabase: {e}. Falling back to memory.")
            
    import uuid
    fallback_msg = {
        "id": str(uuid.uuid4()),
        "session_id": session_id,
        "role": role,
        "content": content,
        "documents": documents or [],
        "created_at": now_str
    }
    if session_id not in _fallback_messages:
        _fallback_messages[session_id] = []
    _fallback_messages[session_id].append(fallback_msg)
    
    if session_id in _fallback_sessions:
        _fallback_sessions[session_id]["updated_at"] = now_str
        
    return fallback_msg

def get_chat_messages(session_id):
    if supabase:
        try:
            resp = supabase.table("ai_chat_messages")\
                           .select("*")\
                           .eq("session_id", session_id)\
                           .order("created_at", desc=False)\
                           .execute()
            if resp.data is not None:
                return resp.data
        except Exception as e:
            print(f"[warn] Failed to get_chat_messages from Supabase: {e}. Falling back to memory.")
            
    return _fallback_messages.get(session_id, [])