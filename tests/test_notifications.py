""""Tests for the outbound notification dispatcher."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from types import SimpleNamespace
from typing import Any

import pytest

from webui.notifications import (
    DEFAULT_BOT_NAME,
    DEFAULT_EMBED_COLOR,
    NotificationDispatcher,
    bot_display_name,
    format_color,
    normalize_hex_color,
    notifications,
    parse_discord_color,
)


class _FakeSettings:
    def __init__(self, **kwargs: Any) -> None:
        self.discord_webhook_url = ""
        self.telegram_bot_token = ""
        self.telegram_chat_id = ""
        self.bot_name = ""
        self.webhook_avatar = ""
        self.embed_color = DEFAULT_EMBED_COLOR
        self.notify_drop_claimed = True
        self.notify_campaign_complete = True
        self.notify_channel_switch = True
        self.notify_fatal_error = True
        for key, value in kwargs.items():
            setattr(self, key, value)


def _effective_title(settings: Any) -> str:
    """Run the manager's tab-title decision outside a full UI session."""
    from webui.manager import WebUIManager

    manager = object.__new__(WebUIManager)
    manager._twitch = SimpleNamespace(settings=settings)
    return manager._effective_title()


class _FakeSettings:
    def __init__(self, **kwargs: Any) -> None:
        self.discord_webhook_url = ""
        self.telegram_bot_token = ""
        self.telegram_chat_id = ""
        self.bot_name = ""
        self.webhook_avatar = ""
        self.embed_color = DEFAULT_EMBED_COLOR
        self.notify_drop_claimed = True
        self.notify_campaign_complete = True
        self.notify_channel_switch = True
        self.notify_fatal_error = True
        for key, value in kwargs.items():
            setattr(self, key, value)


@pytest.fixture
def dispatcher() -> NotificationDispatcher:
    return NotificationDispatcher()


