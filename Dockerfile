# One image for the public demo: scripted planner, synthetic data, no model and no database.
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLANNER=scripted \
    SALES_BACKEND=memory \
    ACTIONGATE_API_URL=http://127.0.0.1:8000 \
    ACTIONGATE_DB_PATH=/app/data/actiongate.sqlite3 \
    OUTBOX_PATH=/app/data/outbox.jsonl

RUN useradd --create-home --uid 1000 actiongate

WORKDIR /app
COPY . .
RUN pip install . \
    && mkdir -p /app/data \
    && chown -R actiongate:actiongate /app/data

USER actiongate
EXPOSE 8501
CMD ["sh", "deploy/start.sh"]
