"""Train NLP + structured models and export .pkl files to models/."""
import re
import joblib
import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.feature_extraction import text
from sklearn.metrics import accuracy_score, f1_score, classification_report

BASE_DIR = Path(__file__).parent.parent
DATA_PATHS = [
    BASE_DIR / "Data Collection" / "Data_Collection.csv",
    BASE_DIR / "Data_Collection.csv",
    BASE_DIR / "data" / "Data_Collection.csv",
]
DATA_PATH = next((p for p in DATA_PATHS if p.exists()), None)
if DATA_PATH is None:
    raise FileNotFoundError(
        "Data_Collection.csv not found. "
        "Place it in project root or 'Data Collection/' folder."
    )

MODEL_DIR = Path(__file__).parent / "models"
MODEL_DIR.mkdir(exist_ok=True)


def normalize_text(text_val):
    text_val = str(text_val).lower().strip()
    text_val = re.sub(r"https?://\S+|www\.\S+", "[url]", text_val)
    text_val = re.sub(r"\S+@\S+\.\S+", "[email]", text_val)
    text_val = re.sub(r"\b\d+\b", "[num]", text_val)
    text_val = re.sub(r"\s+", " ", text_val).strip()
    return text_val


def parse_experience(val):
    if pd.isna(val) or val == '':
        return 0.0
    val = str(val).lower().strip()
    if "fresher" in val or "entry" in val:
        return 0.0
    match = re.search(r"(\d+)", val)
    return float(match.group(1)) if match else 0.0


def parse_salary(val):
    if pd.isna(val):
        return 0.0
    nums = re.findall(r"\d+", str(val).replace(",", ""))
    if nums:
        return float(nums[0])
    return 0.0


def load_and_clean():
    df = pd.read_csv(DATA_PATH)
    print(f"Raw rows: {len(df)}")

    df['Label'] = df['Label'].astype(str).str.strip().str.capitalize()
    label_map = {'Legit': 0, 'Suspicious': 1, 'Scam': 2}
    df['Label_Encoded'] = df['Label'].map(label_map)
    df = df.dropna(subset=['Label_Encoded'])
    df['Label_Encoded'] = df['Label_Encoded'].astype(int)

    df['Description'] = df['Description'].fillna('').apply(normalize_text)
    df['Job'] = df['Job'].fillna('').apply(normalize_text)
    df['Skills'] = df['Skills'].fillna('')
    df['Company'] = df['Company'].fillna('Unknown')
    df['Location'] = df['Location'].fillna('Unknown')
    df['Experience'] = df['Experience'].apply(parse_experience)
    df['Salary_Numeric'] = df['Salary/Stripend'].apply(parse_salary)
    df['Keyword_Score'] = pd.to_numeric(df.get('Keyword_Score', 0), errors='coerce').fillna(0)
    df['Description_Length'] = df['Description'].str.len()

    df['Combined_Text'] = (
        df['Job'].fillna('') + ' ' +
        df['Description'].fillna('') + ' ' +
        df['Skills'].fillna('')
    )
    df = df.drop_duplicates(subset=['Combined_Text'])
    df = df.dropna(subset=['Job', 'Location'])

    print(f"Cleaned rows: {len(df)}")
    print(f"Label distribution:\n{df['Label_Encoded'].value_counts().sort_index()}")
    return df


def train_nlp(df):
    X = df['Combined_Text'].fillna('').astype(str)
    y = df['Label_Encoded'].values

    X_tr, X_te, y_tr, y_te = train_test_split(
        X, y, test_size=0.20, stratify=y, random_state=42
    )

    extended_stopwords = [
        "rs", "number", "work", "home", "earn", "earning", "tasks", "whatsapp",
        "online", "daily", "month", "payment", "registration", "hours", "needed",
        "income", "receive", "customer", "operations", "lead", "team", "management",
        "experience", "skills", "job", "company", "position", "hire", "hiring",
    ]
    stopwords = list(text.ENGLISH_STOP_WORDS.union(extended_stopwords))

    pipeline = Pipeline([
        ("tfidf", TfidfVectorizer(
            max_features=100,
            ngram_range=(1, 2),
            stop_words=stopwords,
            min_df=2,
            max_df=0.8,
            sublinear_tf=True,
        )),
        ("clf", LogisticRegression(
            C=1.0, max_iter=1000, class_weight='balanced', random_state=42
        )),
    ])
    pipeline.fit(X_tr, y_tr)
    y_pred = pipeline.predict(X_te)
    acc = accuracy_score(y_te, y_pred)
    f1 = f1_score(y_te, y_pred, average='weighted', zero_division=0)
    print(f"NLP F1 (weighted): {f1:.4f}")
    print(classification_report(y_te, y_pred, target_names=['Legit', 'Suspicious', 'Scam']))
    return pipeline, acc


def train_structured(df):
    df_ml = df.copy()
    df_ml['Salary_Numeric'] = df_ml['Salary_Numeric'].fillna(df_ml['Salary_Numeric'].median())
    df_ml['Experience'] = df_ml['Experience'].fillna(0)
    df_ml['Keyword_Score'] = df_ml['Keyword_Score'].fillna(0)
    df_ml['Description_Length'] = df_ml['Description_Length'].fillna(0)

    le_location = LabelEncoder()
    le_title = LabelEncoder()
    df_ml['Location_Enc'] = le_location.fit_transform(df_ml['Location'].astype(str))
    df_ml['Title_Enc'] = le_title.fit_transform(df_ml['Job'].astype(str))

    features = df_ml[[
        'Salary_Numeric', 'Experience', 'Keyword_Score',
        'Description_Length', 'Location_Enc', 'Title_Enc'
    ]]
    X = features.values
    y = df_ml['Label_Encoded'].values

    X_tr, X_te, y_tr, y_te = train_test_split(
        X, y, test_size=0.20, stratify=y, random_state=42
    )
    scaler = StandardScaler()
    X_tr_s = scaler.fit_transform(X_tr)
    X_te_s = scaler.transform(X_te)

    lr = LogisticRegression(
        C=1.0, max_iter=1000, class_weight='balanced', random_state=42
    )
    lr.fit(X_tr_s, y_tr)
    structured_acc = accuracy_score(y_te, lr.predict(X_te_s))
    return lr, scaler, le_location, le_title, structured_acc


def main():
    print("\n" + "=" * 60)
    print("ScamShield ML Training — Data_Collection.csv")
    print("=" * 60)
    print(f"Dataset: {DATA_PATH}\n")

    df = load_and_clean()
    nlp_pipeline, acc = train_nlp(df)
    lr_standalone, scaler, le_location, le_title, structured_acc = train_structured(df)

    joblib.dump(nlp_pipeline, MODEL_DIR / 'nlp_pipeline.pkl')
    joblib.dump(lr_standalone, MODEL_DIR / 'logistic_model.pkl')
    joblib.dump(scaler, MODEL_DIR / 'scaler.pkl')
    joblib.dump(le_location, MODEL_DIR / 'le_location.pkl')
    joblib.dump(le_title, MODEL_DIR / 'le_title.pkl')

    print(f"\n✅ NLP Pipeline Accuracy: {acc:.4f} ({acc * 100:.2f}%)")
    print(f"✅ Structured LR Accuracy: {structured_acc:.4f} ({structured_acc * 100:.2f}%)")
    print(f"✅ All models saved to: {MODEL_DIR}\n")


if __name__ == "__main__":
    main()
