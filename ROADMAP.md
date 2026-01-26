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

### Phase 3: Core Task Management
- [ ] Task model
- [ ] Fixed status workflow (New → In Progress → On Hold → Complete)
- [ ] Task list view with filtering
- [ ] Task detail view
- [ ] Task create/edit forms (HTMX)
- [ ] Status transitions
- [ ] Activity logging (immutable)

### Phase 4: Comments & Attachments
- [ ] Comment model
- [ ] Add comment form (HTMX partial)
- [ ] Attachment model with hash-based deduplication
- [ ] File upload handling
- [ ] File download endpoint

### Phase 5: Watching & Notifications
- [ ] Task watchers (add/remove)
- [ ] Notification queue table
- [ ] Background notification worker (polling, no Celery)
- [ ] Email notifications
- [ ] Ntfy notifications
- [ ] "Skip notification" checkbox for minor edits

### Phase 6: Admin & Polish
- [ ] Admin role decorator
- [ ] User management UI
- [ ] Database backup endpoint
- [ ] Activity reports (date range filter)

### Phase 7: Deployment
- [ ] Dockerfile
- [ ] docker-compose.yml (app + worker + ntfy)
- [ ] Caddyfile for reverse proxy
- [ ] Production config example

---

## Deferred Features
These are specified in the original requirements but deferred to future phases:
- Groups (users can only belong to groups, no nested groups)
- Subtasks / task hierarchy
- Custom task types and workflows
- Recurring tasks
- Private tasks / ACL
- Batched notifications
- Charting / advanced reporting
- Typeahead for user selection

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
- [x] `make run` starts server on 0.0.0.0:5000
- [x] `make check` passes (ruff + ty)

### Phase 2 ✓
- [x] Can request magic link via email
- [x] Link logs user in
- [x] "Trust this device" creates persistent session
- [x] Logout clears session

### Phase 3
- [ ] Can create/edit/view tasks
- [ ] Status transitions work
- [ ] Activity log records all changes
- [ ] Task list filters by status

### Phase 4
- [ ] File upload works
- [ ] Duplicate files are deduplicated
- [ ] Download returns correct file with original filename
- [ ] Comments can be added to tasks

### Phase 5
- [ ] `make worker` starts background worker
- [ ] Task changes queue notifications
- [ ] Email notifications send
- [ ] Ntfy notifications send

### Phase 7
- [ ] `docker compose up` starts all services
- [ ] Caddy reverse proxy works
- [ ] Self-hosted ntfy works
