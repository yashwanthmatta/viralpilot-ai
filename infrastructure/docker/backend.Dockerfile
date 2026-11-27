# One image for the API, the worker and the static dashboard.
FROM node:22-alpine AS web
WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json* ./
RUN npm ci
COPY apps/web ./
# Same-origin build: the dashboard calls the API on the same host.
ENV NEXT_OUTPUT=export NEXT_PUBLIC_API_URL=""
RUN npm run build

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY pyproject.toml alembic.ini ./
COPY packages ./packages
COPY apps/api ./apps/api
COPY apps/worker ./apps/worker
COPY migrations ./migrations
COPY scripts/run_all.sh scripts/start_web.sh ./scripts/
RUN pip install ".[ml]"
USER app
COPY --from=web /web/out ./web
ENV MEDIA_DIR=/data/media WEB_DIST=/app/web
EXPOSE 8000
CMD ["sh", "scripts/start_web.sh"]
