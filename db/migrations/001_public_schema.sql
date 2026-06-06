-- ─────────────────────────────────────────────────────────────────────────────
-- 001_public_schema.sql
-- Ops agent internal tables (public schema).
-- LangGraph checkpoint tables (checkpoints, checkpoint_blobs, checkpoint_writes)
-- are NOT here — they are auto-created by AsyncPostgresSaver.from_conn_string().
-- ─────────────────────────────────────────────────────────────────────────────

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. sessions
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sessions (
    session_id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_query          TEXT        NOT NULL,
    intent              VARCHAR(20) NOT NULL
                            CHECK (intent IN ('diagnose', 'fix', 'recall', 'summarize')),
    status              VARCHAR(20) NOT NULL DEFAULT 'running'
                            CHECK (status IN ('running', 'completed', 'failed', 'awaiting_approval')),
    active_specialists  JSONB,
    retry_count         SMALLINT    DEFAULT 0,
    reflection_passed   BOOLEAN,
    reflection_notes    JSONB,
    correlation_matrix  JSONB,
    final_response      JSONB,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    completed_at        TIMESTAMPTZ
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. specialist_findings
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS specialist_findings (
    id                    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id            UUID        NOT NULL
                              REFERENCES sessions(session_id) ON DELETE CASCADE,
    domain                VARCHAR(20) NOT NULL
                              CHECK (domain IN ('sales', 'inventory', 'marketing', 'support')),
    signals               JSONB       NOT NULL,
    confidence            FLOAT       NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    raw_tool_outputs      JSONB,
    sub_question_answered TEXT,
    created_at            TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (session_id, domain)
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 3. root_causes
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS root_causes (
    id                 UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id         UUID        NOT NULL
                           REFERENCES sessions(session_id) ON DELETE CASCADE,
    description        TEXT        NOT NULL,
    confidence         FLOAT       NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    supporting_domains JSONB       NOT NULL,
    evidence           JSONB       NOT NULL,
    rank               SMALLINT,
    created_at         TIMESTAMPTZ DEFAULT NOW()
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 4. hitl_requests
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS hitl_requests (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id       UUID        NOT NULL UNIQUE
                         REFERENCES sessions(session_id) ON DELETE CASCADE,
    status           VARCHAR(20) NOT NULL DEFAULT 'pending'
                         CHECK (status IN ('pending', 'approved', 'rejected', 'modified', 'timed_out')),
    proposed_actions JSONB       NOT NULL,
    approved_actions JSONB,
    reviewer_note    TEXT,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    resolved_at      TIMESTAMPTZ
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 5. executed_actions
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS executed_actions (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID        NOT NULL
                        REFERENCES sessions(session_id) ON DELETE CASCADE,
    hitl_request_id UUID
                        REFERENCES hitl_requests(id) ON DELETE SET NULL,
    action_type     VARCHAR(30) NOT NULL
                        CHECK (action_type IN ('restock', 'apply_discount', 'pause_campaign', 'create_ticket')),
    parameters      JSONB       NOT NULL,
    status          VARCHAR(10) NOT NULL CHECK (status IN ('success', 'failed')),
    api_response    JSONB,
    executed_at     TIMESTAMPTZ DEFAULT NOW()
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 6. incidents
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS incidents (
    incident_id      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id       UUID
                         REFERENCES sessions(session_id) ON DELETE SET NULL,
    query            TEXT        NOT NULL,
    intent           VARCHAR(20) NOT NULL,
    root_causes      JSONB       NOT NULL,
    actions_proposed JSONB       NOT NULL,
    actions_approved JSONB       NOT NULL,
    actions_executed JSONB       NOT NULL,
    outcome_summary  TEXT        NOT NULL,
    embedding_text   TEXT        NOT NULL,
    qdrant_point_id  UUID,
    created_at       TIMESTAMPTZ DEFAULT NOW()
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Indexes
-- ─────────────────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_sessions_intent      ON sessions(intent);
CREATE INDEX IF NOT EXISTS idx_sessions_status      ON sessions(status);
CREATE INDEX IF NOT EXISTS idx_sessions_created_at  ON sessions(created_at);

CREATE INDEX IF NOT EXISTS idx_specialist_findings_session_id ON specialist_findings(session_id);
CREATE INDEX IF NOT EXISTS idx_root_causes_session_id         ON root_causes(session_id);

CREATE INDEX IF NOT EXISTS idx_incidents_intent       ON incidents(intent);
CREATE INDEX IF NOT EXISTS idx_incidents_created_at   ON incidents(created_at);
CREATE INDEX IF NOT EXISTS idx_incidents_qdrant_point ON incidents(qdrant_point_id);
