-- Docs initial schema

CREATE TABLE IF NOT EXISTS runs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    state         TEXT NOT NULL,
    county        TEXT NOT NULL,
    query_type    TEXT NOT NULL,
    query_value   TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending',
    plan_json     JSONB,
    error_message TEXT,
    started_at    TIMESTAMPTZ,
    completed_at  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS run_events (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id      UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    event_type  TEXT NOT NULL,
    source      TEXT,
    payload     JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_run_events_run_id ON run_events(run_id);

CREATE TABLE IF NOT EXISTS records (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id           UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    source           TEXT NOT NULL,
    apn              TEXT,
    owner_name       TEXT,
    legal_desc       TEXT,
    assessed_value   NUMERIC,
    property_address TEXT,
    raw_json         JSONB DEFAULT '{}',
    created_at       TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS documents (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id            UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    document_type     TEXT,
    recording_date    DATE,
    book_page         TEXT,
    instrument_number TEXT,
    grantor           TEXT,
    grantee           TEXT,
    source_url        TEXT,
    screenshot_path   TEXT,
    ocr_json          JSONB DEFAULT '{}',
    created_at        TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS reports (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id      UUID UNIQUE NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    report_json JSONB NOT NULL DEFAULT '{}',
    html_path   TEXT,
    pdf_path    TEXT,
    created_at  TIMESTAMPTZ DEFAULT now()
);
