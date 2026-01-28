# Cadence - Implementation Roadmap

## Overview
Self-hosted task/issue tracker built with Python, Flask, HTMX, and SQLite (via APSW).

## Tech Stack
- Python 3.14+
- Flask + HTMX (no SPA)
- APSW for SQLite
- PicoCSS (compact variant)
- uv for dependency management
- ty for typechecking, ruff for linting
- Docker + Caddy for deployment

---

## Implementation Phases

### Phase 1: Foundation ✓
- [x] Project scaffolding (pyproject.toml, Makefile, wsgi.py)
- [x] Database schema v1 (all tables)
- [x] APSW connection handling with transaction context manager
- [x] Schema migration framework
- [x] Jinja2 templates + PicoCSS
- [x] Static file serving (htmx, pico vendored)
- [x] Dark mode toggle

### Phase 2: Authentication ✓
- [x] User model and CRUD
- [x] Magic link generation (signed tokens)
- [x] Email sending (SMTP)
- [x] Magic link verification endpoint
- [x] Session handling
- [x] "Trust this device" persistent cookie (365 days)
- [x] Logout

### Phase 3: Core Task Management ✓
- [x] Task model
- [x] Fixed status workflow (New → In Progress → On Hold → Complete)
- [x] Task list view with filtering
- [x] Task detail view
- [x] Task create/edit forms (HTMX)
- [x] Status transitions
- [x] Activity logging (immutable)

### Phase 4: Comments & Attachments
- [x] Comment model
- [x] Add comment form (HTMX partial)
- [x] Attachment model with hash-based deduplication
- [x] File upload handling
- [x] File download endpoint
- [x] Unified timeline view (merge comments/attachments into activity section)
- [x] Simplified markdown in task descriptions and comments

### Phase 5: Watching & Notifications ✓
- [x] Task watchers (add/remove)
- [x] Notification queue table
- [x] Background notification worker (polling, no Celery)
- [x] Email notifications (HTML with rendered markdown)
- [x] Ntfy notifications (opt-in via settings)
- [x] "Skip notification" checkbox for edits, comments, uploads
- [x] User settings page (email/push notification preferences)

### Phase 6: Admin & Polish ✓
- [x] Admin role decorator
- [x] User management UI
- [x] Database backup endpoint
- [x] Activity reports (date range filter)

### Phase 7: Deployment ✓
- [x] Dockerfile (multi-stage build, Python 3.14)
- [x] docker-compose.yml (app + worker + init)
- [x] Caddyfile for reverse proxy (with SSL)
- [x] Production config example
- [x] .dockerignore

---

## Deferred Features
These are specified in the original requirements but deferred to future phases:
- Full text search
- Groups (users can only belong to groups, no nested groups)
- Subtasks / task hierarchy
- Tags/lables for tasks (using Tom Select), multiple tags per task permitted. Subtasks inherit parent tags by default, new tags can be created in place with tom-select; tags can be assigned a colour from the selection of picocss colours
- Custom task types and workflows
- Recurring tasks
- ~~Private tasks / ACL~~ ✓
- Batched notifications
- Charting / advanced reporting

---

## Architecture Notes

### File Storage
- Blobs stored at `{BLOBS_DIRECTORY}/{hash[:2]}/{hash}`
- `file_blob` table tracks hash, size, mime_type
- `attachment` table tracks original filename per upload
- Automatic deduplication via hash

### Background Worker
- Standalone Python script (`worker/notification_worker.py`)
- Polls `notification_queue` table
- Sends via SMTP or ntfy
- Run with `make worker`

### HTMX Patterns
- Full page requests get complete HTML
- HTMX requests (`HX-Request` header) get partials
- Use `hx-target`, `hx-swap` for updates

---

## Verification Checklist

### Phase 1 ✓
- [x] `make sync` installs dependencies
- [x] `make init-db` creates database with all tables
- [x] `make run` starts production server, `make rundev` starts dev server
- [x] `make check` passes (ruff + ty)

### Phase 2 ✓
- [x] Can request magic link via email
- [x] Link logs user in
- [x] "Trust this device" creates persistent session
- [x] Logout clears session

### Phase 3 ✓
- [x] Can create/edit/view tasks
- [x] Status transitions work
- [x] Activity log records all changes
- [x] Task list filters by status

### Phase 4
- [x] File upload works
- [x] Duplicate files are deduplicated
- [x] Download returns correct file with original filename
- [x] Comments can be added to tasks
- [x] Unified timeline view works
- [x] Markdown renders in descriptions and comments

### Phase 5 ✓
- [x] `make worker` starts background worker
- [x] Task changes queue notifications
- [x] Email notifications send (HTML with markdown)
- [x] Ntfy notifications send (when user has topic configured)
- [x] Skip notification option on edits, comments, uploads

### Phase 6 ✓
- [x] Admin can manage users
- [x] Database backup works
- [x] Activity reports filter by date

### Phase 7 ✓
- [x] `docker compose up` starts all services
- [x] Database auto-initialized on first run
- [x] Worker container runs alongside app
- [x] Caddy reverse proxy configured
- [x] Production config example provided
