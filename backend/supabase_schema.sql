-- CSV Uploads table
CREATE TABLE csv_uploads (
    id UUID PRIMARY KEY,
    filename TEXT NOT NULL,
    template TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- CSV Rows table
CREATE TABLE csv_rows (
    id UUID PRIMARY KEY,
    upload_id UUID REFERENCES csv_uploads(id) ON DELETE CASCADE,
    data JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Jobs table
CREATE TABLE jobs (
    id UUID PRIMARY KEY,
    row_id UUID REFERENCES csv_rows(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Blogs table
CREATE TABLE blogs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID REFERENCES jobs(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX idx_csv_rows_upload_id ON csv_rows(upload_id);
CREATE INDEX idx_jobs_row_id ON jobs(row_id);
CREATE INDEX idx_jobs_status ON jobs(status);
CREATE INDEX idx_blogs_job_id ON blogs(job_id);
