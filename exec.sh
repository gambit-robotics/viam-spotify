#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Always run setup (it's idempotent)
"$SCRIPT_DIR/setup.sh"

# Activate virtualenv and run the module
source "$SCRIPT_DIR/venv/bin/activate"
exec python3 -m src.main "$@"
