# Web UI build. Static output, so it always runs on the build machine's platform
# (multi-arch images do not emulate Node).
FROM --platform=$BUILDPLATFORM node:24-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# API + worker, serving the built web UI on the same origin
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY backend/pyproject.toml ./
COPY backend/app ./app
RUN pip install --no-cache-dir .

COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
COPY --from=web /web/dist ./web

# Release version (CI passes the image version); empty: the package version.
ARG ZUKAN_VERSION=
ENV ZUKAN_VERSION=$ZUKAN_VERSION

RUN useradd --create-home tcg && mkdir -p /data/images && chown tcg /data/images
COPY deploy/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
ENV TCG_IMAGE_DIR=/data/images TCG_IMPORT_DIR=/data/import TCG_WEB_DIR=/app/web

EXPOSE 8000
# Starts as root to fix data folder ownership, then runs as `tcg`.
ENTRYPOINT ["docker-entrypoint.sh"]
# Forwarded headers are only read from the proxies in FORWARDED_ALLOW_IPS (127.0.0.1 by
# default; compose sets it from TCG_FORWARDED_ALLOW_IPS).
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers"]
