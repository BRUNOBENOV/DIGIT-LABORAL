FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/* \
    && addgroup --system digit \
    && adduser --system --ingroup digit --home /app digit

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=digit:digit . .
RUN mkdir -p /app/data/uploads /app/data/imports /app/data/backups /app/backups \
    && chown -R digit:digit /app/data /app/backups

USER digit

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.getenv('PORT','8000')+'/health/live', timeout=4)" || exit 1

CMD ["sh", "-c", "python -m app.admin_recovery && uvicorn app.production_entry:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
