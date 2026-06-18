/* ═══════════════════════════════════════════════
   ScamShield — Main JavaScript
   ═══════════════════════════════════════════════ */

// ── Character counter ──────────────────────────
const textarea = document.getElementById('job_description');
const charCount = document.getElementById('charCount');
if (textarea) {
  textarea.addEventListener('input', () => {
    charCount.textContent = textarea.value.length;
  });
}

// ── Example job postings ───────────────────────
const EXAMPLES = {
  scam: {
    job_title: 'Work From Home Data Entry',
    company: 'QuickEarn Solutions',
    location: 'Remote',
    salary: 75000,
    experience: 0,
    url: 'https://quickearnjobs.blogspot.com/apply-now',
    job_description: `Urgency Hiring! Earn ₹50,000-₹1,00,000 per month from home!

No experience required. No qualification needed. Anyone can apply.

Work: Simple copy-paste tasks and online data entry from home.
Payment: Daily payment guaranteed. 
Requirements: Just a smartphone or laptop.

Process: WhatsApp HR immediately on 9876543210. Instant joining available.
Limited seats only! Hurry up and apply today!

IMPORTANT: Registration fee of ₹999 only for training kit. Pay security deposit of ₹2000 which is fully refundable.

Contact us only on WhatsApp. No office visits required.
Be your own boss! Unlimited earning potential. Flexible hours.`
  },
  legit: {
    job_title: 'Data Analyst Intern',
    company: 'Infosys BPM Limited',
    location: 'Bengaluru, Karnataka',
    salary: 18000,
    experience: 0,
    url: 'https://internshala.com/internship/data-analyst-internship',
    job_description: `We are looking for a motivated Data Analyst Intern to join our Analytics team at Infosys BPM Limited.

Role Overview:
You will work closely with our senior analysts to help process and visualize business data.

Responsibilities:
- Assist in cleaning and transforming datasets using Python/Excel
- Create dashboards in Tableau or Power BI
- Prepare weekly reports for stakeholders
- Support the team in ad-hoc data requests

Requirements:
- Currently pursuing B.Tech / BCA / B.Sc (final year preferred)
- Basic knowledge of SQL, Python, or Excel
- Strong attention to detail
- Good communication skills

Stipend: ₹15,000 - ₹18,000 per month
Duration: 3 months (possibility of full-time offer)
Working Hours: 9am – 6pm IST

Selection Process: Online aptitude test → Technical interview → HR round

Apply through Internshala portal only. For queries email: careers@infosys.com`
  }
};

function loadExample(type) {
  const ex = EXAMPLES[type];
  if (!ex) return;
  const fields = {
    job_title: ex.job_title,
    company: ex.company,
    location: ex.location,
    salary: ex.salary,
    experience: ex.experience,
    url: ex.url,
    job_description: ex.job_description
  };
  for (const [id, val] of Object.entries(fields)) {
    const el = document.getElementById(id);
    if (el) el.value = val;
  }
  if (charCount) charCount.textContent = ex.job_description.length;
}

// ── Clear Form ─────────────────────────────────
function clearForm() {
  const form = document.getElementById('analyzeForm');
  if (form) {
    form.reset();
    if (charCount) charCount.textContent = '0';
  }
}

// ── Form Submit (Analyze page — shows live panel + stores for /results) ──
const analyzeForm = document.getElementById('analyzeForm');
if (analyzeForm) {
  analyzeForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    await runAnalysis();
  });
}

