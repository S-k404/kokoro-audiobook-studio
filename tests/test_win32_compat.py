from __future__ import annotations

from types import SimpleNamespace

from audiobook_studio import app as studio_app
from audiobook_studio import server as studio_server


class _FakeMsvcrt:
    def __init__(self, seq):
        self._items = list(seq)

    def getwch(self):
        return self._items.pop(0)


def test_decode_win_key_arrows_enter_and_esc():
    fake = _FakeMsvcrt(["\xe0", "H", "\xe0", "P", "\xe0", "I", "\xe0", "Q", "\r", "\x1b", "a"])
    assert studio_app._decode_win_key(fake) == "up"
    assert studio_app._decode_win_key(fake) == "down"
    assert studio_app._decode_win_key(fake) == "pgup"
    assert studio_app._decode_win_key(fake) == "pgdn"
    assert studio_app._decode_win_key(fake) == "enter"
    assert studio_app._decode_win_key(fake) == "esc"
    assert studio_app._decode_win_key(fake) == "a"


def test_arrows_available_on_win32_tty(monkeypatch):
    monkeypatch.setattr(studio_app.sys, "platform", "win32")
    monkeypatch.setattr(studio_app.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(studio_app.sys, "stdout", SimpleNamespace(isatty=lambda: True))
    assert studio_app.arrows_available() is True


def test_server_backend_name_matches_device():
    assert studio_server._backend_name("mps") == "pytorch-metal-mps"
    assert studio_server._backend_name("cuda") == "pytorch-cuda"
    assert studio_server._backend_name("cpu") == "pytorch-cpu"
