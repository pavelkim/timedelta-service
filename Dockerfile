FROM python:3.13-slim AS base

ARG APP_VERSION=0.0.0

WORKDIR /app

COPY requirements.txt ./
COPY vendor/ ./vendor/

RUN pip install --no-cache-dir -r requirements.txt

COPY tdsvc/ ./tdsvc/
COPY .version ./

# --- tdsvc service ---
FROM base AS tdsvc

LABEL org.opencontainers.image.title="TimeDelta Service (tdsvc)"
LABEL org.opencontainers.image.description="TimeDelta Service (tdsvc) - Clock comparison"
LABEL org.opencontainers.image.authors="Pavel Kim <hello@pavelkim.com>"
LABEL org.opencontainers.image.version="${APP_VERSION}"

COPY entrypoint.sh ./

ENTRYPOINT ["/app/entrypoint.sh"]

# --- tdsvc exporter ---
FROM base AS tdsvc-exporter

LABEL org.opencontainers.image.title="TimeDelta Service Exporter (tdsvc_exporter)"
LABEL org.opencontainers.image.description="TimeDelta Service Exporter - neighbour stats display"
LABEL org.opencontainers.image.authors="Pavel Kim <hello@pavelkim.com>"
LABEL org.opencontainers.image.version="${APP_VERSION}"

COPY entrypoint-exporter.sh ./

ENTRYPOINT ["/app/entrypoint-exporter.sh"]
