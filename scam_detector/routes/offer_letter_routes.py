import io
import re
from datetime import datetime
from flask import render_template, request, session, redirect, url_for, jsonify, make_response
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.enums import TA_CENTER

from scam_detector.database.supabase_client import log_activity, get_company_reputation_stats
from scam_detector.rule_engine.rules import keyword_fraud_score
from scam_detector.services.explanation_service import get_groq_explanation

# Try to import pdf extractor
try:
    from scam_detector.utils.pdf_extractor import extract_pdf_text
    _pdf_extractor_available = True
except ImportError:
    _pdf_extractor_available = False
    extract_pdf_text = None

# Try to import standalone scraper image/pdf text extractors
try:
    from scam_detector.utils.scamshield_scraper import (
        extract_text_from_pdf as ss_extract_pdf,
        extract_text_from_image as ss_extract_image
    )
    _ss_scraper_available = True
except ImportError:
    _ss_scraper_available = False
    ss_extract_pdf = None
    ss_extract_image = None


def register_offer_letter_routes(app):
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
        run ML pipeline + explanation, return JSON results.
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

        # ── 5. AI explanation ──────────────────────────────────────────────────
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

        if _ss_scraper_available and ss_extract_image is not None:
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

        groq_data = None
        try:
            groq_data = get_groq_explanation(
                risk_score=risk_score, risk_level=risk_level, risk_label=risk_label,
                red_flags=red_flags, matched_keywords=matched_keywords,
                job_title='Image / Poster', company=company or 'Unknown',
                details={'keyword_score': round(kw_score, 1), 'domain_score': 0, 'salary_score': 0, 'nlp_model_score': 0}
            )
        except Exception:
            pass

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

        pdf_buf = io.BytesIO()
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
                                       fontSize=12, textColor=colors.HexColor('#cbd5e1'),
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
