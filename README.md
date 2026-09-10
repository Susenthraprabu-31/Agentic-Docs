# Docs — Public Records Research

Agentic public records research demo for **Gila County, Arizona**. Uses Playwright browser automation starting at [NETR Online](https://publicrecords.netronline.com/), OpenAI agents for orchestration, Mistral OCR for scanned documents, Supabase for persistence, and a React live-progress UI.

## Stack

- **Backend:** Python 3.11+, FastAPI, Playwright, OpenAI, Mistral OCR, Supabase
- **Frontend:** React 18, Vite, TypeScript, Tailwind CSS

## Setup

### 1. Supabase

1. Create a project at [supabase.com](https://supabase.com)
2. Run SQL from `backend/app/db/migrations/001_initial.sql` in the SQL Editor
3. Create Storage buckets: `screenshots`, `reports` (optional for MVP — local files used as fallback)

### 2. Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
playwright install chromium
copy .env.example .env          # fill in API keys
uvicorn app.api.main:app --reload --port 8000
```

### 3. Frontend

```bash
cd frontend
npm install
npm run dev                     # http://localhost:5173
```

## API

| Method | Route | Description |
|--------|-------|-------------|
| POST | `/search` | Start a research run |
| GET | `/runs/{id}` | Run status + events |
| WS | `/runs/{id}/stream` | Live progress stream |
| GET | `/reports/by-run/{run_id}` | Report JSON |
| GET | `/reports/{id}/download` | PDF download |
| GET | `/docs` | Swagger UI |

## Architecture

All browser automation starts at NETR Online → resolves "Go to Data Online" links → searches Assessor, Recorder, and GIS portals in one Playwright session.

**Agents:**
1. **Orchestrator** (OpenAI GPT-4o) — plans and coordinates sources
2. **Extraction Normalizer** (OpenAI GPT-4o) — maps raw HTML/OCR to structured schemas
3. **Mistral OCR** — scanned document extraction

Without Supabase credentials, the backend uses an in-memory store for local development.
