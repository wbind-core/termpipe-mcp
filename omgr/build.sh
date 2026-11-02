#!/bin/bash
set -e

echo "🔨 Building OMGR..."
cd "$(dirname "$0")"

# Ensure PyInstaller is installed
if ! command -v pyinstaller &> /dev/null; then
    echo "⚠️  PyInstaller not found. Installing via pipx..."
    pipx install pyinstaller || pip3 install --user pyinstaller
fi

# Build single executable
pyinstaller --onefile --name omgr main.py

# Move to bin
echo "🚀 Deploying to ~/.local/bin/omgr"
mkdir -p ~/.local/bin
mv dist/omgr ~/.local/bin/omgr

echo "🧹 Cleaning up build files..."
rm -rf build dist omgr.spec

echo "✅ Deployment complete!"
