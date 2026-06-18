import { useState } from 'react';
import { motion } from 'framer-motion';
import { Link } from 'react-router-dom';
import CyberBackground from '../effects/CyberBackground';
import { signup, validateEmail, validatePassword, getErrorMessage } from '../../lib/api';
import './AuthPages.css';

export default function Signup() {
  const [formData, setFormData] = useState({
    full_name: '',
    email: '',
    password: '',
    confirm_password: '',
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);

  const handleChange = (e) => {
    const { name, value } = e.target;
    setFormData((prev) => ({
      ...prev,
      [name]: value,
    }));
    setError('');
  };

  const validateForm = () => {
    if (!formData.full_name.trim()) {
      setError('Full name is required');
      return false;
    }
    if (!validateEmail(formData.email)) {
      setError('Valid email is required');
      return false;
    }
    if (formData.password.length < 8) {
      setError('Password must be at least 8 characters');
      return false;
    }
    if (formData.password !== formData.confirm_password) {
      setError('Passwords do not match');
      return false;
    }
    return true;
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    if (!validateForm()) {
      return;
    }

    setLoading(true);

    try {
      await signup(formData.full_name, formData.email, formData.password);

      setSuccess(true);
      setFormData({
        full_name: '',
        email: '',
        password: '',
        confirm_password: '',
      });

      // Redirect after 2 seconds
      setTimeout(() => {
        window.location.href = '/login?registered=true';
      }, 2000);
    } catch (err) {
      setError(getErrorMessage(err));
      setLoading(false);
    }
  };

  const containerVariants = {
    hidden: { opacity: 0, y: 20 },
    visible: {
      opacity: 1,
      y: 0,
      transition: {
        duration: 0.6,
        ease: 'easeOut',
      },
    },
  };

  const itemVariants = {
    hidden: { opacity: 0, y: 10 },
    visible: {
      opacity: 1,
      y: 0,
      transition: {
        duration: 0.4,
      },
    },
  };

  if (success) {
    return (
      <CyberBackground>
        <motion.div
          className="auth-container"
          variants={containerVariants}
          initial="hidden"
          animate="visible"
        >
          <div className="auth-card">
            <motion.div
              className="success-message"
              animate={{ scale: [0.8, 1] }}
              transition={{ duration: 0.5 }}
            >
              <div className="success-icon">
                <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
                  <circle cx="24" cy="24" r="22" stroke="#6339e4" strokeWidth="2" />
                  <path
                    d="M18 24L22 28L30 16"
                    stroke="#6339e4"
                    strokeWidth="2.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </div>
              <h2 className="success-title">Account created!</h2>
              <p className="success-text">
                Your account has been created successfully. Redirecting to login...
              </p>
            </motion.div>
          </div>
        </motion.div>
      </CyberBackground>
    );
  }

  return (
    <CyberBackground>
      <motion.div
        className="auth-container"
        variants={containerVariants}
        initial="hidden"
        animate="visible"
      >
        <div className="auth-card">
          {/* Logo section */}
          <motion.div className="auth-logo-section" variants={itemVariants}>
            <div className="auth-logo-icon">
              <svg
                width="32"
                height="32"
                viewBox="0 0 32 32"
                fill="none"
                xmlns="http://www.w3.org/2000/svg"
              >
                <path
                  d="M16 2L28 8V16C28 24.8366 16 30 16 30C16 30 4 24.8366 4 16V8L16 2Z"
                  stroke="#6339e4"
                  strokeWidth="2"
                  fill="none"
                />
                <path
                  d="M12 16L14.5 18.5L20 12"
                  stroke="#6339e4"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </div>
            <h1 className="auth-title">ScamShield</h1>
          </motion.div>

          {/* Heading */}
          <motion.div variants={itemVariants}>
            <h2 className="auth-heading">Create your account</h2>
            <p className="auth-subheading">Join us to detect and protect against job scams</p>
          </motion.div>

          {/* Error message */}
          {error && (
            <motion.div
              className="auth-error"
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
            >
              {error}
            </motion.div>
          )}

          {/* Form */}
          <form onSubmit={handleSubmit} className="auth-form">
            {/* Full name field */}
            <motion.div className="form-group" variants={itemVariants}>
              <label htmlFor="full_name" className="form-label">
                Full name
              </label>
              <input
                id="full_name"
                type="text"
                name="full_name"
                placeholder="Enter your full name"
                value={formData.full_name}
                onChange={handleChange}
                required
                className="form-input"
                disabled={loading}
              />
            </motion.div>

            {/* Email field */}
            <motion.div className="form-group" variants={itemVariants}>
              <label htmlFor="email" className="form-label">
                Email address
              </label>
              <input
                id="email"
                type="email"
                name="email"
                placeholder="Enter your email"
                value={formData.email}
                onChange={handleChange}
                required
                className="form-input"
                disabled={loading}
              />
            </motion.div>

            {/* Password field */}
            <motion.div className="form-group" variants={itemVariants}>
              <label htmlFor="password" className="form-label">
                Password
              </label>
              <div className="password-input-wrapper">
                <input
                  id="password"
                  type={showPassword ? 'text' : 'password'}
                  name="password"
                  placeholder="Create a strong password"
                  value={formData.password}
                  onChange={handleChange}
                  required
                  className="form-input"
                  disabled={loading}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="password-toggle"
                  disabled={loading}
                >
                  {showPassword ? (
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                      <path
                        d="M3 12s2-8 9-8 9 8 9 8-2 8-9 8-9-8-9-8z"
                        stroke="currentColor"
                        strokeWidth="2"
                      />
                      <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="2" />
                    </svg>
                  ) : (
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                      <path
                        d="M3 3l18 18M6.5 9.5C5 11 4 12 4 12s2 8 8 8c1.5 0 2.8-.3 3.9-.8M12.5 7C15.5 7 18 9 19.5 11.5"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                      />
                    </svg>
                  )}
                </button>
              </div>
              <p className="form-hint">At least 8 characters</p>
            </motion.div>

            {/* Confirm password field */}
            <motion.div className="form-group" variants={itemVariants}>
              <label htmlFor="confirm_password" className="form-label">
                Confirm password
              </label>
              <div className="password-input-wrapper">
                <input
                  id="confirm_password"
                  type={showConfirm ? 'text' : 'password'}
                  name="confirm_password"
                  placeholder="Re-enter your password"
                  value={formData.confirm_password}
                  onChange={handleChange}
                  required
                  className="form-input"
                  disabled={loading}
                />
                <button
                  type="button"
                  onClick={() => setShowConfirm(!showConfirm)}
                  className="password-toggle"
                  disabled={loading}
                >
                  {showConfirm ? (
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                      <path
                        d="M3 12s2-8 9-8 9 8 9 8-2 8-9 8-9-8-9-8z"
                        stroke="currentColor"
                        strokeWidth="2"
                      />
                      <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="2" />
                    </svg>
                  ) : (
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                      <path
                        d="M3 3l18 18M6.5 9.5C5 11 4 12 4 12s2 8 8 8c1.5 0 2.8-.3 3.9-.8M12.5 7C15.5 7 18 9 19.5 11.5"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                      />
                    </svg>
                  )}
                </button>
              </div>
            </motion.div>

            {/* Terms checkbox */}
            <motion.div className="form-group form-checkbox-group" variants={itemVariants}>
              <label className="form-checkbox">
                <input type="checkbox" required disabled={loading} />
                <span>
                  I agree to the{' '}
                  <a href="/terms" target="_blank" rel="noopener noreferrer">
                    Terms of Service
                  </a>{' '}
                  and{' '}
                  <a href="/privacy" target="_blank" rel="noopener noreferrer">
                    Privacy Policy
                  </a>
                </span>
              </label>
            </motion.div>

            {/* Submit button */}
            <motion.button
              type="submit"
              className="auth-button"
              disabled={loading}
              variants={itemVariants}
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
            >
              {loading ? (
                <motion.span
                  animate={{ rotate: 360 }}
                  transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}
                  className="spinner"
                />
              ) : (
                'Create account'
              )}
            </motion.button>
          </form>

          {/* Divider */}
          <div className="form-divider">
            <span>Already have an account?</span>
          </div>

          {/* Sign in link */}
          <motion.div variants={itemVariants}>
            <Link to="/login" className="auth-signup-link">
              Sign in instead
            </Link>
          </motion.div>
        </div>
      </motion.div>
    </CyberBackground>
  );
}
