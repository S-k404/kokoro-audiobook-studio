#!/usr/bin/env python3
"""
pdf2epub_tts.py - turn a text-based PDF into a clean, chaptered EPUB that
TTS tools (kokoro-tts, Audiblez, ttsforge) can read without tripping over
page numbers, running headers, hyphenated line breaks or hard-wrapped lines.

    pip install pymupdf ebooklib
    python pdf2epub_tts.py book.pdf
    python pdf2epub_tts.py book.pdf -o out.epub --pages 9-310 --skip-front --strip-citations

What it cleans
  * running headers/footers and page numbers (detected by repetition)
  * words hyphenated across line breaks, and hard-wrapped lines -> real paragraphs
  * paragraphs split across pages or columns (single- and two-column layouts)
  * ligatures, soft hyphens, zero-width junk, footnote markers, bullets,
    dot-leader table-of-contents lines, drop caps, "* * *" scene breaks
  * optionally: footnote text, URLs and [12]-style citations

Chapters come from the PDF outline if it has one, otherwise from "Chapter N"
style headings, otherwise from fixed-size chunks. Each chapter is its own
XHTML file, so TTS tools can render (and resume) chapter by chapter.

Scanned PDFs (no text layer) need OCR first:
    ocrmypdf --deskew --skip-text in.pdf out.pdf
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import statistics
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.request
import uuid
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

try:
    import pymupdf
except ImportError:
    try:
        import fitz as pymupdf
    except ImportError:
        sys.exit("Missing dependency. Run:  pip install pymupdf ebooklib")

try:
    from ebooklib import epub
except ImportError:
    epub = None

def clean_book_stem(stem: str) -> str:
    """Filesystem-safe book name; drops trailing '-- <md5> -- ...' download suffixes."""
    stem = re.sub(r"\s*--\s*[a-f0-9]{32}\s*--.*", "", stem, flags=re.I)
    return re.sub(r'[^\w\s\-_.,()\'"]', "", stem).strip() or stem


def ffmetadata_escape(value: str) -> str:
    """Escape a value for an ffmpeg FFMETADATA1 file (blocks key/section injection)."""
    value = " ".join(str(value).splitlines())
    return re.sub(r"([=;#\\])", r"\\\1", value)


BREAK = "\0BREAK"  # sentinel for scene breaks ("* * *")

NUMBER_WORDS = (
    "one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|"
    "fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|"
    "fifty|sixty|seventy|eighty|ninety|hundred"
)
CHAPTER_RE = re.compile(
    rf"^(?:chapter|part|book|section)\s+(?:\d+|[ivxlc]+|(?:{NUMBER_WORDS})(?:[- ](?:{NUMBER_WORDS}))*)\b"
    r"[\s:.\-\u2013\u2014]*(.*)$",
    re.I,
)
NAMED_HEADING_RE = re.compile(
    r"^(prologue|epilogue|preface|foreword|introduction|afterword|conclusion|"
    r"author'?s note|acknowledg(?:e)?ments)$",
    re.I,
)
BARE_NUMBER_RE = re.compile(
    rf"^(?:chapter\s+)?(?:\d+|[ivxlc]+|(?:{NUMBER_WORDS}))\.?$", re.I
)
DROP_TITLE_RE = re.compile(
    r"^(index|bibliography|references|notes|endnotes|footnotes|copyright(?: page)?|"
    r"table of contents|contents|title page|colophon|about the authors?|also by\b.*)$",
    re.I,
)
PAGENUM_RE = re.compile(
    r"^(?:page\s+)?(?:\d{1,4}|[ivxlc]{1,6}|[IVXLC]{1,6})(?:\s*(?:of|/)\s*\d{1,4})?$",
    re.I,
)
BULLET_RE = re.compile(r"^(?:[\u2022\u25aa\u25e6\u2023\u25a0\u25a1\u25cf\u25cb\u00b7]|\d{1,2}[.)])\s+")
LEADING_BULLET_RE = re.compile(r"^[\u2022\u25aa\u25e6\u2023\u25a0\u25a1\u25cf\u25cb\u00b7]\s*")
DOT_LEADER_RE = re.compile(r"(?:\.\s?){4,}\s*\d*\s*$")
SUPERSCRIPT_RE = re.compile(r"(?<=[A-Za-z.,;:)\u201d\"'\u2019])[\u00b2\u00b3\u00b9\u2070-\u2079]+")
FOOTNOTE_MARK_RE = re.compile(r"^[\d,*\u2020\u2021\u00a7\s\-\u2013]+$")


# --------------------------------------------------------------------------
# data
# --------------------------------------------------------------------------
@dataclass
class Line:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    size: float
    base: float  # baseline y of the dominant span (robust to drop caps / mixed sizes)
    block: int
    page: int
    ph: float  # page height
    left: float = 0.0   # left/right edge of the text column this line sits in
    right: float = 0.0


@dataclass
class Para:
    text: str
    page: int


@dataclass
class Section:
    title: str
    paras: list


# --------------------------------------------------------------------------
# character-level cleaning
# --------------------------------------------------------------------------
_INVISIBLE = dict.fromkeys(map(ord, "\u00ad\u200b\u200c\u200d\u2060\ufeff"), None)


def clean_chars(s: str) -> str:
    s = SUPERSCRIPT_RE.sub("", s)
    s = unicodedata.normalize("NFKC", s)  # fi/fl ligatures, nbsp, etc.
    s = s.translate(_INVISIBLE)
    s = "".join(c for c in s if c == "\t" or unicodedata.category(c)[0] != "C")
    return re.sub(r"\s+", " ", s).strip()


def ends_sentence(t: str) -> bool:
    t = t.rstrip().rstrip("\"\u201d\u2019')]\u00bb*")
    return bool(t) and t[-1] in ".?!\u2026:"


def continues_flow(prev: str, nxt: str) -> bool:
    """Does `nxt` (after a page/column jump) continue the unfinished `prev`?"""
    if ends_sentence(prev):
        return False
    return nxt[:1].islower() or prev.rstrip().endswith((",", ";", "-", "\u2013", "\u2014"))


# --------------------------------------------------------------------------
# extraction
# --------------------------------------------------------------------------
def _dominant_span(spans):
    real = [s for s in spans if s["text"].strip()]
    return max(real, key=lambda s: len(s["text"].strip())) if real else None


def _is_footnote_mark(s, main) -> bool:
    """Superscript-style footnote markers ("3", "*", dagger) that would be read as digits."""
    if s is main or not s["text"].strip() or not FOOTNOTE_MARK_RE.match(s["text"]):
        return False
    raised = s["origin"][1] < main["origin"][1] - 0.15 * main["size"]
    return bool(s["flags"] & 1) or (s["size"] < 0.8 * main["size"] and raised)


def extract_pages(doc, first: int, last: int, sort: bool) -> list[list[Line]]:
    pages = []
    for pno in range(first, last + 1):
        page = doc[pno]
        ph = page.rect.height
        out: list[Line] = []
        for b_i, b in enumerate(page.get_text("dict", sort=sort)["blocks"]):
            if b.get("type") != 0:
                continue
            for ln in b["lines"]:
                if abs(ln.get("dir", (1, 0))[1]) > 0.5:  # skip vertical/rotated text
                    continue
                main = _dominant_span(ln["spans"])
                if main is None:
                    continue
                parts, after_dropcap = [], False
                for s in ln["spans"]:
                    if _is_footnote_mark(s, main) or (after_dropcap and not s["text"].strip()):
                        continue
                    t = s["text"].strip()
                    after_dropcap = len(t) == 1 and t.isalpha() and s["size"] >= 1.4 * main["size"]
                    parts.append(s["text"])
                raw = "".join(parts).rstrip()
                if raw.endswith("\u00ad"):  # soft hyphen at line end = real hyphenation
                    raw = raw[:-1] + "-"
                text = clean_chars(raw)
                if not text:
                    continue
                x0, y0, x1, y1 = ln["bbox"]
                out.append(Line(text, x0, y0, x1, y1, round(main["size"], 1),
                                main["origin"][1], b_i, pno, ph))
        pages.append(out)
    return pages


# --------------------------------------------------------------------------
# running headers / footers / page numbers
# --------------------------------------------------------------------------
def _in_band(ln: Line, band: float) -> bool:
    return ln.y0 < ln.ph * band or ln.y1 > ln.ph * (1 - band)


def _hf_key(t: str) -> str:
    return re.sub(r"\d+", "#", t.lower()).strip()


def is_pagenum(t: str) -> bool:
    return bool(PAGENUM_RE.match(t.strip(" -\u2013\u2014\u2022\u00b7|[]()")))


def strip_running_text(pages: list[list[Line]], band: float = 0.09):
    """Drop page numbers and text that repeats every page or every other page
    in the top/bottom margin. Chapter headings that recur only once per
    chapter are kept (their page gaps are large)."""
    seen: dict[str, set[int]] = defaultdict(set)
    for lines in pages:
        for ln in lines:
            if _in_band(ln, band):
                seen[_hf_key(ln.text)].add(ln.page)
    repeated = set()
    for key, pgs in seen.items():
        pgs = sorted(pgs)
        if len(pgs) >= 3 and statistics.median(b - a for a, b in zip(pgs, pgs[1:])) <= 2:
            repeated.add(key)

    removed, cleaned = 0, []
    for lines in pages:
        keep = []
        for ln in lines:
            if _in_band(ln, band) and (is_pagenum(ln.text) or _hf_key(ln.text) in repeated):
                removed += 1
            else:
                keep.append(ln)
        cleaned.append(keep)
    return cleaned, removed


def drop_footnote_text(pages: list[list[Line]]):
    """Remove small-print lines in the lower part of the page (footnotes)."""
    sizes: Counter = Counter()
    for lines in pages:
        for l in lines:
            sizes[l.size] += len(l.text)
    if not sizes:
        return pages, 0
    body = sizes.most_common(1)[0][0]
    removed, out = 0, []
    for lines in pages:
        keep = [l for l in lines if not (l.size < body * 0.88 and l.y0 > l.ph * 0.6)]
        removed += len(lines) - len(keep)
        out.append(keep)
    return out, removed


# --------------------------------------------------------------------------
# lines -> paragraphs
# --------------------------------------------------------------------------
def _typical_leading(pages) -> float:
    diffs = []
    for lines in pages:
        for a, b in zip(lines, lines[1:]):
            dy = b.base - a.base
            if 0 < dy < 2.5 * a.size and abs(a.size - b.size) < 0.5:
                diffs.append(dy)
    return statistics.median(diffs) if diffs else 14.0


def annotate_columns(pages: list[list[Line]]) -> None:
    """Give every line the left/right edge of its text column (handles 1- and 2-column pages)."""
    for lines in pages:
        if not lines:
            continue
        body = [l for l in lines if len(l.text) > 25] or lines
        span = max(l.x1 for l in body) - min(l.x0 for l in body)
        lefts = Counter(round(l.x0 / 3) * 3 for l in body).most_common(4)
        first, n1 = lefts[0]
        second = next((k for k, n in lefts[1:] if abs(k - first) > 0.3 * span and n >= 0.25 * n1), None)
        col_lefts = sorted([first] + ([second] if second is not None else []))

        def col_for(l):
            return max((c for c in col_lefts if c <= l.x0 + 2), default=col_lefts[0])

        extents = {}
        for cl in col_lefts:
            xs = sorted(l.x1 for l in body if col_for(l) == cl) or [cl + span]
            extents[cl] = xs[int(0.9 * (len(xs) - 1))]
        for l in lines:
            cl = col_for(l)
            l.left, l.right = cl, extents[cl]


def _is_indented(ln) -> bool:
    return ln.x0 > ln.left + 0.9 * ln.size


def _is_short(ln, frac=0.12) -> bool:
    return ln.x1 < ln.right - frac * (ln.right - ln.left)


def _detect_indent_style(pages, L) -> bool:
    """True if this book marks paragraphs with first-line indents. Looks at lines that
    clearly end a paragraph (short + end of sentence) and checks whether the next line is indented."""
    starts = indented = 0
    for lines in pages:
        for a, b in zip(lines, lines[1:]):
            if (a.page == b.page and ends_sentence(a.text) and _is_short(a, 0.3)
                    and 0 < b.base - a.base <= 1.45 * L):
                starts += 1
                indented += _is_indented(b)
    return starts >= 5 and indented / starts >= 0.6


def _is_ornament(t: str) -> bool:
    return len(t) <= 15 and not re.search(r"[A-Za-z0-9]", t)  # "* * *", "~", "***"


def _new_paragraph(prev, ln, L, indent_style) -> bool:
    if prev is None:
        return True
    if _is_ornament(prev.text) or _is_ornament(ln.text):  # scene-break lines stand alone
        return True
    if ln.page != prev.page or ln.base < prev.base - 0.5 * prev.size:  # page / column jump
        if abs(ln.size - prev.size) > 1.0 or BULLET_RE.match(ln.text):
            return True
        if not ends_sentence(prev.text):
            if indent_style and not _is_indented(ln):  # e.g. "...Stretched | Marguerite ..."
                return False
            return not continues_flow(prev.text, ln.text)
        if indent_style:  # trust indents: unindented line after a full-width line continues
            return _is_indented(ln) or _is_short(prev, 0.3)
        return True
    if abs(ln.size - prev.size) > 1.0 or BULLET_RE.match(ln.text):
        return True
    if ln.base - prev.base > 1.45 * L:  # extra vertical gap
        return True
    if ends_sentence(prev.text):
        if _is_indented(ln):  # first-line indent
            return True
        if not indent_style:  # no indents in this book: fall back on line shape / blocks
            if _is_short(prev) or ln.block != prev.block:
                return True
    return False


def _join(parts: list[str]) -> str:
    out = ""
    for t in parts:
        if not out:
            out = t
        elif len(out) == 1 and out.isalpha() and t[:1].islower():  # drop cap: "T" + "he"
            out += t
        elif out.endswith("-") and len(out) > 1 and out[-2].isalpha():
            out = out[:-1] + t if t[:1].islower() else out + t  # de-hyphenate
        else:
            out += " " + t
    return out


def build_paragraphs(pages: list[list[Line]]) -> list[Para]:
    L = _typical_leading(pages)
    annotate_columns(pages)
    indent_style = _detect_indent_style(pages, L)
    paras: list[Para] = []
    cur: list[str] = []
    cur_page = 0
    prev = None

    def flush():
        if cur:
            paras.append(Para(_join(cur), cur_page))
            cur.clear()

    for lines in pages:
        if not lines:
            continue
        for ln in lines:
            if _new_paragraph(prev, ln, L, indent_style):
                flush()
                cur_page = ln.page
            cur.append(ln.text)
            prev = ln
    flush()
    return paras


def tidy_paragraphs(paras: list[Para], strip_urls: bool, strip_cites: bool) -> list[Para]:
    out: list[Para] = []
    for p in paras:
        t = LEADING_BULLET_RE.sub("", p.text)
        if DOT_LEADER_RE.search(t):  # table-of-contents line
            continue
        if strip_urls:
            t = re.sub(r"(?:https?://|www\.)\S+", "", t)
        if strip_cites:
            t = re.sub(r"\[\d+(?:\s*[,\u2013-]\s*\d+)*\]", "", t)
        t = re.sub(r"\s+([,.;:!?])", r"\1", t)
        t = re.sub(r"\s{2,}", " ", t).strip()
        if not t:
            continue
        if not re.search(r"[A-Za-z0-9]", t):  # "* * *" etc.
            if len(t) <= 15:
                t = BREAK
            else:
                continue
        out.append(Para(t, p.page))

    # drop caps that ended up as their own paragraph
    merged: list[Para] = []
    i = 0
    while i < len(out):
        p = out[i]
        if len(p.text) == 1 and p.text.isalpha() and i + 1 < len(out) and out[i + 1].text[:1].islower():
            out[i + 1] = Para(p.text + out[i + 1].text, p.page)
        else:
            merged.append(p)
        i += 1
    return merged


# --------------------------------------------------------------------------
# chapters
# --------------------------------------------------------------------------
def _norm(s: str) -> str:
    return re.sub(r"\W+", " ", s.lower()).strip()


def drop_title_echo(title: str, paras: list[str]) -> list[str]:
    """Remove a heading paragraph that just repeats the chapter title."""
    nt = _norm(title)
    i = 0
    while i < min(3, len(paras)):
        p = paras[i]
        short = p != BREAK and len(p) < 100 and not ends_sentence(p)
        if short and (BARE_NUMBER_RE.match(p) or (_norm(p) and (_norm(p) in nt or nt in _norm(p)))):
            del paras[i]
        else:
            i += 1
    return paras


def sections_from_outline(doc, paras: list[Para], first: int, last: int):
    by_level: dict[int, list[tuple[int, str]]] = defaultdict(list)
    for lvl, title, pg in doc.get_toc(simple=True):
        pg -= 1
        title = re.sub(r"\s+", " ", title).strip()
        if title and first <= pg <= last:
            by_level[lvl].append((pg, title))
    if not by_level:
        return None
    chosen = next((l for l in sorted(by_level) if len(by_level[l]) >= 5), None)
    if chosen is None:
        chosen = max(by_level, key=lambda k: len(by_level[k]))
        if len(by_level[chosen]) < 2:
            return None
    starts: dict[int, str] = {}
    for pg, title in sorted(by_level[chosen]):
        starts.setdefault(pg, title)
    starts_l = sorted(starts.items())

    sections = []
    front = [p.text for p in paras if p.page < starts_l[0][0]]
    if front:
        sections.append(Section("Front matter", front))
    for i, (pg, title) in enumerate(starts_l):
        end = starts_l[i + 1][0] if i + 1 < len(starts_l) else last + 1
        body = [p.text for p in paras if pg <= p.page < end]
        sections.append(Section(title, drop_title_echo(title, body)))
    return sections


def sections_from_headings(paras: list[Para], min_words: int):
    cands = []  # (index into paras, title, paragraphs consumed)
    i = 0
    while i < len(paras):
        t = paras[i].text
        if t != BREAK and len(t) <= 80 and not DOT_LEADER_RE.search(t):
            m = CHAPTER_RE.match(t)
            if m or NAMED_HEADING_RE.match(t):
                title, used = t, 1
                nxt = paras[i + 1].text if i + 1 < len(paras) else ""
                bare = bool(m) and not m.group(1).strip()
                if bare and nxt and nxt != BREAK and len(nxt) <= 70 and not ends_sentence(nxt) \
                        and not CHAPTER_RE.match(nxt):
                    title, used = f"{t}: {nxt}", 2
                cands.append((i, title, used))
                i += used
                continue
        i += 1

    words = lambda a, b: sum(len(p.text.split()) for p in paras[a:b])
    kept = []
    for k, (idx, title, used) in enumerate(cands):
        nxt_idx = cands[k + 1][0] if k + 1 < len(cands) else len(paras)
        if words(idx + used, nxt_idx) >= min_words:  # filters TOC lists / false positives
            kept.append((idx, title, used))
    if len(kept) < 2:
        return None

    sections = []
    if kept[0][0] > 0:
        sections.append(Section("Front matter", [p.text for p in paras[: kept[0][0]]]))
    for k, (idx, title, used) in enumerate(kept):
        end = kept[k + 1][0] if k + 1 < len(kept) else len(paras)
        sections.append(Section(title, [p.text for p in paras[idx + used: end]]))
    return sections


def chunk(paras: list[str], limit: int) -> list[list[str]]:
    chunks, cur, n = [], [], 0
    for p in paras:
        w = len(p.split())
        if cur and n + w > limit:
            chunks.append(cur)
            cur, n = [], 0
        cur.append(p)
        n += w
    if cur:
        chunks.append(cur)
    return chunks


def finalize(sections: list[Section], args) -> list[Section]:
    final = []
    for s in sections:
        paras = list(s.paras)
        while paras and paras[0] == BREAK:
            paras.pop(0)
        while paras and paras[-1] == BREAK:
            paras.pop()
        if not any(p != BREAK for p in paras):
            continue
        if args.skip_front and s.title == "Front matter":
            continue
        if not args.keep_all_sections and DROP_TITLE_RE.match(s.title.strip()):
            print(f"  skipping section: {s.title!r}")
            continue
        if sum(len(p.split()) for p in paras) > args.max_words:
            parts = chunk(paras, args.max_words)
            for n, part in enumerate(parts, 1):
                final.append(Section(f"{s.title} (part {n})", part))
        else:
            final.append(Section(s.title, paras))
    return final


# --------------------------------------------------------------------------
# output
# --------------------------------------------------------------------------
def write_epub(sections, out: Path, title: str, author: str, lang: str):
    if epub is None:
        sys.exit("ebooklib is required to write .epub files. Run: pip install ebooklib")
    esc = lambda s: html.escape(s, quote=False)
    book = epub.EpubBook()
    book.set_identifier(f"urn:uuid:{uuid.uuid4()}")
    book.set_title(title)
    book.set_language(lang)
    book.add_author(author)
    items = []
    for i, s in enumerate(sections, 1):
        body = [f"<h1>{esc(s.title)}</h1>"]
        body += ["<hr/>" if p == BREAK else f"<p>{esc(p)}</p>" for p in s.paras]
        ch = epub.EpubHtml(title=s.title, file_name=f"chapter_{i:03d}.xhtml", lang=lang)
        ch.content = "\n".join(body)
        book.add_item(ch)
        items.append(ch)
    book.toc = items
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = items  # nav stays out of the spine so TTS tools don't read it
    epub.write_epub(str(out), book)


def dump_text(sections, path: Path):
    with open(path, "w", encoding="utf-8") as f:
        for s in sections:
            f.write(f"{s.title}\n\n")
            for p in s.paras:
                f.write(("* * *" if p == BREAK else p) + "\n\n")
            f.write("\n")


# --------------------------------------------------------------------------
# audio synthesis & audiobook compilation (Kokoro Docker / Speaches)
# --------------------------------------------------------------------------
def chunk_paragraphs_for_tts(paras: list[str], max_chars: int = 350) -> list[str]:
    """Splits section paragraphs into natural sentence-level chunks suitable for Kokoro TTS."""
    def _split_long(text: str, limit: int) -> list[str]:
        if len(text) <= limit:
            return [text]
        # Split on commas, semicolons, dashes, colons
        clauses = re.split(r'(?<=[,;:\u2013\u2014])\s+', text)
        res = []
        cur = ""
        for c in clauses:
            if len(c) > limit:
                # Split on words if single clause is still too long
                words = c.split()
                w_cur = ""
                for w in words:
                    if len(w_cur) + len(w) + 1 <= limit:
                        w_cur = (w_cur + " " + w).strip()
                    else:
                        if w_cur:
                            res.append(w_cur)
                        w_cur = w
                if w_cur:
                    res.append(w_cur)
            elif len(cur) + len(c) + 1 <= limit:
                cur = (cur + " " + c).strip()
            else:
                if cur:
                    res.append(cur)
                cur = c
        if cur:
            res.append(cur)
        return res

    chunks = []
    current = ""
    for p in paras:
        if p == BREAK:
            if current:
                chunks.append(current)
                current = ""
            continue
        sentences = re.split(r'(?<=[.?!])\s+', p)
        for s in sentences:
            s = s.strip()
            if not s:
                continue
            subparts = _split_long(s, max_chars)
            for part in subparts:
                if len(current) + len(part) + 1 <= max_chars:
                    current = (current + " " + part).strip()
                else:
                    if current:
                        chunks.append(current)
                    current = part
    if current:
        chunks.append(current)
    return chunks


def _synthesize_chunk_http(text: str, endpoint: str, model: str, voice: str, speed: float) -> bytes:
    effective_model = model
    if effective_model in ("hexgrad/Kokoro-82M", "kokoro", "Kokoro-82M"):
        effective_model = "speaches-ai/Kokoro-82M-v1.0-ONNX"

    url = endpoint.rstrip("/")
    if not url.endswith("/audio/speech"):
        url = f"{url}/audio/speech" if "/v1" in url else f"{url}/v1/audio/speech"

    payload = {
        "model": effective_model,
        "input": text,
        "voice": voice,
        "response_format": "mp3",
        "speed": speed,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Connection": "close",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def _get_audio_duration_ms(path: Path) -> int:
    """Probes exact audio duration in milliseconds using ffprobe."""
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path)
        ]
        out = subprocess.check_output(cmd, text=True).strip()
        return int(float(out) * 1000)
    except Exception:
        # Fallback approximation: 1s ~= 8000 bytes at ~64kbps mp3
        return int((path.stat().st_size / 8000) * 1000)

