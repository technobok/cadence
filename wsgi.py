"""WSGI entry point for Cadence (gunicorn wsgi:app)."""

from cadence import create_app

app = create_app()
