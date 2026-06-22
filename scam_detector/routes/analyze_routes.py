import urllib.parse
from flask import request, jsonify, session
import numpy as np

# Import database functions
from scam_detector.database.supabase_client import (
    supabase, save_analysis, get_company_reputation_stats,
    save_company_reputation_report, save_job_post, log_activity,
    get_platform_stats
)

# Import rules
from scam_detector.rule_engine.rules import keyword_fraud_score, check_salary_anomaly, get_user_report_score

# Import domain intelligence
try:
    from scam_detector.domain_intelligence.domain_intelligence import (
        compute_domain_intelligence_score,
        get_domain_intelligence_details
    )
    _domain_intelligence_available = True
except ImportError:
    _domain_intelligence_available = False

# Import local explanation
from scam_detector.services.explanation_service import get_local_explanation

# Import ML model inference and helpers
from scam_detector.services.model_service import (
    nlp_model, ml_model, tfidf_vec, trigram_vec, label_encoder, feature_config,
    le_location, le_title, nlp_pipeline, logistic_model, scaler,
    run_new_model_inference, normalize_text, parse_experience, parse_salary,
    safe_encode, check_domain_risk
)

# Import scrapers and utilities
try:
    from scam_detector.utils.scraper import scrape_job
    _new_scraper_available = True
except ImportError:
    _new_scraper_available = False
    scrape_job = None

try:
    from scam_detector.utils.html_cleaner import clean_html_description
    _html_cleaner_available = True
except ImportError:
    _html_cleaner_available = False

try:
    from scam_detector.utils.scamshield_scraper import (
        validate_url as ss_validate_url,
        scrape_url as ss_scrape_url,
        analyze_url as ss_analyze_url,
        compute_trust as ss_compute_trust,
        get_recommendation as ss_get_recommendation,
        extract_text_from_pdf as ss_extract_pdf,
        extract_text_from_image as ss_extract_image
    )
    _ss_scraper_available = True
except ImportError:
    _ss_scraper_available = False


