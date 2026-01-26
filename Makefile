.PHONY: help sync install init-db run rundev check clean worker

SHELL := /bin/bash
VENV_DIR := .venv_docker
PYTHON := $(VENV_DIR)/bin/python
FLASK := $(VENV_DIR)/bin/flask
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
	@echo "check    - Run ruff and ty for code quality"
	@echo "worker   - Run the notification worker"
	@echo "clean    - Remove temporary files and database"

sync:
	@echo "--- Syncing dependencies ---"
	@uv sync --extra dev

install: sync

init-db:
	@echo "--- Creating blank database ---"
	@$(FLASK) --app wsgi init-db
	@echo "Database created. Run 'make run' to start the server."

run:
	@echo "--- Starting server (production settings) ---"
	@$(PYTHON) wsgi.py

rundev:
	@echo "--- Starting server (dev settings, debug=True) ---"
	@$(PYTHON) wsgi.py --dev

worker:
	@echo "--- Starting notification worker ---"
	@$(PYTHON) -m worker.notification_worker

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
