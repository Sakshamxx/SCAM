#!/usr/bin/env python
# coding: utf-8

# # 🚨 Fake Internship & Job Scam Detection System
# ## ML + NLP Pipeline Notebook
# **Graphura India Private Limited**
# 
# ---
# ### Pipeline Overview
# 1. Data Loading & EDA
# 2. Data Cleaning & Leakage Removal
# 3. Feature Engineering (Salary, Text, Structural)
# 4. NLP Pipeline (TF-IDF, BoW, N-Grams)
# 5. Word Cloud Visualizations
# 6. Model Training (Logistic Regression, Random Forest, XGBoost, Naive Bayes)
# 7. Cross-Validation & Bias Analysis
# 8. Evaluation (Accuracy, Precision, Recall, F1, ROC-AUC)
# 9. Model Saving
# 10. Inference Pipeline
# ---

# In[4]:


# ── CELL 1: Imports ──────────────────────────────────────────────────────────
import pandas as pd
import numpy as np
import re
import os
import pickle
import warnings
warnings.filterwarnings('ignore')

# NLP
from sklearn.feature_extraction.text import TfidfVectorizer, CountVectorizer

# ML
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.naive_bayes import MultinomialNB
from xgboost import XGBClassifier

# Pipeline & Preprocessing
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.model_selection import train_test_split, cross_val_score, StratifiedKFold
from sklearn.metrics import (classification_report, confusion_matrix,
                              accuracy_score, roc_auc_score, roc_curve,
                              ConfusionMatrixDisplay)
from scipy.sparse import hstack, csr_matrix
from imblearn.over_sampling import SMOTE

# Visualizations
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')
import seaborn as sns
from wordcloud import WordCloud

os.makedirs('saved_models', exist_ok=True)
os.makedirs('plots', exist_ok=True)
print('✅ All imports successful')


# ---
# ## 📊 Step 1 — Data Loading & EDA

# In[5]:


# ── CELL 2: Load & Inspect ───────────────────────────────────────────────────
df = pd.read_excel('/Users/sakshamchauhan/Desktop/SCAM/Data_Collection.xlsx')
print(f'Shape: {df.shape}')
print(f'Columns: {df.columns.tolist()}')
df.head(3)


# In[ ]:


# ── CELL 3: Class Distribution ───────────────────────────────────────────────
label_counts = df['Label'].value_counts()
print('Label Distribution:')
print(label_counts)

fig, ax = plt.subplots(figsize=(7, 4))
colors = ['#2ecc71', '#e74c3c', '#f39c12']
label_counts.plot(kind='bar', color=colors, edgecolor='black', ax=ax)
ax.set_title('Class Distribution', fontsize=14, fontweight='bold')
ax.set_xlabel('Label')
ax.set_ylabel('Count')
for i, v in enumerate(label_counts):
    ax.text(i, v + 20, str(v), ha='center', fontweight='bold')
plt.tight_layout()
plt.savefig('plots/class_distribution.png', dpi=150)
plt.show()
print('Saved → plots/class_distribution.png')


# In[ ]:


# ── CELL 4: Application_Method vs Label (Leakage Check) ────────────────────
pivot = pd.crosstab(df['Application_Method'], df['Label'])
print('Application_Method vs Label:')
print(pivot)
print()
# Company_Verified vs Label
print('Company_Verified vs Label:')
print(pd.crosstab(df['Company_Verified'], df['Label']))
print()
print('Salary_Disclosed vs Label:')
print(pd.crosstab(df['Salary_Disclosed'], df['Label']))
print()
print('Remote_Flag vs Label:')
print(pd.crosstab(df['Remote_Flag'], df['Label']))


# In[ ]:


# ── CELL 5: Keyword_Score Leakage Check ─────────────────────────────────────
print('Keyword_Score mean by Label:')
print(df.groupby('Label')['Keyword_Score'].mean())
print()
print('Description_Length mean by Label:')
print(df.groupby('Label')['Description_Length'].mean())


# ---
# ## 🧹 Step 2 — Data Cleaning & Leakage Removal
# 
# ### ⚠️ Leakage Columns Identified & Dropped:
# | Column | Reason for Drop |
# |--------|----------------|
# | `Company_Verified` | Perfectly separates Legit (Yes) vs Scam (No) — 100% leakage |
# | `Salary_Disclosed` | Perfectly separates Legit (Yes) vs Suspicious (No) — 100% leakage |
# | `Application_Method` | WhatsApp/Telegram = Scam only; LinkedIn/Indeed = Legit only — 100% leakage |
# | `Keyword_Score` | Computed from label-derived signals — leakage |
# | `Description_Length` | Already captured from text itself — redundant & leaky |
# | `Remote_Flag` | Heavily correlated (Yes ≈ Suspicious/Scam) — potential leakage |
# 
# ### ✅ Features Kept:
# `Job`, `Description`, `Salary/Stripend`, `Skills`, `Experience`, `Employment_Type`, `Education_Required`, `Company`, `Location`