def register_analyze_routes(app):
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

            # Normalize text and combine
            normalized_job = normalize_text(job_title)
            normalized_description = normalize_text(description)
            normalized_skills = str(skills).strip()
            combined_text = f"{normalized_job} {normalized_description} {normalized_skills}"

            # Get NLP predictions and probabilities
            print(f'[analyze] nlp_pipeline type: {type(nlp_pipeline).__name__ if nlp_pipeline is not None else "None"}')
            print(f'[analyze] nlp_model type:    {type(nlp_model).__name__ if nlp_model is not None else "None"}')
            print(f'[analyze] ml_model type:     {type(ml_model).__name__ if ml_model is not None else "None"}')
            print(f'[analyze] tfidf_vec type:    {type(tfidf_vec).__name__ if tfidf_vec is not None else "None"}')
            print(f'[analyze] trigram_vec type:  {type(trigram_vec).__name__ if trigram_vec is not None else "None"}')
            print(f'[analyze] le_location type:  {type(le_location).__name__ if le_location is not None else "None"}')
            print(f'[analyze] le_title type:     {type(le_title).__name__ if le_title is not None else "None"}')

            if nlp_pipeline is not None:
                try:
                    print(f'[analyze] Running nlp_pipeline.predict on combined_text len={len(combined_text)}')
                    nlp_pred = nlp_pipeline.predict([combined_text])[0]
                    print(f'[analyze] nlp_pred={nlp_pred} type={type(nlp_pred).__name__}')
                    nlp_proba = nlp_pipeline.predict_proba([combined_text])[0]
                    print(f'[analyze] nlp_proba={nlp_proba}')
                except Exception as e:
                    import traceback as _tb
                    print(f'[analyze] nlp_pipeline prediction failed:')
                    _tb.print_exc()
                    nlp_pred = 0
                    nlp_proba = np.array([1.0, 0.0, 0.0])
            else:
                nlp_pred = 0
                nlp_proba = np.array([1.0, 0.0, 0.0])

            # Heuristics for UI details & component scores
            kw_score, matched_kw = keyword_fraud_score(combined_text)

            # Skills-based fraud signal
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

            # Community reputation
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

            # NEW MODEL INFERENCE
            nlp_score_component, ml_score_component = run_new_model_inference(
                job_text=description,
                job_title=job_title,
                skills=skills
            )

            # Fallback to legacy NLP pipeline
            if nlp_score_component == 0.0 and nlp_pipeline is not None:
                try:
                    nlp_proba_legacy = nlp_pipeline.predict_proba([combined_text])[0]
                    nlp_score_component = round(min(100.0, nlp_proba_legacy[1] * 50 + nlp_proba_legacy[2] * 100), 1)
                except Exception:
                    pass

            # Legacy structured ML fallback
            if ml_score_component == 0.0:
                salary_numeric = parse_salary(salary)
                experience_val = parse_experience(data.get('experience', ''))
                kw_count = len(matched_kw)
                desc_len = len(normalized_description)
                loc_enc = safe_encode(le_location, location if location else 'Unknown', default_val='Unknown')
                title_enc = safe_encode(le_title, normalized_job, default_val='')
                if logistic_model is not None and scaler is not None:
                    try:
                        features_arr = np.array([[salary_numeric, experience_val, kw_count, desc_len, loc_enc, title_enc]])
                        scaled_features = scaler.transform(features_arr)
                        structured_proba = logistic_model.predict_proba(scaled_features)[0]
                        ml_score_component = round(min(100.0, float(structured_proba[1] * 50 + structured_proba[2] * 100)), 1)
                    except Exception as e:
                        print(f"[warn] Legacy logistic model failed: {e}")
                        ml_score_component = 50.0
                else:
                    ml_score_component = 50.0

            # RULE-BASED SCORE (50% keyword, 30% salary, 20% community)
            rule_based_score = min(100.0, max(0.0,
                kw_score * 0.5 +
                salary_score * 0.3 +
                community_score * 0.2
            ))

            # DOMAIN INTELLIGENCE SCORE
            domain_intelligence_score = 50.0
            domain_details_full = {}
            if _domain_intelligence_available and url:
                try:
                    domain_intelligence_score = compute_domain_intelligence_score(url)
                    domain_details_full = get_domain_intelligence_details(url)
                except Exception as e:
                    print(f"[warn] Domain intelligence calculation failed: {e}")
                    domain_intelligence_score = 50.0

            # FINAL HYBRID SCORE
            risk_score = (
                (ml_score_component  * 0.30) +
                (nlp_score_component * 0.30) +
                (rule_based_score    * 0.30) +
                (domain_intelligence_score * 0.10)
            )
            skills_nudge = skills_fraud_score * 0.05
            risk_score = round(min(100.0, max(0.0, risk_score + skills_nudge)), 1)

            # RISK LEVEL
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

            # Confidence calculation
            if prediction == 2:
                confidence = round((nlp_score_component + ml_score_component) / 2.0, 1)
            elif prediction == 0:
                confidence = round(100.0 - (nlp_score_component + ml_score_component) / 2.0, 1)
            else:
                confidence = round(50.0 + abs(risk_score - 45.0), 1)
            confidence = round(min(99.9, max(0.1, confidence)), 1)

            # Details dictionary
            details = {
                'keyword_score': round(kw_score, 1),
                'salary_score': round(salary_score, 1),
                'report_score': round(community_score, 1),
                'rule_based_score': round(rule_based_score, 1),
                'nlp_model_score': round(nlp_score_component, 1),
                'ml_model_score': round(ml_score_component, 1),
                'domain_score': round(domain_intelligence_score, 1),
                'domain_intelligence_score': round(domain_intelligence_score, 1),
                'domain_risk_factors': domain_details_full.get('risk_factors', []),
                'matched_keywords': [k for k, v in matched_kw[:8]],
                'skills_fraud_score': round(skills_fraud_score, 1),
                'matched_suspicious_skills': matched_suspicious_skills[:6],
                'hybrid_weights': {
                    'ml': 0.30, 'nlp': 0.30, 'rule_based': 0.30, 'domain': 0.10
                },
                'component_contributions': {
                    'ml_contribution': round(ml_score_component * 0.30, 1),
                    'nlp_contribution': round(nlp_score_component * 0.30, 1),
                    'rule_based_contribution': round(rule_based_score * 0.30, 1),
                    'domain_contribution': round(domain_intelligence_score * 0.10, 1),
                },
                'models_used': {
                    'nlp_model': nlp_model is not None,
                    'ml_model': ml_model is not None,
                    'tfidf_vec': tfidf_vec is not None,
                    'trigram_vec': trigram_vec is not None,
                    'domain_intelligence': _domain_intelligence_available,
                }
            }

            # Red flags list
            red_flags = []
            if details['keyword_score'] > 50:
                red_flags.append('High-risk keywords detected')
            if details['domain_intelligence_score'] > 60:
                red_flags.append('Suspicious domain characteristics')
                for risk_factor in domain_details_full.get('risk_factors', [])[:2]:
                    red_flags.append(f"• {risk_factor}")
            if details['salary_score'] > 60:
                red_flags.append('Unrealistically high salary')
            if nlp_score_component > 60:
                red_flags.append(f"NLP model flagged high scam probability ({nlp_score_component:.0f}/100)")
            if ml_score_component > 60:
                red_flags.append(f"ML model flagged high fraud risk ({ml_score_component:.0f}/100)")
            if details['matched_keywords']:
                red_flags.append(f"Scam phrases: {', '.join(details['matched_keywords'][:3])}")
            if matched_suspicious_skills:
                red_flags.append(f"Suspicious skill signals: {', '.join(matched_suspicious_skills[:3])}")

            if company_count > 0:
                red_flags.append(f"This company has been reported as scam by {company_count} users.")
            if domain_count > 0:
                red_flags.append(f"This domain has received {domain_count} scam reports.")
            elif listing_count > 0:
                red_flags.append(f"This listing has received {listing_count} scam reports.")

            # Safety recommendations
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

            # Save reputation report if marked as scam
            if risk_level == 'Scam':
                try:
                    reason = f"Automated analysis score: {risk_score}. Flags: {', '.join(red_flags[:3])}"
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

            # Save job post
            try:
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

            # Explanation summary
            explanation_data = None
            try:
                explanation_data = get_local_explanation(
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
                print(f"Explanation error: {e}")

            return jsonify({
                'prediction': prediction,
                'confidence': confidence,
                'risk_score': risk_score,
                'risk_level': risk_level,
                'risk_label': risk_label,
                'details': details,
                'red_flags': red_flags,
                'tips': tips,
                'local_explanation': explanation_data,
                'groq_explanation': explanation_data,
                'hybrid_score': {
                    'ml_score': round(ml_score_component, 1),
                    'nlp_score': round(nlp_score_component, 1),
                    'rule_based_score': round(rule_based_score, 1),
                    'domain_score': round(domain_intelligence_score, 1),
                    'weights': {'ml': 30, 'nlp': 30, 'rule_based': 30, 'domain': 10},
                    'contributions': details.get('component_contributions', {}),
                },
                'models_loaded': {
                    'nlp_model': nlp_model is not None,
                    'ml_model': ml_model is not None,
                    'tfidf_vec': tfidf_vec is not None,
                    'trigram_vec': trigram_vec is not None,
                    'domain_intelligence': _domain_intelligence_available,
                    'nlp': nlp_model is not None or nlp_pipeline is not None,
                    'lr': logistic_model is not None,
                }
            })

        except Exception as e:
            import traceback as _tb
            print('\n' + '='*60)
            print('[analyze] UNHANDLED EXCEPTION — full traceback:')
            _tb.print_exc()
            print('='*60 + '\n')
            return jsonify({
                'error': str(e),
                'traceback': _tb.format_exc(),
            }), 500

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
                    if _html_cleaner_available and result.get('job_description'):
                        result['job_description'] = clean_html_description(result['job_description'])
                    result['_scrape_method'] = sr.method
                    return jsonify(result)
                print(f'[scrape] New scraper partial ({sr.method}): {sr.error}')
                if sr.data and (sr.data.get('job_title') or sr.data.get('job_description')):
                    result = sr.data
                    if _html_cleaner_available and result.get('job_description'):
                        result['job_description'] = clean_html_description(result['job_description'])
                    result['_scrape_method'] = sr.method
                    return jsonify(result)
            except Exception as e:
                print(f'[scrape] New scraper exception: {e}')
                return jsonify({'error': f'Scraping error: {str(e)}'}), 500

        # Fallback to scamshield_scraper directly
        if _ss_scraper_available:
            try:
                if not ss_validate_url(url):
                    return jsonify({'error': 'Invalid or unsupported URL format'}), 400
                scraped = ss_scrape_url(url)
                if scraped.get('scrape_success'):
                    job_desc = scraped.get('raw_text', scraped.get('body_text', ''))[:3000]
                    if _html_cleaner_available:
                        job_desc = clean_html_description(job_desc)
                    return jsonify({
                        'job_title':       scraped.get('page_title', ''),
                        'job_description': job_desc,
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
        """Run standalone scraper rule-based URL analysis."""
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
            'nlp_model': nlp_model is not None,
            'ml_model': ml_model is not None,
            'tfidf_vectorizer': tfidf_vec is not None,
            'trigram_vectorizer': trigram_vec is not None,
            'label_encoder': label_encoder is not None,
            'feature_config': feature_config is not None,
            'le_location': le_location is not None,
            'le_title': le_title is not None,
            'nlp_pipeline': nlp_pipeline is not None,
            'logistic_model': logistic_model is not None,
            'scaler': scaler is not None,
        }
        all_critical_loaded = model_status['nlp_model'] and model_status['ml_model']

        nlp_test_result = None
        try:
            if nlp_model and tfidf_vec:
                combined = "earn 50000 per day registration fee whatsapp"
                X_tfidf = tfidf_vec.transform([combined])
                proba = nlp_model.predict_proba(X_tfidf)[0]
                classes = list(nlp_model.classes_)
                
                legit_idx = classes.index(0) if 0 in classes else -1
                scam_idx = classes.index(1) if 1 in classes else -1
                susp_idx = classes.index(2) if 2 in classes else -1
                
                nlp_test_result = {
                    'legit': round(float(proba[legit_idx]), 3) if legit_idx >= 0 else 0.0,
                    'scam': round(float(proba[scam_idx]), 3) if scam_idx >= 0 else 0.0,
                    'suspicious': round(float(proba[susp_idx]), 3) if susp_idx >= 0 else 0.0,
                }
        except Exception as e:
            nlp_test_result = {'error': str(e)}

        return jsonify({
            'status': 'healthy' if all_critical_loaded else 'degraded',
            'models': model_status,
            'nlp_test': nlp_test_result,
            'nlp_accuracy': '99.36%',
            'dataset_size': 9318,
            'version': '3.0',
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

    @app.route('/analyze-unified', methods=['POST'])
    def analyze_unified():
        """Unified analysis pipeline accepts URL, text, PDF, or image."""
        if 'user' not in session:
            return jsonify({'error': 'Unauthorized. Please log in.'}), 401

        company_name  = ''
        job_title_val = ''
        platform_name = ''
        description   = ''
        url           = ''
        red_flags     = []
        trust_indicators = []

        content_type = request.content_type or ''

        if 'multipart/form-data' in content_type:
            url         = request.form.get('url', '').strip()
            description = request.form.get('description', '').strip()
            company_name= request.form.get('company', '').strip()
            pdf_file    = request.files.get('pdf')

            if pdf_file and pdf_file.filename.lower().endswith('.pdf') and _ss_scraper_available:
                try:
                    pdf_bytes = pdf_file.read()
                    extracted = ss_extract_pdf(pdf_bytes)
                    if extracted.get('success') and extracted.get('text'):
                        description = description + '\n' + extracted['text']
                except Exception as _pe_err:
                    print(f'[analyze-unified] PDF extraction failed: {_pe_err}')

        elif request.is_json:
            data        = request.get_json() or {}
            url         = data.get('url', '').strip()
            description = data.get('description', data.get('job_description', '')).strip()
            company_name= data.get('company', '').strip()
            job_title_val = data.get('job_title', '').strip()

        if not url and not description:
            return jsonify({'error': 'Provide at least a URL or job description.'}), 400

        scraper_score = 50.0
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
                page_title = scraper_data.get('page_title', '')
                if page_title and not job_title_val:
                    job_title_val = page_title
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

        ml_score = 50.0
        try:
            if nlp_pipeline is not None:
                proba = nlp_pipeline.predict_proba([combined_text])[0]
                ml_score = float(proba[1] * 50 + proba[2] * 100)
        except Exception as _ml_err:
            print(f'[analyze-unified] ML error: {_ml_err}')

        domain_score = check_domain_risk(url) if url else 30.0
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

        confidence = round(abs(final_score - 50) * 2, 1)

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

        if url and url.startswith('https://'):
            trust_indicators.append('HTTPS enabled')
        if not scraper_data.get('suspicious_tld'):
            trust_indicators.append('Standard TLD')
        if domain_score <= 30:
            trust_indicators.append('Domain appears trustworthy')
        if community_count == 0:
            trust_indicators.append('No community scam reports found')

        if risk_level == 'Scam':
            recommendation = 'Do NOT apply. This listing shows strong scam indicators. Never pay any fees.'
        elif risk_level == 'Suspicious':
            recommendation = 'Proceed with caution. Verify the company on official portals before applying.'
        else:
            recommendation = 'This listing appears safe. Always read the offer carefully before sharing personal data.'

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
                'notebook_pipeline':  False,
                'scraper':            _ss_scraper_available,
            },
        })
