CREATE TABLE IF NOT EXISTS category_priority (
    category TEXT PRIMARY KEY,
    weight NUMERIC(4,1) NOT NULL DEFAULT 5.0,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS issues (
    id SERIAL PRIMARY KEY,
    issue_date DATE NOT NULL,
    branch_code TEXT NOT NULL,
    category TEXT NOT NULL,
    issue_type TEXT NOT NULL CHECK (issue_type IN ('INVENTORY_SHORTAGE', 'STAFF_SHORTAGE')),
    severity NUMERIC(4,1) NOT NULL DEFAULT 5.0,
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'PENDING', 'RESOLVED')),
    gap NUMERIC,
    min_quantity NUMERIC,
    current_quantity NUMERIC,
    resolution_note TEXT,
    predicted BOOLEAN NOT NULL DEFAULT FALSE,
    confidence NUMERIC(3,2),
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS issues_unique_open
    ON issues (issue_date, branch_code, category, issue_type)
    WHERE status != 'RESOLVED';

CREATE INDEX IF NOT EXISTS issues_date_status ON issues (issue_date, status);
CREATE INDEX IF NOT EXISTS issues_severity ON issues (severity DESC);
