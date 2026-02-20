# Litestream Integration Plan

## Overview
Add Litestream as an optional backup/replication option for continuous WAL-based replication with point-in-time recovery. Litestream runs as a separate external process; Cadence provides configuration examples and optional status monitoring in the admin UI.

## Key Decisions
- **Litestream as external process**: Not managed by Cadence - users run it via systemd, Docker, etc.
- **Complementary to existing backups**: APSW manual backups remain for quick snapshots; Litestream for continuous replication
- **Optional status monitoring**: Admin UI shows replication status when configured
- **No restore UI**: Restore requires downtime, documented as CLI procedure

## Files to Create

### 1. `litestream.yml.example`
```yaml
dbs:
  - path: instance/cadence.sqlite3
    replicas:
      # Local file replica (for testing)
      - type: file
        path: instance/litestream-replicas
        retention: 24h

      # S3 replica (uncomment and configure)
      # - type: s3
      #   bucket: your-bucket
      #   path: cadence
      #   endpoint: https://s3.amazonaws.com
      #   retention: 168h
```

### 2. `docs/litestream.md`
- Installation instructions
- Configuration guide (local file, S3, etc.)
- Running with systemd
- Restore procedure
- Monitoring setup

## Files to Modify

### `Makefile`
Add targets:
```makefile
litestream-replicate:
	litestream replicate -config litestream.yml

litestream-restore:
	@echo "WARNING: This will overwrite the database!"
	@read -p "Continue? [y/N] " c && [ "$$c" = "y" ]
	litestream restore -config litestream.yml instance/cadence.sqlite3
```

### `config.ini.example`
Add optional section:
```ini
[litestream]
# Optional: URL to Litestream metrics endpoint (requires -addr flag)
# STATUS_URL = http://localhost:9090/metrics
```

### `src/cadence/__init__.py`
- Parse `[litestream]` config section
- Add `LITESTREAM_STATUS_URL` to app config

### `src/cadence/blueprints/admin.py`
Add function to fetch Litestream status:
```python
def get_litestream_status() -> dict | None:
    """Fetch Litestream replication status if configured."""
    status_url = current_app.config.get("LITESTREAM_STATUS_URL")
    if not status_url:
        return None
    try:
        response = requests.get(status_url, timeout=2)
        # Parse Prometheus metrics for replication info
        return parse_litestream_metrics(response.text)
    except Exception:
        return {"error": "Unable to reach Litestream"}
```

Update `backups()` route to include Litestream status in context.

### `src/cadence/templates/admin/backups.html`
Add conditional Litestream status section:
- Show "Litestream not configured" with setup link when `STATUS_URL` not set
- Show replication status (last sync time, replica info) when configured
- Show error state if Litestream unreachable

## Implementation Order
1. Create `litestream.yml.example`
2. Add Makefile targets
3. Update `config.ini.example` with litestream section
4. Add config parsing in `__init__.py`
5. Add status fetching in `admin.py`
6. Update `backups.html` template
7. Create `docs/litestream.md`

## Verification
- [ ] `litestream.yml.example` works with `litestream replicate`
- [ ] `make litestream-replicate` starts replication
- [ ] `make litestream-restore` restores database (with confirmation)
- [ ] Admin UI shows "not configured" when STATUS_URL not set
- [ ] Admin UI shows status when Litestream running with `-addr`
- [ ] Admin UI handles Litestream being unreachable gracefully
- [ ] Manual APSW backups still work alongside Litestream