# In[ ]:


# ── CELL 6: Drop Leakage Columns ────────────────────────────────────────────
LEAKAGE_COLS = [
    'Company_Verified',
    'Salary_Disclosed',
    'Application_Method',
    'Keyword_Score',
    'Description_Length',
    'Remote_Flag'
]

df_clean = df.drop(columns=LEAKAGE_COLS).copy()
print(f'Remaining columns: {df_clean.columns.tolist()}')
print(f'Shape after drop: {df_clean.shape}')

# Fill missing text
for col in ['Job', 'Description', 'Company', 'Location', 'Skills']:
    df_clean[col] = df_clean[col].fillna('').astype(str)

# Standardize Experience
df_clean['Experience'] = df_clean['Experience'].fillna('0').astype(str).str.strip()

print(f'Nulls remaining:\n{df_clean.isnull().sum()}')


# ---
# ## ⚙️ Step 3 — Feature Engineering

# In[ ]:


# ── CELL 7: Salary Feature Engineering ──────────────────────────────────────
def parse_salary(s):
    """Extract numeric salary features from raw salary string."""
    s = str(s).replace(',', '').replace('₹', '').replace('/month', '').strip()
    # Remove rupee signs and text
    nums = re.findall(r'\d+', s)
    nums = [int(n) for n in nums if int(n) > 100]  # filter noise
    if not nums:
        return pd.Series({'salary_min': 0, 'salary_max': 0,
                          'salary_range': 0, 'salary_is_missing': 1,
                          'salary_unrealistic': 0})
    s_min = min(nums)
    s_max = max(nums)
    # Unrealistic if max > 100000/month (scam pattern: 4,30,000 - 9,30,000)
    unrealistic = 1 if s_max > 100000 else 0
    return pd.Series({
        'salary_min': s_min,
        'salary_max': s_max,
        'salary_range': s_max - s_min,
        'salary_is_missing': 0,
        'salary_unrealistic': unrealistic
    })

salary_features = df_clean['Salary/Stripend'].apply(parse_salary)
print('Salary features sample:')
print(salary_features.head(5))
print()
print('Unrealistic salary by label:')
print(pd.crosstab(df_clean['Label'], salary_features['salary_unrealistic']))


# In[ ]:


# ── CELL 8: Structural Feature Engineering ───────────────────────────────────
# Known fraud keywords for scoring (from project brief NLP section)
FRAUD_KEYWORDS = [
    'registration fee', 'training fee', 'deposit', 'instant joining',
    'earn daily', 'limited seats', 'whatsapp hr', 'no interview',
    'work from home earn', 'part time earn', 'guaranteed income',
    'no experience required', 'earn from home', 'join immediately',
    'urgently required', 'simple task', 'easy money', 'click here to apply',
    'telegram group', 'online earning', 'data entry work from home'
]

def count_fraud_keywords(text):
    text = text.lower()
    return sum(1 for kw in FRAUD_KEYWORDS if kw in text)

def text_features(row):
    desc = str(row['Description']).lower()
    job  = str(row['Job']).lower()
    combined = desc + ' ' + job
    return pd.Series({
        'fraud_kw_count': count_fraud_keywords(combined),
        'desc_word_count': len(desc.split()),
        'desc_char_count': len(desc),
        'has_url': int(bool(re.search(r'http|www|bit\.ly|t\.me', combined))),
        'exclamation_count': combined.count('!'),
        'caps_ratio': sum(1 for c in desc if c.isupper()) / max(len(desc), 1),
        'has_phone': int(bool(re.search(r'\b\d{10}\b|\+91', combined))),
        'has_whatsapp': int('whatsapp' in combined),
        'has_telegram': int('telegram' in combined),
        'has_gmail': int('gmail' in combined),
        'has_yahoo': int('yahoo' in combined),
        'missing_desc': int(len(desc.strip()) < 50),
        'has_fee_mention': int(bool(re.search(r'fee|deposit|pay|payment|charge', combined))),
        'num_responsibilities': combined.count('responsible') + combined.count('responsibility'),
    })

struct_features = df_clean.apply(text_features, axis=1)

