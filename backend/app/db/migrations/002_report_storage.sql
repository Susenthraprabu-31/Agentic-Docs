-- Add Supabase Storage metadata for report PDFs

ALTER TABLE reports
    ADD COLUMN IF NOT EXISTS storage_path TEXT,
    ADD COLUMN IF NOT EXISTS storage_url TEXT;
