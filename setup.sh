#!/bin/bash
set -e

cd "$(dirname "$0")"

# Install Python dependencies based on platform
if command -v apt-get &> /dev/null; then
    # Debian/Ubuntu
    sudo apt-get update
    sudo apt-get install -y python3-pip python3-venv
elif command -v yum &> /dev/null; then
    # RHEL/CentOS/Fedora
    sudo yum install -y python3-pip python3-virtualenv
elif command -v brew &> /dev/null; then
    # macOS with Homebrew
    brew install python3 || true
fi

python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt

chmod +x exec.sh
