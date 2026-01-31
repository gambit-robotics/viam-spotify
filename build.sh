#!/bin/bash
set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_NAME="venv"
DIST_DIR="$SCRIPT_DIR/dist"
LIBRESPOT_VERSION="v0.6.2"

cd "$SCRIPT_DIR"

# Detect target architecture for go-librespot
# Viam builds natively per-architecture, so uname -m gives the target arch
get_librespot_arch() {
    # Check for explicit override (useful for local testing)
    if [ -n "${TARGET_ARCH:-}" ]; then
        echo "$TARGET_ARCH"
        return
    fi

    local arch=$(uname -m)
    case "$arch" in
        x86_64|amd64)
            echo "x86_64"
            ;;
        aarch64|arm64)
            echo "arm64"
            ;;
        armv6l|armv7l)
            echo "armv6"
            ;;
        *)
            echo "Error: Unsupported architecture: $arch" >&2
            exit 1
            ;;
    esac
}

# Download go-librespot binary for bundling
download_librespot() {
    local arch=$(get_librespot_arch)
    local archive_name="go-librespot_linux_${arch}.tar.gz"
    local download_url="https://github.com/devgianlu/go-librespot/releases/download/${LIBRESPOT_VERSION}/${archive_name}"

    echo "Downloading go-librespot ${LIBRESPOT_VERSION} for linux/${arch}..."

    local temp_dir=$(mktemp -d)
    if ! curl -fsSL "$download_url" -o "${temp_dir}/${archive_name}"; then
        echo "Error: Failed to download go-librespot from $download_url"
        rm -rf "$temp_dir"
        exit 1
    fi

    tar -xzf "${temp_dir}/${archive_name}" -C "$temp_dir"
    mv "${temp_dir}/go-librespot" "$DIST_DIR/go-librespot"
    chmod +x "$DIST_DIR/go-librespot"
    rm -rf "$temp_dir"
    echo "go-librespot downloaded and bundled"
}

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

# Download go-librespot binary to bundle with module (dist/ created by PyInstaller)
download_librespot

# Create the module tarball (include both binaries)
echo "Creating module archive..."
cd dist
tar -czf archive.tar.gz spotify-module go-librespot
cd ..

# Copy meta.json to dist for reference
cp meta.json "$DIST_DIR/"

echo "Build complete: dist/archive.tar.gz"
