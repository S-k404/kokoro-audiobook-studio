#!/usr/bin/env bash
# Convenience launcher for Kokoro Audiobook Studio:
#   ./run.sh [book|number|path] [voice] [flags]
#   ./run.sh --doctor
#   ./run.sh --voices
#   ./run.sh --list
#   ./run.sh --dry-run
set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -x .venv/bin/audiobook-studio ]; then
  exec .venv/bin/audiobook-studio "$@"
elif command -v uv >/dev/null 2>&1; then
  exec uv run --python 3.12 --project . audiobook-studio "$@"
elif [ -x "$HOME/.kokoro-audiobook-studio/venv/bin/audiobook-studio" ]; then
  exec "$HOME/.kokoro-audiobook-studio/venv/bin/audiobook-studio" "$@"
else
  exec python3 -m audiobook_studio.app "$@"
fi