# Employment type encoding
emp_dummies = pd.get_dummies(df_clean['Employment_Type'], prefix='emp', drop_first=False).astype(int)
edu_dummies = pd.get_dummies(df_clean['Education_Required'], prefix='edu', drop_first=False).astype(int)

print('Structural features shape:', struct_features.shape)
print('Fraud keyword count by label:')
print(pd.concat([df_clean['Label'], struct_features['fraud_kw_count']], axis=1).groupby('Label').mean())


# In[ ]:


# ── CELL 9: Combine Structured Features ─────────────────────────────────────
struct_all = pd.concat([salary_features, struct_features, emp_dummies, edu_dummies], axis=1)
struct_all = struct_all.fillna(0)
print('Combined structured feature matrix shape:', struct_all.shape)
struct_all.head(3)


# ---
# ## 📝 Step 4 — NLP: Text Preprocessing & TF-IDF

# In[ ]:


# ── CELL 10: Text Cleaning ───────────────────────────────────────────────────
STOPWORDS = {
    'the','a','an','and','or','but','in','on','at','to','for','of','is','it',
    'this','that','be','as','by','with','are','was','were','has','have','will',
    'from','we','our','you','your','their','its','not','no','can','about',
    'also','any','all','more','than','they','we','us','do','does','did','been',
    'if','then','so','such','each','per','should','may','would','could','when',
    'into','out','up','down','day','time','make','new','use','get','work'
}

def clean_text(text):
    text = str(text).lower()
    text = re.sub(r'http\S+|www\S+', ' url ', text)      # URLs
    text = re.sub(r'[^a-z0-9\s]', ' ', text)              # keep alphanumeric
    text = re.sub(r'\d+', ' num ', text)                  # replace numbers
    text = re.sub(r'\s+', ' ', text).strip()              # normalize spaces
    tokens = [w for w in text.split() if w not in STOPWORDS and len(w) > 2]
    return ' '.join(tokens)

# Combine title + description + skills for rich text
df_clean['text_combined'] = (
    df_clean['Job'].apply(clean_text) + ' ' +
    df_clean['Description'].apply(clean_text) + ' ' +
    df_clean['Skills'].apply(clean_text)
)

print('Sample cleaned text:')
print(df_clean['text_combined'].iloc[0][:200])


# In[ ]:


# ── CELL 11: Label Encoding ─────────────────────────────────────────────────
le = LabelEncoder()
y = le.fit_transform(df_clean['Label'])
print('Label mapping:', dict(zip(le.classes_, le.transform(le.classes_))))

# Save encoder
with open('saved_models/label_encoder.pkl', 'wb') as f:
    pickle.dump(le, f)
print('Saved → saved_models/label_encoder.pkl')


# In[ ]:


# ── CELL 12: TF-IDF Vectorizer (Unigram + Bigram) ───────────────────────────
tfidf_vec = TfidfVectorizer(
    max_features=8000,
    ngram_range=(1, 2),     # Unigram + Bigram
    min_df=2,
    max_df=0.95,
    sublinear_tf=True       # apply log(1+tf) for better scaling
)

# Bag of Words Vectorizer (Unigram)
bow_vec = CountVectorizer(
    max_features=5000,
    ngram_range=(1, 1)      # Unigram BoW
)

# Trigram TF-IDF
trigram_vec = TfidfVectorizer(
    max_features=3000,
    ngram_range=(3, 3),     # Trigram only
    min_df=2,
    max_df=0.95,
    sublinear_tf=True
)

# Train-Test Split (stratified)
X_text = df_clean['text_combined']
X_struct = struct_all.values

X_text_train, X_text_test, X_struct_train, X_struct_test, y_train, y_test = train_test_split(
    X_text, X_struct, y, test_size=0.2, random_state=42, stratify=y
)

print(f'Train: {len(y_train)} | Test: {len(y_test)}')
print('Train class distribution:', pd.Series(y_train).value_counts().to_dict())


# In[ ]:


# ── CELL 13: Fit Vectorizers & Build Feature Matrix ──────────────────────────
# TF-IDF (Unigram + Bigram)
X_tfidf_train = tfidf_vec.fit_transform(X_text_train)
X_tfidf_test  = tfidf_vec.transform(X_text_test)

# BoW Unigram
X_bow_train = bow_vec.fit_transform(X_text_train)
X_bow_test  = bow_vec.transform(X_text_test)

# Trigram
X_tri_train = trigram_vec.fit_transform(X_text_train)
X_tri_test  = trigram_vec.transform(X_text_test)

# Structured features as sparse
X_struct_train_sp = csr_matrix(X_struct_train)
X_struct_test_sp  = csr_matrix(X_struct_test)

