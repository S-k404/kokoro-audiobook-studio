# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.1.0] - 2026-09-20

### Added
- Installer prompts and safeguards: offers to install Python/ffmpeg (Homebrew or apt),
  Homebrew itself (explicit consent only), warns on unsupported platforms, low disk space,
  no network and too-long install paths, never overwrites existing commands, and offers to
  pre-download the model.
- `audiobook-studio --doctor` self-check, `--download-model`, and `--yes`.
- Confirmation step with chapter preview, plus warnings for books without detectable
  chapters or with little extractable text (likely scanned).
- `constraints.txt` with tested versions of the speech stack.
- Unit tests and a GitHub Actions workflow.
- Contributing guide, security policy and issue templates.

## [1.0.0]

### Added
- PDF and EPUB to chaptered `.m4b` / `.mp3` audiobook conversion with Kokoro-82M.
- PDF cleanup: running headers/footers, page numbers and citation markers.
- Apple Silicon GPU (Metal/MPS) synthesis with CUDA/CPU fallback.
- Interactive terminal wizard with live progress dashboard and CLI flags.
- On-demand local speech server bound to `127.0.0.1`.

### Security
- Only known voices are accepted; request size is capped.
- Chapter titles are escaped before being written to ffmpeg metadata.
