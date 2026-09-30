"""Instellingen voor Gunicorn (de webserver in de container)."""

import os

# In de container altijd op poort 8000; welk adres/poort je van buiten gebruikt
# regel je in docker-compose.yml (LUISTER_ADRES en POORT).
bind = "0.0.0.0:8000"

# 2 processen x 4 threads is ruim voor een team van 10-15 personen
workers = int(os.environ.get("GUNICORN_WORKERS", "2"))
threads = int(os.environ.get("GUNICORN_THREADS", "4"))
timeout = 120  # ruim, voor een grote Excel-import

# Logs naar de console, zodat 'docker compose logs' ze toont
accesslog = "-"
errorlog = "-"
loglevel = "info"
