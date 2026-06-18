/**
 * Analysis Card Population Module
 * Handles comprehensive analysis display from API response
 */

function populateAnalysisCards(analysisData) {
  if (!analysisData) {
    console.warn('No analysis data provided');
    return;
  }

  console.log('Populating analysis cards:', analysisData);

  // Show analysis section
  const analysisSection = document.getElementById('analysisSection');
  if (analysisSection) {
    analysisSection.style.display = 'block';
  }

  // Populate ML Analysis
  if (analysisData.ml_analysis) {
    populateMLAnalysis(analysisData.ml_analysis);
  }

  // Populate NLP Analysis
  if (analysisData.nlp_analysis) {
    populateNLPAnalysis(analysisData.nlp_analysis);
  }

  // Populate Rule-Based Analysis
  if (analysisData.rule_analysis) {
    populateRuleAnalysis(analysisData.rule_analysis);
  }

  // Populate Community Analysis
  if (analysisData.community_analysis) {
    populateCommunityAnalysis(analysisData.community_analysis);
  }

  // Populate Verdict
  if (analysisData.verdict) {
    populateVerdict(analysisData.verdict);
  }
}

/**
 * Populate ML Analysis Card
 */
function populateMLAnalysis(mlAnalysis) {
  const mlScore = document.getElementById('mlScore');
  const mlScoreBar = document.getElementById('mlScoreBar');
  const mlConfidence = document.getElementById('mlConfidence');
  const mlSignals = document.getElementById('mlSignals');

  if (mlScore) mlScore.textContent = mlAnalysis.score;
  if (mlScoreBar) mlScoreBar.style.width = mlAnalysis.score + '%';

  // Set confidence badge color
  if (mlConfidence) {
    mlConfidence.textContent = mlAnalysis.confidence;
    mlConfidence.className = 'confidence-badge confidence-' + mlAnalysis.confidence.toLowerCase();
  }

  // Add signals
  if (mlSignals && mlAnalysis.signals) {
    mlSignals.innerHTML = '';
    mlAnalysis.signals.forEach((signal) => {
      const item = document.createElement('div');
      item.className = 'analysis-item';
      item.innerHTML = `
        <span class="analysis-item-label">→ ${signal}</span>
      `;
      mlSignals.appendChild(item);
    });
  }
}

/**
 * Populate NLP Analysis Card
 */
function populateNLPAnalysis(nlpAnalysis) {
  const nlpScore = document.getElementById('nlpScore');
  const nlpScoreBar = document.getElementById('nlpScoreBar');
  const nlpConfidence = document.getElementById('nlpConfidence');
  const patternsList = document.getElementById('patternsList');

  if (nlpScore) nlpScore.textContent = nlpAnalysis.score;
  if (nlpScoreBar) nlpScoreBar.style.width = nlpAnalysis.score + '%';

  if (nlpConfidence) {
    nlpConfidence.textContent = nlpAnalysis.confidence;
    nlpConfidence.className = 'confidence-badge confidence-' + nlpAnalysis.confidence.toLowerCase();
  }

  // Add detected patterns
  if (patternsList && nlpAnalysis.detected_patterns) {
    patternsList.innerHTML = '';
    nlpAnalysis.detected_patterns.forEach((pattern) => {
      const li = document.createElement('li');
      li.textContent = pattern;
      patternsList.appendChild(li);
    });

    if (nlpAnalysis.detected_patterns.length === 0) {
      const li = document.createElement('li');
      li.textContent = 'No suspicious keywords detected';
      li.style.color = '#10b981';
      patternsList.appendChild(li);
    }
  }

  // Add suspicious skills if present
  if (nlpAnalysis.suspicious_skills && nlpAnalysis.suspicious_skills.length > 0) {
    const skillsDiv = document.createElement('div');
    skillsDiv.style.marginTop = '12px';
    skillsDiv.innerHTML = '<div style="font-weight: 500; color: #e2e8f0; margin-bottom: 8px;">Suspicious Skill Signals:</div>';
    const skillsList = document.createElement('ul');
    skillsList.className = 'patterns-list';
    nlpAnalysis.suspicious_skills.forEach((skill) => {
      const li = document.createElement('li');
      li.textContent = skill;
      skillsList.appendChild(li);
    });
    skillsDiv.appendChild(skillsList);
    document.getElementById('nlpPatterns').appendChild(skillsDiv);
  }
}

/**
 * Populate Rule-Based Analysis Card
 */
