#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_NAME="venv"
PYTHON="python3"

# go-librespot version and paths
LIBRESPOT_VERSION="v0.6.2"
LIBRESPOT_BIN="/usr/local/bin/go-librespot"

# Detect platform and get archive name (Linux only)
get_archive_name() {
    local os=$(uname -s | tr '[:upper:]' '[:lower:]')
    local arch=$(uname -m)

    if [ "$os" != "linux" ]; then
        echo ""
        return 1
    fi

    case "$arch" in
        x86_64|amd64)
            arch="x86_64"
            ;;
        aarch64|arm64)
            arch="arm64"
            ;;
        armv6l|armv7l)
            arch="armv6"
            ;;
        *)
            echo ""
            return 1
            ;;
    esac

    echo "go-librespot_${os}_${arch}.tar.gz"
}

# Download go-librespot binary
install_librespot() {
    if [ -f "$LIBRESPOT_BIN" ]; then
        echo "go-librespot already installed at $LIBRESPOT_BIN"
        return 0
    fi

    local archive_name=$(get_archive_name)
    if [ -z "$archive_name" ]; then
        echo ""
        echo "Skipping go-librespot install (not on supported Linux architecture)"
        echo ""
        return 0
    fi

    local download_url="https://github.com/devgianlu/go-librespot/releases/download/${LIBRESPOT_VERSION}/${archive_name}"

    echo "Downloading go-librespot ${LIBRESPOT_VERSION}..."

    # Download to temp location
    local temp_dir=$(mktemp -d)
    local temp_archive="${temp_dir}/${archive_name}"

    if ! curl -fsSL "$download_url" -o "$temp_archive"; then
        echo "Failed to download go-librespot from $download_url"
        rm -rf "$temp_dir"
        exit 1
    fi

    # Extract archive
    echo "Extracting go-librespot..."
    tar -xzf "$temp_archive" -C "$temp_dir"

    # Install binary (may need sudo)
    echo "Installing go-librespot to $LIBRESPOT_BIN..."
    if [ -w "$(dirname $LIBRESPOT_BIN)" ]; then
        mv "${temp_dir}/go-librespot" "$LIBRESPOT_BIN"
        chmod +x "$LIBRESPOT_BIN"
    else
        sudo mv "${temp_dir}/go-librespot" "$LIBRESPOT_BIN"
        sudo chmod +x "$LIBRESPOT_BIN"
    fi

    rm -rf "$temp_dir"
    echo "go-librespot installed successfully"
}

# Install audio dependencies (Linux only)
install_audio_deps() {
    if [ "$(uname -s)" != "Linux" ]; then
        return 0
    fi

    echo "Installing audio dependencies..."

    # Detect package manager
    if command -v apt-get &> /dev/null; then
        sudo apt-get update -qq
        sudo apt-get install -y -qq \
            libasound2-dev \
            libogg-dev \
            libvorbis-dev \
            libflac-dev \
            avahi-daemon
    elif command -v dnf &> /dev/null; then
        sudo dnf install -y \
            alsa-lib-devel \
            libogg-devel \
            libvorbis-devel \
            flac-devel \
            avahi
    elif command -v pacman &> /dev/null; then
        sudo pacman -S --noconfirm \
            alsa-lib \
            libogg \
            libvorbis \
            flac \
            avahi
    else
        echo "Warning: Could not detect package manager. Please install audio libraries manually."
    fi
}

# Create virtualenv if it doesn't exist
if [ ! -d "$SCRIPT_DIR/$VENV_NAME" ]; then
    echo "Creating virtual environment..."
    $PYTHON -m venv "$SCRIPT_DIR/$VENV_NAME"
fi

# Activate and install dependencies
echo "Installing Python dependencies..."
source "$SCRIPT_DIR/$VENV_NAME/bin/activate"
pip install --upgrade pip -q
pip install -r "$SCRIPT_DIR/requirements.txt" -q

# Install go-librespot
install_librespot

# Install audio deps on Linux
install_audio_deps

echo ""
echo "Setup complete!"
echo ""
echo "The device will appear as a Spotify Connect speaker."
echo "Open Spotify on your phone and look for your device in 'Devices Available'."
