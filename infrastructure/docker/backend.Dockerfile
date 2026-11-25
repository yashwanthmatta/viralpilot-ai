# One image for the API and the worker (different start commands).
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
RUN pip install ".[ml]"
USER app
ENV MEDIA_DIR=/data/media
EXPOSE 8000
CMD ["uvicorn", "vp_api.app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