# === FINAL FEATURE MATRIX: TF-IDF + Trigram + Structured ===
X_train_full = hstack([X_tfidf_train, X_tri_train, X_struct_train_sp])
X_test_full  = hstack([X_tfidf_test,  X_tri_test,  X_struct_test_sp])

print(f'Full feature matrix — Train: {X_train_full.shape} | Test: {X_test_full.shape}')
print(f'TF-IDF features: {X_tfidf_train.shape[1]}')
print(f'Trigram features: {X_tri_train.shape[1]}')
print(f'Structured features: {X_struct_train_sp.shape[1]}')

# Save vectorizers
with open('saved_models/tfidf_vectorizer.pkl', 'wb') as f:
    pickle.dump(tfidf_vec, f)
with open('saved_models/bow_vectorizer.pkl', 'wb') as f:
    pickle.dump(bow_vec, f)
with open('saved_models/trigram_vectorizer.pkl', 'wb') as f:
    pickle.dump(trigram_vec, f)
print('Vectorizers saved ✅')


# ---
# ## ☁️ Step 5 — Word Clouds

# In[ ]:


# ── CELL 14: Word Clouds per Class ──────────────────────────────────────────
labels_list = ['Legit', 'Scam', 'Suspicious']
colors_map  = {'Legit': 'Greens', 'Scam': 'Reds', 'Suspicious': 'Oranges'}

fig, axes = plt.subplots(1, 3, figsize=(18, 5))
for ax, label in zip(axes, labels_list):
    mask = df_clean['Label'] == label
    corpus = ' '.join(df_clean.loc[mask, 'text_combined'])
    wc = WordCloud(
        width=600, height=400,
        background_color='white',
        colormap=colors_map[label],
        max_words=100,
        collocations=False
    ).generate(corpus)
    ax.imshow(wc, interpolation='bilinear')
    ax.set_title(f'Word Cloud — {label}', fontsize=14, fontweight='bold')
    ax.axis('off')

plt.tight_layout()
plt.savefig('plots/wordclouds.png', dpi=150)
plt.show()
print('Saved → plots/wordclouds.png')


# In[ ]:


# ── CELL 15: Top TF-IDF Terms per Class ─────────────────────────────────────
feature_names = tfidf_vec.get_feature_names_out()

fig, axes = plt.subplots(1, 3, figsize=(18, 5))
for ax, label in zip(axes, labels_list):
    mask = df_clean['Label'] == label
    subset = X_tfidf_train[le.transform(pd.Series([label] * mask.sum()))]
    # Get indices of this class in training
    train_idx = X_text_train.index
    class_mask_train = df_clean.loc[train_idx, 'Label'] == label
    class_tfidf = X_tfidf_train[class_mask_train.values]
    mean_scores = class_tfidf.mean(axis=0).A1
    top_idx = mean_scores.argsort()[-20:][::-1]
    top_terms = [feature_names[i] for i in top_idx]
    top_scores = [mean_scores[i] for i in top_idx]

    color = {'Legit': '#27ae60', 'Scam': '#e74c3c', 'Suspicious': '#f39c12'}[label]
    ax.barh(top_terms[::-1], top_scores[::-1], color=color, edgecolor='black', alpha=0.8)
    ax.set_title(f'Top 20 TF-IDF Terms — {label}', fontweight='bold')
    ax.set_xlabel('Mean TF-IDF Score')

plt.tight_layout()
plt.savefig('plots/tfidf_top_terms.png', dpi=150)
plt.show()
print('Saved → plots/tfidf_top_terms.png')


# In[ ]:


# ── CELL 16: N-Gram Analysis (Bigram Counts) ─────────────────────────────────
bigram_vec_analysis = CountVectorizer(ngram_range=(2, 2), max_features=30, min_df=2)
X_bigram_all = bigram_vec_analysis.fit_transform(df_clean['text_combined'])
bigram_names = bigram_vec_analysis.get_feature_names_out()

fig, axes = plt.subplots(1, 3, figsize=(18, 5))
for ax, label in zip(axes, labels_list):
    mask = df_clean['Label'] == label
    counts = X_bigram_all[mask.values].sum(axis=0).A1
    top_idx = counts.argsort()[-15:][::-1]
    top_bigrams = [bigram_names[i] for i in top_idx]
    top_counts  = [counts[i] for i in top_idx]
    color = {'Legit': '#27ae60', 'Scam': '#e74c3c', 'Suspicious': '#f39c12'}[label]
    ax.barh(top_bigrams[::-1], top_counts[::-1], color=color, alpha=0.8)
    ax.set_title(f'Top Bigrams — {label}', fontweight='bold')
    ax.set_xlabel('Count')

