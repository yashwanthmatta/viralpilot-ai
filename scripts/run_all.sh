#!/bin/sh
# Single-container mode: API + worker + beat in one service (cheapest 24/7
# setup, and the API can serve previews from the same disk the worker
# renders to). If either process exits, the container exits so the host
# restarts it; jobs resume from the database.
set -eu
celery -A vp_worker.celery_app worker -B --concurrency=1 --loglevel=INFO \
  --schedule="${MEDIA_DIR:-/data/media}/celerybeat-schedule" &
WORKER=$!
uvicorn vp_api.app:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers &
API=$!
trap 'kill -TERM $WORKER $API 2>/dev/null' TERM INT
while kill -0 $WORKER 2>/dev/null && kill -0 $API 2>/dev/null; do sleep 5; done
kill -TERM $WORKER $API 2>/dev/null || true
wait
exit 1
