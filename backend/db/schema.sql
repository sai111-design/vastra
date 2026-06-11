-- Vastra application schema (PostgreSQL canonical form).
-- The SQLite deployment target applies textual translations at load time;
-- see backend/db/connection.py (_translate_for_sqlite).

CREATE TABLE IF NOT EXISTS sessions (
    id            TEXT PRIMARY KEY,
    store_domain  TEXT NOT NULL,
    cart_id       TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_active   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS messages (
    id           BIGSERIAL PRIMARY KEY,
    session_id   TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role         TEXT NOT NULL CHECK (role IN ('user','assistant')),
    content      TEXT NOT NULL,
    events_json  TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, created_at);

CREATE TABLE IF NOT EXISTS buyer_profiles (
    session_id    TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    sizes_json    TEXT NOT NULL DEFAULT '{}',
    budget_min    INTEGER,
    budget_max    INTEGER,
    style_tags    TEXT NOT NULL DEFAULT '[]',
    last_category TEXT,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tool_call_log (
    id          BIGSERIAL PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    agent       TEXT NOT NULL,
    tool_name   TEXT NOT NULL,
    args_json   TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('ok','error','retried')),
    confirmed   BOOLEAN,
    latency_ms  INTEGER,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_toolcalls_session ON tool_call_log(session_id, created_at);