async function runAnalysis() {
  const btn       = document.getElementById('analyzeBtn');
  const btnText   = btn ? btn.querySelector('.btn-text') : null;
  const btnLoader = btn ? btn.querySelector('.btn-loader') : null;
  const btnIcon   = btn ? btn.querySelector('.btn-icon') : null;

  // Show loading state on button
  if (btn) btn.disabled = true;
  if (btnText)   btnText.style.display   = 'none';
  if (btnIcon)   btnIcon.style.display   = 'none';
  if (btnLoader) { btnLoader.style.display = 'flex'; btnLoader.style.alignItems = 'center'; btnLoader.style.gap = '8px'; }

  // Switch right panel to loading
  const idleState      = document.getElementById('idleState');
  const loadingState   = document.getElementById('analysisLoading');
  const resultsState   = document.getElementById('analysisResults');
  if (idleState)    idleState.style.display    = 'none';
  if (loadingState) loadingState.style.display = 'block';
  if (resultsState) resultsState.style.display = 'none';

  const payload = {
    job_title:       (document.getElementById('job_title')       || {}).value?.trim() || '',
    company:         (document.getElementById('company')         || {}).value?.trim() || '',
    location:        (document.getElementById('location')        || {}).value?.trim() || '',
    job_description: (document.getElementById('job_description') || {}).value?.trim() || '',
    url:             (document.getElementById('url')             || {}).value?.trim() || '',
    salary:          parseFloat((document.getElementById('salary') || {}).value) || null,
    experience:      parseFloat((document.getElementById('experience') || {}).value) || null,
    skills:          (document.getElementById('skills')          || {}).value?.trim() || '',
  };

  const context = { job_title: payload.job_title, company: payload.company };

  try {
    const data = await ScamShieldAPI.analyzeJob(payload);

    const enriched = Object.assign({}, data, {
      job_title:        payload.job_title,
      company:          payload.company,
      location:         payload.location,
      url:              payload.url,
      prediction:       data.risk_level && ['HIGH', 'CRITICAL'].includes(data.risk_level) ? 'Scam' : 'Legitimate',
      confidence:       data.structured_ml_score != null ? data.structured_ml_score : data.risk_score,
      matched_keywords: data.details ? data.details.matched_keywords : [],
    });

    // Store for full results page
    sessionStorage.setItem('scamshield_result', JSON.stringify(enriched));
    sessionStorage.setItem('scamshield_context', JSON.stringify(context));

    // Show live panel results
    renderLivePanel(data);

  } catch (err) {
    if (loadingState) loadingState.style.display = 'none';
    if (idleState)    idleState.style.display    = 'block';
    showToast('❌ Analysis failed: ' + (err.message || 'Server error'), 'error');
    console.error(err);
  } finally {
    if (btn) btn.disabled = false;
    if (btnText)   btnText.style.display   = 'inline';
    if (btnIcon)   btnIcon.style.display   = 'inline';
    if (btnLoader) btnLoader.style.display = 'none';
  }
}

// ── Render live results on analyze page right panel ─────────────────────────
function renderLivePanel(data) {
  const loadingState = document.getElementById('analysisLoading');
  const resultsState = document.getElementById('analysisResults');
  if (loadingState) loadingState.style.display = 'none';
  if (resultsState) resultsState.style.display = 'block';

  const d = data.details || {};
  const colorMap = { green: '#10b981', yellow: '#f59e0b', red: '#ef4444', critical: '#7c3aed' };
  const accentColor = colorMap[data.risk_color] || '#6366f1';

  // Verdict + score
  const verdictEl = document.getElementById('liveVerdictText');
  const scoreEl   = document.getElementById('liveRiskScore');
  const badge     = document.getElementById('liveVerdictBadge');
  if (verdictEl) verdictEl.textContent = data.risk_label || '—';
  if (scoreEl)   scoreEl.textContent   = Math.round(data.risk_score) + '/100';
  if (scoreEl)   scoreEl.style.color   = accentColor;
  if (badge)     badge.style.borderColor = accentColor + '55';

  // Score bars
  function liveBar(scoreId, barId, val) {
    const s = document.getElementById(scoreId);
    const b = document.getElementById(barId);
    if (s) s.textContent = Math.round(val) + '/100';
    setTimeout(() => { if (b) b.style.width = Math.min(val, 100) + '%'; }, 100);
  }
  liveBar('liveKwScore',  'liveKwBar',  d.keyword_score   || 0);
  liveBar('liveDomScore', 'liveDomBar', d.domain_score    || 0);
  liveBar('liveSalScore', 'liveSalBar', d.salary_score    || 0);
  liveBar('liveNlpScore', 'liveNlpBar', d.nlp_model_score || 0);

  // Skills fraud score bar (live panel)
  const liveSkillsRow = document.getElementById('liveSkillsRow');
  if (d.skills_fraud_score > 0) {
    liveBar('liveSkillsScore', 'liveSkillsBar', d.skills_fraud_score * 2.5); // scale 40→100 for bar
    if (liveSkillsRow) liveSkillsRow.style.display = 'block';
  } else if (liveSkillsRow) {
    liveSkillsRow.style.display = 'none';
  }

  // Recruiter Assessment (from Groq)
  const recDiv  = document.getElementById('liveRecruiterAssessment');
  const recText = document.getElementById('liveRecruiterText');
  if (data.groq_explanation && data.groq_explanation.recruiter_assessment) {
    if (recText) recText.textContent = data.groq_explanation.recruiter_assessment;
    if (recDiv)  recDiv.style.display = 'block';
  } else if (recDiv) {
    recDiv.style.display = 'none';
  }

  // Detected Keywords
  const kwSec  = document.getElementById('liveKeywordsSection');
  const kwTags = document.getElementById('liveKeywordTags');
  if (d.matched_keywords && d.matched_keywords.length > 0) {
    if (kwTags) kwTags.innerHTML = d.matched_keywords.map(kw =>
      `<span class="kw-tag" style="font-size:0.78rem; padding:3px 10px;">🔴 ${kw}</span>`
    ).join('');
    if (kwSec) kwSec.style.display = 'block';
  } else if (kwSec) {
    kwSec.style.display = 'none';
  }

  // Update Report Scam link with company
  const reportBtn = document.getElementById('liveReportBtn');
  if (reportBtn) {
    const company = (document.getElementById('company') || {}).value?.trim() || '';
    if (company) reportBtn.href = '/report-scam?company=' + encodeURIComponent(company);
  }
}

