#!/usr/bin/env bash
# =============================================================================
# install.sh — Installer for Kokoro Audiobook Studio (best on Apple Silicon)
# =============================================================================
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${KOKORO_STUDIO_HOME:-$HOME/.kokoro-audiobook-studio}"

echo ""
echo "🎧 Kokoro Audiobook Studio — installer"
echo ""

# Platform check: Metal acceleration needs Apple Silicon; everything else runs on CPU/CUDA.
OS="$(uname -s)"; ARCH="$(uname -m)"
if [[ "$OS" == "Darwin" && "$ARCH" == "arm64" ]]; then
    echo "✅ Apple Silicon detected — Metal GPU acceleration will be used."
else
    echo "⚠️  $OS/$ARCH: no Metal GPU. It will still run, but on CPU/CUDA and much slower."
fi

# Kokoro requires Python 3.10–3.12 (3.13+ is not supported), so look for one explicitly.
PYTHON_BIN=""
for cand in python3.12 python3.11 python3.10 python3; do
    if command -v "$cand" &>/dev/null \
       && "$cand" -c 'import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] < (3,13) else 1)' 2>/dev/null; then
        PYTHON_BIN="$(command -v "$cand")"; break
    fi
done
if [[ -z "$PYTHON_BIN" ]]; then
    echo "❌ Python 3.10, 3.11 or 3.12 is required (Kokoro does not support 3.13+ yet)." >&2
    echo "   Install one, e.g.:  brew install python@3.12" >&2
    exit 1
fi
echo "🐍 Using $PYTHON_BIN ($("$PYTHON_BIN" -V))"

# ffmpeg (M4B packaging) — never install anything without asking.
if ! command -v ffmpeg &>/dev/null || ! command -v ffprobe &>/dev/null; then
    echo "📦 ffmpeg/ffprobe are required for M4B packaging."
    if command -v brew &>/dev/null; then
        read -r -p "   Install ffmpeg with Homebrew now? [y/N] " ans
        [[ "$ans" =~ ^[Yy]$ ]] && brew install ffmpeg
    fi
    command -v ffmpeg &>/dev/null || { echo "❌ Please install ffmpeg (e.g. 'brew install ffmpeg') and re-run." >&2; exit 1; }
fi

mkdir -p "$INSTALL_DIR"
echo "📦 Creating virtual environment in $INSTALL_DIR/venv ..."
"$PYTHON_BIN" -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
echo "📦 Installing PyTorch, Kokoro and dependencies (this can take a few minutes)..."
"$INSTALL_DIR/venv/bin/pip" install "$SRC_DIR"

# Expose the CLI on PATH via ~/.local/bin. Never overwrite anything that is not
# already a link to this installation (e.g. an older script of the same name).
mkdir -p "$HOME/.local/bin"
SKIPPED=0
for cmd in audiobook-studio make_audiobook; do
    target="$HOME/.local/bin/$cmd"
    want="$INSTALL_DIR/venv/bin/$cmd"
    if [[ -L "$target" && "$(readlink "$target")" == "$want" ]]; then
        :  # our own link from a previous install; nothing to do
    elif [[ -e "$target" || -L "$target" ]]; then
        echo "⚠️  $target already exists — leaving it untouched."
        echo "   Run this tool with: $want"
        SKIPPED=1
        continue
    else
        ln -s "$want" "$target"
    fi
done

if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
    echo ""
    echo "ℹ️  Add ~/.local/bin to your PATH (zsh):"
    echo '    echo '"'"'export PATH="$HOME/.local/bin:$PATH"'"'"' >> ~/.zshrc'
fi

echo ""
if [[ "$SKIPPED" == "1" ]]; then
    echo "🎉 Installed, but some commands were not linked (see warnings above)."
    echo "   Use the full paths shown, or remove the existing files and re-run ./install.sh."
else
    echo "🎉 Done. Run 'audiobook-studio' in a new terminal."
fi
echo "   The first synthesis downloads the Kokoro model (~330 MB) from Hugging Face."
echo ""
