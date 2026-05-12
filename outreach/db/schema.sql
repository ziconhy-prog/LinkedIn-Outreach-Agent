-- LinkedIn Outreach Agent — schema v1
-- Forward-compatible: every table is created in Phase 1, even though only
-- `prospects` is populated yet. This avoids future migrations.

CREATE TABLE IF NOT EXISTS prospects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,                          -- 'bni' | 'hashtag' | 'manual'
    source_id TEXT NOT NULL,                       -- stable id within the source
    name TEXT NOT NULL,
    company TEXT,
    profession TEXT,
    area TEXT,
    city TEXT,
    bni_chapter TEXT,
    phone TEXT,
    category TEXT,
    linkedin_url TEXT,                             -- enriched on demand later
    enrichment_status TEXT NOT NULL DEFAULT 'pending', -- 'pending'|'found'|'not_found'|'error'
    enrichment_attempted_at TEXT,
    score REAL,                                    -- computed at surfacing time
    do_not_contact INTEGER NOT NULL DEFAULT 0,     -- boolean (0|1)
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source, source_id)
);

CREATE TABLE IF NOT EXISTS threads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prospect_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',         -- 'queued'|'active'|'closed_ghosted'|'closed_declined'|'closed_meeting'|'closed_dnc'
    last_outbound_at TEXT,                         -- used by same-day duplicate guardrail
    last_inbound_at TEXT,                          -- used by same-day duplicate guardrail
    outbound_count INTEGER NOT NULL DEFAULT 0,
    inbound_count INTEGER NOT NULL DEFAULT 0,
    closed_at TEXT,
    closed_reason TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (prospect_id) REFERENCES prospects(id)
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id INTEGER NOT NULL,
    direction TEXT NOT NULL,                       -- 'inbound'|'outbound'
    role TEXT,                                     -- 'opener'|'follow_up'|'reply'|'closer'
    content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',          -- 'draft'|'approved'|'sent'|'skipped'|'edited'
    sent_at TEXT,
    approved_via TEXT,                             -- 'telegram' (only allowed value v1)
    approved_at TEXT,
    needs_attention INTEGER NOT NULL DEFAULT 0,    -- ⚠️ NEEDS YOU flag
    needs_attention_reason TEXT,                   -- e.g. 'pricing_question'
    redraft_instruction TEXT,                      -- operator's redraft guidance (set via /redraft)
    redraft_requested_at TEXT,                     -- when /redraft was issued
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (thread_id) REFERENCES threads(id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    action TEXT NOT NULL,                          -- 'profile_view'|'name_search'|'message_send'|...
    target TEXT,                                   -- prospect id, URL, etc.
    success INTEGER NOT NULL DEFAULT 1,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS do_not_contact (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prospect_id INTEGER,
    name TEXT,
    linkedin_url TEXT,
    reason TEXT,                                   -- 'requested'|'declined'|'aggressive'
    added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(linkedin_url),
    FOREIGN KEY (prospect_id) REFERENCES prospects(id)
);

CREATE TABLE IF NOT EXISTS daily_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,                     -- YYYY-MM-DD Malaysia time
    openers_sent INTEGER NOT NULL DEFAULT 0,
    replies_sent INTEGER NOT NULL DEFAULT 0,
    needs_you_count INTEGER NOT NULL DEFAULT 0,
    new_replies_received INTEGER NOT NULL DEFAULT 0,
    threads_ghosted INTEGER NOT NULL DEFAULT 0,
    threads_declined INTEGER NOT NULL DEFAULT 0,
    threads_meeting_booked INTEGER NOT NULL DEFAULT 0,
    active_threads INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS research (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prospect_id INTEGER NOT NULL UNIQUE,
    raw_json TEXT,                                 -- raw scrape: headline, location, posts
    brief_md TEXT,                                 -- LLM-synthesized brief (markdown)
    gathered_at TEXT,                              -- when raw scrape was done
    brief_at TEXT,                                 -- when brief was synthesized
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (prospect_id) REFERENCES prospects(id)
);

CREATE INDEX IF NOT EXISTS idx_prospects_enrichment ON prospects(enrichment_status);
CREATE INDEX IF NOT EXISTS idx_prospects_dnc ON prospects(do_not_contact);
CREATE INDEX IF NOT EXISTS idx_threads_status ON threads(status);
CREATE INDEX IF NOT EXISTS idx_threads_prospect ON threads(prospect_id);
CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages(thread_id);
CREATE INDEX IF NOT EXISTS idx_messages_direction ON messages(thread_id, direction, created_at);
CREATE INDEX IF NOT EXISTS idx_research_prospect ON research(prospect_id);
