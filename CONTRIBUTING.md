# Contributing

Thanks for helping improve Kokoro Audiobook Studio.

## Development setup

Use Python 3.10, 3.11 or 3.12 (Kokoro does not support 3.13+ yet) and ffmpeg.

```bash
git clone https://github.com/S-k404/kokoro-audiobook-studio.git
cd kokoro-audiobook-studio
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e . pytest
```

## Running the tests

```bash
python -m pytest
```

The unit tests cover the converter and CLI helpers and do not need the Kokoro
model. To test the full pipeline, convert a small PDF with `audiobook-studio`;
the first run downloads the model (~330 MB).

## Pull requests

- Keep changes focused and describe the problem they solve.
- Add or update tests for behaviour changes, and update `CHANGELOG.md`.
- Do not commit books, audio files or model weights.
- Never commit secrets or personal paths.

## Reporting bugs

Open an issue using the bug template and include your macOS/Python versions,
the command you ran, and the last lines of `~/.kokoro-audiobook-studio/server.log`.
