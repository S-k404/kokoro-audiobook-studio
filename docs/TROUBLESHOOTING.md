# Troubleshooting

Run the self-check first — it covers most of the issues below in one command:

```bash
audiobook-studio --doctor
```

It lists what works and what does not (Python, ffmpeg, GPU, speech engine,
voice model, output folder, port) and says how to fix each problem.

## Install and setup

**`No matching distribution found for kokoro` or `requires a different Python`**
You are using Python 3.13 or newer. Install 3.12 (`brew install python@3.12`)
and re-run `./install.sh`, which picks a supported version automatically.

**`command not found: audiobook-studio`**
`~/.local/bin` is not on your PATH. Run this, then open a new terminal:
```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
```

**`ffmpeg` or `ffprobe` not found**
```bash
brew install ffmpeg
```

**Installation fails with network or pip errors**
Check your internet connection, VPN or proxy (`HTTPS_PROXY`), and that you
have about 4 GB free. The installer offers to retry without the pinned
versions; only accept that if the pinned install fails, since newer versions
are untested.

## Running the server

**"Server failed to start"**
Look at the log for the real reason:
```bash
tail -50 ~/.kokoro-audiobook-studio/server.log
```
The first start downloads the model and can take a few minutes on a slow
connection. If the download was interrupted, run the command again.

**Port 8001 is already in use**
If another Kokoro server is already running there, the app will simply use
it. If it is something else, choose another port:
```bash
KOKORO_PORT=8011 KOKORO_ENDPOINT=http://127.0.0.1:8011/v1 audiobook-studio
```

**Log says `Error processing file ... espeak-ng-data/phontab`**
The environment is installed in a folder with a very long path (the speech
engine's data folder must be under about 130 characters deep). Reinstall in a
shorter location, for example `~/.kokoro-audiobook-studio` (what `install.sh`
uses).

**The first conversion seems stuck**
The voice model (~330 MB) is downloaded the first time it is needed. Run
`audiobook-studio --download-model` to fetch it with visible progress, and
check your internet connection or proxy. Partial downloads resume.

**"Aborted, no audiobook written ... chunks could not be synthesized"**
The speech server failed part-way through a chapter. The app stops rather
than produce an audiobook with silent gaps. Check `server.log` (path shown in
the message), free up memory, and run again. If you hit Metal errors, try
`PYTORCH_ENABLE_MPS_FALLBACK=1 audiobook-studio`.

**It is slow**
On an Intel Mac or Linux there is no Metal GPU, so synthesis runs on the CPU
(or CUDA if available). Apple Silicon is where this project is fast.

## Book content

**"No readable text found"**
The PDF is probably scanned images. Run it through an OCR tool first (for
example `ocrmypdf`), then convert the result.

**"Document is password protected"**
Remove the password from the PDF first.

**Chapter names look wrong, or there are too few chapters**
Run with `--dry-run` to preview the detected chapters (the app also shows
them and asks before it starts). PDFs without an outline or clear headings
fall back to evenly sized sections; adding bookmarks to the PDF, or
converting from an EPUB, gives better chapters.
