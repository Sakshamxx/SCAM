# 🛡️ ScamShield — Fake Job & Internship Detection System

**ScamShield** is a production-grade, full-stack intelligent screening system designed to identify and analyze fake job postings, scam internships, and fraudulent recruitment domains. It leverages a hybrid scoring engine combining Machine Learning classifiers, NLP pipeline models, rule-based heuristics, and domain intelligence.

---

## 🚀 Key Features

*   **Hybrid Prediction Engine**: Integrates a Naive Bayes NLP model (for post description analysis) and a Logistic Regression ML model (for tabular features) to score risk dynamically.
*   **Deep Document Analysis (OCR)**: Extracts text from PDFs and scanned images using a tiered pipeline: `pdfplumber` ➔ `PyMuPDF` ➔ Tesseract OCR fallback.
*   **Domain & WHOIS Intelligence**: Checks registrar details, registration age, and blacklists suspicious domains using `python-whois`.
*   **Supabase Database Integration**: Stores scam reports, domain blacklists, company reputations, and system logs.
*   **Render-Ready Deployment**: Includes automated blueprint setup for system dependencies (`poppler-utils` & `tesseract-ocr`) and Gunicorn configuration out of the box.

---

## 📁 Repository Structure

```directory
SCAM/
├── Procfile                    # Render process manager configuration
├── render.yaml                 # Infrastructure-as-code for Render deployment
├── requirements.txt            # Unified production dependencies
├── run_scamshield.command      # Interactive macOS local launcher
├── Data_Collection.xlsx       # Base ML/NLP training dataset
└── scam_detector/              # Main application package
    ├── app.py                  # Flask application initialization
    ├── wsgi.py                 # WSGI entrypoint for Gunicorn
    ├── config/                 # Settings and environment configuration
    ├── database/               # Supabase API handlers and schema definitions
    ├── domain_intelligence/    # Domain age and WHOIS lookup logic
    ├── models/                 # Pre-trained ML/NLP models (.pkl)
    ├── nlp/                    # NLP preprocessing and text training modules
    ├── routes/                 # Modular Blueprint route handlers
    ├── rule_engine/            # Heuristic checks (salary, keywords, whitelist)
    ├── services/               # Core business logic (model loading & PDF OCR)
    ├── static/                 # CSS/JS styling, fonts, and images
    └── templates/              # HTML views (dashboard, analyzer, logs)
```

---

## 🛠️ Local Setup

### Prerequisites
*   Python 3.11.x
*   Tesseract OCR engine (installed on your system, e.g. `brew install tesseract`)
*   Poppler (for PDF rendering, e.g. `brew install poppler`)

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Create a `.env` file in the root folder with the following variables:
```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-supabase-anon-key
SECRET_KEY=your-flask-secret-key
```

### 3. Run the Application
**On macOS**: Simply double-click or run:
```bash
./run_scamshield.command
```

**Otherwise**:
```bash
python scam_detector/app.py
```
Open your browser at **http://localhost:5001**.

---

## 🌐 Render Deployment

Deploying to Render takes one step:

1.  Connect your GitHub repository to Render.
2.  Render will automatically detect [render.yaml](file:///Users/sakshamchauhan/Desktop/SCAM/render.yaml), configure Python 3.11, install system dependencies (`poppler-utils`, `tesseract-ocr`, `libgl1`), and launch the service via Gunicorn.

---

## 📊 Heuristic Risk Scoring Model

The final risk rating is computed as:
$$Risk = (ML\text{ Model} \times 0.30) + (NLP\text{ Model} \times 0.30) + (Rule\text{-Based} \times 0.30) + (Domain\text{ Intel} \times 0.10)$$
