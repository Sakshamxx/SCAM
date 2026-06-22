import pickle
import joblib
from scam_detector.config.settings import MODEL_DIR

def _load_pickle(name):
    """Load a pickle file from models directory."""
    path = MODEL_DIR / name
    if path.exists():
        try:
            with open(path, 'rb') as f:
                return pickle.load(f)
        except Exception as e:
            print(f"[warn] Failed to load {name}: {e}")
    return None

# Load models and configurations
nlp_model       = _load_pickle('nlp_model.pkl')          # Naive Bayes NLP model (TF-IDF only)
ml_model        = _load_pickle('ml_model.pkl')           # Best ML model (LR/RF/XGB on full features)
tfidf_vec       = _load_pickle('tfidf_vectorizer.pkl')   # TF-IDF vectorizer
trigram_vec     = _load_pickle('trigram_vectorizer.pkl') # Trigram vectorizer
label_encoder   = _load_pickle('label_encoder.pkl')      # Label encoder (Legit/Scam/Suspicious)
feature_config  = _load_pickle('feature_config.pkl')     # Feature config & fraud keywords

# Fallback models (corrupted or missing in production)
nlp_pipeline    = None
logistic_model  = None
scaler          = None

# Encoding maps
le_location     = _load_pickle('le_location.pkl')
le_title        = _load_pickle('le_title.pkl')

nlp_le_location = le_location
nlp_le_title    = le_title
tfidf_vectorizer = tfidf_vec

if feature_config and 'fraud_keywords' in feature_config:
    _feature_config_keywords = feature_config['fraud_keywords']
else:
    _feature_config_keywords = []

# Status output function
def print_model_status():
    print("\n" + "=" * 55)
    print("ScamShield v3.0 — Hybrid Model Status")
    print("=" * 55)
    print(f"NLP Model (Naive Bayes):    {'✅ Loaded' if nlp_model else '❌ Missing'}")
    print(f"ML Model (Best Ensemble):   {'✅ Loaded' if ml_model else '❌ Missing'}")
    print(f"TF-IDF Vectorizer:          {'✅ Loaded' if tfidf_vec else '❌ Missing'}")
    print(f"Trigram Vectorizer:         {'✅ Loaded' if trigram_vec else '❌ Missing'}")
    print(f"Label Encoder:              {'✅ Loaded' if label_encoder else '❌ Missing'}")
    print(f"Feature Config:             {'✅ Loaded' if feature_config else '❌ Missing'}")
    print(f"Legacy NLP Pipeline:        {'✅ Loaded' if nlp_pipeline else '⚠ Not found (using new model)'}")
    print("=" * 55 + "\n")


# ── Model Cleaning & Inference Helpers ──
import re
import numpy as np
import urllib.parse
from scipy.sparse import hstack, csr_matrix

STOPWORDS_SET = {
    'the','a','an','and','or','but','in','on','at','to','for','of','is','it',
    'this','that','be','as','by','with','are','was','were','has','have','will',
    'from','we','our','you','your','their','its','not','no','can','about',
    'also','any','all','more','than','they','us','do','does','did','been',
    'if','then','so','such','each','per','should','may','would','could','when',
    'into','out','up','down','day','time','make','new','use','get','work'
}

