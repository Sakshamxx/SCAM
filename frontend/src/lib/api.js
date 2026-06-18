/**
 * API utility functions for authentication and app communication
 * Integrates with Flask backend endpoints
 */

const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:5000';

/**
 * Generic API request handler
 * @param {string} endpoint - The API endpoint (without domain)
 * @param {string} method - HTTP method (GET, POST, etc.)
 * @param {object} body - Request body for POST/PUT requests
 * @returns {Promise<object>} - Parsed JSON response
 */
async function apiRequest(endpoint, method = 'GET', body = null) {
  const token = localStorage.getItem('token');
  const headers = {
    'Content-Type': 'application/json',
  };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const config = {
    method,
    headers,
  };

  if (body && (method === 'POST' || method === 'PUT' || method === 'PATCH')) {
    config.body = JSON.stringify(body);
  }

  try {
    const response = await fetch(`${API_BASE_URL}${endpoint}`, config);
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.message || `HTTP ${response.status}`);
    }

    return data;
  } catch (error) {
    console.error(`API Error [${method} ${endpoint}]:`, error);
    throw error;
  }
}

/**
 * User Authentication APIs
 */

/**
 * Sign up a new user
 * @param {string} fullName - User's full name
 * @param {string} email - User's email address
 * @param {string} password - User's password
 * @returns {Promise<object>} - { user, message, token }
 */
export async function signup(fullName, email, password) {
  return apiRequest('/api/signup', 'POST', {
    full_name: fullName,
    email,
    password,
  });
}

/**
 * Sign in an existing user
 * @param {string} email - User's email address
 * @param {string} password - User's password
 * @returns {Promise<object>} - { token, user }
 */
export async function login(email, password) {
  const data = await apiRequest('/api/login', 'POST', {
    email,
    password,
  });

  // Store token for future requests
  if (data.token) {
    localStorage.setItem('token', data.token);
  }

  return data;
}

/**
 * Sign out the current user
 * @returns {Promise<object>} - { message }
 */
export async function logout() {
  try {
    await apiRequest('/api/logout', 'POST');
  } finally {
    // Always clear local token regardless of API response
    localStorage.removeItem('token');
  }
}

/**
 * Get current user information
 * @returns {Promise<object>} - User data
 */
export async function getCurrentUser() {
  return apiRequest('/api/user', 'GET');
}

/**
 * Request password reset
 * @param {string} email - User's email address
 * @returns {Promise<object>} - { message }
 */
export async function requestPasswordReset(email) {
  return apiRequest('/api/password-reset', 'POST', { email });
}

/**
 * Reset password with token
 * @param {string} token - Password reset token
 * @param {string} password - New password
 * @returns {Promise<object>} - { message }
 */
export async function resetPassword(token, password) {
  return apiRequest('/api/password-reset/confirm', 'POST', {
    token,
    password,
  });
}

/**
 * Verify email address
 * @param {string} email - Email to verify
 * @param {string} code - Verification code
 * @returns {Promise<object>} - { message }
 */
export async function verifyEmail(email, code) {
  return apiRequest('/api/verify-email', 'POST', {
    email,
    code,
  });
}

/**
 * Scam Detection APIs
 */

/**
 * Analyze a job listing for scam signals
 * @param {string} jobTitle - Job title
 * @param {string} jobDescription - Full job description
 * @param {string} companyName - Company name
 * @returns {Promise<object>} - { risk_score, signals, analysis }
 */
export async function analyzeJobListing(jobTitle, jobDescription, companyName) {
  return apiRequest('/api/analyze', 'POST', {
    job_title: jobTitle,
    job_description: jobDescription,
    company_name: companyName,
  });
}

/**
 * Verify company information
 * @param {string} companyName - Company name to verify
 * @param {string} companyEmail - Company email domain
 * @returns {Promise<object>} - { verified, reputation, details }
 */
export async function verifyCompany(companyName, companyEmail) {
  return apiRequest('/api/verify-company', 'POST', {
    company_name: companyName,
    company_email: companyEmail,
  });
}

/**
 * Check domain legitimacy
 * @param {string} domain - Domain to check
 * @returns {Promise<object>} - { is_legitimate, risk_level, details }
 */
export async function checkDomain(domain) {
  return apiRequest('/api/check-domain', 'POST', { domain });
}

/**
 * Report a suspected scam
 * @param {string} jobTitle - Job title
 * @param {string} companyName - Company name
 * @param {string} description - Description of the scam
 * @param {string} email - Reporter's email (optional)
 * @returns {Promise<object>} - { message, report_id }
 */
export async function reportScam(jobTitle, companyName, description, email = null) {
  return apiRequest('/api/report-scam', 'POST', {
    job_title: jobTitle,
    company_name: companyName,
    description,
    email,
  });
}

/**
 * Get scam statistics
 * @returns {Promise<object>} - { total_reports, active_scams, recent_alerts }
 */
