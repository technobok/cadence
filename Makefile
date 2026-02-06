.PHONY: help sync install init-db run rundev worker check clean config-list config-set config-import

SHELL := /bin/bash
VENV_DIR := .venv_docker
ADMIN := $(VENV_DIR)/bin/cadence-admin
WEB := $(VENV_DIR)/bin/cadence-web
PYTHON := $(VENV_DIR)/bin/python
GUNICORN := $(VENV_DIR)/bin/gunicorn
RUFF := $(VENV_DIR)/bin/ruff
TY := $(VENV_DIR)/bin/ty

help:
	@echo "Cadence - Task & Issue Tracker"
	@echo "------------------------------"
	@echo "sync     - Sync dependencies with uv (creates venv if needed)"
	@echo "install  - Alias for sync"
	@echo "init-db  - Create a blank database"
	@echo "run      - Run server with production settings (HOST:PORT)"
	@echo "rundev   - Run server with dev settings (DEV_HOST:DEV_PORT, debug=True)"
	@echo "worker   - Run the notification worker"
	@echo "config-list  - Show all config settings"
	@echo "config-set KEY=key VAL=value  - Set a config value"
	@echo "config-import FILE=path  - Import settings from INI file"
	@echo "check    - Run ruff and ty for code quality"
	@echo "clean    - Remove temporary files and database"

sync:
	@echo "--- Syncing dependencies ---"
	@uv sync --extra dev

install: sync

init-db:
	@echo "--- Creating blank database ---"
	@$(ADMIN) init-db
	@echo "Database created. Run 'make run' to start the server."

run:
	@echo "--- Starting server (production settings) ---"
	@$(WEB)

rundev:
	@echo "--- Starting server (dev settings, debug=True) ---"
	@$(WEB) --dev

worker:
	@echo "--- Starting notification worker ---"
	@$(PYTHON) -m worker.notification_worker

config-list:
	@$(ADMIN) config list

config-set:
	@$(ADMIN) config set $(KEY) $(VAL)

config-import:
	@$(ADMIN) config import $(or $(FILE),$(file))

check:
	@echo "--- Running code quality checks ---"
	@$(RUFF) format src
	@$(RUFF) check src --fix
	@$(TY) check src

clean:
	@echo "--- Cleaning up ---"
	@find . -type f -name '*.py[co]' -delete
	@find . -type d -name '__pycache__' -delete
	@rm -f instance/cadence.sqlite3
