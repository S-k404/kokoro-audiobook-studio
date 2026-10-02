# Configuration reference

Full reference for voices and environment variables. For everyday use, see the
Quick start and Usage sections in the [README](../README.md).

## Voices

The interactive wizard shows ten curated voices. Any Kokoro voice code also
works with `-v`, for example `-v am_echo`.

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

Pick a voice per run with `-v`/`-voice`, for example:

```bash
audiobook-studio 3 bella
audiobook-studio 3:george   # colon style, same thing
```

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `BOOKS_DIR` | `~/Documents/Books` | Where your PDFs and EPUBs are |
| `AUDIO_DIR` | `~/Documents/AudioBook` | Where audiobooks are written |
| `KOKORO_PORT` | `8001` | Port for the local speech server |
| `KOKORO_HOST` | `127.0.0.1` | Address the server listens on |
| `KOKORO_ENDPOINT` | `http://127.0.0.1:8001/v1` | Use an already running or remote Kokoro server instead |
| `KOKORO_STUDIO_HOME` | `~/.kokoro-audiobook-studio` | Server log and state files |

Settings can also be changed from the app's **Settings** menu (voice, speed,
format, books/output folders), which persists them for future runs.

`KOKORO_HOST` and `KOKORO_PORT` only matter if you need to run the speech
server on a non-default address, for example to share one GPU-backed server
between machines on a trusted network — see the Security and privacy section
of the README before doing this, since the server has no authentication.