// ── Legacy wrapper kept for compatibility ────────────────────────────────────
async function runAnalysisAndRedirect() {
  await runAnalysis();
}

// ── Results Page — Load from sessionStorage ─────
function loadResultsFromSession() {
  const resultRaw  = sessionStorage.getItem('scamshield_result');
  const contextRaw = sessionStorage.getItem('scamshield_context');
  const noData = document.getElementById('noDataState');
  const content = document.getElementById('resultPageContent');

  if (!resultRaw) {
    if (noData) noData.style.display = 'block';
    if (content) content.style.display = 'none';
    return;
  }

  if (noData) noData.style.display = 'none';
  if (content) content.style.display = 'block';

  const data    = JSON.parse(resultRaw);
  const context = contextRaw ? JSON.parse(contextRaw) : {};

  // Populate report header
  const ts = new Date();
  const tsEl = document.getElementById('reportTimestamp');
  if (tsEl) tsEl.textContent = ts.toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' });

  const jobTitleEl = document.getElementById('reportJobTitle');
  if (jobTitleEl) jobTitleEl.textContent = context.job_title ? `Analysis: "${context.job_title}"` : 'Job Analysis Report';

  const companyEl = document.getElementById('reportCompany');
  if (companyEl) companyEl.textContent = context.company || 'Submitted job posting';

  // Verdict badge
  const verdictBadge = document.getElementById('reportVerdictBadge');
  const verdictText  = document.getElementById('reportVerdictText');
  if (verdictBadge && verdictText) {
    verdictText.textContent = data.risk_label || '—';
    verdictBadge.className = 'report-verdict-badge badge-' + (data.risk_color || 'green');
  }

  // Risk level badge in card
  const riskLevelBadge = document.getElementById('riskLevelBadge');
  if (riskLevelBadge) {
    riskLevelBadge.textContent = data.risk_level || '—';
    riskLevelBadge.className = 'result-card-badge badge-' + (data.risk_color || 'green') + '-soft';
  }

  // Render gauge
  renderResultsOnPage(data);

  // Pre-fill Report Scam link with company name
  if (typeof updateReportLink === 'function') {
    updateReportLink(context.company || data.company || '');
  }

  // Initialize comprehensive analysis cards if data available
  if (data.comprehensive_analysis && typeof initializeAnalysis === 'function') {
    setTimeout(() => {
      initializeAnalysis(data.comprehensive_analysis);
    }, 100);
  }
}

