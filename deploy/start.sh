#!/bin/sh
# One container, two processes: the API on 8000 (internal) and the UI on $PORT (public).
set -e
if [ -z "$DEMO_OPERATOR_TOKEN" ]; then
  # Generated per start if the host does not set one. The UI and API share it through the environment.
  DEMO_OPERATOR_TOKEN=$(python -c 'import secrets; print(secrets.token_hex(24))')
  export DEMO_OPERATOR_TOKEN
fi
uvicorn api.main:app --host 127.0.0.1 --port 8000 &
exec streamlit run ui/app.py --server.address 0.0.0.0 --server.port "${PORT:-8501}" \
  --server.headless true --browser.gatherUsageStats false
