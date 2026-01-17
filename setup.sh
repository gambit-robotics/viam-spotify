#!/bin/bash
set -e

cd "$(dirname "$0")"

if command -v apt-get &> /dev/null; then
    sudo apt-get update
    sudo apt-get install -y python3-pip python3-venv
fi

python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt

chmod +x exec.sh
