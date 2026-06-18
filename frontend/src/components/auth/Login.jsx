import { useState } from 'react';
import { motion } from 'framer-motion';
import { Link } from 'react-router-dom';
import CyberBackground from '../effects/CyberBackground';
import { login, getErrorMessage } from '../../lib/api';
import './AuthPages.css';

export default function Login() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [showPassword, setShowPassword] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      const data = await login(email, password);
      // Redirect to dashboard on success
      window.location.href = '/dashboard';
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
            <h2 className="auth-heading">Welcome back</h2>
            <p className="auth-subheading">Sign in to your account to continue</p>
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
            {/* Email field */}
            <motion.div className="form-group" variants={itemVariants}>
              <label htmlFor="email" className="form-label">
                Email address
              </label>
              <input
                id="email"
                type="email"
                placeholder="Enter your email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                className="form-input"
                disabled={loading}
              />
            </motion.div>

            {/* Password field */}
            <motion.div className="form-group" variants={itemVariants}>
              <div className="form-label-row">
                <label htmlFor="password" className="form-label">
                  Password
                </label>
                <Link to="/forgot-password" className="form-link">
                  Forgot password?
                </Link>
              </div>
              <div className="password-input-wrapper">
                <input
                  id="password"
                  type={showPassword ? 'text' : 'password'}
                  placeholder="Enter your password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
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
                'Sign in'
              )}
            </motion.button>
          </form>

          {/* Divider */}
          <div className="form-divider">
            <span>Don't have an account?</span>
          </div>

          {/* Sign up link */}
          <motion.div variants={itemVariants}>
            <Link to="/signup" className="auth-signup-link">
              Create new account
            </Link>
          </motion.div>

          {/* Footer text */}
          <p className="auth-footer-text">
            By signing in, you agree to our{' '}
            <a href="/terms" target="_blank" rel="noopener noreferrer">
              Terms of Service
            </a>{' '}
            and{' '}
            <a href="/privacy" target="_blank" rel="noopener noreferrer">
              Privacy Policy
            </a>
          </p>
        </div>
      </motion.div>
    </CyberBackground>
  );
}