// ── Render Results (Results page) ──────────────
function renderResultsOnPage(data) {
  const score = data.risk_score;
  const color = data.risk_color;

  // Animate Gauge
  animateGauge(score, color);

  // Risk Badge
  const badge = document.getElementById('riskBadge');
  if (badge) badge.className = 'risk-badge-large badge-' + color;
  const riskLabelEl = document.getElementById('riskLabelText');
  if (riskLabelEl) riskLabelEl.textContent = data.risk_label;

  // Score Bars
  const d = data.details;
  setTimeout(() => {
    setBar('kwScore',  'kwBar',  d.keyword_score);
    setBar('domScore', 'domBar', d.domain_score);
    setBar('salScore', 'salBar', d.salary_score);
    setBar('nlpScore', 'nlpBar', d.nlp_model_score);
  }, 300);

  // Skills Analysis Card (result page)
  const skillsCard      = document.getElementById('skillsAnalysisCard');
  const skillsScoreEl   = document.getElementById('skillsFraudScore');
  const skillsBarEl     = document.getElementById('skillsFraudBar');
  const skillsTagsEl    = document.getElementById('suspiciousSkillTags');
  const skillsClearEl   = document.getElementById('skillsClearMsg');
  if (d.skills_fraud_score > 0 && d.matched_suspicious_skills && d.matched_suspicious_skills.length > 0) {
    if (skillsCard) skillsCard.style.display = 'block';
    if (skillsScoreEl) skillsScoreEl.textContent = d.skills_fraud_score + '/40';
    if (skillsBarEl) setTimeout(() => { skillsBarEl.style.width = Math.min(d.skills_fraud_score * 2.5, 100) + '%'; }, 400);
    if (skillsTagsEl) skillsTagsEl.innerHTML = d.matched_suspicious_skills.map(s =>
      `<span class="kw-tag" style="font-size:0.78rem; padding:3px 10px; background:rgba(239,68,68,0.12); border:1px solid rgba(239,68,68,0.3); color:#fca5a5; border-radius:100px;">🔴 ${s}</span>`
    ).join('');
    if (skillsClearEl) skillsClearEl.style.display = 'none';
  } else {
    if (skillsCard) skillsCard.style.display = 'block';
    if (skillsScoreEl) skillsScoreEl.textContent = '0/40';
    if (skillsBarEl) setTimeout(() => { skillsBarEl.style.width = '0%'; }, 400);
    if (skillsTagsEl) skillsTagsEl.innerHTML = '';
    if (skillsClearEl) skillsClearEl.style.display = 'block';
  }

  // Confidence Score (structured ML)
  const confCard = document.getElementById('confidenceCard');
  const confPct  = document.getElementById('confidencePct');
  const confBar  = document.getElementById('confidenceBar');
  if (data.structured_ml_score !== null && data.structured_ml_score !== undefined) {
    if (confPct) confPct.textContent = data.structured_ml_score.toFixed(1) + '%';
    if (confBar) setTimeout(() => { confBar.style.width = Math.min(data.structured_ml_score, 100) + '%'; }, 400);
  } else {
    if (confCard) confCard.style.display = 'none';
  }

  // Matched Keywords
  const kwCard = document.getElementById('matchedKeywordsCard');
  const kwTags = document.getElementById('keywordTags');
  const kwCount = document.getElementById('kwCount');
  if (d.matched_keywords && d.matched_keywords.length > 0) {
    if (kwTags) kwTags.innerHTML = d.matched_keywords.map(kw => `<span class="kw-tag">🔴 ${kw}</span>`).join('');
    if (kwCount) kwCount.textContent = d.matched_keywords.length + ' found';
    if (kwCard) kwCard.style.display = 'block';
  } else {
    if (kwCard) kwCard.style.display = 'none';
  }

  // Red Flags
  const flagsCard = document.getElementById('redFlagsCard');
  const flagsList = document.getElementById('flagsList');
  if (data.red_flags && data.red_flags.length > 0) {
    if (flagsList) flagsList.innerHTML = data.red_flags.map(f => `<li>${f}</li>`).join('');
    if (flagsCard) flagsCard.style.display = 'block';
  } else {
    if (flagsCard) flagsCard.style.display = 'none';
  }

  // Safety Tips
  const tipsCard = document.getElementById('tipsCard');
  const tipsList = document.getElementById('tipsList');
  if (data.tips && data.tips.length > 0) {
    if (tipsList) tipsList.innerHTML = data.tips.map(t => `<li>${t}</li>`).join('');
    if (tipsCard) tipsCard.style.display = 'block';
  } else {
    if (tipsCard) tipsCard.style.display = 'none';
  }

  // All-clear card
  const allClear = document.getElementById('allClearCard');
  if (allClear) {
    if (data.risk_score <= 30 && (!data.red_flags || data.red_flags.length === 0)) {
      allClear.style.display = 'block';
    } else {
      allClear.style.display = 'none';
    }
  }

  // Groq AI Explanation
  if (data.groq_explanation) {
    renderGroqExplanation(data.groq_explanation);
  }
}

