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


# ---------------------------------------------------------------------------
# Arrow-key menus
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("raw, name", [
    (b"\x1b[A", "up"), (b"\x1bOA", "up"), (b"\x1b[B", "down"), (b"\x1bOB", "down"),
    (b"\x1b[H", "home"), (b"\x1b[F", "end"), (b"\x1b[5~", "pgup"), (b"\x1b[6~", "pgdn"),
    (b"\r", "enter"), (b"\n", "enter"), (b"\x1b", "esc"), (b"\x1b[15~", ""), (b"q", "q"), (b"7", "7"),
])
def test_decode_key(raw, name):
    assert app._decode_key(raw) == name


def test_decode_key_ctrl_c_and_ctrl_d():
    with pytest.raises(KeyboardInterrupt):
        app._decode_key(b"\x03")
    with pytest.raises(EOFError):
        app._decode_key(b"\x04")


def run_loop(keys, count=4, start=0, shortcuts=None, escape=None, page=10):
    it = iter(keys)
    drawn = []
    result = app._select_loop(count, start, lambda: next(it), drawn.append, shortcuts, escape, page)
    return result, drawn


def test_select_loop_moves_and_wraps():
    assert run_loop(["down", "down", "enter"])[0] == 2
    assert run_loop(["up", "enter"])[0] == 3              # up from the first row wraps to the last
    assert run_loop(["end", "enter"])[0] == 3
    assert run_loop(["end", "home", "enter"])[0] == 0
    assert run_loop(["j", "j", "k", "enter"])[0] == 1      # vim keys
    assert run_loop(["pgdn", "enter"], count=30, page=10)[0] == 10
    assert run_loop(["pgup", "enter"], count=30, start=4, page=10)[0] == 0


def test_select_loop_ignores_unknown_keys_and_redraws_only_on_movement():
    result, drawn = run_loop(["x", "", "down", "enter"])
    assert result == 1
    assert drawn == [0, 1]  # initial draw + one move


def test_select_loop_shortcut_and_escape():
    assert run_loop(["down", "b"], shortcuts={"b": 3})[0] == 3
    assert run_loop(["esc"], escape=3)[0] == 3
    it = iter(["esc", "enter"])  # Esc does nothing when the menu has no escape entry
    assert app._select_loop(4, 2, lambda: next(it), lambda pos: None) == 2


def test_choose_in_arrow_mode_returns_the_selected_key(monkeypatch):
    from contextlib import nullcontext
    keys = iter(["down", "down", "enter"])
    monkeypatch.setattr(app, "arrows_available", lambda: True)
    monkeypatch.setattr(app, "_raw_keys", lambda: nullcontext(0))
    monkeypatch.setattr(app, "_read_key", lambda fd: next(keys))
    items = [("a", "Alpha"), ("b", "Beta"), ("c", "Gamma [dim](x)[/dim]")]
    assert app.choose("Pick", items, default="a") == "c"


def test_choose_arrow_mode_shortcuts_default_and_escape(monkeypatch):
    from contextlib import nullcontext
    monkeypatch.setattr(app, "arrows_available", lambda: True)
    monkeypatch.setattr(app, "_raw_keys", lambda: nullcontext(0))
    items = [("1", "One"), ("2", "Two"), ("q", "Quit")]

    def run(keys, **kw):
        it = iter(keys)
        monkeypatch.setattr(app, "_read_key", lambda fd: next(it))
        return app.choose("Pick", items, **kw)

    assert run(["enter"], default="2") == "2"                    # the cursor starts on the default
    assert run(["Q"], default="1") == "q"                        # one-character keys jump straight there
    assert run(["esc"], default="1", escape="q") == "q"
    assert run(["down", "enter"], default="1", show_keys=False) == "2"


def test_choose_shortcuts_are_off_when_keys_are_hidden(monkeypatch):
    from contextlib import nullcontext
    monkeypatch.setattr(app, "arrows_available", lambda: True)
    monkeypatch.setattr(app, "_raw_keys", lambda: nullcontext(0))
    it = iter(["2", "enter"])  # "2" must not select "2" when keys are not shown; Enter takes the cursor row
    monkeypatch.setattr(app, "_read_key", lambda fd: next(it))
    assert app.choose("Pick", [("1", "One"), ("2", "Two")], default="1", show_keys=False) == "1"


def test_arrows_unavailable_without_a_terminal(monkeypatch):
    monkeypatch.setattr(app.sys.stdin, "isatty", lambda: False, raising=False)
    assert app.arrows_available() is False


def test_book_picker_arrow_mode(tmp_path, monkeypatch):
    from contextlib import nullcontext
    monkeypatch.setattr(app, "arrows_available", lambda: True)
    monkeypatch.setattr(app, "_raw_keys", lambda: nullcontext(0))
    books, audio = tmp_path / "b", tmp_path / "a"
    books.mkdir()
    audio.mkdir()
    (books / "One [draft].epub").write_bytes(b"PK")  # brackets in a title must not be eaten as markup
    (books / "Two.pdf").write_bytes(b"%PDF")
    library = app.scan_books_library(books, audio)

    def pick(keys):
        it = iter(keys)
        monkeypatch.setattr(app, "_read_key", lambda fd: next(it))
        return app.select_book_interactive(library, books)

    assert pick(["down", "enter"]).path.name == "Two.pdf"
    assert pick(["enter"]).path.name == "One [draft].epub"
    assert pick(["esc"]) is None
    assert pick(["end", "up", "enter"]) == "all"          # entries: 2 books, search, all, back
    feed(monkeypatch, ["two"])                             # "Search..." falls through to the typed prompt
    it = iter(["down", "down", "enter"])
    monkeypatch.setattr(app, "_read_key", lambda fd: next(it))
    assert app.select_book_interactive(library, books).path.name == "Two.pdf"


def test_voice_picker_arrow_mode(monkeypatch):
    from contextlib import nullcontext
    monkeypatch.setattr(app, "arrows_available", lambda: True)
    monkeypatch.setattr(app, "_raw_keys", lambda: nullcontext(0))

    def pick(keys, current="af_heart", typed=None):
        it = iter(keys)
        monkeypatch.setattr(app, "_read_key", lambda fd: next(it))
        if typed is not None:
            feed(monkeypatch, [typed])
        return app.select_voice_interactive(current)

    assert pick(["enter"], current="am_adam") == "am_adam"     # the cursor starts on the current voice
    assert pick(["down", "enter"]) == "af_bella"
    assert pick(["end", "enter"], typed="eric") == "am_eric"   # "Type another..." then a name or alias
    assert pick(["enter"], current="am_echo") == "am_echo"     # a custom current voice stays selectable
