"""
Regenerates random_forest_model.pkl using the already-fitted tfidf_vectorizer.pkl
and scaler.pkl from job_scam_detection.ipynb. Does not refit either of them, and
does not touch best_model.pkl / pipeline.pkl / sentence_transformer.pkl.
"""
import re
import numpy as np
import pandas as pd
import nltk
import spacy
import joblib
from sentence_transformers import SentenceTransformer
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, roc_auc_score
from scipy.sparse import hstack, csr_matrix

# --- CONFIRM THIS PATH IN STEP 1 BEFORE RUNNING ---
CSV_PATH = "/Users/sakshamchauhan/Desktop/SCAM/fake internship/data collection/Data_Collection_latest.csv"

BASE_DIR = "fake internship"  # where the existing fitted artifacts live

print("Loading existing fitted artifacts (NOT refitting)...")
tfidf_vectorizer = joblib.load(f"{BASE_DIR}/tfidf_vectorizer.pkl")
scaler = joblib.load(f"{BASE_DIR}/scaler.pkl")

# sentence_transformer.pkl is known to fail unpickling on this environment
# (version-skew issue, separate from this task) — load the stock pretrained
# model directly instead, exactly as the notebook's st_model originally was
# before saving (it's a frozen pretrained checkpoint, never fine-tuned here,
# so this is equivalent, not an approximation).
st_model = SentenceTransformer("all-MiniLM-L6-v2")

print(f"Loading dataset: {CSV_PATH}")
df = pd.read_csv(CSV_PATH)
print(f"Dataset shape: {df.shape}")

# --- Phase 1: Target construction (must match notebook exactly) ---
df["Target"] = df["Label"].map({"Legit": 0, "Scam": 1, "Suspicious": 1})
np.random.seed(42)
noise_mask = np.random.rand(len(df)) < 0.05
df["Target"] = df["Target"].astype(int)
df.loc[noise_mask, "Target"] = 1 - df.loc[noise_mask, "Target"]
print(f"Injected 5% random label noise. Flipped labels: {noise_mask.sum()}")

# --- Phase 2: Feature engineering (must match notebook exactly) ---
df["Job"] = df["Job"].fillna("")
df["Company"] = df["Company"].fillna("")
df["Location"] = df["Location"].fillna("")
df["Description"] = df["Description"].fillna("")
df["Skills"] = df["Skills"].fillna("")
df["Experience"] = df["Experience"].fillna("")
df["Education_Required"] = df["Education_Required"].fillna("")

combined_text = (
    df["Job"] + " " +
    df["Company"] + " " +
    df["Location"] + " " +
    df["Description"] + " " +
    df["Skills"] + " " +
    df["Experience"] + " " +
    df["Education_Required"]
)

print("Extracting handcrafted features from raw combined text...")
df["Text_Length"] = combined_text.str.len()
df["Word_Count"] = combined_text.apply(lambda x: len(x.split()))
df["Sentence_Count"] = combined_text.apply(lambda x: len(nltk.sent_tokenize(x)) if isinstance(x, str) else 0)
df["Avg_Word_Length"] = combined_text.apply(lambda x: np.mean([len(w) for w in x.split()]) if len(x.split()) > 0 else 0.0)
df["Uppercase_Ratio"] = combined_text.apply(lambda x: sum(1 for c in x if c.isupper()) / len(x) if len(x) > 0 else 0.0)
df["Num_Digits"] = combined_text.apply(lambda x: sum(1 for c in x if c.isdigit()))
df["Num_Special_Chars"] = combined_text.apply(lambda x: sum(1 for c in x if not c.isalnum() and not c.isspace()))

