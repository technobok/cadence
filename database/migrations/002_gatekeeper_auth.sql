-- Migration 002: Gatekeeper Auth
-- Migrate from integer user IDs to gatekeeper username strings.
-- User preferences (display_name, email_notifications, ntfy_topic, is_admin)
-- now live in gatekeeper's user_property table (app="cadence").
-- Username is derived from user.email (gatekeeper's identifier).

BEGIN TRANSACTION;

-- ============================================================
-- 1. task: owner_id INTEGER -> owner TEXT
-- ============================================================

CREATE TABLE task_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    owner TEXT NOT NULL,
    due_date TEXT,
    is_private INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

INSERT INTO task_new (id, uuid, title, description, status, owner, due_date, is_private, created_at, updated_at)
SELECT
    t.id,
    t.uuid,
    t.title,
    t.description,
    t.status,
    COALESCE(u.email, 'unknown'),
    t.due_date,
    t.is_private,
    t.created_at,
    t.updated_at
FROM task t
LEFT JOIN user u ON t.owner_id = u.id;

DROP TABLE task;
ALTER TABLE task_new RENAME TO task;

-- ============================================================
-- 2. task_watcher: user_id INTEGER -> username TEXT
-- ============================================================

CREATE TABLE task_watcher_new (
    task_id INTEGER NOT NULL,
    username TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (task_id, username),
    FOREIGN KEY (task_id) REFERENCES task(id) ON DELETE CASCADE
);

INSERT INTO task_watcher_new (task_id, username, created_at)
SELECT
    tw.task_id,
    COALESCE(u.email, 'unknown'),
    tw.created_at
FROM task_watcher tw
LEFT JOIN user u ON tw.user_id = u.id;

DROP TABLE task_watcher;
ALTER TABLE task_watcher_new RENAME TO task_watcher;

-- ============================================================
-- 3. comment: user_id INTEGER -> username TEXT
-- ============================================================

CREATE TABLE comment_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT UNIQUE NOT NULL,
    task_id INTEGER NOT NULL,
    username TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (task_id) REFERENCES task(id) ON DELETE CASCADE
);

INSERT INTO comment_new (id, uuid, task_id, username, content, created_at, updated_at)
SELECT
    c.id,
    c.uuid,
    c.task_id,
    COALESCE(u.email, 'unknown'),
    c.content,
    c.created_at,
    c.updated_at
FROM comment c
LEFT JOIN user u ON c.user_id = u.id;

DROP TABLE comment;
ALTER TABLE comment_new RENAME TO comment;

-- ============================================================
-- 4. attachment: uploaded_by INTEGER -> uploaded_by TEXT
-- ============================================================

CREATE TABLE attachment_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT UNIQUE NOT NULL,
    task_id INTEGER NOT NULL,
    file_blob_id INTEGER NOT NULL,
    original_filename TEXT NOT NULL,
    uploaded_by TEXT NOT NULL,
    uploaded_at TEXT NOT NULL,
    FOREIGN KEY (task_id) REFERENCES task(id) ON DELETE CASCADE,
    FOREIGN KEY (file_blob_id) REFERENCES file_blob(id) ON DELETE RESTRICT
);

INSERT INTO attachment_new (id, uuid, task_id, file_blob_id, original_filename, uploaded_by, uploaded_at)
SELECT
    a.id,
    a.uuid,
    a.task_id,
    a.file_blob_id,
    a.original_filename,
    COALESCE(u.email, 'unknown'),
    a.uploaded_at
FROM attachment a
LEFT JOIN user u ON a.uploaded_by = u.id;

DROP TABLE attachment;
ALTER TABLE attachment_new RENAME TO attachment;

-- ============================================================
-- 5. activity_log: user_id INTEGER -> username TEXT
-- ============================================================

CREATE TABLE activity_log_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT UNIQUE NOT NULL,
    task_id INTEGER NOT NULL,
    username TEXT,
    action TEXT NOT NULL,
    details TEXT,
    logged_at TEXT NOT NULL,
    skip_notification INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (task_id) REFERENCES task(id) ON DELETE CASCADE
);

INSERT INTO activity_log_new (id, uuid, task_id, username, action, details, logged_at, skip_notification)
SELECT
    al.id,
    al.uuid,
    al.task_id,
    CASE WHEN al.user_id IS NULL THEN NULL ELSE COALESCE(u.email, 'unknown') END,
    al.action,
    al.details,
    al.logged_at,
    al.skip_notification
FROM activity_log al
LEFT JOIN user u ON al.user_id = u.id;

DROP TABLE activity_log;
ALTER TABLE activity_log_new RENAME TO activity_log;

-- ============================================================
-- 6. notification_queue: user_id INTEGER -> username TEXT
-- ============================================================

CREATE TABLE notification_queue_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT UNIQUE NOT NULL,
    username TEXT NOT NULL,
    task_id INTEGER,
    channel TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    body_html TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    retries INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    sent_at TEXT
);

INSERT INTO notification_queue_new (id, uuid, username, task_id, channel, subject, body, body_html, status, retries, created_at, sent_at)
SELECT
    nq.id,
    nq.uuid,
    COALESCE(u.email, 'unknown'),
    nq.task_id,
    nq.channel,
    nq.subject,
    nq.body,
    nq.body_html,
    nq.status,
    nq.retries,
    nq.created_at,
    nq.sent_at
FROM notification_queue nq
LEFT JOIN user u ON nq.user_id = u.id;

DROP TABLE notification_queue;
ALTER TABLE notification_queue_new RENAME TO notification_queue;

-- ============================================================
-- 7. Drop user and session tables
-- ============================================================

DROP TABLE IF EXISTS session;
DROP TABLE IF EXISTS user;

-- ============================================================
-- 8. Recreate indexes
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_task_uuid ON task(uuid);
CREATE INDEX IF NOT EXISTS idx_task_owner ON task(owner);
CREATE INDEX IF NOT EXISTS idx_task_status ON task(status);
CREATE INDEX IF NOT EXISTS idx_task_due_date ON task(due_date);
CREATE INDEX IF NOT EXISTS idx_task_created ON task(created_at);

CREATE INDEX IF NOT EXISTS idx_comment_task ON comment(task_id);
CREATE INDEX IF NOT EXISTS idx_comment_created ON comment(created_at);

CREATE INDEX IF NOT EXISTS idx_attachment_task ON attachment(task_id);

CREATE INDEX IF NOT EXISTS idx_activity_log_task ON activity_log(task_id);
CREATE INDEX IF NOT EXISTS idx_activity_log_time ON activity_log(logged_at);
CREATE INDEX IF NOT EXISTS idx_activity_log_username ON activity_log(username);

CREATE INDEX IF NOT EXISTS idx_notification_queue_status ON notification_queue(status);
CREATE INDEX IF NOT EXISTS idx_notification_queue_username ON notification_queue(username);
CREATE INDEX IF NOT EXISTS idx_notification_queue_created ON notification_queue(created_at);

-- ============================================================
-- 9. Update schema version
-- ============================================================

UPDATE db_metadata SET value = '2' WHERE key = 'schema_version';

COMMIT;