plt.tight_layout()
plt.savefig('plots/bigram_analysis.png', dpi=150)
plt.show()
print('Saved → plots/bigram_analysis.png')


# ---
# ## 🤖 Step 6 — Model Training

# In[ ]:


# ── CELL 17: Helper — Evaluate & Save Model ──────────────────────────────────
results = {}

def evaluate_model(name, model, X_tr, X_te, y_tr, y_te, save=True):
    model.fit(X_tr, y_tr)
    y_pred = model.predict(X_te)
    acc = accuracy_score(y_te, y_pred)
    report = classification_report(y_te, y_pred, target_names=le.classes_, output_dict=True)
    print(f'\n{'='*55}')
    print(f'  {name}')
    print(f'{'='*55}')
    print(f'  Accuracy: {acc:.4f}')
    print(f'  Macro F1: {report["macro avg"]["f1-score"]:.4f}')
    print(classification_report(y_te, y_pred, target_names=le.classes_))

    # Confusion Matrix
    cm = confusion_matrix(y_te, y_pred)
    fig, ax = plt.subplots(figsize=(6, 5))
    disp = ConfusionMatrixDisplay(cm, display_labels=le.classes_)
    disp.plot(ax=ax, colorbar=False, cmap='Blues')
    ax.set_title(f'{name}\nAccuracy: {acc:.4f}', fontweight='bold')
    plt.tight_layout()
    safe_name = name.lower().replace(' ', '_')
    plt.savefig(f'plots/cm_{safe_name}.png', dpi=150)
    plt.show()

    results[name] = {'accuracy': acc, 'macro_f1': report['macro avg']['f1-score']}
    if save:
        with open(f'saved_models/{safe_name}.pkl', 'wb') as f:
            pickle.dump(model, f)
        print(f'  Saved → saved_models/{safe_name}.pkl')
    return model

print('Helper defined ✅')


# In[ ]:


# ── CELL 18: Model 1 — Logistic Regression ──────────────────────────────────
lr = LogisticRegression(max_iter=1000, C=1.0, class_weight='balanced', random_state=42)
lr_model = evaluate_model('Logistic Regression', lr, X_train_full, X_test_full, y_train, y_test)


# In[ ]:


# ── CELL 19: Model 2 — Naive Bayes (on TF-IDF only, needs non-negative) ─────
# Naive Bayes works on TF-IDF + BoW only (sparse, non-negative)
nb = MultinomialNB(alpha=0.1)
nb_model = evaluate_model('Naive Bayes', nb, X_tfidf_train, X_tfidf_test, y_train, y_test)


# In[ ]:


# ── CELL 20: Model 3 — Random Forest ────────────────────────────────────────
rf = RandomForestClassifier(
    n_estimators=300,
    max_depth=None,
    min_samples_leaf=2,
    class_weight='balanced',
    random_state=42,
    n_jobs=-1
)
rf_model = evaluate_model('Random Forest', rf, X_train_full, X_test_full, y_train, y_test)


# In[ ]:


# ── CELL 21: Model 4 — XGBoost ──────────────────────────────────────────────
scale_pw = len(y_train[y_train != 1]) / max(len(y_train[y_train == 1]), 1)
xgb = XGBClassifier(
    n_estimators=300,
    max_depth=6,
    learning_rate=0.1,
    subsample=0.8,
    colsample_bytree=0.8,
    use_label_encoder=False,
    eval_metric='mlogloss',
    random_state=42,
    n_jobs=-1
)
xgb_model = evaluate_model('XGBoost', xgb, X_train_full, X_test_full, y_train, y_test)


# ---
# ## 🔁 Step 7 — Cross-Validation & Bias Analysis

# In[ ]:


# ── CELL 22: Stratified K-Fold Cross Validation ──────────────────────────────
print('Running 5-Fold Stratified Cross Validation on full dataset...\n')

# Rebuild full feature matrix for all data
X_tfidf_all = tfidf_vec.transform(df_clean['text_combined'])
X_tri_all   = trigram_vec.transform(df_clean['text_combined'])
X_struct_all_sp = csr_matrix(struct_all.values)
X_full_all = hstack([X_tfidf_all, X_tri_all, X_struct_all_sp])

skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

cv_models = {
    'Logistic Regression': LogisticRegression(max_iter=1000, C=1.0, class_weight='balanced', random_state=42),
    'Random Forest': RandomForestClassifier(n_estimators=100, class_weight='balanced', random_state=42, n_jobs=-1),
    'XGBoost': XGBClassifier(n_estimators=100, use_label_encoder=False, eval_metric='mlogloss', random_state=42, n_jobs=-1),
}