export async function getScamStats() {
  return apiRequest('/api/stats', 'GET');
}

/**
 * User Dashboard APIs
 */

/**
 * Get user's analysis history
 * @param {number} limit - Number of records to fetch (default: 10)
 * @param {number} offset - Pagination offset (default: 0)
 * @returns {Promise<object>} - { analyses, total, page }
 */
export async function getAnalysisHistory(limit = 10, offset = 0) {
  return apiRequest(`/api/history?limit=${limit}&offset=${offset}`, 'GET');
}

/**
 * Get a specific analysis report
 * @param {string} analysisId - Analysis ID
 * @returns {Promise<object>} - Full analysis report data
 */
export async function getAnalysisReport(analysisId) {
  return apiRequest(`/api/analysis/${analysisId}`, 'GET');
}

/**
 * Delete an analysis
 * @param {string} analysisId - Analysis ID to delete
 * @returns {Promise<object>} - { message }
 */
export async function deleteAnalysis(analysisId) {
  return apiRequest(`/api/analysis/${analysisId}`, 'DELETE');
}

/**
 * Update user profile
 * @param {object} updates - Profile updates (name, email, etc.)
 * @returns {Promise<object>} - Updated user data
 */
export async function updateProfile(updates) {
  return apiRequest('/api/user/profile', 'PUT', updates);
}

/**
 * Change user password
 * @param {string} currentPassword - Current password
 * @param {string} newPassword - New password
 * @returns {Promise<object>} - { message }
 */
export async function changePassword(currentPassword, newPassword) {
  return apiRequest('/api/user/change-password', 'POST', {
    current_password: currentPassword,
    new_password: newPassword,
  });
}

/**
 * Community APIs
 */

/**
 * Get community reports and discussions
 * @param {number} limit - Number of records to fetch
 * @param {number} offset - Pagination offset
 * @returns {Promise<object>} - { reports, total }
 */
export async function getCommunityReports(limit = 20, offset = 0) {
  return apiRequest(`/api/community/reports?limit=${limit}&offset=${offset}`, 'GET');
}

/**
 * Post a community comment
 * @param {string} reportId - Report ID to comment on
 * @param {string} comment - Comment text
 * @returns {Promise<object>} - { message, comment_id }
 */
export async function postComment(reportId, comment) {
  return apiRequest('/api/community/comment', 'POST', {
    report_id: reportId,
    comment,
  });
}

/**
 * Utility Functions
 */

/**
 * Check if user is authenticated
 * @returns {boolean} - True if token exists
 */
export function isAuthenticated() {
  return !!localStorage.getItem('token');
}

/**
 * Get stored authentication token
 * @returns {string|null} - Authentication token or null
 */
export function getToken() {
  return localStorage.getItem('token');
}

/**
 * Clear authentication token
 */
export function clearToken() {
  localStorage.removeItem('token');
}

/**
 * Handle API error and extract user-friendly message
 * @param {Error} error - The error object
 * @returns {string} - User-friendly error message
 */
export function getErrorMessage(error) {
  if (error.message) {
    return error.message;
  }
  return 'An unexpected error occurred. Please try again.';
}

/**
 * Validate email format
 * @param {string} email - Email to validate
 * @returns {boolean} - True if valid
 */
export function validateEmail(email) {
  const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  return re.test(email);
}

/**
 * Validate password strength
 * @param {string} password - Password to validate
 * @returns {object} - { isValid, strength, message }
 */
export function validatePassword(password) {
  const checks = {
    length: password.length >= 8,
    uppercase: /[A-Z]/.test(password),
    lowercase: /[a-z]/.test(password),
    numbers: /\d/.test(password),
    special: /[!@#$%^&*()_+\-=\[\]{};':"\\|,.<>\/?]/.test(password),
  };

  const passedChecks = Object.values(checks).filter(Boolean).length;
  let strength = 'weak';
  let message = 'Password is weak';

  if (passedChecks >= 4) {
    strength = 'strong';
    message = 'Password is strong';
  } else if (passedChecks >= 3) {
    strength = 'medium';
    message = 'Password is medium strength';
  }

  return {
    isValid: checks.length,
    strength,
    message,
    checks,
  };
}

export default {
  // Auth
  signup,
  login,
  logout,
  getCurrentUser,
  requestPasswordReset,
  resetPassword,
  verifyEmail,

  // Scam Detection
  analyzeJobListing,
  verifyCompany,
  checkDomain,
  reportScam,
  getScamStats,

  // Dashboard
  getAnalysisHistory,
  getAnalysisReport,
  deleteAnalysis,
  updateProfile,
  changePassword,

  // Community
  getCommunityReports,
  postComment,

  // Utilities
  isAuthenticated,
  getToken,
  clearToken,
  getErrorMessage,
  validateEmail,
  validatePassword,
};
