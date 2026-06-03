CREATE TABLE IF NOT EXISTS employees (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    branch_code TEXT NOT NULL,
    roles TEXT[] NOT NULL DEFAULT '{}',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS shifts (
    id SERIAL PRIMARY KEY,
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    shift_date DATE NOT NULL,
    shift_type TEXT NOT NULL,   -- 'morning' | 'evening' | 'full' | 'off'
    branch_code TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual',  -- 'excel' | 'manual'
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS shifts_unique
    ON shifts (employee_id, shift_date, branch_code);

CREATE TABLE IF NOT EXISTS staff_exceptions (
    id SERIAL PRIMARY KEY,
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    from_date DATE NOT NULL,
    to_date DATE NOT NULL,
    exception_type TEXT NOT NULL CHECK (exception_type IN ('SICK', 'VACATION', 'TRAINING', 'OTHER')),
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS staff_exceptions_dates
    ON staff_exceptions (employee_id, from_date, to_date);