// ── Gauge Animation ────────────────────────────
function animateGauge(score, colorKey) {
  const TOTAL_ARC = 251.2; // half-circle arc length
  const fill = document.getElementById('gaugeFill');
  const scoreEl = document.getElementById('gaugeScore');
  const labelEl = document.getElementById('gaugeLabel');
  if (!fill || !scoreEl) return;

  const colorMap = {
    green:    '#10b981',
    yellow:   '#f59e0b',
    red:      '#ef4444',
    critical: '#7c3aed'
  };
  const strokeColor = colorMap[colorKey] || '#10b981';

  const dashFilled = (score / 100) * TOTAL_ARC;
  const dashEmpty  = TOTAL_ARC - dashFilled;

  fill.setAttribute('stroke', strokeColor);
  fill.setAttribute('stroke-dasharray', `${dashFilled} ${dashEmpty}`);

  // Animate score number counting up
  let current = 0;
  const step  = score / 50;
  const timer = setInterval(() => {
    current = Math.min(current + step, score);
    scoreEl.textContent = Math.round(current);
    if (current >= score) clearInterval(timer);
  }, 20);

  if (labelEl) labelEl.textContent = 'out of 100';
}

// ── Bar Helper ─────────────────────────────────
function setBar(scoreId, barId, value) {
  const scoreEl = document.getElementById(scoreId);
  const barEl   = document.getElementById(barId);
  if (scoreEl) scoreEl.textContent = Math.round(value) + '/100';
  if (barEl)   barEl.style.width   = Math.min(value, 100) + '%';
}

// ── Groq AI Explanation Renderer ───────────────
function renderGroqExplanation(groq) {
  const card    = document.getElementById('groqCard');
  const content = document.getElementById('groqExplanationContent');
  if (!card || !content || !groq) return;

  let html = '';

  if (groq.explanation) {
    html += `
      <div style="margin-bottom:16px; padding:14px 16px; background:rgba(99,102,241,0.08); border-radius:10px; border-left:3px solid #6366f1;">
        <div style="font-size:0.75rem; color:#a5b4fc; font-weight:600; margin-bottom:6px; text-transform:uppercase; letter-spacing:0.05em;">Why This Job Was Flagged</div>
        <p style="color:#e2e8f0; font-size:0.87rem; line-height:1.7; margin:0;">${groq.explanation}</p>
      </div>`;
  }

  if (groq.recruiter_assessment) {
    html += `
      <div style="margin-bottom:16px; padding:12px 16px; background:rgba(255,255,255,0.04); border-radius:10px;">
        <div style="font-size:0.75rem; color:#94a3b8; font-weight:600; margin-bottom:5px;">👤 RECRUITER ASSESSMENT</div>
        <p style="color:#cbd5e1; font-size:0.85rem; line-height:1.6; margin:0;">${groq.recruiter_assessment}</p>
      </div>`;
  }

  if (groq.recommendations && groq.recommendations.length) {
    const recs = Array.isArray(groq.recommendations) ? groq.recommendations : [groq.recommendations];
    html += `
      <div style="margin-bottom:16px;">
        <div style="font-size:0.75rem; color:#94a3b8; font-weight:600; margin-bottom:8px;">✅ AI RECOMMENDATIONS</div>
        <ul style="list-style:none; padding:0; margin:0; display:flex; flex-direction:column; gap:6px;">
          ${recs.map(r => `<li style="display:flex; gap:8px; align-items:flex-start; color:#cbd5e1; font-size:0.84rem; line-height:1.6;"><span style="color:#10b981; flex-shrink:0; margin-top:2px;">→</span>${r}</li>`).join('')}
        </ul>
      </div>`;
  }

  if (groq.safety_advice) {
    html += `
      <div style="padding:10px 14px; background:rgba(16,185,129,0.08); border-radius:10px; border-left:3px solid #10b981;">
        <span style="font-size:0.75rem; color:#6ee7b7; font-weight:600;">🛡️ SAFETY GUIDANCE: </span>
        <span style="color:#a7f3d0; font-size:0.83rem;">${groq.safety_advice}</span>
      </div>`;
  }

  content.innerHTML = html;
  card.style.display = 'block';
}

