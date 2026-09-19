# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
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
