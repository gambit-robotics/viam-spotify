#!/bin/bash
cd "$(dirname "$0")"

# Activate virtual environment
source .venv/bin/activate

exec python3 -m src.main "$@"
