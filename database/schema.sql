-- Cadence Database Schema
-- All datetimes stored as ISO 8601 UTC strings

PRAGMA foreign_keys = ON;

-- Database metadata for versioning
CREATE TABLE IF NOT EXISTS db_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT OR IGNORE INTO db_metadata (key, value) VALUES ('schema_version', '1');

-- Application settings
CREATE TABLE IF NOT EXISTS app_setting (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    description TEXT
);

-- Users
CREATE TABLE IF NOT EXISTS user (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE NOT NULL,
    display_name TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    is_admin INTEGER NOT NULL DEFAULT 0,
    ntfy_topic TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_user_email ON user(email);
CREATE INDEX IF NOT EXISTS idx_user_uuid ON user(uuid);

-- Sessions (for trusted device login)
CREATE TABLE IF NOT EXISTS session (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL,
    token_hash TEXT NOT NULL,
    device_name TEXT,
    is_trusted INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    last_used_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_session_user_id ON session(user_id);
CREATE INDEX IF NOT EXISTS idx_session_token_hash ON session(token_hash);
CREATE INDEX IF NOT EXISTS idx_session_expires ON session(expires_at);

-- Tasks
CREATE TABLE IF NOT EXISTS task (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    owner_id INTEGER NOT NULL,
    due_date TEXT,
    is_private INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (owner_id) REFERENCES user(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_task_uuid ON task(uuid);
CREATE INDEX IF NOT EXISTS idx_task_owner ON task(owner_id);
CREATE INDEX IF NOT EXISTS idx_task_status ON task(status);
CREATE INDEX IF NOT EXISTS idx_task_due_date ON task(due_date);
CREATE INDEX IF NOT EXISTS idx_task_created ON task(created_at);

-- Task watchers
CREATE TABLE IF NOT EXISTS task_watcher (
    task_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (task_id, user_id),
    FOREIGN KEY (task_id) REFERENCES task(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE
);

-- Comments
CREATE TABLE IF NOT EXISTS comment (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT UNIQUE NOT NULL,
    task_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (task_id) REFERENCES task(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_comment_task ON comment(task_id);
CREATE INDEX IF NOT EXISTS idx_comment_created ON comment(created_at);

-- File blobs (deduplicated storage)
-- Path derived from hash: {BLOB_DIRECTORY}/{hash[:2]}/{hash}
CREATE TABLE IF NOT EXISTS file_blob (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sha256_hash TEXT UNIQUE NOT NULL,
    file_size INTEGER NOT NULL,
    mime_type TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_file_blob_hash ON file_blob(sha256_hash);

-- Attachments (metadata per upload)
CREATE TABLE IF NOT EXISTS attachment (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT UNIQUE NOT NULL,
    task_id INTEGER NOT NULL,
    file_blob_id INTEGER NOT NULL,
    original_filename TEXT NOT NULL,
    uploaded_by INTEGER NOT NULL,
    uploaded_at TEXT NOT NULL,
    FOREIGN KEY (task_id) REFERENCES task(id) ON DELETE CASCADE,
    FOREIGN KEY (file_blob_id) REFERENCES file_blob(id) ON DELETE RESTRICT,
    FOREIGN KEY (uploaded_by) REFERENCES user(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_attachment_task ON attachment(task_id);

-- Activity log (immutable)
CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT UNIQUE NOT NULL,
    task_id INTEGER NOT NULL,
    user_id INTEGER,
    action TEXT NOT NULL,
    details TEXT,
    logged_at TEXT NOT NULL,
    skip_notification INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (task_id) REFERENCES task(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_activity_log_task ON activity_log(task_id);
CREATE INDEX IF NOT EXISTS idx_activity_log_time ON activity_log(logged_at);
CREATE INDEX IF NOT EXISTS idx_activity_log_user ON activity_log(user_id);

-- Notification queue
CREATE TABLE IF NOT EXISTS notification_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL,
    task_id INTEGER,
    channel TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    retries INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    sent_at TEXT,
    FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE,
    FOREIGN KEY (task_id) REFERENCES task(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_notification_queue_status ON notification_queue(status);
CREATE INDEX IF NOT EXISTS idx_notification_queue_user ON notification_queue(user_id);
CREATE INDEX IF NOT EXISTS idx_notification_queue_created ON notification_queue(created_at);

-- Default app settings
INSERT OR IGNORE INTO app_setting (key, value, description) VALUES
    ('notification_batch_interval_seconds', '0', 'How often to batch notifications (0 = immediate)'),
    ('default_task_status', 'new', 'Default status for new tasks');
