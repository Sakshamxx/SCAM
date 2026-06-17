import os
import re
import numpy as np
import spacy
import nltk
from scipy.sparse import hstack, csr_matrix
import joblib
from sklearn.base import BaseEstimator, TransformerMixin

class DenseTransformer(BaseEstimator, TransformerMixin):
    def fit(self, X, y=None):
        return self
    def transform(self, X, y=None):
        if hasattr(X, "toarray"):
            return X.toarray()
        return X

class JobScamInferencePipeline:
    def __init__(self, model, tfidf_vec, st_model, scaler):
        self.model = model
        self.tfidf = tfidf_vec
        self.st = st_model
        self.scaler = scaler
        self.nlp = spacy.load('en_core_web_sm', disable=['parser', 'ner'])
        self.salary_regex = re.compile(r'₹|\$|stipend|salary|/month|/year|lpa', re.IGNORECASE)
        self.email_regex = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
        self.website_regex = re.compile(r'https?://\S+|www\.\S+|\b\w+\.(?:com|org|net|edu|gov|co|io|biz|info|in)\b', re.IGNORECASE)
        self.phone_regex = re.compile(r'(?:\+?\d{1,3}[ -]?)?\(?\d{3}\)?[ -]?\d{3}[ -]?\d{4}|\b\d{10}\b|\b\d{5}[ -]?\d{5}\b')
        
    def _clean_text(self, text):
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'https?://\S+|www\.\S+', ' ', text)
        text = re.sub(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', ' ', text)
        text = re.sub(r'[^a-zA-Z0-9\s]', ' ', text)
        return text.lower()
        
    def predict(self, raw_post):
        # raw_post keys: Job, Company, Location, Description, Skills, Experience, Education_Required, Salary_Disclosed, Description_Length, Keyword_Score
        combined = (
            str(raw_post.get('Job', '')) + ' ' + 
            str(raw_post.get('Company', '')) + ' ' + 
            str(raw_post.get('Location', '')) + ' ' + 
            str(raw_post.get('Description', '')) + ' ' + 
            str(raw_post.get('Skills', '')) + ' ' + 
            str(raw_post.get('Experience', '')) + ' ' + 
            str(raw_post.get('Education_Required', ''))
        )
        
        # Handcrafted Features
        text_len = len(combined)
        word_cnt = len(combined.split())
        sent_cnt = len(nltk.sent_tokenize(combined))
        avg_word_len = np.mean([len(w) for w in combined.split()]) if word_cnt > 0 else 0.0
        upper_ratio = sum(1 for c in combined if c.isupper()) / text_len if text_len > 0 else 0.0
        num_digits = sum(1 for c in combined if c.isdigit())
        num_special = sum(1 for c in combined if not c.isalnum() and not c.isspace())
        
        pres_salary = 1 if raw_post.get('Salary_Disclosed') == 'Yes' or self.salary_regex.search(str(raw_post.get('Job', '')) + ' ' + str(raw_post.get('Description', ''))) else 0
        pres_email = 1 if self.email_regex.search(combined) else 0
        pres_web = 1 if self.website_regex.search(combined) else 0
        pres_phone = 1 if self.phone_regex.search(combined) else 0
        
        handcrafted = np.array([[
            text_len, word_cnt, sent_cnt, avg_word_len, upper_ratio, num_digits, num_special,
            pres_salary, pres_email, pres_web, pres_phone,
            int(raw_post.get('Description_Length', 0)), int(raw_post.get('Keyword_Score', 0))
        ]])
        handcrafted_scaled = self.scaler.transform(handcrafted)
        
        # Clean and preprocess
        cleaned = self._clean_text(combined)
        doc = self.nlp(cleaned)
        lemmatized = ' '.join([token.lemma_ for token in doc if not token.is_stop and not token.is_space and len(token.text) > 1])
        
        # Extract text representations
        tfidf_feat = self.tfidf.transform([lemmatized])
        emb_feat = self.st.encode([cleaned])
        
        # Combine
        X_infer = hstack([
            tfidf_feat, 
            csr_matrix(emb_feat), 
            csr_matrix(handcrafted_scaled)
        ]).tocsr()
        
        # Predict
        if hasattr(self.model, "predict_proba"):
            pred = self.model.predict(X_infer)[0]
            prob = self.model.predict_proba(X_infer)[0, 1]
        else:
            pred = self.model.predict(X_infer)[0]
            prob = 1.0 if pred == 1 else 0.0
            
        return {'Prediction': 'Scam (1)' if pred == 1 else 'Real (0)', 'Scam Probability': float(prob)}

def load_pipeline(path='pipeline.pkl'):
    return joblib.load(path)
