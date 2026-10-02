# Architecture

## Project layout

```
audiobook_studio/
  app.py         terminal interface, live dashboard, M4B packaging
  server.py      local Kokoro speech server (OpenAI-style /v1/audio/speech)
  converter.py   PDF text extraction, cleanup, chapter detection, EPUB writing
```

## How a book is turned into an audiobook

1. **`app.py`** is the entry point. It renders the interactive menu (or
   parses CLI flags), resolves the chosen voice, speed and format, and makes
   sure a speech server is available (`ensure_kokoro_server`) before doing
   anything else.

2. **`converter.py`** handles PDFs and EPUBs:
   - For PDFs, it extracts text line-by-line per page, then identifies and
     strips running headers/footers, page numbers, and footnote text so the
     narration doesn't include page furniture.
   - Lines are reassembled into paragraphs and sections (`build_paragraphs`,
     `sections_from_outline` / `sections_from_headings`), using the PDF's own
     outline/bookmarks when present and falling back to detected headings or
     evenly sized sections otherwise.
   - The cleaned result is written out as a `.epub` alongside the audiobook,
     and that text is what actually gets narrated.
   - EPUBs are read directly, since their chapter and text structure is
     already explicit.

3. **`server.py`** is a small local HTTP server exposing an OpenAI-style
   `/v1/audio/speech` endpoint backed by the Kokoro-82M pipeline. It picks the
   best available device (Apple Metal via PyTorch MPS, CUDA, or CPU) and
   converts the model's raw PCM output into the requested audio format
   (WAV/MP3/etc). It starts on demand when a conversion begins and is torn
   down when the app exits — there is no long-running background service.

4. Back in **`app.py`**, each chapter's text is sent to the server in chunks,
   progress is drawn live (per-chapter and overall), and the resulting audio
   chunks are packaged into a single `.m4b` with real chapter markers via
   `ffmpeg`/`ffmetadata`.

## Design choices worth knowing

- **No persistent daemon.** The speech server is a subprocess owned by the
  CLI session, not a system service — this keeps the security surface small
  (see the README's Security and privacy section) and avoids managing a
  background process.
- **Local-first.** The only network call outside of installing dependencies
  is the one-time voice model download from Hugging Face; after that,
  everything runs offline.
- **Pluggable backend.** `KOKORO_ENDPOINT` lets `app.py` talk to a Kokoro
  server running elsewhere instead of spawning its own, which is how a
  remote/shared GPU setup would be wired in — see
  [CONFIGURATION.md](CONFIGURATION.md).
