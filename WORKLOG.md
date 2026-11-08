# Work log: interactive command-line tool

Date: 2026-09-30. Scope: turn `audiobook-studio` into an interactive command-line tool.

## Step 1: interactive main menu (committed and pushed as `3313432`)

- Bare `audiobook-studio` in a terminal opens a menu that loops until you quit:
  convert a book (with chapter preview), convert all pending, library, settings,
  health check, download voice model.
- Settings (books folder, output folder, voice, speed, format, dry run) live for the
  session and are shown above the menu. CLI flags (`-v`, `-s`, `-f`, `-o`, `--books-dir`,
  `--dry-run`) seed them.
- The speech server stays loaded between books and stops when you quit.
- Ctrl-C inside an action returns to the menu; at the menu it quits.
- Scripted use (`audiobook-studio 3`, `--all`, `--list`, `--doctor`, ...) is unchanged.
  No book and no terminal now exits with status 1 instead of crashing on a prompt.
- Fixes: book picker looped forever on an empty folder; voice prompt reset to #1 on Enter;
  invalid speed silently became 1.0x; `--all` now prints a done/failed summary.

## Step 2: arrow-key menus (uncommitted at the time of writing)

- Up/down, Home/End, PgUp/PgDn, j/k, Enter, Esc; a menu's number or letter jumps straight
  to that row. Used for the main menu, settings, the book action menu, the book list,
  the voice picker and the format picker.
- Standard library only (`termios`/`tty`, Rich `Live`). No new dependency, so
  `constraints.txt`, `uv.lock`, `install.sh` and CI are unchanged.
- Without a terminal (pipes, CI, Windows) the same prompts fall back to typed answers.
- The terminal is always restored (verified after quit and after Ctrl-C).
- Bug found by the new tests and fixed: capital `Q` did not jump to the `q` row.

Files: `audiobook_studio/app.py`, `tests/test_app.py`, `README.md`, `CHANGELOG.md`.

## Verification

- `python -m pytest`: 46 passed (10 before this work).
- Real pseudo-terminal runs: menu navigation with real arrow escape sequences, book list,
  action menu, settings, voice picker, Esc, Ctrl-C, terminal state afterwards.
- Real end-to-end conversion through the menu (3-chapter test PDF, Apple Metal GPU):
  produced a 4 MB `.m4b`; the library then showed it as converted; quitting stopped the
  speech server (port 8001 no longer answering).

## Notes and known limits

- Preview (`p`) and `--dry-run` still write the clean `.epub` to the output folder for PDFs.
  This was already the case; not changed.
- Ctrl-C during synthesis is caught and returns to the menu, but was only tested with a
  stubbed synthesis. The existing thread pool waits for the current chapter's queued
  chunks on exit, so the return may lag by up to a chapter.
- Settings are not saved between launches.
- Mistake during testing: a shell quoting slip ran `--list` and `--all` once against the
  real `~/Documents/Books` folder. `--all` found 0 pending books, so nothing was
  converted or written.

## Commit commands

```bash
cd ~/Documents/Docker/kokoro-audiobook-studio && git add CHANGELOG.md README.md audiobook_studio/app.py tests/test_app.py && git commit -m "feat(cli): arrow-key menus for the interactive session" && git push origin main
```
