-- Run this in Supabase SQL Editor for any missing tables

-- Table 1: job_posts
CREATE TABLE IF NOT EXISTS job_posts (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    title TEXT,
    company_name TEXT,
    salary NUMERIC,
    location TEXT,
    description TEXT,
    skills TEXT,
    posted_date DATE DEFAULT CURRENT_DATE,
    source_url TEXT,
    domain_name TEXT,
    scam_score FLOAT DEFAULT 0,
    risk_level TEXT DEFAULT 'Unknown',
    is_flagged BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Table 2: recruiter_profiles
CREATE TABLE IF NOT EXISTS recruiter_profiles (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    recruiter_name TEXT,
    email TEXT,
    company TEXT,
    linkedin_url TEXT,
    domain_name TEXT,
    verified BOOLEAN DEFAULT FALSE,
    previous_reports INT DEFAULT 0,
    blacklisted BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Table 3: domain_reputation
CREATE TABLE IF NOT EXISTS domain_reputation (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    domain_name TEXT UNIQUE,
    domain_age_days INT DEFAULT 0,
    ssl_valid BOOLEAN DEFAULT TRUE,
    trust_score FLOAT DEFAULT 0.5,
    blacklisted BOOLEAN DEFAULT FALSE,
    whois_checked_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Table 4: flagged_keywords
CREATE TABLE IF NOT EXISTS flagged_keywords (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    keyword TEXT UNIQUE,
    fraud_weight FLOAT DEFAULT 0.5,
    category TEXT DEFAULT 'general',
    created_at TIMESTAMP DEFAULT NOW()
);

-- Seed flagged_keywords with existing FRAUD_KEYWORDS from app.py
INSERT INTO flagged_keywords (keyword, fraud_weight) VALUES
('registration fee', 0.95),
('security deposit', 0.95),
('training fee', 0.90),
('whatsapp hr', 0.91),
('instant joining', 0.82),
('earn daily', 0.77),
('work from home earn', 0.80),
('no experience needed', 0.65),
('limited seats', 0.69),
('no interview', 0.75),
('government job guaranteed', 0.88),
('100% placement guaranteed', 0.85)
ON CONFLICT (keyword) DO NOTHING;

-- Table 5: company_reputation
CREATE TABLE IF NOT EXISTS company_reputation (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    company_name TEXT,
    domain TEXT,
    listing_url TEXT,
    report_reason TEXT,
    user_id TEXT,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Table 6: ai_chat_sessions
CREATE TABLE IF NOT EXISTS ai_chat_sessions (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id TEXT,
    title TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Table 7: ai_chat_messages
CREATE TABLE IF NOT EXISTS ai_chat_messages (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    session_id UUID REFERENCES ai_chat_sessions(id) ON DELETE CASCADE,
    role TEXT,
    content TEXT,
    documents JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