salary_regex = re.compile(r"₹|\$|stipend|salary|/month|/year|lpa", re.IGNORECASE)
df["Presence_Salary"] = df.apply(
    lambda r: 1 if r["Salary_Disclosed"] == "Yes" or salary_regex.search(r["Job"] + " " + r["Description"]) else 0,
    axis=1,
)
email_regex = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
df["Presence_Email"] = combined_text.apply(lambda x: 1 if email_regex.search(x) else 0)
website_regex = re.compile(r"https?://\S+|www\.\S+|\b\w+\.(?:com|org|net|edu|gov|co|io|biz|info|in)\b", re.IGNORECASE)
df["Presence_Website"] = combined_text.apply(lambda x: 1 if website_regex.search(x) else 0)
phone_regex = re.compile(r"(?:\+?\d{1,3}[ -]?)?\(?\d{3}\)?[ -]?\d{3}[ -]?\d{4}|\b\d{10}\b|\b\d{5}[ -]?\d{5}\b")
df["Presence_Phone"] = combined_text.apply(lambda x: 1 if phone_regex.search(x) else 0)

# --- Phase 3: Text cleaning + lemmatization (must match notebook exactly) ---
def clean_text(text):
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"https?://\S+|www\.\S+", " ", text)
    text = re.sub(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", " ", text)
    text = re.sub(r"[^a-zA-Z0-9\s]", " ", text)
    return text.lower()

print("Cleaning text...")
df["Cleaned_Combined_Text"] = combined_text.apply(clean_text)

print("Lemmatizing with spaCy (this is the slow step, same as in the notebook)...")
nlp = spacy.load("en_core_web_sm", disable=["parser", "ner"])
docs = list(nlp.pipe(df["Cleaned_Combined_Text"].tolist(), batch_size=512))
processed_texts = [
    " ".join(t.lemma_ for t in doc if not t.is_stop and not t.is_space and len(t.text) > 1)
    for doc in docs
]
df["Preprocessed_Text"] = processed_texts
df["Preprocessed_Text"] = df["Preprocessed_Text"].fillna("")

# --- Phase 4/5: Feature matrix — TRANSFORM ONLY, never fit ---
print("Vectorizing with the EXISTING fitted tfidf_vectorizer (transform only)...")
tfidf_matrix = tfidf_vectorizer.transform(df["Preprocessed_Text"])

print("Encoding sentence embeddings...")
embeddings = st_model.encode(df["Cleaned_Combined_Text"].tolist(), show_progress_bar=True, batch_size=64)

handcrafted_cols = [
    "Text_Length", "Word_Count", "Sentence_Count", "Avg_Word_Length",
    "Uppercase_Ratio", "Num_Digits", "Num_Special_Chars",
    "Presence_Salary", "Presence_Email", "Presence_Website", "Presence_Phone",
    "Description_Length", "Keyword_Score",
]
handcrafted_features = df[handcrafted_cols].values
print("Scaling handcrafted features with the EXISTING fitted scaler (transform only)...")
handcrafted_scaled = scaler.transform(handcrafted_features)

X_combined = hstack([tfidf_matrix, csr_matrix(embeddings), csr_matrix(handcrafted_scaled)]).tocsr()
print(f"Combined feature matrix shape: {X_combined.shape}")

# --- Phase 6: Same split as the notebook ---
X_train, X_test, y_train, y_test = train_test_split(
    X_combined, df["Target"].values, test_size=0.2, stratify=df["Target"].values, random_state=42
)

# --- Train ONLY the Random Forest, same hyperparameters as the notebook ---
print("Training Random Forest...")
rf_model = RandomForestClassifier(n_estimators=100, max_depth=10, random_state=42)
rf_model.fit(X_train, y_train)

# --- Sanity-check metrics ---
y_pred = rf_model.predict(X_test)
y_prob = rf_model.predict_proba(X_test)[:, 1]
print("\n--- Random Forest test-set metrics (compare against model_comparison.csv) ---")
print(f"Accuracy:  {accuracy_score(y_test, y_pred):.4f}")
print(f"Precision: {precision_score(y_test, y_pred):.4f}")
print(f"Recall:    {recall_score(y_test, y_pred):.4f}")
print(f"F1 Score:  {f1_score(y_test, y_pred):.4f}")
print(f"ROC-AUC:   {roc_auc_score(y_test, y_prob):.4f}")

joblib.dump(rf_model, f"{BASE_DIR}/random_forest_model.pkl")
print(f"\nSaved: {BASE_DIR}/random_forest_model.pkl")