// ── Reset Form (legacy, kept for compatibility) ─
function resetForm() {
  const form = document.getElementById('analyzeForm');
  if (form) form.reset();
  if (charCount) charCount.textContent = '0';
  const analyzeSection = document.getElementById('analyze');
  if (analyzeSection) window.scrollTo({ top: analyzeSection.offsetTop - 80, behavior: 'smooth' });
}

// ── Auto-Fill from URL ─────────────────────────
async function autoFillFromURL() {
  const urlInput = document.getElementById('url');
  const statusEl = document.getElementById('autofillStatus');
  if (!urlInput) return;

  const url = urlInput.value.trim();
  if (!url) {
    showToast('⚠️ Please enter a URL first', 'error');
    urlInput.focus();
    return;
  }

  if (statusEl) statusEl.textContent = '⏳ Fetching...';

  try {
    const data = await ScamShieldAPI.scrapeJob(url);

    if (data.error) {
      showToast('❌ ' + data.error, 'error');
      if (statusEl) statusEl.textContent = '⚡ Fetch job details from this URL';
      return;
    }

    let filled = 0;
    const fieldMap = {
      job_title: data.job_title,
      company:   data.company,
      location:  data.location,
      salary:    data.salary_num,
      experience: data.experience !== null && data.experience !== undefined ? data.experience : null,
      job_description: data.job_description
    };

    for (const [id, val] of Object.entries(fieldMap)) {
      if (val !== null && val !== undefined && val !== '') {
        const el = document.getElementById(id);
        if (el) { el.value = val; filled++; }
      }
    }
    if (data.job_description && charCount) charCount.textContent = data.job_description.length;

    if (filled > 0) {
      showToast(`✅ ${filled} fields auto-filled!`, 'success');
      if (statusEl) statusEl.textContent = '✅ Details fetched!';
    } else {
      showToast('⚠️ No data found — fill in manually', 'error');
      if (statusEl) statusEl.textContent = '⚡ Fetch job details from this URL';
    }

  } catch (err) {
    showToast('❌ Server error. Is Flask running?', 'error');
    if (statusEl) statusEl.textContent = '⚡ Fetch job details from this URL';
    console.error(err);
  }
}

// ── Toast notification (enhanced) ─────────────────────────────────
function showToast(message, type = 'success') {
  // Try global toast system first (from navbar)
  if (typeof showGlobalToast === 'function') {
    showGlobalToast(message, type);
    return;
  }
  // Fallback to original scrape toast
  const toast = document.getElementById('scrapeToast');
  if (!toast) return;
  toast.textContent = message;
  toast.className   = 'scrape-toast ' + (type === 'error' ? 'error' : '');
  setTimeout(() => toast.classList.add('show'), 10);
  setTimeout(() => toast.classList.remove('show'), 3500);
}

// ── URL field Enter key ─────────────────────────
const urlField = document.getElementById('url');
if (urlField) {
  urlField.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); autoFillFromURL(); }
  });
}