function populateRuleAnalysis(ruleAnalysis) {
  const ruleScore = document.getElementById('ruleScore');
  const ruleScoreBar = document.getElementById('ruleScoreBar');
  const triggeredRuleCount = document.getElementById('triggeredRuleCount');
  const rulesList = document.getElementById('rulesList');

  if (ruleScore) ruleScore.textContent = ruleAnalysis.score;
  if (ruleScoreBar) ruleScoreBar.style.width = ruleAnalysis.score + '%';
  if (triggeredRuleCount) triggeredRuleCount.textContent = ruleAnalysis.total_triggered;

  // Add triggered rules
  if (rulesList && ruleAnalysis.triggered_rules) {
    rulesList.innerHTML = '';

    if (ruleAnalysis.triggered_rules.length === 0) {
      const noRules = document.createElement('div');
      noRules.style.cssText =
        'padding: 8px; color: #10b981; font-size: 0.9rem; text-align: center;';
      noRules.textContent = '✓ No suspicious rules triggered';
      rulesList.appendChild(noRules);
    } else {
      ruleAnalysis.triggered_rules.forEach((rule) => {
        const ruleItem = document.createElement('div');
        
        // Apply CRITICAL styling for critical payment rule
        const isCritical = rule.category && rule.category.includes('CRITICAL');
        if (isCritical) {
          ruleItem.className = 'rule-item rule-item-critical';
          ruleItem.style.cssText = `
            background: rgba(239, 68, 68, 0.15) !important;
            border-left-color: #ef4444 !important;
            border: 2px solid rgba(239, 68, 68, 0.5);
            padding: 12px 14px;
            border-radius: 8px;
            margin-bottom: 12px;
          `;
        } else {
          ruleItem.className = 'rule-item';
        }
        
        ruleItem.innerHTML = `
          <div class="rule-item-title">
            <span>${rule.rule}</span>
            <span class="rule-points" style="${isCritical ? 'color: #fca5a5; font-weight: 700;' : ''}">${rule.risk_points} pts</span>
          </div>
          <div class="rule-category" style="${isCritical ? 'color: #ef4444; font-weight: 600;' : ''}">${isCritical ? '⚠️ ' : '📁 '}${rule.category}</div>
          <div class="rule-explanation">${rule.explanation}</div>
        `;
        rulesList.appendChild(ruleItem);
      });
    }
  }
}

/**
 * Populate Community Analysis Card
 */
function populateCommunityAnalysis(communityAnalysis) {
  const communityScore = document.getElementById('communityScore');
  const communityScoreBar = document.getElementById('communityScoreBar');
  const communityConfidence = document.getElementById('communityConfidence');
  const communityReports = document.getElementById('communityReports');

  if (communityScore) communityScore.textContent = communityAnalysis.score;
  if (communityScoreBar) communityScoreBar.style.width = communityAnalysis.score + '%';

  if (communityConfidence) {
    communityConfidence.textContent = communityAnalysis.confidence;
    communityConfidence.className = 'confidence-badge confidence-' + (
      communityAnalysis.score > 0 ? 'high' : 'low'
    );
  }

  // Add report info
  if (communityReports) {
    communityReports.innerHTML = '';
    const reportItem = document.createElement('div');
    reportItem.className = 'analysis-item';
    if (communityAnalysis.reports > 0) {
      reportItem.innerHTML = `
        <span class="analysis-item-label">📊 Community Reports: <span style="color:#fca5a5">${communityAnalysis.reports}</span></span>
        <span class="analysis-item-value">Similar scams reported by other users</span>
      `;
    } else {
      reportItem.innerHTML = `
        <span class="analysis-item-label">✓ No community reports</span>
        <span class="analysis-item-value">This job hasn't been reported yet</span>
      `;
    }
    communityReports.appendChild(reportItem);
  }
}

/**
 * Populate Final Verdict Card
 */
function populateVerdict(verdict) {
  const verdictIcon = document.getElementById('verdictIcon');
  const verdictTitle = document.getElementById('verdictTitle');
  const verdictReason = document.getElementById('verdictReason');
  const recommendationsList = document.getElementById('recommendationsList');
  const verdictCard = document.getElementById('verdictCard');

  // Set icon
  if (verdictIcon) verdictIcon.textContent = verdict.icon;

  // Set title with color based on risk level
  if (verdictTitle) {
    verdictTitle.textContent = verdict.risk_level;
    if (verdict.risk_level.includes('LOW')) {
      verdictTitle.style.color = '#10b981';
    } else if (verdict.risk_level.includes('MEDIUM')) {
      verdictTitle.style.color = '#f59e0b';
    } else {
      verdictTitle.style.color = '#ef4444';
    }
  }

  // Highlight if critical payment detected
  if (verdict.has_critical_payment && verdictCard) {
    verdictCard.style.borderColor = '#ef4444';
    verdictCard.style.borderWidth = '2px';
    verdictCard.style.background = 'linear-gradient(135deg, rgba(127, 29, 29, 0.3), rgba(80, 20, 20, 0.3))';
  }

  // Set reason
  if (verdictReason) verdictReason.textContent = verdict.reason;

  // Add recommendations
  if (recommendationsList && verdict.recommendations) {
    recommendationsList.innerHTML = '';
    verdict.recommendations.forEach((rec) => {
      const recItem = document.createElement('div');
      recItem.className = 'verdict-rec-item';
      
      // Highlight critical payment warnings
      if (rec.includes('NEVER') || rec.includes('payment')) {
        recItem.style.cssText = 'color: #fca5a5; font-weight: 600; padding: 10px 0;';
      }
      
      recItem.textContent = rec;
      recommendationsList.appendChild(recItem);
    });
  }
}

/**
 * Main initialization - call this from result.html after DOM is ready
 */
function initializeAnalysis(analysisData) {
  console.log('Initializing analysis display');
  populateAnalysisCards(analysisData);
}

// Export for use in HTML
window.initializeAnalysis = initializeAnalysis;
window.populateAnalysisCards = populateAnalysisCards;
