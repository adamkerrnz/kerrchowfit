# KerrChow Fit, self-hosted. Build from the repository root:
#   docker build -f docker/Dockerfile -t kerrchowfit .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Pacific/Auckland \
    DB_PATH=/data/kerrchowfit.db

WORKDIR /app
COPY docker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY docker/app ./app
COPY docker/web ./web
# The same page that runs on claude.ai; the server adds the shim when serving it.
COPY index.html ./web/index.html

RUN useradd --uid 1000 --create-home app && mkdir -p /data && chown app:app /data
USER app
VOLUME /data
EXPOSE 8000

HEALTHCHECK --interval=60s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)" || exit 1

# One worker only: the daily refresh and weather jobs run inside this process (also runnable as `python -m app.daily`).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
