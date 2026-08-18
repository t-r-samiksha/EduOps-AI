#!/usr/bin/env bash
# Production build script for Render / Railway / Linux cloud hosts
set -e

echo "==> Python version:"
python --version

echo "==> Upgrading pip..."
pip install --no-cache-dir --upgrade pip

echo "==> Installing production requirements..."
pip install --no-cache-dir -r requirements.txt

echo "==> Build complete!"
