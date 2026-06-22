"""
ScamShield — Model Training & Export Script
==========================================
Trains all models from scam_detection_model.ipynb and exports
them to scam_detector/models/ for use in the Flask app.

Models exported:
  - naive_bayes.pkl          → NLP Model (TF-IDF text, 30% weight)
  - random_forest.pkl        → Primary ML Model (30% weight)
  - logistic_regression.pkl  → Backup ML model
  - xgboost.pkl              → Additional ML model
  - tfidf_vectorizer.pkl     → Text feature extractor
  - trigram_vectorizer.pkl   → Trigram feature extractor
  - label_encoder.pkl        → Class label encoder
  - feature_config.pkl       → Feature column schema + fraud keywords
"""
import re
import os
import pickle
import warnings
warnings.filterwarnings('ignore')

import pandas as pd
import numpy as np
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer, CountVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.naive_bayes import MultinomialNB
from xgboost import XGBClassifier
from sklearn.preprocessing import LabelEncoder
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, accuracy_score
from scipy.sparse import hstack, csr_matrix

# ─── Paths ───────────────────────────────────────────────────────────────────
BASE      = Path(__file__).parent.parent
DATA_PATH = BASE / 'Data_Collection.xlsx'
OUT_DIR   = BASE / 'scam_detector' / 'models'
OUT_DIR.mkdir(exist_ok=True)

print(f"Dataset : {DATA_PATH}")
print(f"Output  : {OUT_DIR}")
assert DATA_PATH.exists(), f"Dataset not found: {DATA_PATH}"

# ─── Load ─────────────────────────────────────────────────────────────────────
print("\n[1/7] Loading data...")
df = pd.read_excel(DATA_PATH)
print(f"  Shape: {df.shape}")
print(f"  Labels: {df['Label'].value_counts().to_dict()}")

# ─── Clean ────────────────────────────────────────────────────────────────────
print("\n[2/7] Cleaning & feature engineering...")
LEAKAGE_COLS = ['Company_Verified', 'Salary_Disclosed', 'Application_Method',
                'Keyword_Score', 'Description_Length', 'Remote_Flag']
existing_leakage = [c for c in LEAKAGE_COLS if c in df.columns]
df_clean = df.drop(columns=existing_leakage).copy()

for col in ['Job', 'Description', 'Company', 'Location', 'Skills']:
    df_clean[col] = df_clean[col].fillna('').astype(str)
df_clean['Experience']        = df_clean['Experience'].fillna('0').astype(str).str.strip()
df_clean['Employment_Type']   = df_clean.get('Employment_Type', pd.Series([''] * len(df_clean))).fillna('')
df_clean['Education_Required']= df_clean.get('Education_Required', pd.Series([''] * len(df_clean))).fillna('')

# ─── Salary features ──────────────────────────────────────────────────────────
def parse_salary(s):
    s = str(s).replace(',', '').replace('₹', '').replace('/month', '').strip()
    nums = re.findall(r'\d+', s)
    nums = [int(n) for n in nums if int(n) > 100]
    if not nums:
        return pd.Series({'salary_min': 0, 'salary_max': 0,
                          'salary_range': 0, 'salary_is_missing': 1,
                          'salary_unrealistic': 0})
    s_min, s_max = min(nums), max(nums)
    return pd.Series({'salary_min': s_min, 'salary_max': s_max,
                      'salary_range': s_max - s_min, 'salary_is_missing': 0,
                      'salary_unrealistic': int(s_max > 100000)})

salary_col = 'Salary/Stripend' if 'Salary/Stripend' in df_clean.columns else 'Salary'
salary_features = df_clean[salary_col].apply(parse_salary)

# ─── Structural features ──────────────────────────────────────────────────────
FRAUD_KEYWORDS = [
    'registration fee', 'training fee', 'deposit', 'instant joining',
    'earn daily', 'limited seats', 'whatsapp hr', 'no interview',
    'work from home earn', 'part time earn', 'guaranteed income',
    'no experience required', 'earn from home', 'join immediately',
    'urgently required', 'simple task', 'easy money', 'click here to apply',
    'telegram group', 'online earning', 'data entry work from home'
]