cv_results = {}
for name, model in cv_models.items():
    scores = cross_val_score(model, X_full_all, y, cv=skf, scoring='accuracy', n_jobs=-1)
    f1_scores = cross_val_score(model, X_full_all, y, cv=skf, scoring='f1_macro', n_jobs=-1)
    cv_results[name] = {
        'acc_mean': scores.mean(),
        'acc_std': scores.std(),
        'f1_mean': f1_scores.mean(),
        'f1_std': f1_scores.std()
    }
    print(f'{name}:')
    print(f'  Accuracy: {scores.mean():.4f} ± {scores.std():.4f}')
    print(f'  Macro F1: {f1_scores.mean():.4f} ± {f1_scores.std():.4f}')
    print()


# In[ ]:


# ── CELL 23: Bias Analysis — Train vs Test Accuracy Gap ─────────────────────
print('Bias Analysis (Train vs Test Accuracy)\n')
bias_models = [
    ('Logistic Regression', lr_model),
    ('Random Forest', rf_model),
    ('XGBoost', xgb_model),
]

bias_data = []
for name, model in bias_models:
    train_acc = accuracy_score(y_train, model.predict(X_train_full))
    test_acc  = accuracy_score(y_test,  model.predict(X_test_full))
    gap = train_acc - test_acc
    bias_data.append({'Model': name, 'Train Acc': train_acc, 'Test Acc': test_acc, 'Gap': gap})
    print(f'{name}:')
    print(f'  Train Accuracy: {train_acc:.4f}')
    print(f'  Test  Accuracy: {test_acc:.4f}')
    print(f'  Gap (overfit?): {gap:.4f} {"⚠️ Overfit" if gap > 0.1 else "✅ OK"}')
    print()

bias_df = pd.DataFrame(bias_data)
x = np.arange(len(bias_df))
fig, ax = plt.subplots(figsize=(8, 5))
ax.bar(x - 0.2, bias_df['Train Acc'], 0.4, label='Train', color='#3498db', alpha=0.8)
ax.bar(x + 0.2, bias_df['Test Acc'],  0.4, label='Test',  color='#e74c3c', alpha=0.8)
ax.set_xticks(x)
ax.set_xticklabels(bias_df['Model'])
ax.set_ylim(0, 1.05)
ax.set_ylabel('Accuracy')
ax.set_title('Bias Analysis: Train vs Test Accuracy', fontweight='bold')
ax.legend()
ax.axhline(y=0.8, color='green', linestyle='--', alpha=0.5, label='80% target')
plt.tight_layout()
plt.savefig('plots/bias_analysis.png', dpi=150)
plt.show()
print('Saved → plots/bias_analysis.png')


# ---
# ## 📈 Step 8 — Model Comparison & Final Evaluation

# In[ ]:


# ── CELL 24: Model Comparison Chart ─────────────────────────────────────────
model_names = list(results.keys())
accuracies  = [results[m]['accuracy'] for m in model_names]
macro_f1s   = [results[m]['macro_f1'] for m in model_names]

x = np.arange(len(model_names))
fig, ax = plt.subplots(figsize=(10, 5))
bars1 = ax.bar(x - 0.2, accuracies, 0.35, label='Accuracy', color='#3498db', alpha=0.9)
bars2 = ax.bar(x + 0.2, macro_f1s,  0.35, label='Macro F1', color='#e74c3c',  alpha=0.9)
ax.set_xticks(x)
ax.set_xticklabels(model_names, rotation=15)
ax.set_ylim(0, 1.05)
ax.set_ylabel('Score')
ax.set_title('Model Comparison: Accuracy & Macro F1 (Test Set)', fontsize=13, fontweight='bold')
ax.legend()
ax.axhline(y=0.80, color='green', linestyle='--', alpha=0.6, label='80% target')
for bar in bars1: ax.annotate(f'{bar.get_height():.3f}', xy=(bar.get_x()+bar.get_width()/2, bar.get_height()), ha='center', va='bottom', fontsize=9)
for bar in bars2: ax.annotate(f'{bar.get_height():.3f}', xy=(bar.get_x()+bar.get_width()/2, bar.get_height()), ha='center', va='bottom', fontsize=9)
plt.tight_layout()
plt.savefig('plots/model_comparison.png', dpi=150)
plt.show()
print('Saved → plots/model_comparison.png')


# In[ ]:


# ── CELL 25: Best Model — Salary Anomaly Feature Importance ─────────────────
# Feature importance from Random Forest on structured features only
rf_struct = RandomForestClassifier(n_estimators=200, class_weight='balanced', random_state=42, n_jobs=-1)
rf_struct.fit(X_struct_train, y_train)
importances = pd.Series(rf_struct.feature_importances_, index=struct_all.columns)
top_feats = importances.nlargest(20)

fig, ax = plt.subplots(figsize=(9, 6))
top_feats[::-1].plot(kind='barh', color='#8e44ad', ax=ax, edgecolor='black', alpha=0.8)
ax.set_title('Top 20 Structured Feature Importances (Random Forest)', fontweight='bold')
ax.set_xlabel('Importance')
plt.tight_layout()
plt.savefig('plots/feature_importance.png', dpi=150)
plt.show()
print('Saved → plots/feature_importance.png')


# In[ ]:


# ── CELL 26: Cross-Validation Summary Plot ───────────────────────────────────
cv_names = list(cv_results.keys())
cv_accs  = [cv_results[m]['acc_mean'] for m in cv_names]
cv_stds  = [cv_results[m]['acc_std']  for m in cv_names]
cv_f1s   = [cv_results[m]['f1_mean']  for m in cv_names]

fig, ax = plt.subplots(figsize=(9, 5))
x = np.arange(len(cv_names))
ax.bar(x, cv_accs, 0.4, yerr=cv_stds, capsize=5, color='#2980b9', alpha=0.8, label='CV Accuracy')
ax.set_xticks(x)
ax.set_xticklabels(cv_names)
ax.set_ylim(0, 1.1)
ax.set_ylabel('CV Accuracy')
ax.set_title('5-Fold Cross Validation Results (mean ± std)', fontweight='bold')
ax.axhline(y=0.80, color='green', linestyle='--', alpha=0.7, label='80% target')
for i, (v, s) in enumerate(zip(cv_accs, cv_stds)):
    ax.text(i, v + s + 0.01, f'{v:.3f}±{s:.3f}', ha='center', fontsize=9, fontweight='bold')
ax.legend()
plt.tight_layout()
plt.savefig('plots/cv_results.png', dpi=150)
plt.show()
print('Saved → plots/cv_results.png')


# ---
# ## 💾 Step 9 — Save All Models & Pipeline Summary

# In[ ]:


# ── CELL 27: Save All Models & Feature Config ───────────────────────────────
# Save structured feature column names (needed for inference)
feature_config = {
    'struct_columns': list(struct_all.columns),
    'fraud_keywords': FRAUD_KEYWORDS,
    'n_tfidf_features': X_tfidf_train.shape[1],
    'n_trigram_features': X_tri_train.shape[1],
    'n_struct_features': X_struct_train.shape[1],
    'label_mapping': dict(zip(le.classes_, le.transform(le.classes_).tolist()))
}
with open('saved_models/feature_config.pkl', 'wb') as f:
    pickle.dump(feature_config, f)

print('📁 Saved Models:')
for fn in sorted(os.listdir('saved_models')):
    size = os.path.getsize(f'saved_models/{fn}') / 1024
    print(f'  saved_models/{fn}  ({size:.1f} KB)')

print()
print('📁 Saved Plots:')
for fn in sorted(os.listdir('plots')):
    print(f'  plots/{fn}')


# In[ ]:


# ── CELL 28: Final Results Summary ──────────────────────────────────────────
print('\n' + '='*60)
print('           FINAL MODEL PERFORMANCE SUMMARY')
print('='*60)
print(f'{"Model":<25} {"Test Acc":>10} {"Macro F1":>10}')
print('-'*60)
for name, r in results.items():
    print(f'{name:<25} {r["accuracy"]:>10.4f} {r["macro_f1"]:>10.4f}')
print('='*60)

best_model_name = max(results, key=lambda k: results[k]['macro_f1'])
print(f'\n🏆 Best Model by Macro F1: {best_model_name}')
print(f'   Accuracy : {results[best_model_name]["accuracy"]:.4f}')
print(f'   Macro F1 : {results[best_model_name]["macro_f1"]:.4f}')


# ---
# ## 🔮 Step 10 — Inference Pipeline

# In[ ]:


# ── CELL 29: Inference Function ──────────────────────────────────────────────
def predict_scam(job_title: str, description: str, salary: str,
                 skills: str = '', employment_type: str = 'Internship',
                 education: str = 'Any Degree', model=None):
    """
    Predict if a job posting is Legit / Suspicious / Scam.

    Parameters
    ----------
    job_title       : Job title string
    description     : Full job description
    salary          : Salary string e.g. '₹ 5,000 - 10,000 /month'
    skills          : Comma-separated skills
    employment_type : Internship / Full-time / Part-time
    education       : Education requirement
    model           : Sklearn model object (default: rf_model)

    Returns
    -------
    dict with prediction, probabilities, and risk score
    """
    if model is None:
        model = rf_model

    # Text features
    clean = clean_text(job_title) + ' ' + clean_text(description) + ' ' + clean_text(skills)
    X_tfidf_inf = tfidf_vec.transform([clean])
    X_tri_inf   = trigram_vec.transform([clean])

    # Salary features
    sal_feats = parse_salary(salary)

    # Text structural features
    dummy_row = pd.Series({'Job': job_title, 'Description': description})
    txt_feats = text_features(dummy_row)

    # Categorical dummies (align with training columns)
    emp_d = {col: 0 for col in emp_dummies.columns}
    edu_d = {col: 0 for col in edu_dummies.columns}
    emp_key = f'emp_{employment_type}'
    edu_key = f'edu_{education}'
    if emp_key in emp_d: emp_d[emp_key] = 1
    if edu_key in edu_d: edu_d[edu_key] = 1

    # Combine all structured
    all_struct = {**sal_feats.to_dict(), **txt_feats.to_dict(), **emp_d, **edu_d}
    struct_row = pd.DataFrame([all_struct])[struct_all.columns].fillna(0)
    X_struct_inf = csr_matrix(struct_row.values)

    X_inf = hstack([X_tfidf_inf, X_tri_inf, X_struct_inf])

    # Predict
    pred_idx  = model.predict(X_inf)[0]
    pred_prob = model.predict_proba(X_inf)[0]
    pred_label = le.inverse_transform([pred_idx])[0]

    # Risk score (0-100)
    scam_idx = list(le.classes_).index('Scam') if 'Scam' in le.classes_ else 1
    susp_idx = list(le.classes_).index('Suspicious') if 'Suspicious' in le.classes_ else 2
    risk_score = int((pred_prob[scam_idx] * 0.7 + pred_prob[susp_idx] * 0.3) * 100)

    if risk_score <= 30:
        risk_level = 'LOW RISK ✅'
    elif risk_score <= 60:
        risk_level = 'MEDIUM RISK ⚠️'
    else:
        risk_level = 'HIGH RISK 🚨'

    return {
        'prediction': pred_label,
        'risk_score': risk_score,
        'risk_level': risk_level,
        'probabilities': dict(zip(le.classes_, pred_prob.round(4))),
        'salary_unrealistic': bool(sal_feats['salary_unrealistic']),
        'fraud_keywords_found': txt_feats['fraud_kw_count'],
        'has_whatsapp': bool(txt_feats['has_whatsapp']),
        'has_telegram': bool(txt_feats['has_telegram']),
    }

print('Inference function defined ✅')


# In[ ]:


# ── CELL 30: Test Inference — Scam Job ──────────────────────────────────────
result = predict_scam(
    job_title='Data Entry Work From Home - Earn Daily',
    description='No experience required. Registration fee ₹500 only. Instant joining. WhatsApp HR at 9999999999. Earn 1000 per day. No interview needed. Limited seats available.',
    salary='430000 - 930000',
    employment_type='Internship',
    education='Any Degree'
)
print('🚨 SCAM JOB TEST:')
for k, v in result.items():
    print(f'  {k}: {v}')


# In[ ]:


# ── CELL 31: Test Inference — Legit Job ─────────────────────────────────────
result2 = predict_scam(
    job_title='Software Engineering Intern',
    description='Selected intern will work on building REST APIs using Python and FastAPI. Responsibilities include writing unit tests, code reviews, and collaborating with senior engineers on real production features.',
    salary='₹ 25,000 /month',
    skills='Python, FastAPI, SQL, Git',
    employment_type='Internship',
    education='Pursuing Degree'
)
print('✅ LEGIT JOB TEST:')
for k, v in result2.items():
    print(f'  {k}: {v}')


# In[ ]:


# ── CELL 32: Summary of Saved Artifacts ─────────────────────────────────────
print('='*60)
print('         ALL SAVED ARTIFACTS')
print('='*60)
print()
print('📦 Models (saved_models/):')
for fn in sorted(os.listdir('saved_models')):
    size_kb = os.path.getsize(f'saved_models/{fn}') / 1024
    print(f'  {fn:<40} {size_kb:>8.1f} KB')
print()
print('🖼️  Plots (plots/):')
for fn in sorted(os.listdir('plots')):
    print(f'  {fn}')
print()
print('='*60)
print('NOTEBOOK COMPLETE ✅')
print('='*60)

