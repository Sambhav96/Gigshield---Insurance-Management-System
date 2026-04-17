# GigShield v4 — Parametric Income Protection for Gig Workers

> **Production-ready** parametric insurance platform for Q-Commerce delivery riders (Zepto, Blinkit, Swiggy Instamart)

[![AUC-ROC](https://img.shields.io/badge/ML%20AUC--ROC-0.9935-brightgreen)](backend/models/)
[![Version](https://img.shields.io/badge/version-4.0-blue)](.)
[![License](https://img.shields.io/badge/license-proprietary-red)](.)

---

## 🚀 Quick Start (5 minutes)

### Prerequisites
- Python 3.11+
- Node.js 18+
- PostgreSQL (Supabase recommended) 
- Redis (Upstash recommended)

### 1. Backend Setup

```bash
cd backend

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your Supabase + Redis credentials

# Run database migrations
alembic upgrade head

# Seed demo data (creates admin/hub/rider accounts + trains ML model)
python scripts/seed_demo_data.py

# Start the API server
uvicorn app.main:app --reload --port 8000
```

### 2. Frontend Setup

```bash
cd frontend/app-frontend

# Install dependencies
npm install

# Configure environment
echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local

# Start the dev server
npm run dev
```

### 3. Start Background Workers (optional for full flow)

```bash
cd backend

# Start Redis (if local)
redis-server &

# Start Celery worker
celery -A app.workers.celery_app worker --loglevel=info &

# Start Celery beat (scheduled jobs)
celery -A app.workers.celery_app beat --loglevel=info &
```

---

## 🔑 Demo Credentials

| Portal | URL | Username/Email | Password |
|--------|-----|---------------|----------|
| **Admin** | `/login/admin` | `admin` | `Admin@GigShield2026` |
| **Hub Manager** | `/login/hub-manager` | `hub_manager` | `Hub@GigShield2026` |
| **Demo Rider** | `/login/rider` | `rider@demo.in` | `Rider@GigShield2026` |

---

## 🏗️ Architecture

```
Frontend (Next.js 14 PWA)
  ├── Rider Portal        /rider/*
  ├── Hub Manager Portal  /hub/*
  └── Admin Portal        /admin/*

Backend (FastAPI)
  ├── Rider API           /api/v1/*
  ├── Internal Admin API  /internal/*
  └── B2B Hub API         /api/v1/b2b/*

ML System
  ├── Vulnerability GBM   AUC-ROC: 0.9935
  ├── DBSCAN Fraud Cluster
  └── YOLOv8 VOV Inference

Workers (Celery + Redis)
  ├── Oracle (every 15 min)
  ├── Payout processor
  ├── Monday debit cycle
  ├── ML retrain (monthly)
  └── Notification delivery
```

---

## 📊 ML Model Performance

```
Model:       CalibratedGBM + IsotonicRegression
AUC-ROC:     0.9935  (CV: 0.9907 ± 0.0006)
Brier Score: 0.0274  (excellent calibration)
F1:          0.9145
Precision:   0.9184
Recall:      0.9105
```

To retrain: `cd backend && python -m app.ml.vulnerability_model`

---

## 🛡️ 6 Trigger Types

| Trigger | Threshold | APIs |
|---------|-----------|------|
| Heavy Rain | >35mm/hr sustained 45min | OWM, IMD |
| Flooding | NDMA advisory + NDWI >0.3 | NDMA, Earth Engine |
| Heatwave | Wet bulb >32°C | Weatherstack |
| Air Quality | AQI >200 | WAQI, CPCB |
| Bandh | Road speed <15% baseline | HERE Maps |
| Platform Down | Uptime <95% for 30min | Direct health check |

---

## 🦄 Unicorn Features

- **Zero-touch payouts**: Oracle fires → fraud check → UPI payout in <60 seconds
- **Calibrated ML pricing**: GBM + isotonic calibration, AUC 0.9935
- **3-layer fraud detection**: Intent (GPS+session+platform) → Presence (H3+haversine) → Bayesian score
- **DBSCAN geospatial fraud clustering**: Detects coordinated enrollment fraud
- **B2B Hub API**: Zepto/Blinkit/Instamart fleet coverage reporting
- **WhatsApp notifications**: Meta Cloud API for India market reach
- **A/B experiment framework**: Deterministic group assignment, admin-managed
- **Rider referral system**: ₹50 reward per successful referral
- **God Mode triggers**: Synthetic trigger injection for investor demos
- **Backtesting engine**: Historical loss ratio simulation
- **IRDAI compliance docs**: Full regulatory framework included

---

## 📁 Project Structure

```
DEVTRAILS FINAL SHOT/
├── backend/
│   ├── app/
│   │   ├── api/          FastAPI routes (v1 + internal)
│   │   ├── ml/           ML models (GBM, DBSCAN, YOLOv8)
│   │   ├── services/     Business logic
│   │   ├── workers/      Celery tasks
│   │   └── external/     API clients (OWM, WAQI, Razorpay...)
│   ├── alembic/versions/ Database migrations
│   ├── models/           Trained ML artifacts
│   ├── scripts/          seed_demo_data.py
│   └── docs/             IRDAI_COMPLIANCE.md
└── frontend/app-frontend/
    ├── app/
    │   ├── admin/        Admin portal
    │   ├── hub/          Hub manager portal  
    │   ├── rider/        Rider PWA
    │   └── login/        Login pages
    ├── components/       Shared components
    └── lib/api/          API client + auth
```

---

## 🔧 Production Checklist

- [ ] Set `ENVIRONMENT=production` in .env
- [ ] Rotate `JWT_SECRET_KEY`
- [ ] Configure real Razorpay API keys
- [ ] Add real OWM/WAQI API keys
- [ ] Set up Supabase RLS policies
- [ ] Configure WhatsApp Business API token
- [ ] Set up Prometheus + Grafana (see `prometheus.yml`)
- [ ] Run `alembic upgrade head` on production DB
- [ ] Set `CORS` to production domain in `main.py`
- [ ] Apply for IRDAI Regulatory Sandbox (see `docs/IRDAI_COMPLIANCE.md`)

---

*GigShield v4.0 — Built with ❤️ for India's 10M+ gig delivery workers*