def text_features(row):
    desc = str(row['Description']).lower()
    job  = str(row['Job']).lower()
    combined = desc + ' ' + job
    return pd.Series({
        'fraud_kw_count':      sum(1 for kw in FRAUD_KEYWORDS if kw in combined),
        'desc_word_count':     len(desc.split()),
        'desc_char_count':     len(desc),
        'has_url':             int(bool(re.search(r'http|www|bit\.ly|t\.me', combined))),
        'exclamation_count':   combined.count('!'),
        'caps_ratio':          sum(1 for c in desc if c.isupper()) / max(len(desc), 1),
        'has_phone':           int(bool(re.search(r'\b\d{10}\b|\+91', combined))),
        'has_whatsapp':        int('whatsapp' in combined),
        'has_telegram':        int('telegram' in combined),
        'has_gmail':           int('gmail' in combined),
        'has_yahoo':           int('yahoo' in combined),
        'missing_desc':        int(len(desc.strip()) < 50),
        'has_fee_mention':     int(bool(re.search(r'fee|deposit|pay|payment|charge', combined))),
        'num_responsibilities':combined.count('responsible') + combined.count('responsibility'),
    })

struct_features = df_clean.apply(text_features, axis=1)
emp_dummies = pd.get_dummies(df_clean['Employment_Type'],    prefix='emp').astype(int)
edu_dummies = pd.get_dummies(df_clean['Education_Required'], prefix='edu').astype(int)
struct_all  = pd.concat([salary_features, struct_features, emp_dummies, edu_dummies], axis=1).fillna(0)
print(f"  Structured feature matrix: {struct_all.shape}")

# ─── Text features ────────────────────────────────────────────────────────────
STOPWORDS = {
    'the','a','an','and','or','but','in','on','at','to','for','of','is','it',
    'this','that','be','as','by','with','are','was','were','has','have','will',
    'from','we','our','you','your','their','its','not','no','can','about',
    'also','any','all','more','than','they','us','do','does','did','been',
    'if','then','so','such','each','per','should','may','would','could','when',
    'into','out','up','down','day','time','make','new','use','get','work'
}

