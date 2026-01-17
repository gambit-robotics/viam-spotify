#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_NAME="venv"
PYTHON="python3"

# Create virtualenv if it doesn't exist
if [ ! -d "$SCRIPT_DIR/$VENV_NAME" ]; then
    echo "Creating virtual environment..."
    $PYTHON -m venv "$SCRIPT_DIR/$VENV_NAME"
fi

# Activate and install dependencies
echo "Installing dependencies..."
source "$SCRIPT_DIR/$VENV_NAME/bin/activate"
pip install --upgrade pip -q
pip install -r "$SCRIPT_DIR/requirements.txt" -q

echo "Setup complete."
