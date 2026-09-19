from audiobook_studio import app


def test_resolve_voice_aliases_and_codes():
    assert app.resolve_voice("bella") == "af_bella"
    assert app.resolve_voice(" GEORGE ") == "bm_george"
    assert app.resolve_voice("af_heart") == "af_heart"
    assert app.resolve_voice("am_echo") == "am_echo"


def test_scan_library_lists_only_books_and_detects_existing_audio(tmp_path):
    books, audio = tmp_path / "books", tmp_path / "audio"
    books.mkdir()
    audio.mkdir()
    (books / "Alpha.pdf").write_bytes(b"%PDF-1.4")
    (books / "Beta.epub").write_bytes(b"PK")
    (books / "notes.txt").write_text("ignore me")
    (books / ".hidden.pdf").write_bytes(b"%PDF-1.4")
    (audio / "Beta.m4b").write_bytes(b"x")

    items = {b.clean_stem: b for b in app.scan_books_library(books, audio)}
    assert set(items) == {"Alpha", "Beta"}
    assert items["Beta"].is_epub and items["Beta"].ready_file is not None
    assert not items["Alpha"].is_epub and items["Alpha"].ready_file is None


def test_scan_library_missing_directory_is_empty(tmp_path):
    assert app.scan_books_library(tmp_path / "nope", tmp_path) == []


def test_endpoint_locality(monkeypatch):
    monkeypatch.setattr(app, "KOKORO_ENDPOINT", "http://127.0.0.1:8001/v1")
    assert app._endpoint_is_local()
    monkeypatch.setattr(app, "KOKORO_ENDPOINT", "http://gpu-box.example:8001/v1")
    assert not app._endpoint_is_local()