// ── Smooth scroll for anchor links ─────────────
document.querySelectorAll('a[href^="#"]').forEach(a => {
  a.addEventListener('click', e => {
    e.preventDefault();
    const target = document.querySelector(a.getAttribute('href'));
    if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
});

// ── Page Router — run correct init per page ─────
(function initPage() {
  const path = window.location.pathname;

  if (path === '/results') {
    loadResultsFromSession();
  }

  // ── Password Strength Meter (login/signup) ──
  const pwdInput = document.getElementById('password');
  const strengthBar = document.getElementById('passwordStrengthBar');
  const strengthLabel = document.getElementById('passwordStrengthLabel');
  if (pwdInput && strengthBar) {
    pwdInput.addEventListener('input', () => {
      const val = pwdInput.value;
      let score = 0;
      if (val.length >= 8) score++;
      if (/[A-Z]/.test(val)) score++;
      if (/[0-9]/.test(val)) score++;
      if (/[^A-Za-z0-9]/.test(val)) score++;
      const levels = [
        { label: 'Weak', color: '#ef4444', width: '25%' },
        { label: 'Fair', color: '#f59e0b', width: '50%' },
        { label: 'Good', color: '#6366f1', width: '75%' },
        { label: 'Strong', color: '#10b981', width: '100%' },
      ];
      const lvl = levels[Math.max(0, Math.min(score - 1, 3))] || levels[0];
      strengthBar.style.width   = val.length > 0 ? lvl.width : '0%';
      strengthBar.style.background = lvl.color;
      if (strengthLabel) strengthLabel.textContent = val.length > 0 ? lvl.label : '';
    });
  }

  // ── Show/Hide Password Toggle ──
  document.querySelectorAll('.pwd-toggle').forEach(btn => {
    btn.addEventListener('click', () => {
      const targetId = btn.dataset.target;
      const input = document.getElementById(targetId);
      if (!input) return;
      if (input.type === 'password') {
        input.type = 'text';
        btn.textContent = '🙈';
      } else {
        input.type = 'password';
        btn.textContent = '👁️';
      }
    });
  });

  // analyze-job and home pages initialize via the DOM guards above
})();

// ── AJAX Report Scam form ───────────────────────────────────────────────────
(function initReportScamAjax() {
  const form = document.getElementById('reportForm');
  if (!form) return;

  form.addEventListener('submit', async (e) => {
    e.preventDefault();

    const btn     = document.getElementById('reportBtn');
    const company = (document.getElementById('company') || {}).value?.trim() || '';
    const website = (document.getElementById('website') || {}).value?.trim() || '';
    const desc    = (document.getElementById('description') || {}).value?.trim() || '';

    if (!company) { showToast('⚠️ Company name is required', 'error'); return; }
    if (!desc || desc.length < 20) { showToast('⚠️ Description must be at least 20 characters', 'error'); return; }

    if (btn) { btn.disabled = true; btn.querySelector('.btn-text').textContent = 'Submitting...'; }

    try {
      const res  = await fetch('/report-scam', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
          'Accept': 'application/json'
        },
        body: new URLSearchParams({ company, website, description: desc })
      });

      // The route returns HTML (success/error Jinja). Check if success param in redirect or check status.
      // We post via FormData to get proper Flask session handling.
      const data = await res.json().catch(() => null);

      if (data && data.success) {
        showSuccessState();
      } else if (data && data.error) {
        showToast('❌ ' + data.error, 'error');
      } else {
        // Plain HTML response – if status 200 assume success
        if (res.ok) { showSuccessState(); }
        else { showToast('❌ Submission failed. Please try again.', 'error'); }
      }
    } catch (err) {
      showToast('❌ Network error. Please try again.', 'error');
      console.error(err);
    } finally {
      if (btn) { btn.disabled = false; btn.querySelector('.btn-text').textContent = 'Submit Report'; }
    }
  });

  function showSuccessState() {
    // Replace form panel with inline success
    const wrapper = document.querySelector('.report-wrapper');
    if (!wrapper) { window.location.href = '/report-scam?submitted=1'; return; }
    wrapper.innerHTML = `
      <div class="report-success-full" style="grid-column:1/-1;">
        <div class="success-icon">✅</div>
        <h2>Report Submitted Successfully!</h2>
        <p>Thank you for helping protect India's job seekers. Our team will review your report and take action if the domain is confirmed malicious.</p>
        <div class="report-action-row">
          <a href="/report-scam" class="result-action-btn result-action-secondary">Submit Another Report</a>
          <a href="/analyze-job" class="result-action-btn result-action-primary">Analyze a Job →</a>
        </div>
      </div>`;
  }
})();

// ── Expose functions to window for backward compatibility with onclick handlers ──
window.loadExample          = loadExample;
window.clearForm            = clearForm;
window.autoFillFromURL      = autoFillFromURL;
window.showToast            = showToast;
window.runAnalysis          = runAnalysis;
window.runAnalysisAndRedirect = runAnalysisAndRedirect;
window.resetForm            = resetForm;
window.animateGauge         = animateGauge;
window.setBar               = setBar;
window.renderGroqExplanation = renderGroqExplanation;
window.loadResultsFromSession = loadResultsFromSession;
