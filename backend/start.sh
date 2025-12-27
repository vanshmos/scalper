#!/bin/bash
cd /tmp/cc-agent/61933887/project/backend
export PATH="/home/appuser/.local/bin:$PATH"
exec python3 -m uvicorn server:app --host 0.0.0.0 --port 8001
