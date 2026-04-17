# GigShield Backend — Run Instructions (No Docker)

## Prerequisites
- Python 3.11+
- PostgreSQL 15 (local or Supabase)
- Redis 7+ (local or Upstash)
- Node.js 20+ (frontend only)

## 1. Python Environment

```bash
cd gigshield/backend

# Create virtual environment
python3.11 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

## 2. Environment Configuration

```bash
cp .env.example .env
# Edit .env — minimum required for local dev:
```

Minimum `.env` for local dev:
```
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/gigshield
REDIS_URL=rediss://default:<UPSTASH_PASSWORD>@<UPSTASH_ENDPOINT>.upstash.io:6379
CELERY_BROKER_URL=rediss://default:<UPSTASH_PASSWORD>@<UPSTASH_ENDPOINT>.upstash.io:6379/0
CELERY_RESULT_BACKEND=rediss://default:<UPSTASH_PASSWORD>@<UPSTASH_ENDPOINT>.upstash.io:6379/1
JWT_SECRET_KEY=change-this-in-production-min-32-chars
RAZORPAY_KEY_ID=rzp_test_placeholder
RAZORPAY_KEY_SECRET=placeholder
RAZORPAY_WEBHOOK_SECRET=placeholder
```

## 3. Database Setup (local PostgreSQL)

```bash
# Create database
createdb gigshield

# Run migrations in order
psql postgresql://postgres:postgres@localhost:5432/gigshield \
  -f supabase/migrations/001_initial_schema.sql
psql postgresql://postgres:postgres@localhost:5432/gigshield \
  -f supabase/migrations/002_missing_tables_audit_fix.sql
psql postgresql://postgres:postgres@localhost:5432/gigshield \
  -f supabase/migrations/003_audit_schema_fixes.sql

# Seed hubs, config, and admin user
python scripts/seed_db.py
```

For **Supabase**: paste each migration file into the Supabase SQL editor and run.

## 4. Run FastAPI Backend

```bash
# Development (auto-reload)
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Production
gunicorn app.main:app \
  -w 4 -k uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000 \
  --timeout 60 \
  --access-logfile -
```

Verify: http://localhost:8000/health → `{"status":"ok","version":"3.0.0"}`
API docs: http://localhost:8000/docs

## 5. Run Celery Workers (separate terminals)

```bash
# Terminal 2 — Main worker (payout, oracle, vov queues)
celery -A app.workers.celery_app worker \
  --loglevel=info \
  -Q payout,oracle,vov,default \
  --concurrency=4

# Terminal 3 — Monday worker (dedicated, concurrency=1)
celery -A app.workers.celery_app worker \
  --loglevel=info \
  -Q monday \
  --concurrency=1

# Terminal 4 — Beat scheduler (all cron jobs)
celery -A app.workers.celery_app beat \
  --loglevel=info \
  --scheduler celery.beat:PersistentScheduler
```

## 6. Run Frontend

```bash
cd ../frontend
cp .env.local.example .env.local
# Set: NEXT_PUBLIC_API_URL=http://localhost:8000

npm install
npm run dev
# → http://localhost:3000
```

## 7. Train ML Model (optional but recommended)

```bash
cd backend
python app/ml/vulnerability_model.py
# Outputs: models/vulnerability_model.pkl + models/vulnerability_model_metrics.json
```

## 8. Test the System

```bash
# Run all tests
pytest tests/ -v

# Run only unit tests (no DB required)
pytest tests/unit/ -v

# Run with coverage
pytest tests/ --cov=app --cov-report=term-missing
```

## 9. Verify End-to-End

```bash
# 1. Send OTP
curl -X POST http://localhost:8000/api/v1/auth/send-otp \
  -H "Content-Type: application/json" \
  -d '{"phone":"9876543210"}'
# → check server logs for OTP (dev mode prints it)

# 2. Verify OTP (use OTP from logs)
curl -X POST http://localhost:8000/api/v1/auth/verify-otp \
  -H "Content-Type: application/json" \
  -d '{"phone":"9876543210","otp":"123456"}'
# → save access_token

TOKEN="eyJ..."

# 3. Admin login
curl -X POST http://localhost:8000/api/v1/auth/admin/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"Admin@GigShield2026"}'
# → save admin access_token

ADMIN_TOKEN="eyJ..."

# 4. Get hubs
curl http://localhost:8000/api/v1/hubs?city=Mumbai \
  -H "Authorization: Bearer $TOKEN"

# 5. Fire test trigger (replace hub_id from step 4)
curl -X POST http://localhost:8000/internal/triggers/evaluate \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"h3_index":"8b5225c50d4ffff","trigger_type":"rain","lat":19.1136,"lng":72.8697}'

# 6. Admin dashboard
curl http://localhost:8000/internal/admin/dashboard \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# 7. Stress test
curl -X POST http://localhost:8000/internal/admin/stress-test/run \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"city":"Mumbai","trigger_type":"rain","plan":"standard","pct_riders_affected":0.4,"avg_duration_hrs":3,"avg_income":700}'
```

## 10. Demo QA Data (Rider + Admin + Hub)

Use this section to seed and reuse fixed demo credentials for full manual testing.

Primary seed command:

```bash
python scripts/seed_demo_data.py
```

If your shell cannot resolve the DB host for direct SQL seeding, use API seeding (still inserts into DB through backend):

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"demo.20260404223722@gigshield.test","password":"Test@12345","phone":"9989797494","name":"Demo Rider","declared_income":1200,"city":"Mumbai"}'
```

Demo credentials:

- Rider email: `demo.20260404223722@gigshield.test`
- Rider phone: `9989797494`
- Rider password: `Test@12345`
- Admin username: `admin`
- Admin password: `Admin@GigShield2026`
- Hub username: `hub_manager`
- Hub password: `Hub@GigShield2026`

Latest validated state:

- Rider login: `200`
- Rider profile fetch: `200`
- Hubs fetch: `200`
- Payout destination save: `200`
- Policy create may return `400` if an active policy already exists for this rider.

## Production Deployment (No Docker)

### Render.com
1. **Backend service**: Python, Build=`pip install -r requirements.txt`, Start=`gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT`
2. **Celery worker service**: Start=`celery -A app.workers.celery_app worker -Q payout,oracle,vov,default --concurrency=4`
3. **Celery beat service**: Start=`celery -A app.workers.celery_app beat`
4. **Database**: Supabase (external)
5. **Redis**: Upstash (external)

### Vercel (Frontend)
```bash
cd frontend
npm run build
vercel deploy --prod
```

### Environment variables needed in production
All variables from `.env.example` — especially:
- `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` + `DATABASE_URL`
- `REDIS_URL` (Upstash)
- `RAZORPAY_*` (live keys)
- `OWM_API_KEY`, `WAQI_API_KEY`, `HERE_API_KEY`
- `WEATHERSTACK_API_KEY` (heat trigger)
- `JWT_SECRET_KEY` (32+ random chars)
- `SENTRY_DSN` (error tracking)
