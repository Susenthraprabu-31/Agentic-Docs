# Docs Architecture

## Flow

1. User submits search (owner name or parcel) via React frontend
2. FastAPI creates a `run` record and enqueues background job
3. **Orchestrator Agent** opens NETR Online county directory page
4. Scrapes Assessor / Recorder / Treasurer / GIS "Go to Data Online" links
5. Follows links in same Playwright session to search county portals
6. **html_extractors** parses structured HTML; **Mistral OCR** handles scanned docs
7. **Extraction Normalizer Agent** validates partial extractions
8. Results persisted to Supabase; events streamed via WebSocket
9. **Report Builder** assembles HTML → PDF; user downloads from UI

## Agents

| Agent | Provider | Role |
|-------|----------|------|
| Orchestrator | OpenAI GPT-4o | Plan sources, invoke drivers, log trail |
| Extraction Normalizer | OpenAI GPT-4o | Map raw data → Pydantic schemas |
| Mistral OCR | mistral-ocr-latest | Scanned document OCR |

## Database Tables

- `runs` — search jobs
- `run_events` — live "we show our work" trail
- `records` — assessor parcel data
- `documents` — recorder filings
- `reports` — assembled report + PDF path
