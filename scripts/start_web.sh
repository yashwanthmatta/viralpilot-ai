#!/bin/sh
# Dashboard only (free mode): the API also serves the static web UI.
# Hosts such as Render set PORT; default to 8000 elsewhere.
exec uvicorn vp_api.app:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers
