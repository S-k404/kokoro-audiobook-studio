#!/usr/bin/env python3
"""
app.py — Interactive Terminal Audiobook Studio with Apple Metal GPU (MPS)
Provides an interactive wizard, PDF-to-EPUB / direct-EPUB pipeline,
custom or baked-in output directories, voice selection, and a full-CMD live dashboard.
"""
from __future__ import annotations

import argparse
import atexit
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import pymupdf
try:
    pymupdf.TOOLS.mupdf_display_errors(False)
except Exception:
    pass
from rich.align import Align
from rich.box import DOUBLE, ROUNDED
from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

# Import conversion & text extraction helpers
CURRENT_DIR = Path(__file__).parent.resolve()
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

try:
    from . import converter as conv
except ImportError:  # run as a plain script
    import converter as conv

console = Console()

# ---------------------------------------------------------------------------
# Constants & Defaults
# ---------------------------------------------------------------------------
DEFAULT_BOOKS_DIR = Path(os.getenv("BOOKS_DIR", Path.home() / "Documents/Books"))
DEFAULT_AUDIO_DIR = Path(os.getenv("AUDIO_DIR", Path.home() / "Documents/AudioBook"))
KOKORO_PORT = int(os.getenv("KOKORO_PORT", "8001"))
KOKORO_HOST = os.getenv("KOKORO_HOST", "127.0.0.1")  # loopback only; the API has no auth
KOKORO_ENDPOINT = os.getenv("KOKORO_ENDPOINT", f"http://127.0.0.1:{KOKORO_PORT}/v1")
STATE_DIR = Path(os.getenv("KOKORO_STUDIO_HOME", Path.home() / ".kokoro-audiobook-studio"))
MIN_SPEED, MAX_SPEED = 0.25, 4.0  # range accepted by the server
DEFAULT_VOICE = "af_heart"
DEFAULT_SPEED = 1.0
DEFAULT_FORMAT = "m4b"

VOICE_CATALOG = [
    ("af_heart",   "heart",   "American Female", "★ Warm, expressive, highest quality [Default]"),
    ("af_bella",   "bella",   "American Female", "Gentle, melodic, ideal for fiction & storytelling"),
    ("af_sky",     "sky",     "American Female", "Bright, upbeat, clear, energetic"),
    ("af_sarah",   "sarah",   "American Female", "Articulate, balanced, non-fiction & tech"),
    ("af_nicole",  "nicole",  "American Female", "Crisp, conversational, modern"),
    ("am_adam",    "adam",    "American Male",   "Deep, steady, resonant, authoritative narrator"),
    ("am_michael", "michael", "American Male",   "Warm, friendly podcast narrator"),
    ("am_onyx",    "onyx",    "American Male",   "Cinematic, deep baritone"),
    ("bf_emma",    "emma",    "British Female",  "Classic British RP, articulate, polished narrator"),
    ("bm_george",  "george",  "British Male",    "Distinguished British literature narrator"),
]

VOICE_MAP = {}
for code, alias, _, _ in VOICE_CATALOG:
    VOICE_MAP[code.lower()] = code
    VOICE_MAP[alias.lower()] = code

# Additional aliases
VOICE_MAP.update({
    "alice": "bf_alice",
    "isabella": "bf_isabella",
    "lily": "bf_lily",
    "daniel": "bm_daniel",
    "fable": "bm_fable",
    "lewis": "bm_lewis",
    "echo": "am_echo",
    "eric": "am_eric",
    "fenrir": "am_fenrir",
    "liam": "am_liam",
    "puck": "am_puck",
    "alloy": "af_alloy",
    "river": "af_river",
})


def resolve_voice(voice_str: str) -> str:
    v = voice_str.strip().lower()
    return VOICE_MAP.get(v, voice_str.strip())


# ---------------------------------------------------------------------------
# Server Lifecycle Manager
# ---------------------------------------------------------------------------
_SERVER_PROC: Optional[subprocess.Popen] = None
_WE_STARTED_SERVER = False


def _endpoint_parts():
    u = urlparse(KOKORO_ENDPOINT)
    return u.scheme or "http", u.hostname or "127.0.0.1", u.port or KOKORO_PORT


def _endpoint_is_local() -> bool:
    return _endpoint_parts()[1] in ("localhost", "127.0.0.1", "::1")


def is_server_running() -> bool:
    scheme, host, port = _endpoint_parts()
    try:
        host = f"[{host}]" if ":" in host else host
        with urllib.request.urlopen(f"{scheme}://{host}:{port}/health", timeout=1.5) as resp:
            return resp.status == 200
    except Exception:
        return False


def stop_server_on_exit():
    global _SERVER_PROC
    if _WE_STARTED_SERVER:
        console.print("\n[cyan]ℹ️  Stopping Kokoro GPU server (on-demand mode)...[/cyan]")
        if _SERVER_PROC and _SERVER_PROC.poll() is None:
            _SERVER_PROC.terminate()
            try:
                _SERVER_PROC.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _SERVER_PROC.kill()
        (STATE_DIR / "server.pid").unlink(missing_ok=True)
        console.print("[green]✅  Kokoro GPU server stopped cleanly.[/green]")


atexit.register(stop_server_on_exit)


def ensure_kokoro_server():
    global _SERVER_PROC, _WE_STARTED_SERVER
    if is_server_running():
        return True
    if not _endpoint_is_local():
        console.print(f"[red]❌ Remote Kokoro endpoint {KOKORO_ENDPOINT} is not reachable.[/red]")
        return False

    console.print(f"[cyan]🚀 Starting on-demand Kokoro GPU server on {KOKORO_HOST}:{KOKORO_PORT}...[/cyan]")
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    log_path = STATE_DIR / "server.log"
    with open(log_path, "a", encoding="utf-8") as log_file:
        _SERVER_PROC = subprocess.Popen(
            [
                sys.executable, "-m", "uvicorn", "audiobook_studio.server:app",
                "--host", KOKORO_HOST,
                "--port", str(KOKORO_PORT),
                "--workers", "1",
            ],
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
    _WE_STARTED_SERVER = True
    (STATE_DIR / "server.pid").write_text(str(_SERVER_PROC.pid))

    # First run downloads the model (~330 MB), so allow generous time.
    for _ in range(180):
        time.sleep(1.0)
        if _SERVER_PROC.poll() is not None:
            break
        if is_server_running():
            console.print("[green]✅  Kokoro GPU server is online and ready.[/green]")
            return True

    console.print(f"[red]❌ Server failed to start on port {KOKORO_PORT}. Check {log_path}[/red]")
    return False


# ---------------------------------------------------------------------------
# Library Scanner
# ---------------------------------------------------------------------------
@dataclass
class BookItem:
    path: Path
    is_epub: bool
    size_mb: float
    title: str
    clean_stem: str
    audio_status: str
    ready_file: Optional[Path] = None


def scan_books_library(books_dir: Path, audio_dir: Path) -> List[BookItem]:
    if not books_dir.is_dir():
        return []

    items = []
    files = sorted(
        [f for f in books_dir.iterdir() if f.suffix.lower() in (".pdf", ".epub") and not f.name.startswith(".")],
        key=lambda x: x.name.lower()
    )

    for b in files:
        size_mb = b.stat().st_size / (1024 * 1024)
        clean_stem = conv.clean_book_stem(b.stem)
        is_epub = b.suffix.lower() == ".epub"

        # Check existing audio in destination
        ready_file = None
        for ext in (".m4b", ".m4u", ".m4a", ".mp3"):
            cand = audio_dir / f"{clean_stem}{ext}"
            if cand.is_file():
                ready_file = cand
                break
            for af in audio_dir.glob(f"*{ext}"):
                if af.stem and len(af.stem) > 6 and (af.stem in clean_stem or clean_stem in af.stem):
                    ready_file = af
                    break
            if ready_file:
                break

        if ready_file:
            audio_status = f"[bold green]✓ Ready[/bold green] ({ready_file.suffix})"
        else:
            audio_status = "[yellow]⏳ Pending[/yellow]"

        items.append(
            BookItem(
                path=b,
                is_epub=is_epub,
                size_mb=size_mb,
                title=clean_stem.replace("_", " ").replace("-", " ").strip(),
                clean_stem=clean_stem,
                audio_status=audio_status,
                ready_file=ready_file,
            )
        )
    return items


# ---------------------------------------------------------------------------
# Interactive Wizard
# ---------------------------------------------------------------------------
def render_banner():
    title_text = Text()
    title_text.append("🎧 AUDIOBOOK STUDIO", style="bold cyan")
    title_text.append(" — Apple Silicon Metal GPU Accelerated", style="bold white")
    subtitle = Text("Transform your PDF & EPUB library into chaptered M4B audiobooks on-demand", style="italic dim")
    banner = Panel(
        Align.center(Group(title_text, subtitle)),
        box=ROUNDED,
        border_style="cyan",
        padding=(1, 2),
    )
    console.print(banner)


def build_books_table(books: List[BookItem]) -> Table:
    table = Table(box=ROUNDED, border_style="bright_blue", show_header=True, header_style="bold cyan")
    table.add_column("#", style="bold yellow", justify="right")
    table.add_column("Type", justify="center")
    table.add_column("Title / Book Name", style="white")
    table.add_column("Size", justify="right")
    table.add_column("Audiobook", justify="center")
    table.add_column("Pipeline Workflow")

    for idx, b in enumerate(books, 1):
        type_badge = "[bold cyan][EPUB][/bold cyan]" if b.is_epub else "[bold yellow][PDF][/bold yellow]"
        workflow = (
            "[cyan]1) Direct TTS synthesis[/cyan]"
            if b.is_epub
            else "[yellow]2) Extract -> EPUB -> TTS[/yellow]"
        )
        display_title = (b.title[:60] + "...") if len(b.title) > 63 else b.title
        table.add_row(str(idx), type_badge, display_title, f"{b.size_mb:.1f} MB", b.audio_status, workflow)
    return table


def select_book_interactive(books: List[BookItem], books_dir: Path) -> Optional[BookItem | Path | str]:
    table = build_books_table(books)
    console.print(table)
    console.print("[dim]Options: Enter a book number, search term, custom file path, or 'all' for batch conversion.[/dim]\n")

    while True:
        choice = Prompt.ask("[bold green]👉 Select a book[/bold green]", default="1").strip()
        if not choice:
            continue

        raw = choice.strip()
        cleaned = raw.strip("'\"").replace("\\ ", " ")

        if cleaned.lower() in ("all", "batch"):
            return "all"

        # Check numeric index
        if cleaned.isdigit():
            val = int(cleaned)
            if 1 <= val <= len(books):
                return books[val - 1]
            console.print(f"[red]Please enter a number between 1 and {len(books)}[/red]")
            continue

        # Check if direct file path
        p = Path(cleaned).expanduser().resolve()
        if p.is_file() and p.suffix.lower() in (".pdf", ".epub"):
            return p

        # Check title substring search
        matches = [b for b in books if cleaned.lower() in b.title.lower() or cleaned.lower() in b.path.name.lower()]
        if len(matches) == 1:
            return matches[0]
        elif len(matches) > 1:
            console.print(f"[yellow]Multiple matches found for '{choice}':[/yellow]")
            for mi, m in enumerate(matches, 1):
                console.print(f"  {mi}. {m.title} ({m.path.suffix})")
            sub_choice = Prompt.ask("Select matching number", choices=[str(i) for i in range(1, len(matches) + 1)])
            return matches[int(sub_choice) - 1]

        console.print(f"[red]Could not find '{choice}'. Please select a valid number or enter a file path.[/red]")


def select_output_directory(default_dir: Path) -> Path:
    console.print("\n[bold cyan]📁 Output Destination Folder:[/bold cyan]")
    console.print(f"[dim]Audiobook files (.m4b) will be saved here. Press Enter to use default.[/dim]")
    ans = Prompt.ask(
        "[bold green]Save audiobooks to[/bold green]",
        default=str(default_dir)
    ).strip()
    cleaned = ans.strip("'\"").replace("\\ ", " ")
    dest = Path(cleaned).expanduser().resolve()
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def select_voice_interactive(current_voice: str) -> str:
    console.print("\n[bold cyan]🎙️ Select a Narrator Voice:[/bold cyan]")
    v_table = Table(box=ROUNDED, border_style="bright_blue", show_header=True, header_style="bold cyan")
    v_table.add_column("#", style="bold yellow", width=3, justify="right")
    v_table.add_column("Voice Code", style="bold green", width=12)
    v_table.add_column("Accent / Gender", width=18)
    v_table.add_column("Style & Characteristics", ratio=1)

    for i, (code, alias, cat, desc) in enumerate(VOICE_CATALOG, 1):
        v_table.add_row(str(i), code, cat, desc)

    console.print(v_table)
    ans = Prompt.ask(
        "[bold green]Choose voice [1-10 or type name][/bold green]",
        default="1"
    ).strip()

    if ans.isdigit():
        val = int(ans)
        if 1 <= val <= len(VOICE_CATALOG):
            return VOICE_CATALOG[val - 1][0]

    return resolve_voice(ans)


def select_audio_settings(default_speed: float, default_format: str) -> Tuple[float, str]:
    speed_ans = Prompt.ask(
        "[bold green]⏩ Playback Speed factor[/bold green]",
        default=str(default_speed)
    ).strip()
    try:
        speed = float(speed_ans)
    except ValueError:
        speed = 1.0
    speed = min(max(speed, MIN_SPEED), MAX_SPEED)

    fmt = Prompt.ask(
        "[bold green]🎵 Audio Format[/bold green] (m4b with chapter markers, or mp3)",
        choices=["m4b", "mp3"],
        default=default_format
    )
    return speed, fmt


# ---------------------------------------------------------------------------
# Dashboard & Live Synthesis Runner
# ---------------------------------------------------------------------------
def synthesize_book_with_dashboard(
    book_path: Path,
    output_dir: Path,
    voice: str,
    speed: float,
    audio_format: str,
    concurrency: int = 4,
    dry_run: bool = False,
):
    is_epub = book_path.suffix.lower() == ".epub"
    clean_stem = conv.clean_book_stem(book_path.stem)
    audio_dest = (output_dir / clean_stem).with_suffix(f".{audio_format}")

    # Step Banner
    console.print()
    if is_epub:
        step_panel = Panel(
            Text.from_markup(
                f"[bold cyan]📘 EPUB File Selected:[/bold cyan] [bold white]{book_path.name}[/bold white]\n"
                f"[green]✓ Direct Pipeline:[/green] Extracting chapter outline and text for immediate TTS synthesis.\n"
                f"Destination: [yellow]{audio_dest}[/yellow]"
            ),
            box=ROUNDED,
            border_style="cyan",
            title="[bold]Workflow: Direct EPUB -> TTS[/bold]",
        )
    else:
        epub_dest = (output_dir / clean_stem).with_suffix(".epub")
        step_panel = Panel(
            Text.from_markup(
                f"[bold yellow]📄 PDF File Selected:[/bold yellow] [bold white]{book_path.name}[/bold white]\n"
                f"[cyan]• Step 1:[/cyan] Extract text layer, clean headers/footers/page numbers -> write clean EPUB: [dim]{epub_dest.name}[/dim]\n"
                f"[cyan]• Step 2:[/cyan] Synthesize chaptered audiobook -> [yellow]{audio_dest.name}[/yellow]"
            ),
            box=ROUNDED,
            border_style="yellow",
            title="[bold]Workflow: PDF -> Clean EPUB -> TTS Audiobook[/bold]",
        )
    console.print(step_panel)

    # 1. Open document & extract sections
    with console.status("[bold green]Analyzing document structure and chapters...[/bold green]", spinner="dots"):
        doc = pymupdf.open(book_path)
        if doc.needs_pass:
            console.print("[red]❌ Document is password protected. Remove password first.[/red]")
            return False

        meta = doc.metadata or {}
        title = (meta.get("title") or "").strip() or clean_stem.replace("_", " ").title()
        author = (meta.get("author") or "").strip() or "Unknown"

        pages = conv.extract_pages(doc, 0, doc.page_count - 1, sort=False)
        pages, _ = conv.strip_running_text(pages)
        paras = conv.tidy_paragraphs(conv.build_paragraphs(pages), strip_urls=False, strip_cites=True)
        if not paras:
            console.print("[red]❌ No readable text found. If this is a scanned PDF, run OCR first.[/red]")
            return False

        sections = conv.sections_from_outline(doc, paras, 0, doc.page_count - 1)
        if not sections:
            sections = conv.sections_from_headings(paras, min_words=80)
        if not sections:
            sections = [conv.Section(f"Section {i}", c) for i, c in enumerate(conv.chunk([p.text for p in paras], 6000), 1)]

        # Drop empty sections
        sections = [s for s in sections if any(p != conv.BREAK and p.strip() for p in s.paras)]
        if not sections:
            console.print("[red]❌ No sections found for audio synthesis.[/red]")
            return False

    total_words = sum(len(p.split()) for s in sections for p in s.paras if p != conv.BREAK)
    est_hours = total_words / 150 / 60

    # If PDF, write the intermediate EPUB
    if not is_epub:
        epub_dest = (output_dir / clean_stem).with_suffix(".epub")
        with console.status(f"[cyan]Writing clean EPUB to {epub_dest.name}...[/cyan]", spinner="dots"):
            conv.write_epub(sections, epub_dest, title, author, lang="en")
        console.print(f"[green]✓ Step 1 Complete:[/green] Saved clean EPUB -> [white]{epub_dest}[/white]")

    if dry_run:
        console.print(f"\n[bold cyan]🔍 Dry Run Summary:[/bold cyan] {len(sections)} sections identified, {total_words:,} words, estimated audio: ~{est_hours:.1f} hours.")
        for idx, s in enumerate(sections[:8], 1):
            wcount = sum(len(p.split()) for p in s.paras if p != conv.BREAK)
            console.print(f"   [yellow]{idx:2d}.[/yellow] {s.title} ({wcount} words)")
        if len(sections) > 8:
            console.print(f"   [dim]... and {len(sections) - 8} more chapters[/dim]")
        console.print("\n[bold green]✓ Dry-run completed successfully.[/bold green]\n")
        return True

    # 2. Setup Rich Live Progress Panel
    console.print(f"\n[bold cyan]🎧 Starting Kokoro Metal GPU Synthesis ({len(sections)} chapters, ~{total_words:,} words, ~{est_hours:.1f}h audio)[/bold cyan]")

    progress_overall = Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]{task.description}[/bold cyan]"),
        BarColumn(bar_width=35, complete_style="cyan", finished_style="green"),
        TaskProgressColumn(),
        TextColumn("[white]({task.completed}/{task.total} Chapters)[/white]"),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
    )

    progress_chapter = Progress(
        TextColumn("[bold yellow]{task.description}[/bold yellow]"),
        BarColumn(bar_width=35, complete_style="yellow", finished_style="green"),
        TaskProgressColumn(),
        TextColumn("[dim]{task.completed}/{task.total} Chunks[/dim]"),
        TimeElapsedColumn(),
    )

    completed_log = []

    def build_history_table():
        tbl = Table(box=ROUNDED, border_style="dim", show_header=True, header_style="bold magenta", expand=True)
        tbl.add_column("Ch #", width=5, justify="right")
        tbl.add_column("Chapter Title", ratio=1)
        tbl.add_column("Duration", width=10, justify="right")
        tbl.add_column("Size", width=10, justify="right")
        tbl.add_column("Status", width=10, justify="center")

        if not completed_log:
            tbl.add_row("-", "[dim]Synthesizing chapters...[/dim]", "-", "-", "[yellow]Working[/yellow]")
        else:
            show = completed_log[-6:] if len(completed_log) > 6 else completed_log
            if len(completed_log) > 6:
                earlier = len(completed_log) - 6
                tbl.add_row("...", f"[dim]({earlier} earlier chapters completed)[/dim]", "", "", "[green]✓[/green]")
            for row in show:
                tbl.add_row(*row)
        return tbl

    history_panel = Panel(build_history_table(), box=ROUNDED, border_style="dim", title="[bold]Completed Chapters Log[/bold]")

    task_overall_id = progress_overall.add_task("Overall Progress", total=len(sections))
    task_chapter_id = progress_chapter.add_task("Current Chapter", total=100)

    # Info header panel
    def make_header_panel():
        grid = Table.grid(expand=True)
        grid.add_column(ratio=1)
        grid.add_column(justify="right")
        grid.add_row(
            Text.from_markup(f"📖 [bold white]{title}[/bold white] [dim]by {author}[/dim]"),
            Text.from_markup(f"[bold green]● Kokoro TTS[/bold green] | {KOKORO_ENDPOINT}")
        )
        grid.add_row(
            Text.from_markup(f"🎙️ Voice: [cyan]{voice}[/cyan] | Speed: [cyan]{speed}x[/cyan] | Format: [cyan]{audio_format.upper()}[/cyan]"),
            Text.from_markup(f"📁 Destination: [dim]{audio_dest}[/dim]")
        )
        return Panel(grid, box=ROUNDED, border_style="cyan", padding=(0, 1))

    dashboard_group = Group(
        make_header_panel(),
        Panel(Group(progress_overall, progress_chapter), box=ROUNDED, border_style="bright_blue", title="[bold]Synthesis Telemetry[/bold]"),
        history_panel,
    )

    # 3. Perform chunk synthesis with live updates
    with tempfile.TemporaryDirectory(prefix="audiobook_studio_") as td:
        temp_dir = Path(td)
        chapter_files = []
        chapter_durations = []
        failure = None

        with Live(dashboard_group, console=console, refresh_per_second=4):
            for ch_idx, s in enumerate(sections, 1):
                chunks = conv.chunk_paragraphs_for_tts(s.paras)
                if not chunks:
                    progress_overall.advance(task_overall_id)
                    continue

                ch_display_title = (s.title[:40] + "...") if len(s.title) > 43 else s.title
                progress_chapter.reset(task_chapter_id, total=len(chunks), description=f"Ch {ch_idx}: {ch_display_title}")

                ch_mp3 = temp_dir / f"chapter_{ch_idx:03d}.mp3"
                chunk_results = [None] * len(chunks)

                def _task(item):
                    idx, chunk_text = item
                    for attempt in range(5):
                        try:
                            audio = conv._synthesize_chunk_http(chunk_text, KOKORO_ENDPOINT, "kokoro", voice, speed)
                            return idx, audio
                        except Exception:
                            if attempt < 4:
                                time.sleep(1.0 * (attempt + 1))
                            else:
                                return idx, None

                with ThreadPoolExecutor(max_workers=concurrency) as executor:
                    completed_count = 0
                    futures = [executor.submit(_task, item) for item in enumerate(chunks)]
                    for fut in as_completed(futures):
                        idx, audio_data = fut.result()
                        chunk_results[idx] = audio_data
                        completed_count += 1
                        progress_chapter.update(task_chapter_id, completed=completed_count)

                failed = [i for i, r in enumerate(chunk_results) if r is None]
                if failed:
                    failure = (
                        f"chapter {ch_idx} ({s.title!r}): {len(failed)}/{len(chunks)} text chunks could not be "
                        f"synthesized after 5 attempts (see {STATE_DIR / 'server.log'})"
                    )
                    break

                # Write chapter MP3
                with open(ch_mp3, "wb") as f:
                    for b in chunk_results:
                        if b:
                            f.write(b)

                dur_ms = conv._get_audio_duration_ms(ch_mp3)
                chapter_files.append((s.title, ch_mp3))
                chapter_durations.append(dur_ms)

                # Update history table
                dur_str = f"{dur_ms / 1000 / 60:.1f} min" if dur_ms >= 60000 else f"{dur_ms / 1000:.0f} sec"
                sz_str = f"{ch_mp3.stat().st_size / (1024 * 1024):.1f} MB"
                completed_log.append((str(ch_idx), ch_display_title, dur_str, sz_str, "[green]✓ Done[/green]"))
                history_panel.renderable = build_history_table()

                progress_overall.advance(task_overall_id)

        if failure:
            console.print(f"\n[red]❌ Aborted, no audiobook written — {failure}[/red]")
            return False

        # 4. Packaging with ffmpeg into M4B
        console.print("\n[bold cyan]📦 Packaging chapters into final M4B audiobook container...[/bold cyan]")
        with console.status("[yellow]Encoding AAC & embedding chapter bookmarks with ffmpeg...[/yellow]", spinner="aesthetic"):
            flist = temp_dir / "flist.txt"
            with open(flist, "w", encoding="utf-8") as f:
                for _, ch_path in chapter_files:
                    f.write(f"file '{ch_path}'\n")

            meta_file = temp_dir / "metadata.txt"
            with open(meta_file, "w", encoding="utf-8") as f:
                f.write(";FFMETADATA1\n")
                f.write(f"title={conv.ffmetadata_escape(title)}\n")
                f.write(f"artist={conv.ffmetadata_escape(author)}\n")
                f.write(f"album={conv.ffmetadata_escape(title)}\n")
                pos_ms = 0
                for (ch_title, _), d_ms in zip(chapter_files, chapter_durations):
                    f.write("\n[CHAPTER]\n")
                    f.write("TIMEBASE=1/1000\n")
                    f.write(f"START={pos_ms}\n")
                    pos_ms += d_ms
                    f.write(f"END={pos_ms}\n")
                    f.write(f"title={conv.ffmetadata_escape(ch_title)}\n")

            if audio_format.lower() in ("m4b", "m4a", "m4u"):
                cmd = [
                    "ffmpeg", "-f", "concat", "-safe", "0",
                    "-i", str(flist),
                    "-i", str(meta_file),
                    "-map_metadata", "1",
                    "-c:a", "aac", "-b:a", "64k",
                    "-f", "ipod",
                    str(audio_dest), "-y"
                ]
            else:
                cmd = [
                    "ffmpeg", "-f", "concat", "-safe", "0",
                    "-i", str(flist),
                    "-i", str(meta_file),
                    "-map_metadata", "1",
                    "-c:a", "libmp3lame", "-b:a", "64k",
                    str(audio_dest), "-y"
                ]

            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode != 0:
                console.print(f"[red]❌ ffmpeg failed (exit {proc.returncode}):[/red]\n{proc.stderr[-1500:]}")
                return False

    final_size_mb = audio_dest.stat().st_size / (1024 * 1024)
    total_sec = sum(chapter_durations) / 1000
    hours = int(total_sec // 3600)
    mins = int((total_sec % 3600) // 60)

    # Success Card
    success_panel = Panel(
        Text.from_markup(
            f"[bold green]🎉 Audiobook Successfully Generated![/bold green]\n\n"
            f"📄 [bold]File:[/bold] [cyan]{audio_dest}[/cyan]\n"
            f"💾 [bold]Size:[/bold] [white]{final_size_mb:.1f} MB[/white]\n"
            f"⏱️ [bold]Audio Length:[/bold] [white]{hours}h {mins}m[/white] ({len(sections)} chapters)\n"
            f"🎙️ [bold]Narrator:[/bold] [cyan]{voice}[/cyan] ({speed}x)\n\n"
            f"[dim]Ready to play in Apple Books, QuickTime, or VLC with chapter bookmarks.[/dim]"
        ),
        box=ROUNDED,
        border_style="green",
        padding=(1, 2),
    )
    console.print(success_panel)
    return True


# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Audiobook Studio App (Apple Metal GPU)")
    parser.add_argument("target", nargs="?", default=None, help="Book number, title, or path")
    parser.add_argument("voice_tag", nargs="?", default=None, help="Optional voice tag at end (e.g. adam, bella, george)")
    parser.add_argument("-v", "--voice", default=None, help="Voice code or alias")
    parser.add_argument("-s", "--speed", type=float, default=DEFAULT_SPEED, help="Speech speed factor (default: 1.0)")
    parser.add_argument("-f", "--format", default=DEFAULT_FORMAT, choices=["m4b", "mp3"], help="Output format (default: m4b)")
    parser.add_argument("-o", "--output", type=Path, default=None, help="Output destination folder")
    parser.add_argument("--books-dir", type=Path, default=DEFAULT_BOOKS_DIR, help="Books directory")
    parser.add_argument("--voices", action="store_true", help="List all available voices")
    parser.add_argument("--list", action="store_true", help="List available books")
    parser.add_argument("--all", action="store_true", help="Batch convert all pending books")
    parser.add_argument("--dry-run", action="store_true", help="Analyze document structure without TTS synthesis")
    args = parser.parse_args()

    books_dir = args.books_dir.expanduser().resolve()
    audio_dir = (args.output or DEFAULT_AUDIO_DIR).expanduser().resolve()
    audio_dir.mkdir(parents=True, exist_ok=True)

    # 1. Handle quick flags
    if args.voices:
        console.print(Panel("[bold cyan]🎙️ Available Kokoro Voices[/bold cyan]", box=ROUNDED))
        v_table = Table(box=ROUNDED, show_header=True, header_style="bold cyan")
        v_table.add_column("Voice Code", style="bold green", width=14)
        v_table.add_column("Accent / Gender", width=18)
        v_table.add_column("Style & Characteristics", ratio=1)
        for code, _, cat, desc in VOICE_CATALOG:
            v_table.add_row(code, cat, desc)
        console.print(v_table)
        sys.exit(0)

    library = scan_books_library(books_dir, audio_dir)

    if args.list:
        render_banner()
        console.print(build_books_table(library))
        sys.exit(0)

    # 2. Resolve Voice
    selected_voice = DEFAULT_VOICE
    if args.voice:
        selected_voice = resolve_voice(args.voice)
    elif args.voice_tag and (args.voice_tag.lower() in VOICE_MAP or "_" in args.voice_tag):
        selected_voice = resolve_voice(args.voice_tag)

    selected_speed = min(max(args.speed, MIN_SPEED), MAX_SPEED)
    selected_format = args.format

    # 3. Interactive Wizard (if invoked without arguments)
    target_item = None

    if args.all:
        target_item = "all"
    elif args.target:
        target_str = args.target.strip()
        # Handle colon notation (e.g. 1:bella, book.pdf:adam)
        if ":" in target_str and not Path(target_str).exists():
            parts = target_str.split(":", 1)
            target_str = parts[0].strip()
            selected_voice = resolve_voice(parts[1])

        cleaned_target = target_str.strip("'\"").replace("\\ ", " ")
        if cleaned_target.isdigit():
            val = int(cleaned_target)
            if 1 <= val <= len(library):
                target_item = library[val - 1]
        elif Path(cleaned_target).is_file():
            target_item = Path(cleaned_target).expanduser().resolve()
        else:
            matches = [b for b in library if cleaned_target.lower() in b.title.lower() or cleaned_target.lower() in b.path.name.lower()]
            if matches:
                target_item = matches[0]

        # If output was not explicitly set on CLI, ask if interactive
        if not args.output and sys.stdin.isatty():
            audio_dir = select_output_directory(audio_dir)

        # If voice was not specified on CLI, ask if interactive
        if not args.voice and not args.voice_tag and ":" not in args.target and sys.stdin.isatty():
            selected_voice = select_voice_interactive(selected_voice)

    if target_item is None:
        render_banner()
        selection = select_book_interactive(library, books_dir)
        if not selection:
            sys.exit(0)
        target_item = selection

        # Ask for output directory (baked-in default confirmed on Enter)
        audio_dir = select_output_directory(audio_dir)

        # Ask for voice if not explicitly provided
        if not args.voice and not args.voice_tag:
            selected_voice = select_voice_interactive(selected_voice)

        # Ask for speed & format
        selected_speed, selected_format = select_audio_settings(selected_speed, selected_format)

    # 4. Ensure Kokoro GPU server is online (skip if dry-run)
    if not args.dry_run:
        if not ensure_kokoro_server():
            sys.exit("Could not connect to Kokoro GPU server.")

    # 5. Process selection
    if target_item == "all":
        pending = [b for b in library if not b.ready_file]
        console.print(f"\n[bold cyan]🚀 Batch Mode: Converting {len(pending)} pending books...[/bold cyan]")
        for idx, b in enumerate(pending, 1):
            console.print(f"\n[bold yellow]══════════════════════════════════════════════════════════════[/bold yellow]")
            console.print(f"[bold]📚 Book [{idx}/{len(pending)}]: {b.title}[/bold]")
            console.print(f"[bold yellow]══════════════════════════════════════════════════════════════[/bold yellow]")
            synthesize_book_with_dashboard(
                book_path=b.path,
                output_dir=audio_dir,
                voice=selected_voice,
                speed=selected_speed,
                audio_format=selected_format,
                dry_run=args.dry_run,
            )
    elif isinstance(target_item, BookItem):
        synthesize_book_with_dashboard(
            book_path=target_item.path,
            output_dir=audio_dir,
            voice=selected_voice,
            speed=selected_speed,
            audio_format=selected_format,
            dry_run=args.dry_run,
        )
    elif isinstance(target_item, Path):
        synthesize_book_with_dashboard(
            book_path=target_item,
            output_dir=audio_dir,
            voice=selected_voice,
            speed=selected_speed,
            audio_format=selected_format,
            dry_run=args.dry_run,
        )


if __name__ == "__main__":
    main()
