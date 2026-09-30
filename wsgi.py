"""Startpunt voor Gunicorn en het flask-commando: `gunicorn wsgi:app`."""

from app import create_app

app = create_app()
