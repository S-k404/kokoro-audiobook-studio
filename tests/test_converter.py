import pymupdf

from audiobook_studio import converter as conv


def test_clean_book_stem_strips_download_suffix():
    stem = "My Book -- " + "a" * 32 + " -- Some Site"
    assert conv.clean_book_stem(stem) == "My Book"


def test_clean_book_stem_removes_unsafe_characters():
    assert conv.clean_book_stem("a/b:c*d") == "abcd"


def test_clean_book_stem_never_returns_empty():
    assert conv.clean_book_stem("///") == "///"


def test_ffmetadata_escape_blocks_injection():
    out = conv.ffmetadata_escape("Title\n[CHAPTER]\nSTART=0")
    assert "\n" not in out
    assert conv.ffmetadata_escape("a=b;c#d\\e") == r"a\=b\;c\#d\\e"


def test_chunk_paragraphs_respects_limit():
    text = "This is a sentence. " * 100
    chunks = conv.chunk_paragraphs_for_tts([text], max_chars=350)
    assert len(chunks) > 1
    assert all(0 < len(c) <= 400 for c in chunks)


def _make_pdf(path):
    doc = pymupdf.open()
    for n in range(1, 4):
        page = doc.new_page()
        page.insert_text((72, 40), "RUNNING HEADER TEXT", fontsize=9)
        page.insert_text((72, 90), f"Chapter {n}: Topic {n}", fontsize=20)
        body = "This is a plain body paragraph used by the tests. " * 8
        page.insert_textbox(pymupdf.Rect(72, 120, 520, 700), body, fontsize=12)
        page.insert_text((290, 800), str(n), fontsize=9)
    doc.save(path)
    return path


def test_pdf_pipeline_strips_running_text_and_writes_epub(tmp_path):
    pdf = _make_pdf(tmp_path / "book.pdf")
    doc = pymupdf.open(pdf)
    pages = conv.extract_pages(doc, 0, doc.page_count - 1, sort=False)
    pages, _ = conv.strip_running_text(pages)
    paras = conv.tidy_paragraphs(conv.build_paragraphs(pages), strip_urls=False, strip_cites=True)

    text = " ".join(p.text for p in paras)
    assert "RUNNING HEADER TEXT" not in text
    assert "plain body paragraph" in text

    sections = conv.sections_from_headings(paras, min_words=20) or [
        conv.Section("Section 1", [p.text for p in paras])
    ]
    out = tmp_path / "book.epub"
    conv.write_epub(sections, out, "Test Book", "Tester", lang="en")
    assert out.is_file() and out.stat().st_size > 500
