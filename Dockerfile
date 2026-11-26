# Website container for Google Cloud Run. The same image runs the move-alerts Cloud Run job
# (python -m jobs.intraday_alerts, every 15 minutes from Cloud Scheduler); the other jobs run in GitHub Actions.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 APP_ENV=prod
WORKDIR /app

COPY requirements-web.txt .
RUN pip install -r requirements-web.txt

COPY tracker/ tracker/
COPY ui/ ui/
COPY web/ web/
COPY config/ config/
COPY jobs/__init__.py jobs/intraday_alerts.py jobs/

RUN useradd --create-home app && chown -R app /app
USER app

# Cloud Run sets PORT. One worker keeps memory low on the free tier; requests are short.
CMD exec uvicorn web.main:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers --forwarded-allow-ips="*"
