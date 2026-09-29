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


# ---------------------------------------------------------------------------
# Interactive session
# ---------------------------------------------------------------------------
import pytest


def feed(monkeypatch, answers):
    """Script the answers to every Prompt.ask / Confirm.ask; running out acts like EOF (Ctrl-D)."""
    it = iter(answers)

    def fake(*args, **kwargs):
        try:
            return next(it)
        except StopIteration:
            raise EOFError

    monkeypatch.setattr(app.Prompt, "ask", staticmethod(fake))
    monkeypatch.setattr(app.Confirm, "ask", staticmethod(fake))


@pytest.fixture
def studio(tmp_path, monkeypatch):
    """Two books (one already converted) and a recorder standing in for the TTS pipeline."""
    books, audio = tmp_path / "books", tmp_path / "audio"
    books.mkdir()
    audio.mkdir()
    (books / "Alpha.epub").write_bytes(b"PK")
    (books / "Beta.epub").write_bytes(b"PK")
    (audio / "Beta.m4b").write_bytes(b"x")
    calls = []
    monkeypatch.setattr(app, "synthesize_book_with_dashboard", lambda **kw: calls.append(kw) or True)
    return app.Settings(books_dir=books, audio_dir=audio), calls


def test_session_quits_and_survives_eof(studio, monkeypatch):
    settings, calls = studio
    feed(monkeypatch, ["q"])
    app.interactive_session(settings)
    feed(monkeypatch, [])  # EOF at the main prompt
    app.interactive_session(settings)
    assert calls == []


def test_session_convert_uses_current_settings_and_asks_confirmation(studio, monkeypatch):
    settings, calls = studio
    settings.voice, settings.speed, settings.audio_format = "am_adam", 1.25, "mp3"
    feed(monkeypatch, ["1", "alpha", "c", "q"])  # convert -> search "alpha" -> convert -> quit
    app.interactive_session(settings)
    assert len(calls) == 1
    assert calls[0]["book_path"].name == "Alpha.epub"
    assert (calls[0]["voice"], calls[0]["speed"], calls[0]["audio_format"]) == ("am_adam", 1.25, "mp3")
    assert calls[0]["confirm"] is True and calls[0]["dry_run"] is False


def test_session_preview_is_dry_run_and_returns_to_action_prompt(studio, monkeypatch):
    settings, calls = studio
    feed(monkeypatch, ["1", "1", "p", "b", "q"])  # pick book 1 -> preview -> back -> quit
    app.interactive_session(settings)
    assert [c["dry_run"] for c in calls] == [True]


def test_session_changing_settings_from_the_convert_flow(studio, monkeypatch):
    settings, calls = studio
    feed(monkeypatch, ["1", "1", "s", "4", "2", "b", "c", "q"])  # ... settings -> speed 2 -> back -> convert
    app.interactive_session(settings)
    assert calls[0]["speed"] == 2.0


def test_session_convert_all_only_converts_pending_books(studio, monkeypatch):
    settings, calls = studio
    feed(monkeypatch, ["2", True, "q"])
    app.interactive_session(settings)
    assert [c["book_path"].name for c in calls] == ["Alpha.epub"]


def test_session_convert_all_declined_does_nothing(studio, monkeypatch):
    settings, calls = studio
    feed(monkeypatch, ["2", False, "q"])
    app.interactive_session(settings)
    assert calls == []


def test_session_ctrl_c_in_an_action_returns_to_menu(studio, monkeypatch):
    settings, calls = studio
    answers = iter(["1", KeyboardInterrupt, "q"])

    def fake(*args, **kwargs):
        value = next(answers)
        if value is KeyboardInterrupt:
            raise KeyboardInterrupt
        return value

    monkeypatch.setattr(app.Prompt, "ask", staticmethod(fake))
    app.interactive_session(settings)  # must not raise
    assert calls == []


def test_settings_menu_edits_every_setting(studio, monkeypatch, tmp_path):
    settings, _ = studio
    new_books = tmp_path / "more"
    new_books.mkdir()
    feed(monkeypatch, ["1", str(new_books), "1", str(tmp_path / "nope"), "4", "1.5", "5", "mp3", "6", "b"])
    app.settings_menu(settings)
    assert settings.books_dir == new_books.resolve()  # the missing folder was rejected, not saved
    assert (settings.speed, settings.audio_format, settings.dry_run) == (1.5, "mp3", True)


def test_ask_speed_reprompts_on_garbage_and_clamps(monkeypatch):
    feed(monkeypatch, ["fast", "nan", "inf", "99"])
    assert app.ask_speed(1.0) == app.MAX_SPEED
    feed(monkeypatch, ["0.01"])
    assert app.ask_speed(1.0) == app.MIN_SPEED


def test_voice_prompt_defaults_to_current_voice(monkeypatch):
    seen = {}

    def fake(*args, **kwargs):
        seen.update(kwargs)
        return kwargs["default"]

    monkeypatch.setattr(app.Prompt, "ask", staticmethod(fake))
    assert app.select_voice_interactive("am_adam") == "am_adam"
    assert seen["default"] == "6"  # Enter keeps the current voice instead of resetting to #1


def test_book_picker_can_go_back_and_handles_empty_library(tmp_path, monkeypatch):
    feed(monkeypatch, ["q"])
    assert app.select_book_interactive([], tmp_path) is None
    feed(monkeypatch, ["3", "all"])  # out-of-range number on an empty library must not loop forever
    assert app.select_book_interactive([], tmp_path) == "all"


def test_main_without_terminal_or_target_exits_instead_of_prompting(tmp_path, monkeypatch):
    monkeypatch.setattr(app.sys, "argv", ["audiobook-studio", "--books-dir", str(tmp_path), "-o", str(tmp_path)])
    monkeypatch.setattr(app.sys.stdin, "isatty", lambda: False, raising=False)
    with pytest.raises(SystemExit) as exc:
        app.main()
    assert exc.value.code == 1
