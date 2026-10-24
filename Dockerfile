# One image for the API and the Streamlit UI. Compose picks the command per service.
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN useradd --create-home --uid 1000 actiongate

WORKDIR /app
COPY . .
RUN pip install . \
    && mkdir -p /app/data \
    && chown -R actiongate:actiongate /app/data

USER actiongate
EXPOSE 8000 8501
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