def clean_text_for_model(text):
    """Clean text to match training preprocessing."""
    text = str(text).lower()
    text = re.sub(r'http\S+|www\S+', ' url ', text)
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    text = re.sub(r'\d+', ' num ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    tokens = [w for w in text.split() if w not in STOPWORDS_SET and len(w) > 2]
    return ' '.join(tokens)

def run_new_model_inference(job_text, job_title='', skills=''):
    """
    Run inference using the new trained NLP model and ML model.
    Returns:
        nlp_score (0-100): NLP model scam probability score
        ml_score  (0-100): ML  model scam probability score
    """
    nlp_score = 0.0
    ml_score  = 0.0

    combined = (
        clean_text_for_model(job_title) + ' ' +
        clean_text_for_model(job_text)  + ' ' +
        clean_text_for_model(skills)
    ).strip()

    if not combined or not tfidf_vec:
        print('[inference] Skipping — empty text or missing tfidf_vec')
        return nlp_score, ml_score

    try:
        X_tfidf = tfidf_vec.transform([combined])
        print(f'[inference] X_tfidf shape: {X_tfidf.shape}')

        # NLP Model
        if nlp_model is not None:
            nlp_proba = nlp_model.predict_proba(X_tfidf)[0]
            classes_list = nlp_model.classes_.tolist()
            scam_idx = classes_list.index(1) if 1 in classes_list else -1
            susp_idx = classes_list.index(2) if 2 in classes_list else -1
            scam_prob = float(nlp_proba[scam_idx]) if scam_idx >= 0 else 0.0
            susp_prob = float(nlp_proba[susp_idx]) if susp_idx >= 0 else 0.0
            nlp_score = round(min(100.0, scam_prob * 100.0 + susp_prob * 50.0), 1)
            print(f'[inference] nlp_score: {nlp_score}  (scam_prob={scam_prob:.4f}, susp_prob={susp_prob:.4f})')

        # ML Model
        if ml_model is not None and trigram_vec is not None:
            X_tri = trigram_vec.transform([combined])
            print(f'[inference] X_tri shape: {X_tri.shape}')

            n_tfidf   = X_tfidf.shape[1]
            n_tri     = X_tri.shape[1]
            n_ml_exp  = getattr(ml_model, 'n_features_in_', n_tfidf + n_tri)
            n_struct  = n_ml_exp - n_tfidf - n_tri

            if n_struct < 0:
                n_struct = 0

            if n_struct > 0:
                X_struct_zeros = csr_matrix(np.zeros((1, n_struct)))
                X_full = hstack([X_tfidf, X_tri, X_struct_zeros])
            else:
                X_full = hstack([X_tfidf, X_tri])

            print(f'[inference] X_full shape: {X_full.shape}  (n_struct_pad={n_struct})')

            ml_proba = ml_model.predict_proba(X_full)[0]
            classes_list = ml_model.classes_.tolist()
            scam_idx = classes_list.index(1) if 1 in classes_list else -1
            susp_idx = classes_list.index(2) if 2 in classes_list else -1
            scam_prob = float(ml_proba[scam_idx]) if scam_idx >= 0 else 0.0
            susp_prob = float(ml_proba[susp_idx]) if susp_idx >= 0 else 0.0
            ml_score = round(min(100.0, scam_prob * 100.0 + susp_prob * 50.0), 1)
            print(f'[inference] ml_score:  {ml_score}  (scam_prob={scam_prob:.4f}, susp_prob={susp_prob:.4f})')

        elif ml_model is not None:
            n_ml_exp = getattr(ml_model, 'n_features_in_', X_tfidf.shape[1])
            n_pad    = n_ml_exp - X_tfidf.shape[1]
            if n_pad > 0:
                X_full = hstack([X_tfidf, csr_matrix(np.zeros((1, n_pad)))])
            else:
                X_full = X_tfidf
            ml_proba   = ml_model.predict_proba(X_full)[0]
            classes_list = ml_model.classes_.tolist()
            scam_idx = classes_list.index(1) if 1 in classes_list else -1
            susp_idx = classes_list.index(2) if 2 in classes_list else -1
            scam_prob = float(ml_proba[scam_idx]) if scam_idx >= 0 else 0.0
            susp_prob = float(ml_proba[susp_idx]) if susp_idx >= 0 else 0.0
            ml_score  = round(min(100.0, scam_prob * 100.0 + susp_prob * 50.0), 1)

    except Exception as e:
        import traceback
        print(f'[inference] ERROR in run_new_model_inference: {e}')
        traceback.print_exc()

    return nlp_score, ml_score

def normalize_text(text_val):
    text_val = str(text_val).lower().strip()
    text_val = re.sub(r"https?://\S+|www\.\S+", "[url]", text_val)
    text_val = re.sub(r"\S+@\S+\.\S+", "[email]", text_val)
    text_val = re.sub(r"\b\d+\b", "[num]", text_val)
    text_val = re.sub(r"\s+", " ", text_val).strip()
    return text_val

def parse_experience(val):
    if val is None or val == '':
        return 0.0
    val_str = str(val).lower().strip()
    if "fresher" in val_str or "entry" in val_str:
        return 0.0
    match = re.search(r"(\d+)", val_str)
    return float(match.group(1)) if match else 0.0

def parse_salary(val):
    if val is None or val == '':
        return 0.0
    nums = re.findall(r"\d+", str(val).replace(",", ""))
    if nums:
        return float(nums[0])
    return 0.0

def safe_encode(le, val, default_val='Unknown'):
    """Safely encode a value using a sklearn LabelEncoder."""
    if le is None:
        return 0
    if not hasattr(le, 'classes_') or not hasattr(le, 'transform'):
        print(f'[safe_encode] WARNING: le is {type(le).__name__}, not a LabelEncoder — returning 0')
        return 0
    val_clean = str(val).strip()
    try:
        classes = le.classes_.tolist() if hasattr(le.classes_, 'tolist') else list(le.classes_)
        if val_clean in classes:
            return int(le.transform([val_clean])[0])
        val_lower = val_clean.lower()
        for idx, c in enumerate(classes):
            if str(c).lower().strip() == val_lower:
                return idx
        if default_val in classes:
            return int(le.transform([default_val])[0])
    except Exception as _se_err:
        print(f'[safe_encode] ERROR encoding "{val}": {_se_err}')
    return 0

def check_domain_risk(url):
    """Assign domain risk (0–100) based on URL patterns."""
    if not url or url.strip() == '':
        return 30.0

    url_lower = url.lower()
    suspicious_words = ['free', 'earn', 'job-hiring', 'work-from-home', 'daily-earn',
                        'part-time', 'online-job', 'home-job', 'gig', 'quick-money']
    trusted_domains = ['linkedin.com', 'naukri.com', 'indeed.com', 'internshala.com',
                       'glassdoor.com', 'monster.com', 'shine.com', 'foundit.in',
                       'adzuna.in', 'timesjobs.com', 'freshersworld.com']

    if any(td in url_lower for td in trusted_domains):
        return 10.0

    risk = 30.0
    if any(sw in url_lower for sw in suspicious_words):
        risk += 30.0

    free_hosts = ['blogspot', 'wordpress.com', 'weebly', 'wix.com', 'sites.google', 'jimdo']
    if any(fh in url_lower for fh in free_hosts):
        risk += 25.0

    shorteners = ['bit.ly', 'tinyurl', 'goo.gl', 't.co', 'ow.ly', 'is.gd', 'rb.gy']
    if any(sh in url_lower for sh in shorteners):
        risk += 35.0

    big_brands = ['google', 'amazon', 'microsoft', 'flipkart', 'infosys', 'tcs', 'wipro']
    parsed = urllib.parse.urlparse(url_lower)
    domain = parsed.netloc
    for brand in big_brands:
        if brand in domain and not domain.startswith(brand + '.'):
            risk += 50.0
            break

    if url_lower.startswith('http://'):
        risk += 15.0

    return min(100.0, round(risk, 1))

