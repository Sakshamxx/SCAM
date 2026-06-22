import re
import urllib.parse
from flask import render_template, request, session, redirect, url_for, jsonify, make_response

from scam_detector.database.supabase_client import (
    supabase, log_activity, get_recruiter_profile,
    get_scam_reports, save_scam_report
)
from scam_detector.routes.main_routes import verify_domain
from scam_detector.services.pdf_service import build_pdf

def register_verify_routes(app):
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
                db_profiles = get_recruiter_profile(
                    email=email, company=name, domain=domain
                )
                if db_profiles:
                    blacklisted_in_db = any(p.get('blacklisted') for p in db_profiles)
                    previous_reports = sum(p.get('previous_reports', 0) for p in db_profiles)
            except Exception as _e:
                print("Error loading recruiter profile:", _e)
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

    @app.route('/report-scam', methods=['GET', 'POST'])
    def report_scam():
        if 'user' not in session:
            return redirect(url_for('login', error='Please log in to report a scam.'))

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
