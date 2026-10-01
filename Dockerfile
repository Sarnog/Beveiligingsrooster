# ==========================================================
# Beveiligingsrooster – container-image
# Basis: officiële Python-image (Debian slim). Werkt op elke host met Docker,
# dus zowel in een Alpine- als een Debian-LXC.
# ==========================================================
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    FLASK_APP=wsgi:app \
    DATA_MAP=/data \
    TZ=Europe/Amsterdam

# Tijdzone: de app gebruikt het Python-pakket 'tzdata' (zie requirements.txt),
# dus er zijn geen extra systeempakketten nodig.

# Eigen gebruiker zonder rootrechten (uid 1000)
RUN useradd --uid 1000 --user-group --create-home --shell /usr/sbin/nologin rooster \
    && mkdir -p /data && chown rooster:rooster /data

WORKDIR /app

# Eerst alleen de afhankelijkheden (sneller herbouwen bij codewijzigingen).
# requirements.lock bevat de exacte versies (gemaakt met pip-compile uit requirements.txt),
# zodat elke build precies dezelfde pakketten krijgt.
COPY requirements.txt requirements.lock ./
RUN pip install -r requirements.lock

COPY app ./app
COPY migrations ./migrations
COPY docker ./docker
COPY wsgi.py ./

VOLUME ["/data"]
EXPOSE 8000

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["web"]
