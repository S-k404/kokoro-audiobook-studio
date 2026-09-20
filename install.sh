#!/usr/bin/env bash
# =============================================================================
# install.sh — Installer for Kokoro Audiobook Studio (best on Apple Silicon)
#
# Asks before installing anything on your system. Options:
#   -y, --yes    accept the default "yes" for package installs (never for Homebrew itself)
#   -h, --help   show this help
# Environment: KOKORO_STUDIO_HOME sets the install location (keep the path short).
# =============================================================================
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_HOME="$HOME/.kokoro-audiobook-studio"
INSTALL_DIR="${KOKORO_STUDIO_HOME:-$DEFAULT_HOME}"
ASSUME_YES=0

for arg in "$@"; do
    case "$arg" in
        -y|--yes) ASSUME_YES=1 ;;
        -h|--help) sed -n '2,9p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unknown option: $arg (try --help)" >&2; exit 2 ;;
    esac
done

# --- helpers -----------------------------------------------------------------
die()  { echo "❌ $*" >&2; exit 1; }
warn() { echo "⚠️  $*"; }

# ask "question" [y|n default]. Non-interactive runs use the default; --yes accepts.
ask() {
    local q="$1" def="${2:-n}" hint="[y/N]" ans
    [[ "$def" == y ]] && hint="[Y/n]"
    [[ "$ASSUME_YES" == 1 ]] && return 0
    [[ -t 0 ]] || { [[ "$def" == y ]]; return; }
    read -r -p "   $q $hint " ans || ans=""
    ans="${ans:-$def}"
    [[ "$ans" =~ ^[Yy] ]]
}

# ask_explicit: like ask, but --yes does NOT count and it needs a real terminal (default no).
ask_explicit() {
    local ans
    [[ -t 0 ]] || return 1
    read -r -p "   $1 [y/N] " ans || ans=""
    [[ "$ans" =~ ^[Yy] ]]
}

SUDO=""
if [[ "$(id -u)" != 0 ]] && command -v sudo &>/dev/null; then SUDO="sudo"; fi

OS="$(uname -s)"; ARCH="$(uname -m)"

load_brew_env() {
    local b
    for b in /opt/homebrew/bin/brew /usr/local/bin/brew /home/linuxbrew/.linuxbrew/bin/brew; do
        if [[ -x "$b" ]]; then eval "$("$b" shellenv)"; return 0; fi
    done
    return 1
}
command -v brew &>/dev/null || load_brew_env || true

# Detect the system package manager we know how to drive.
PKG=""
if command -v brew &>/dev/null; then PKG="brew"
elif command -v apt-get &>/dev/null; then PKG="apt"
fi

find_python() {
    local cand
    for cand in python3.12 python3.11 python3.10 python3; do
        if command -v "$cand" &>/dev/null \
           && "$cand" -c 'import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] < (3,13) else 1)' 2>/dev/null; then
            command -v "$cand"; return 0
        fi
    done
    return 1
}

# Offer to install Homebrew on macOS when it is missing (official installer; explicit consent only).
offer_homebrew() {
    [[ "$OS" == "Darwin" && -z "$PKG" ]] || return 0
    echo ""
    echo "🍺 Homebrew is not installed. It is the easiest way to get Python and ffmpeg on a Mac."
    echo "   Its official installer (https://brew.sh) will run and may ask for your password."
    if ask_explicit "Install Homebrew now?"; then
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" \
            || warn "Homebrew installation did not finish."
        load_brew_env && PKG="brew" || true
    else
        echo "   Skipped. Manual alternatives: Python from https://www.python.org/downloads/ (3.12) and"
        echo "   ffmpeg from https://ffmpeg.org/download.html, then re-run ./install.sh."
    fi
}

echo ""
echo "🎧 Kokoro Audiobook Studio — installer"
echo ""

# --- 1. platform -------------------------------------------------------------
if [[ "$OS" == "Darwin" && "$ARCH" == "arm64" ]]; then
    echo "✅ Apple Silicon detected — Metal GPU acceleration will be used."
else
    warn "$OS/$ARCH is not Apple Silicon. This setup is EXPERIMENTAL here: it runs on CPU/CUDA,"
    echo "   is much slower, and was not tested on Intel Macs (recent PyTorch builds may be unavailable)."
    ask "Continue anyway?" n || die "Cancelled. Nothing was installed."
fi

# --- 2. Python 3.10–3.12 -----------------------------------------------------
PYTHON_BIN="$(find_python || true)"
if [[ -z "$PYTHON_BIN" ]]; then
    echo "🐍 Python 3.10, 3.11 or 3.12 is required (Kokoro does not support 3.13+ yet); none was found."
    offer_homebrew
    case "$PKG" in
        brew) ask "Install Python 3.12 with Homebrew?" y && brew install python@3.12 ;;
        apt)  ask "Install Python with apt (needs sudo)?" y && { $SUDO apt-get update && $SUDO apt-get install -y python3 python3-venv; } ;;
    esac
    PYTHON_BIN="$(find_python || true)"
    [[ -n "$PYTHON_BIN" ]] || die "No supported Python found. Install Python 3.12 (https://www.python.org/downloads/) and re-run ./install.sh."
fi
echo "🐍 Using $PYTHON_BIN ($("$PYTHON_BIN" -V))"

