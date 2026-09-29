# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Interactive main menu. Running `audiobook-studio` in a terminal now opens a session that
  stays open across conversions: convert a book (with a chapter preview), convert all
  pending books, browse the library, change settings (books/output folder, voice, speed,
  format, dry run), run the health check, or download the model. The speech server stays
  warm between books and stops when you quit. Ctrl-C inside an action returns to the menu.
- `-V` / `--version` flag.
- `run.sh`, a convenience launcher that works whether the project was set up with
  `install.sh`, `uv`, or a local `.venv`.
- `uv.lock` for a reproducible install with [uv](https://docs.astral.sh/uv/).

### Changed
- Bare `audiobook-studio` opens the menu instead of the one-shot wizard. Scripted use
  (`audiobook-studio 3`, `--all`, `--list`, ...) is unchanged; with no book and no
  terminal it now exits with an error instead of failing on a prompt.
- A book search that matches nothing now says so and opens the menu instead of silently
  starting the wizard.
- `--all` prints a "done / failed" summary when it finishes.
- The voice prompt defaults to the current voice, and an invalid speed re-asks instead of
  silently falling back to 1.0x.

### Fixed
- The book picker no longer loops forever when the books folder is empty; `q` goes back.

### Notes
- Performance profiling on Apple Silicon (no code changes yet). Synthesis measured
  ~20x real time end to end; the Kokoro model on the GPU is ~98% of the time
  (decoder ~51%, predictor text encoder ~12%), while G2P and MP3 encoding are
  under 3% combined. fp16 is not usable on MPS (Metal matmul dtype assertion), and
  CPU-only was ~10x versus ~25x on MPS. Speedups will therefore have to come from
  scheduling and pipelining, not from the server's audio plumbing.

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

### Fixed
- The speech server no longer starts until synthesis is confirmed.
- Cancelling the confirmation prompt with EOF (e.g. piped input) no longer crashes
  with a traceback.
- Chapter-detection warnings now show in `--dry-run`, not only during synthesis.
- Corrected guidance on the phonemizer's path-length limit: it fails with an install
  path of roughly 130+ characters to its data folder, not merely "very long" ones.

## [1.0.0] - 2026-09-19

### Added
- PDF and EPUB to chaptered `.m4b` / `.mp3` audiobook conversion with Kokoro-82M.
- PDF cleanup: running headers/footers, page numbers and citation markers.
- Apple Silicon GPU (Metal/MPS) synthesis with CUDA/CPU fallback.
- Interactive terminal wizard with live progress dashboard and CLI flags.
- On-demand local speech server bound to `127.0.0.1`.

### Security
- Only known voices are accepted; request size is capped.
- Chapter titles are escaped before being written to ffmpeg metadata.
