# Supabase setup guide — DocIntel

This guide provisions Supabase (Postgres 16 + pgvector + Storage) and points the
DocIntel backend at it. Local development continues to use SQLite/local storage;
this is only needed for production deployment.

## 1. Create the Supabase project

1. Go to https://supabase.com and create a project.
2. Note these values from **Settings → API**:
   - **Project URL** → `SUPABASE_URL`
   - **Service role key** → `SUPABASE_SERVICE_KEY` (keep secret; never expose to the browser)
   - **anon public key** (not needed by the backend)
3. From **Settings → Database**, note the connection string:
   - `postgresql://postgres.<ref>:<password>@aws-...-pooler.supabase.com:6543/postgres`
   - Set `DATABASE_URL=postgresql+psycopg://postgres.<ref>:<password>@aws-...-pooler.supabase.com:6543/postgres`
     (the `+psycopg` driver prefix is added automatically by the backend config).

## 2. Enable pgvector

pgvector is available as an extension in Supabase. The backend ensures it on
startup:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

Run this once in the Supabase SQL Editor (or let the app do it —
`init_db` executes `CREATE EXTENSION IF NOT EXISTS vector`).

## 3. Create the Storage bucket

The backend uses bucket name `documents` (configurable via `SUPABASE_BUCKET`).

In the Supabase dashboard, go to **Storage → Create a bucket**:
- Name: `documents`
- Public: **false** (files are served via short-lived signed logic in the app)
- Enable RLS: **true**

Add an RLS policy so the service role can manage objects:

```sql
-- Service role bypasses RLS, so no user policy is strictly required for the backend.
-- If you want authenticated users to read their own uploads, add a policy here.
```

## 4. Configure the backend

Copy `backend/.env.example` to `backend/.env` and fill in:

```ini
# database
DATABASE_URL=postgresql+psycopg://postgres.<ref>:<pw>@aws-...-pooler.supabase.com:6543/postgres
environment=production

# storage
storage_backend=supabase
supabase_url=https://<ref>.supabase.co
supabase_service_key=<service-role-key>
supabase_bucket=documents

# AI (Groq)
groq_api_key=<your-groq-key>
groq_model=llama-3.3-70b-versatile

# security
secret_key=<long-random-string>
cookie_secure=true        # set true behind HTTPS
access_token_minutes=720
```

## 5. Initialize the database

```bash
cd backend
uv sync --extra dev
uv run python -m cli init-db
```

This creates all tables, the `pgvector` extension, the GIN full-text index,
the HNSW vector index, and the sheet-rows GIN index, then seeds the demo user
(`admin@docintel.local` / `admin12345` — **change this in production**).

## 6. Run

```bash
# API
uv run uvicorn app.main:app --port 8000

# Worker (run separately from the API; scale horizontally if needed)
uv run python -m app.worker
```

Set `AUTO_WORKER=true` only if you want the API to run an in-process worker
(single-service demo, not recommended for production).

## 7. Verify

```bash
curl https://<your-api>/health/ready
curl https://<your-api>/api/v1/meta
```

`meta.storage_backend` should report `supabase` and `meta.ai_enabled` should be
`true` when `GROQ_API_KEY` is set.

## 8. Security checklist for production

- [ ] Rotate `secret_key` away from the default
- [ ] Set `cookie_secure=true` and serve the API over HTTPS
- [ ] Restrict `SUPABASE_SERVICE_KEY` to backend-only environments
- [ ] Change the demo password or disable the seeded demo user
- [ ] Review CORS (`frontend_origin`) and rate limits
- [ ] Enable Supabase backups and point-in-time recovery
