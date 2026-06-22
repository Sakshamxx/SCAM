def get_local_fallback_explanation(risk_score, risk_level, risk_label, red_flags, matched_keywords,
                                   job_title='', company='', details=None):
    """Local rule-based explanation engine (no external API needed)."""
    details = details or {}
    kw_list = ', '.join(matched_keywords[:3]) if matched_keywords else 'none detected'
    ml_score  = details.get('ml_model_score', 0)
    nlp_score = details.get('nlp_model_score', 0)

    if risk_level == 'Scam':
        explanation = (
            f"This job listing for '{job_title}' at '{company}' has been flagged with a high risk score of "
            f"{risk_score}/100. Our ML model ({ml_score:.0f}/100) and NLP text classifier ({nlp_score:.0f}/100) "
            f"both detected strong indicators of fraud. Suspicious phrases identified: {kw_list}."
        )
        recruiter_assessment = "The recruiter credentials and contact methods match patterns commonly associated with employment scams."
        safety_advice = "DO NOT pay any fees or share sensitive personal documents (PAN/Aadhaar) with this recruiter."
        recommendations = [
            "Never pay any registration fee, training fee, or document charge to secure a job.",
            "Verify the recruiter's official company email rather than generic Gmail/WhatsApp.",
            "Cross-verify the job listing on the company's official careers portal.",
            "Refuse any requests for upfront bank account details or identity documents."
        ]
    elif risk_level == 'Suspicious':
        explanation = (
            f"The job listing for '{job_title}' at '{company}' has a moderate risk score of {risk_score}/100. "
            f"ML signals ({ml_score:.0f}/100) and NLP analysis ({nlp_score:.0f}/100) show mixed indicators. "
            f"While not definitively fraudulent, it contains suspicious phrases requiring validation."
        )
        recruiter_assessment = "The recruiter signals are mixed, showing unverified email domains or non-standard application procedures."
        safety_advice = "Verify the job posting and company credentials before continuing with the application."
        recommendations = [
            "Research the company's registration status and search for employee reviews online.",
            "Ask the recruiter for official corporate identification or an official email confirmation.",
            "Do not participate in instant hiring decisions without a formal interview process."
        ]
    else:
        explanation = (
            f"The job listing for '{job_title}' at '{company}' displays very few risk indicators, scoring {risk_score}/100. "
            f"ML analysis ({ml_score:.0f}/100) and NLP classifier ({nlp_score:.0f}/100) both indicate this "
            f"aligns with standard, legitimate hiring practices."
        )
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


def get_local_explanation(risk_score, risk_level, risk_label, red_flags, matched_keywords,
                          job_title='', company='', details=None):
    """Primary explanation function — uses local engine (no external API)."""
    return get_local_fallback_explanation(
        risk_score, risk_level, risk_label, red_flags, matched_keywords,
        job_title, company, details
    )

# Backward compatibility aliases
get_groq_fallback_explanation = get_local_fallback_explanation
get_groq_explanation = get_local_explanation