# --- 3. ffmpeg / ffprobe -----------------------------------------------------
if ! command -v ffmpeg &>/dev/null || ! command -v ffprobe &>/dev/null; then
    echo "🎞️  ffmpeg and ffprobe are required to build the audiobook files."
    offer_homebrew
    case "$PKG" in
        brew) ask "Install ffmpeg with Homebrew?" y && brew install ffmpeg ;;
        apt)  ask "Install ffmpeg with apt (needs sudo)?" y && { $SUDO apt-get update && $SUDO apt-get install -y ffmpeg; } ;;
    esac
    if ! command -v ffmpeg &>/dev/null || ! command -v ffprobe &>/dev/null; then
        die "ffmpeg is still missing. Install it (macOS: brew install ffmpeg, Debian/Ubuntu: sudo apt install ffmpeg, Fedora: see rpmfusion) and re-run ./install.sh."
    fi
fi

# --- 4. install location: keep it short (the speech engine breaks on very long paths) ---
# The engine's data folder sits ~70 characters below the install dir and fails beyond ~130-150 in total.
projected=$(( ${#INSTALL_DIR} + 70 ))
if (( projected > 125 )); then
    warn "The install path is too long ($projected characters to the speech data; the limit is about 130)."
    echo "   The speech engine would fail to start with a path this long."
    if [[ "$INSTALL_DIR" != "$DEFAULT_HOME" ]] && ask "Use the short default $DEFAULT_HOME instead?" y; then
        INSTALL_DIR="$DEFAULT_HOME"
    else
        die "Set KOKORO_STUDIO_HOME to a shorter folder (e.g. \$HOME/.kokoro-audiobook-studio) and re-run."
    fi
fi

# --- 5. disk space and network ----------------------------------------------
mkdir -p "$INSTALL_DIR"
free_kb="$(df -k "$INSTALL_DIR" | awk 'NR==2 {print $4}')"
if [[ "$free_kb" =~ ^[0-9]+$ ]] && (( free_kb < 4 * 1024 * 1024 )); then
    warn "Only $(( free_kb / 1024 / 1024 )) GB free at $INSTALL_DIR; about 4 GB is needed (PyTorch + model)."
    ask "Continue anyway?" n || die "Cancelled. Free up disk space and re-run."
fi
if command -v curl &>/dev/null && ! curl -fsS --max-time 10 -o /dev/null https://pypi.org/simple/pip/ 2>/dev/null; then
    warn "Cannot reach pypi.org. Check your internet connection, VPN or proxy (HTTPS_PROXY)."
    ask "Try to install anyway?" n || die "Cancelled. Fix the connection and re-run."
fi

# --- 6. virtual environment --------------------------------------------------
echo "📦 Creating virtual environment in $INSTALL_DIR/venv ..."
if ! "$PYTHON_BIN" -m venv "$INSTALL_DIR/venv" 2>/dev/null; then
    rm -rf "$INSTALL_DIR/venv"
    if [[ "$PKG" == "apt" ]]; then
        pyver="$("$PYTHON_BIN" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
        echo "   Python's venv module is missing (Debian/Ubuntu ship it separately)."
        ask "Install python${pyver}-venv with apt (needs sudo)?" y \
            && { $SUDO apt-get update && $SUDO apt-get install -y "python${pyver}-venv" python3-venv || true; }
    fi
    "$PYTHON_BIN" -m venv "$INSTALL_DIR/venv" || die "Could not create a virtual environment with $PYTHON_BIN."
fi
"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip

# --- 7. install with tested version pins ------------------------------------
echo "📦 Installing PyTorch, Kokoro and dependencies (this can take several minutes)..."
PIP="$INSTALL_DIR/venv/bin/pip"
if ! "$PIP" install -c "$SRC_DIR/constraints.txt" "$SRC_DIR"; then
    echo ""
    warn "Installation failed. Common causes: no internet, a VPN/proxy, or too little disk space."
    if ask "Retry once without the tested version pins (may install untested newer versions)?" n; then
        "$PIP" install "$SRC_DIR" || die "Installation failed again. See the error above; the README's Troubleshooting section may help."
    else
        die "Installation failed. Fix the problem above and re-run ./install.sh."
    fi
fi

# --- 8. commands on PATH (never overwrite existing ones) --------------------
mkdir -p "$HOME/.local/bin"
SKIPPED=0
for cmd in audiobook-studio make_audiobook; do
    target="$HOME/.local/bin/$cmd"
    want="$INSTALL_DIR/venv/bin/$cmd"
    if [[ -L "$target" && "$(readlink "$target")" == "$want" ]]; then
        :  # our own link from a previous install
    elif [[ -e "$target" || -L "$target" ]]; then
        warn "$target already exists — leaving it untouched."
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

# --- 9. voice model download (so first use is not a silent wait) ------------
echo ""
echo "🎙️  The voice model (~330 MB) is downloaded from Hugging Face."
if ask "Download it now so the first conversion starts right away?" y; then
    "$INSTALL_DIR/venv/bin/audiobook-studio" --download-model \
        || warn "Model download failed. It will be retried on first use; or run: audiobook-studio --download-model"
else
    echo "   Skipped. It will download automatically on your first conversion."
fi

# --- 10. self-check ----------------------------------------------------------
echo ""
echo "🔍 Checking the installation..."
DOCTOR_OK=0
"$INSTALL_DIR/venv/bin/audiobook-studio" --doctor || DOCTOR_OK=1

echo ""
if [[ "$DOCTOR_OK" != 0 ]]; then
    echo "❌ Installed, but the self-check found problems (see above). Re-check anytime with: audiobook-studio --doctor"
    exit 1
elif [[ "$SKIPPED" == "1" ]]; then
    echo "🎉 Installed, but some commands were not linked (see warnings above)."
    echo "   Use the full paths shown, or remove the existing files and re-run ./install.sh."
else
    echo "🎉 Done. Run 'audiobook-studio' in a new terminal."
fi
