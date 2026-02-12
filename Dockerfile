FROM python:3.13-slim

ARG APP_VERSION=0.0.0

LABEL org.opencontainers.image.title="TimeDelta Service (tdsvc)"
LABEL org.opencontainers.image.description="TimeDelta Service (tdsvc) - Clock comparison"
LABEL org.opencontainers.image.authors="Pavel Kim <hello@pavelkim.com>"
LABEL org.opencontainers.image.version="${APP_VERSION}"

WORKDIR /app

COPY requirements.txt ./
COPY vendor/ ./vendor/

RUN pip install --no-cache-dir -r requirements.txt

COPY tdsvc/ ./tdsvc/
COPY entrypoint.sh ./
COPY .version ./

ENTRYPOINT ["/app/entrypoint.sh"]