def _capture(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_post(url: str, payload: dict[str, Any]) -> tuple[bool, str]:
        calls.append((url, payload))
        return True, "HTTP 204"

    monkeypatch.setattr("webui.notifications._post_json", fake_post)
    return calls


# -- configuration detection ---------------------------------------------


def test_nothing_configured_sends_nothing(
    dispatcher: NotificationDispatcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    dispatcher.bind(_FakeSettings())
    calls = _capture(monkeypatch)
    assert dispatcher.send("drop_claimed", "t", "b") == {}
    assert calls == []


def test_discord_only(dispatcher: NotificationDispatcher, monkeypatch: pytest.MonkeyPatch) -> None:
    dispatcher.bind(_FakeSettings(discord_webhook_url="https://example.test/hook"))
    calls = _capture(monkeypatch)
    results = dispatcher.send("drop_claimed", "Drop", "claimed something")
    assert set(results) == {"discord"}
    assert results["discord"][0] is True
    assert len(calls) == 1
    url, payload = calls[0]
    assert url == "https://example.test/hook"
    # Discord rejects an empty "content", so the body must live in an embed.
    assert "content" not in payload
    assert payload["embeds"][0]["title"] == "Drop"
    assert payload["embeds"][0]["description"] == "claimed something"
    assert payload["username"] == DEFAULT_BOT_NAME
    assert payload["embeds"][0]["author"]["name"] == DEFAULT_BOT_NAME
    assert payload["embeds"][0]["color"] == int(DEFAULT_EMBED_COLOR.lstrip("#"), 16)
    # No avatar configured, so nothing may override Discord's webhook avatar.
    assert "avatar_url" not in payload


def test_discord_custom_identity(
    dispatcher: NotificationDispatcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    dispatcher.bind(
        _FakeSettings(
            discord_webhook_url="https://example.test/hook",
            bot_name="TDM 1",
            webhook_avatar="https://example.test/me.png",
            embed_color="#ff0000",
        )
    )
    calls = _capture(monkeypatch)
    dispatcher.send("drop_claimed", "Drop", "body")
    url, payload = calls[0]
    assert payload["username"] == "TDM 1"
    assert payload["avatar_url"] == "https://example.test/me.png"
    embed = payload["embeds"][0]
    assert embed["color"] == 0xFF0000
    assert embed["author"] == {
        "name": "TDM 1",
        "icon_url": "https://example.test/me.png",
    }


def test_telegram_uses_display_name(
    dispatcher: NotificationDispatcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    dispatcher.bind(
        _FakeSettings(
            telegram_bot_token="123:ABC",
            telegram_chat_id="-1001",
            bot_name="TDM 1",
        )
    )
    calls = _capture(monkeypatch)
    dispatcher.send("channel_switch", "Switch", "now watching x")
    text = calls[0][1]["text"]
    assert "[TDM 1]" in text
    assert "now watching x" in text


def test_telegram_default_name_when_unset(
    dispatcher: NotificationDispatcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    dispatcher.bind(
        _FakeSettings(telegram_bot_token="123:ABC", telegram_chat_id="-1001")
    )
    calls = _capture(monkeypatch)
    dispatcher.send("channel_switch", "Switch", "body")
    assert f"[{DEFAULT_BOT_NAME}]" in calls[0][1]["text"]


# -- color parsing -------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("#ff0000", 0xFF0000),
        ("00ff00", 0x00FF00),
        ("0x0000ff", 0x0000FF),
        ("rgb(1, 2, 3)", 0x010203),
        ("#7d46ff", 0x7D46FF),
        ("abc", 0xAABBCC),  # 3-digit shorthand
    ],
)
def test_parse_discord_color(raw: str, expected: int) -> None:
    assert parse_discord_color(raw) == expected


def test_parse_discord_color_falls_back_on_garbage() -> None:
    assert parse_discord_color("not-a-color") == int(
        DEFAULT_EMBED_COLOR.lstrip("#"), 16
    )
    assert parse_discord_color("") == int(DEFAULT_EMBED_COLOR.lstrip("#"), 16)


def test_normalize_and_format_color() -> None:
    assert normalize_hex_color(" #AB12CD ") == "#ab12cd"
    assert normalize_hex_color("rgb(16, 32, 48)") == "#102030"
    assert normalize_hex_color("rgb(999, 0, 0)") is None
    assert normalize_hex_color("x") is None
    assert format_color("#7d46ff", "rgb") == "rgb(125, 70, 255)"
    assert format_color("#7d46ff", "hex") == "#7d46ff"
    assert format_color(None, "rgb") == "rgb(125, 70, 255)"


def test_bot_display_name_falls_back() -> None:
    assert bot_display_name(_FakeSettings()) == DEFAULT_BOT_NAME
    assert bot_display_name(_FakeSettings(bot_name="Miner 7")) == "Miner 7"
    assert bot_display_name(_FakeSettings(bot_name="   ")) == DEFAULT_BOT_NAME


def test_telegram_only(dispatcher: NotificationDispatcher, monkeypatch: pytest.MonkeyPatch) -> None:
    dispatcher.bind(
        _FakeSettings(telegram_bot_token="123:ABC", telegram_chat_id="-1001")
    )
    calls = _capture(monkeypatch)
    results = dispatcher.send("channel_switch", "Switch", "now watching x")
    assert set(results) == {"telegram"}
    url, payload = calls[0]
    assert url == "https://api.telegram.org/bot123:ABC/sendMessage"
    assert payload["chat_id"] == "-1001"
    assert "now watching x" in payload["text"]


def test_both_targets(
    dispatcher: NotificationDispatcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    dispatcher.bind(
        _FakeSettings(
            discord_webhook_url="https://example.test/hook",
            telegram_bot_token="123:ABC",
            telegram_chat_id="42",
        )
    )
    calls = _capture(monkeypatch)
    results = dispatcher.send("fatal_error", "Boom", "it broke")
    assert set(results) == {"discord", "telegram"}
    assert len(calls) == 2


def test_telegram_requires_both_token_and_chat(dispatcher: NotificationDispatcher) -> None:
    dispatcher.bind(_FakeSettings(telegram_bot_token="123:ABC"))
    assert dispatcher._telegram_configured() is False


# -- per-event toggles ---------------------------------------------------


def test_disabled_event_is_not_sent(
    dispatcher: NotificationDispatcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    dispatcher.bind(
        _FakeSettings(
            discord_webhook_url="https://example.test/hook",
            notify_drop_claimed=False,
        )
    )
    calls = _capture(monkeypatch)
    assert dispatcher.send("drop_claimed", "t", "b") == {}
    assert calls == []
    # ...but a different event still goes out.
    assert dispatcher.send("channel_switch", "t", "b") != {}


# -- truncation ----------------------------------------------------------


def test_long_body_is_truncated(
    dispatcher: NotificationDispatcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    dispatcher.bind(_FakeSettings(discord_webhook_url="https://example.test/hook"))
    calls = _capture(monkeypatch)
    dispatcher.send("drop_claimed", "T" * 100, "B" * 10000)
    _url, payload = calls[0]
    # Discord's own limits are 256 for a title and 4096 for a description.
    # We stay just inside both to leave room for the footer.
    assert len(payload["embeds"][0]["title"]) == 100
    assert len(payload["embeds"][0]["description"]) == 4000


# -- test button ---------------------------------------------------------


def test_test_dispatch_reports_missing_config(dispatcher: NotificationDispatcher) -> None:
    dispatcher.bind(_FakeSettings())
    ok, detail = dispatcher.test("discord")
    assert ok is False
    assert "webhook" in detail.lower()
    ok, detail = dispatcher.test("telegram")
    assert ok is False
    assert "telegram" in detail.lower()


def test_test_dispatch_reports_failure(
    dispatcher: NotificationDispatcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    dispatcher.bind(_FakeSettings(discord_webhook_url="https://example.test/hook"))
    monkeypatch.setattr(
        "webui.notifications._post_json",
        lambda url, payload: (False, "HTTP 400: bad webhook"),
    )
    ok, detail = dispatcher.test("discord")
    assert ok is False
    assert "400" in detail


# -- transport error handling -------------------------------------------


def test_http_error_is_captured_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    """The transport must convert HTTP failures into a result, not an exception."""

    def raise_http(request, timeout=None):  # type: ignore[no-untyped-def]
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(urllib.request, "urlopen", raise_http)
    dispatcher = NotificationDispatcher()
    dispatcher.bind(_FakeSettings(discord_webhook_url="https://example.test/hook"))
    results = dispatcher.send("drop_claimed", "t", "b")
    ok, detail = results["discord"]
    assert ok is False
    assert "401" in detail


def test_send_reports_failures_without_raising(
    dispatcher: NotificationDispatcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    dispatcher.bind(_FakeSettings(discord_webhook_url="https://example.test/hook"))
    monkeypatch.setattr(
        "webui.notifications._post_json",
        lambda url, payload: (False, "connection refused"),
    )
    # A dead webhook must not take the miner down.
    results = dispatcher.send("drop_claimed", "t", "b")
    assert results["discord"] == (False, "connection refused")


# -- module singleton ----------------------------------------------------


def test_singleton_is_a_dispatcher() -> None:
    assert isinstance(notifications, NotificationDispatcher)


# -- browser tab title ---------------------------------------------------


def test_effective_title_tracks_bot_name_by_default() -> None:
    settings = _FakeSettings()
    assert _effective_title(settings) == DEFAULT_BOT_NAME
    settings.bot_name = "Miner Prime"
    assert _effective_title(settings) == "Miner Prime"


def test_effective_title_uses_custom_when_pinned() -> None:
    settings = _FakeSettings(bot_name="Miner Prime")
    settings.custom_tab_title = True
    settings.tab_title = "  Front Desk  "
    assert _effective_title(settings) == "Front Desk"
    # A pinned-but-empty custom title falls back to the bot name.
    settings.tab_title = ""
    assert _effective_title(settings) == "Miner Prime"
    # Turning the pin off falls back too.
    settings.custom_tab_title = False
    assert _effective_title(settings) == "Miner Prime"
