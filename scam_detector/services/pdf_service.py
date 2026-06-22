import io
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.enums import TA_CENTER, TA_LEFT

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
        
        # Safe float conversion helper for weighted contribution
        def get_weighted_contrib(score_key, weight):
            try:
                val = details.get(score_key)
                if val is None or val == '—':
                    return '—'
                return f"{float(val) * weight:.1f}"
            except (ValueError, TypeError):
                return '—'

        breakdown = [
            ['Component', 'Score', 'Weight', 'Weighted Contribution'],
            ['ML Model Score', str(details.get('ml_model_score', '—')), '30%', get_weighted_contrib('ml_model_score', 0.3)],
            ['NLP Model Score', str(details.get('nlp_model_score', '—')), '30%', get_weighted_contrib('nlp_model_score', 0.3)],
            ['Rule-Based Score', str(details.get('rule_based_score', '—')), '30%', get_weighted_contrib('rule_based_score', 0.3)],
            ['Domain Score', str(details.get('domain_score', '—')), '10%', get_weighted_contrib('domain_score', 0.1)],
        ]
        btbl = Table(breakdown, colWidths=[70*mm, 30*mm, 30*mm, 40*mm])
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
