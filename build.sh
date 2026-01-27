#!/bin/bash
set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_NAME="venv"
DIST_DIR="$SCRIPT_DIR/dist"

cd "$SCRIPT_DIR"

# Ensure venv exists
if [ ! -d "$VENV_NAME" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_NAME"
fi

# Activate venv
source "$VENV_NAME/bin/activate"

# Install dependencies
pip install -Uqq pip
pip install -qr requirements.txt
pip install -Uqq pyinstaller

# Clean previous build
rm -rf build dist

# Build with PyInstaller
echo "Building module with PyInstaller..."
pyinstaller --onefile --noconfirm \
    --name spotify-module \
    --hidden-import=viam \
    --hidden-import=viam.services.discovery \
    --hidden-import=viam.services.generic \
    --hidden-import=colorthief \
    --hidden-import=requests \
    --hidden-import=websocket \
    --hidden-import=yaml \
    --hidden-import=audio_discovery \
    --hidden-import=spotify_service \
    --hidden-import=librespot_client \
    --hidden-import=librespot_manager \
    --collect-submodules=viam \
    --collect-submodules=grpclib \
    --collect-submodules=google \
    --paths=src \
    src/main.py

# Create dist directory
mkdir -p "$DIST_DIR"

# Create the module tarball
echo "Creating module archive..."
cd dist
tar -czf archive.tar.gz spotify-module
cd ..

# Copy meta.json to dist for reference
cp meta.json "$DIST_DIR/"

echo "Build complete: dist/archive.tar.gz"