def clean_text(text):
    text = str(text).lower()
    text = re.sub(r'http\S+|www\S+', ' url ', text)
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    text = re.sub(r'\d+', ' num ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    tokens = [w for w in text.split() if w not in STOPWORDS and len(w) > 2]
    return ' '.join(tokens)

df_clean['text_combined'] = (
    df_clean['Job'].apply(clean_text) + ' ' +
    df_clean['Description'].apply(clean_text) + ' ' +
    df_clean['Skills'].apply(clean_text)
)

# ─── Label encode ─────────────────────────────────────────────────────────────
le = LabelEncoder()
y  = le.fit_transform(df_clean['Label'])
print(f"  Labels: {dict(zip(le.classes_, le.transform(le.classes_)))}")

# ─── Train / Test split ───────────────────────────────────────────────────────
print("\n[3/7] Splitting data...")
X_text   = df_clean['text_combined']
X_struct = struct_all.values
(X_text_train, X_text_test,
 X_struct_train, X_struct_test,
 y_train, y_test) = train_test_split(
    X_text, X_struct, y,
    test_size=0.2, random_state=42, stratify=y
)
print(f"  Train: {len(y_train)} | Test: {len(y_test)}")

# ─── Vectorize ────────────────────────────────────────────────────────────────
print("\n[4/7] Vectorizing text...")
tfidf_vec = TfidfVectorizer(max_features=8000, ngram_range=(1, 2),
                             min_df=2, max_df=0.95, sublinear_tf=True)
trigram_vec = TfidfVectorizer(max_features=3000, ngram_range=(3, 3),
                               min_df=2, max_df=0.95, sublinear_tf=True)

X_tfidf_train = tfidf_vec.fit_transform(X_text_train)
X_tfidf_test  = tfidf_vec.transform(X_text_test)
X_tri_train   = trigram_vec.fit_transform(X_text_train)
X_tri_test    = trigram_vec.transform(X_text_test)

X_struct_tr_sp = csr_matrix(X_struct_train)
X_struct_te_sp = csr_matrix(X_struct_test)
X_train_full   = hstack([X_tfidf_train, X_tri_train, X_struct_tr_sp])
X_test_full    = hstack([X_tfidf_test,  X_tri_test,  X_struct_te_sp])
print(f"  Full feature matrix: train={X_train_full.shape}, test={X_test_full.shape}")

# ─── Train models ─────────────────────────────────────────────────────────────
print("\n[5/7] Training models...")

def train_and_report(name, model, X_tr, X_te, y_tr, y_te):
    model.fit(X_tr, y_tr)
    acc = accuracy_score(y_te, model.predict(X_te))
    from sklearn.metrics import f1_score
    f1 = f1_score(y_te, model.predict(X_te), average='macro')
    print(f"  [{name}] Accuracy={acc:.4f} | MacroF1={f1:.4f}")
    return model, acc, f1

# NLP MODEL: Naive Bayes on TF-IDF only (our new NLP model)
nb_model, nb_acc, nb_f1 = train_and_report(
    'Naive Bayes (NLP)', MultinomialNB(alpha=0.1),
    X_tfidf_train, X_tfidf_test, y_train, y_test
)

# LOGISTIC REGRESSION on full features
lr_model, lr_acc, lr_f1 = train_and_report(
    'Logistic Regression', LogisticRegression(max_iter=1000, C=1.0,
    class_weight='balanced', random_state=42),
    X_train_full, X_test_full, y_train, y_test
)

# RANDOM FOREST on full features
rf_model, rf_acc, rf_f1 = train_and_report(
    'Random Forest', RandomForestClassifier(
        n_estimators=200, min_samples_leaf=2,
        class_weight='balanced', random_state=42, n_jobs=-1),
    X_train_full, X_test_full, y_train, y_test
)

# XGBOOST on full features
xgb_model, xgb_acc, xgb_f1 = train_and_report(
    'XGBoost', XGBClassifier(
        n_estimators=200, max_depth=6, learning_rate=0.1,
        subsample=0.8, colsample_bytree=0.8,
        eval_metric='mlogloss', random_state=42, n_jobs=-1),
    X_train_full, X_test_full, y_train, y_test
)

# ─── Pick best ML model ───────────────────────────────────────────────────────
scores = {'logistic_regression': lr_f1, 'random_forest': rf_f1, 'xgboost': xgb_f1}
best_ml_name = max(scores, key=scores.get)
best_ml_model = {'logistic_regression': lr_model,
                 'random_forest': rf_model,
                 'xgboost': xgb_model}[best_ml_name]
print(f"\n  Best ML model: {best_ml_name} (MacroF1={scores[best_ml_name]:.4f})")

# ─── Save all models ──────────────────────────────────────────────────────────
print(f"\n[6/7] Saving models to {OUT_DIR}...")

def save(obj, name):
    path = OUT_DIR / name
    with open(path, 'wb') as f:
        pickle.dump(obj, f)
    kb = path.stat().st_size / 1024
    print(f"  ✅ {name}  ({kb:.1f} KB)")

save(nb_model,       'nlp_model.pkl')           # NLP model (Naive Bayes on TF-IDF)
save(best_ml_model,  'ml_model.pkl')            # Best ML model
save(lr_model,       'logistic_regression.pkl') # Logistic Regression
save(rf_model,       'random_forest.pkl')        # Random Forest
save(xgb_model,      'xgboost.pkl')             # XGBoost
save(tfidf_vec,      'tfidf_vectorizer.pkl')    # TF-IDF vectorizer
save(trigram_vec,    'trigram_vectorizer.pkl')  # Trigram vectorizer
save(le,             'label_encoder.pkl')       # Label encoder

feature_config = {
    'struct_columns':     list(struct_all.columns),
    'fraud_keywords':     FRAUD_KEYWORDS,
    'n_tfidf_features':   X_tfidf_train.shape[1],
    'n_trigram_features': X_tri_train.shape[1],
    'n_struct_features':  X_struct_tr_sp.shape[1],
    'label_mapping':      dict(zip(le.classes_, le.transform(le.classes_).tolist())),
    'best_ml_model_name': best_ml_name,
    'model_accuracy': {
        'naive_bayes': nb_acc, 'logistic_regression': lr_acc,
        'random_forest': rf_acc, 'xgboost': xgb_acc
    }
}
save(feature_config, 'feature_config.pkl')

print(f"\n[7/7] Summary")
print(f"  NLP Model (Naive Bayes)  : Acc={nb_acc:.4f} | F1={nb_f1:.4f}")
print(f"  LR Model                 : Acc={lr_acc:.4f} | F1={lr_f1:.4f}")
print(f"  Random Forest            : Acc={rf_acc:.4f} | F1={rf_f1:.4f}")
print(f"  XGBoost                  : Acc={xgb_acc:.4f} | F1={xgb_f1:.4f}")
print(f"\n✅ All models exported to: {OUT_DIR}")
print("   Ready for Flask integration.")
