# 🛡️ ScamShield — Fake Job & Internship Detection System
**by Graphura India Private Limited**

## Setup in 3 Steps

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Copy your trained .pkl models to the `models/` folder
Copy these files from your notebook output into `scam_detector/models/`:
- `nlp_pipeline.pkl`
- `random_forest_model.pkl`
- `decision_tree_model.pkl`
- `logistic_model.pkl`
- `scaler.pkl`
- `le_location.pkl`
- `le_title.pkl`

> **Note:** The app works even without .pkl files — it uses the keyword + domain + salary scoring engine as fallback.

### 3. Run the app
```bash
python app.py
```
Open your browser at: **http://localhost:5000**

## Project Structure
```
scam_detector/
├── app.py                  ← Flask backend
├── requirements.txt
├── models/                 ← Put your .pkl files here
│   ├── nlp_pipeline.pkl
│   ├── random_forest_model.pkl
│   └── ...
├── templates/
│   └── index.html          ← Frontend UI
└── static/
    ├── css/style.css
    └── js/main.js
```

## Risk Score Formula
```
Risk Score = Keyword×0.40 + Domain×0.30 + Salary×0.20 + NLP Model×0.10
```
