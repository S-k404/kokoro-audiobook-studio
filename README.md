# Kokoro Audiobook Studio

[![CI](https://github.com/S-k404/kokoro-audiobook-studio/actions/workflows/ci.yml/badge.svg)](https://github.com/S-k404/kokoro-audiobook-studio/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10--3.12-blue.svg)](pyproject.toml)
[![Platform](https://img.shields.io/badge/platform-macOS%20Apple%20Silicon-lightgrey.svg)](#requirements)

**Turn textbooks and technical PDFs into chaptered audiobooks, entirely on your Mac.**

A terminal app that reads a PDF or EPUB, strips the running headers, footers, page numbers and footnote noise that make PDFs painful to listen to, and narrates it with the open-source [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) voice model on the Apple Silicon GPU. The result is a single `.m4b` file with real chapter markers for Apple Books, VLC, or any audiobook player.

Nothing leaves your machine after the one-time model download: no cloud API, no per-character fees, no account.

## Why this exists

Most text-to-speech tools read a PDF exactly as printed, so you hear "Page 214" and the chapter title again every few minutes. This one is built for long, structured, non-fiction books such as textbooks, manuals and lecture notes:

* **PDF cleanup first.** Running headers and footers, page numbers and citation markers are removed before narration. The cleaned text is also saved as an `.epub` you can keep.
* **Real chapters.** Chapter boundaries come from the book's outline (or its headings) and are written into the `.m4b`, so you can skip and resume by chapter.
* **Runs on the Apple GPU.** PyTorch's Metal (MPS) backend generates audio many times faster than real time on M-series Macs.
* **No background process.** The speech server starts when you convert a book and shuts down when you are done.

## Requirements

| | |
|---|---|
| Computer | Mac with Apple Silicon (M1 or newer) recommended. Linux runs on CPU/CUDA and Intel Macs are untested; both are much slower and treated as experimental. |
| Python | **3.10, 3.11 or 3.12.** Python 3.13+ is not supported by Kokoro yet. |
| ffmpeg | Needed to build the `.m4b`. The installer can install it for you (Homebrew on macOS, apt on Debian/Ubuntu). |
| Disk / network | About 2 GB for PyTorch, plus a ~330 MB voice model downloaded from Hugging Face the first time you convert a book. |

You do not have to prepare any of this by hand: the installer checks each requirement, tells you what is missing, and asks before installing anything.

## Install

### Option 1: install script (recommended)

```bash
git clone https://github.com/S-k404/kokoro-audiobook-studio.git
cd kokoro-audiobook-studio
./install.sh
```

The installer checks your system and **asks before changing anything**:

* finds Python 3.10-3.12 and ffmpeg, and offers to install them if they are missing (with Homebrew on macOS, or apt on Debian/Ubuntu; it can also offer to install Homebrew itself, only if you say yes)
* warns you on Intel Macs and Linux, and when disk space is low, the internet is unreachable, or the install folder path is too long
* installs into its own environment at `~/.kokoro-audiobook-studio` using tested version pins from `constraints.txt`, so it does not touch your other Python projects
* adds `audiobook-studio` to `~/.local/bin` without overwriting any command that already exists there
* offers to download the ~330 MB voice model right away, so your first conversion does not stall
* finishes with a self-check (`audiobook-studio --doctor`) that shows exactly what works

Use `./install.sh --yes` to accept the default answers without prompts. If a step fails, the installer stops with a message saying what to do; see Troubleshooting.

### Option 2: manual install

```bash
brew install ffmpeg
git clone https://github.com/S-k404/kokoro-audiobook-studio.git
cd kokoro-audiobook-studio
python3.12 -m venv .venv          # any of 3.10, 3.11, 3.12
source .venv/bin/activate
pip install -c constraints.txt .
audiobook-studio --download-model # optional: fetch the voice model now (~330 MB)
audiobook-studio --doctor         # verify the setup
```

Keep your environment in a **short folder path**: the speech engine fails to start when its data folder is more than about 130 characters deep (see Troubleshooting).

## Quick start

Put your books in `~/Documents/Books` (or pass any path), then run:

```bash
audiobook-studio
```

A wizard lists your books, then asks for the output folder, narrator voice and speed. Finished audiobooks go to `~/Documents/AudioBook` by default.

Before generating anything, the app shows the detected chapters and asks you to confirm. It warns you if no chapters were detected (the book is then split into evenly sized sections) or if the PDF looks scanned. Use `--yes` to skip the question.

Try a dry run first to see how a book will be split into chapters, without generating any audio:

```bash
audiobook-studio "my textbook" --dry-run
```

## Usage

```bash
audiobook-studio                       # interactive wizard
audiobook-studio 3                     # book number 3 from the list
audiobook-studio "digital fund"        # search by title
audiobook-studio ~/Downloads/book.pdf  # any file path
audiobook-studio 3 bella               # pick a voice
audiobook-studio 3:george              # same thing, colon style
audiobook-studio 3 -s 1.1 -f mp3       # speed 1.1x, MP3 instead of M4B
audiobook-studio 3 -o ~/Audio          # custom output folder
audiobook-studio --all                 # convert every book not yet converted
audiobook-studio --list                # show your library
audiobook-studio --voices              # show the voice list
audiobook-studio --doctor              # check that everything needed works
audiobook-studio --download-model      # download the voice model now
audiobook-studio 3 --yes               # skip the confirmation question
```

`make_audiobook` is an alias for `audiobook-studio`.

### How each format is handled

* **EPUB:** chapters and text are read directly and narrated.
* **PDF:** text is extracted and cleaned, a clean `.epub` is written next to the audiobook, and that is narrated. Scanned PDFs (images of pages) have no text layer and need OCR first.

### Voices

The wizard shows ten curated voices. Any Kokoro voice code also works with `-v`, for example `-v am_echo`.

| Code | Alias | Accent / Gender | Character |
|---|---|---|---|
| `af_heart` | `heart` | American F | Warm, expressive (default) |
| `af_bella` | `bella` | American F | Gentle, good for fiction |
| `af_sky` | `sky` | American F | Bright, energetic |
| `af_sarah` | `sarah` | American F | Balanced, good for non-fiction |
| `af_nicole` | `nicole` | American F | Crisp, conversational |
| `am_adam` | `adam` | American M | Deep, steady narrator |
| `am_michael` | `michael` | American M | Friendly podcast style |
| `am_onyx` | `onyx` | American M | Deep baritone |
| `bf_emma` | `emma` | British F | Polished British narrator |
| `bm_george` | `george` | British M | Distinguished British narrator |

### Settings (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `BOOKS_DIR` | `~/Documents/Books` | Where your PDFs and EPUBs are |
| `AUDIO_DIR` | `~/Documents/AudioBook` | Where audiobooks are written |
| `KOKORO_PORT` | `8001` | Port for the local speech server |
| `KOKORO_HOST` | `127.0.0.1` | Address the server listens on |
| `KOKORO_ENDPOINT` | `http://127.0.0.1:8001/v1` | Use an already running or remote Kokoro server instead |
| `KOKORO_STUDIO_HOME` | `~/.kokoro-audiobook-studio` | Server log and state files |

## What it looks like

```text
Select a book (1-4, name, path, or 'all'): 3
Save audiobooks to [~/Documents/AudioBook]: <Enter>
Choose voice [1-10 or type name] (1): 1

 Overall Progress   ━━━━━━━━━━━━━━━╸        42% (15/37 Chapters)  0:14:22  0:18:45
 Ch 16: Shift Registers  ━━━━━━━━━━━━━━╸   85% 17/20 Chunks  0:00:32

 Ch #  Chapter Title              Duration    Size   Status
   14  Serial-In Parallel-Out      8.1 min    6.5 MB  Done
   15  Universal Shift Register   15.0 min   11.8 MB  Done
```

## Troubleshooting

**`No matching distribution found for kokoro` or `requires a different Python`**
You are using Python 3.13 or newer. Install 3.12 (`brew install python@3.12`) and re-run `./install.sh`, which picks a supported version automatically.

**First, run the self-check**
```bash
audiobook-studio --doctor
```
It lists what works and what does not (Python, ffmpeg, GPU, speech engine, voice model, output folder, port) and says how to fix each problem.

**`command not found: audiobook-studio`**
`~/.local/bin` is not on your PATH. Run this, then open a new terminal:
```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
```

**`ffmpeg` or `ffprobe` not found**
```bash
brew install ffmpeg
```

**"Server failed to start"**
Look at the log for the real reason:
```bash
tail -50 ~/.kokoro-audiobook-studio/server.log
```
The first start downloads the model and can take a few minutes on a slow connection. If the download was interrupted, run the command again.

**Port 8001 is already in use**
If another Kokoro server is already running there, the app will simply use it. If it is something else, choose another port:
```bash
KOKORO_PORT=8011 KOKORO_ENDPOINT=http://127.0.0.1:8011/v1 audiobook-studio
```

**Log says `Error processing file ... espeak-ng-data/phontab`**
The environment is installed in a folder with a very long path (the speech engine's data folder must be under about 130 characters deep). Reinstall in a shorter location, for example `~/.kokoro-audiobook-studio` (what `install.sh` uses).

**The first conversion seems stuck**
The voice model (~330 MB) is downloaded the first time it is needed. Run `audiobook-studio --download-model` to fetch it with visible progress, and check your internet connection or proxy. Partial downloads resume.

**Installation fails with network or pip errors**
Check your internet connection, VPN or proxy (`HTTPS_PROXY`), and that you have about 4 GB free. The installer offers to retry without the pinned versions; only accept that if the pinned install fails, since newer versions are untested.

**"No readable text found"**
The PDF is probably scanned images. Run it through an OCR tool first (for example `ocrmypdf`), then convert the result.

**"Document is password protected"**
Remove the password from the PDF first.

**"Aborted, no audiobook written ... chunks could not be synthesized"**
The speech server failed part-way through a chapter. The app stops rather than produce an audiobook with silent gaps. Check `server.log` (path shown in the message), free up memory, and run again. If you hit Metal errors, try `PYTORCH_ENABLE_MPS_FALLBACK=1 audiobook-studio`.

**It is slow**
On an Intel Mac or Linux there is no Metal GPU, so synthesis runs on the CPU (or CUDA if available). Apple Silicon is where this project is fast.

**Chapter names look wrong, or there are too few chapters**
Run with `--dry-run` to preview the detected chapters (the app also shows them and asks before it starts). PDFs without an outline or clear headings fall back to evenly sized sections; adding bookmarks to the PDF, or converting from an EPUB, gives better chapters.

## Optional: double-clickable launcher

```bash
osacompile -o "/Applications/Audiobook Studio.app" -e '
tell application "Terminal"
    activate
    do script "audiobook-studio"
end tell'
```

If the app cannot find the command, use the full path (`$HOME/.local/bin/audiobook-studio`) in the script.

## Performance

Measured by the author on an Apple Silicon Mac. Your numbers will vary with chip, memory and book.

| Book | Audio length | Synthesis time | Speed |
|---|---|---|---|
| Astronomy 2e (OpenStax), 43 chapters | 55.5 h | ~3.5 h | ~16x real time |
| Additive Manufacturing, 14 chapters | 8.0 h | ~32 min | ~15x real time |
| Python Illustrated, 18 chapters | 9.0 h | ~38 min | ~14x real time |

## Security and privacy

* Everything runs locally. The only network access is the one-time model download from Hugging Face.
* The speech server listens on `127.0.0.1` only and has no authentication. Do not expose it to a network. If you set `KOKORO_HOST=0.0.0.0`, anyone on that network can use your GPU.
* PDFs and EPUBs are parsed by third-party libraries. As with any document tool, only open files you trust and keep dependencies up to date.

## Project layout

```
audiobook_studio/
  app.py         terminal interface, live dashboard, M4B packaging
  server.py      local Kokoro speech server (OpenAI-style /v1/audio/speech)
  converter.py   PDF text extraction, cleanup, chapter detection, EPUB writing
```

## Legal

Only convert books you have the right to use. Kokoro-82M is Apache-2.0 licensed. This project depends on PyMuPDF, which is licensed under AGPL-3.0 (or a commercial license); review that if you plan to redistribute a combined work.

## Contributing

Bug reports and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for setup and testing, [SECURITY.md](SECURITY.md) for reporting vulnerabilities, and [CHANGELOG.md](CHANGELOG.md) for release history.

## License

MIT. Copyright (c) 2026 SK.
