"""Tests for webui.telegram_bot (command replies, no network)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from webui.telegram_bot import (
    COMMANDS,
    help_text,
    respond,
    status_reply,
    streams_reply,
)

CHAT_ID = "-1001234567890"


def _manager(summary: dict | None = None) -> SimpleNamespace:
    settings = SimpleNamespace(bot_name="")
    twitch = SimpleNamespace(settings=settings)
    return SimpleNamespace(
        _twitch=twitch,
        status_summary=lambda: summary or {},
        streams_summary=lambda: [],
    )


def _respond(message, manager, **kwargs) -> list[str]:
    return asyncio.run(respond(message, manager=manager, chat_id=CHAT_ID, **kwargs))


def test_help_contains_every_command() -> None:
    reply = help_text()
    for command, _summary in COMMANDS:
        assert command in reply
    assert reply.startswith("*[Twitch Drops Miner]")


def test_start_and_help_show_the_menu() -> None:
    manager = _manager()
    for command in ("/start", "/help"):
        replies = _respond({"chat": {"id": CHAT_ID}, "text": command}, manager)
        assert replies == [help_text()]
        assert "Available commands" in replies[0]


def test_status_reply_renders_snapshot() -> None:
    manager = _manager(
        {
            "logged_in": True,
            "user_id": 12345,
            "status": "Watching...",
            "channels": 3,
            "watching": True,
        }
    )
    replies = _respond({"chat": {"id": CHAT_ID}, "text": "/status"}, manager)
    assert len(replies) == 1
    text = replies[0]
    assert "Login: yes" in text and "user 12345" in text
    assert "Channels tracked: 3" in text and "Watching: yes" in text


def test_status_logged_out_gets_login_hint() -> None:
    text = status_reply(
        {"logged_in": False, "status": "LOGGED_OUT", "channels": 0, "watching": False}
    )
    assert "Login: no" in text
    assert "Log in" in text


def test_test_command_uses_provided_delivery() -> None:
    manager = _manager()

    async def ok_delivery(target: str) -> tuple[bool, str]:
        return True, "HTTP 200"

    replies = _respond(
        {"chat": {"id": CHAT_ID}, "text": "/test"}, manager, send_test=ok_delivery
    )
    assert replies == ["Test notification sent."]

    async def fail_delivery(target: str) -> tuple[bool, str]:
        return False, "HTTP 401"

    replies = _respond(
        {"chat": {"id": CHAT_ID}, "text": "/test"}, manager, send_test=fail_delivery
    )
    assert replies == ["Test failed: HTTP 401"]


def test_testdiscord_targets_the_discord_channel() -> None:
    manager = _manager()
    targets: list[str] = []

    async def delivery(target: str) -> tuple[bool, str]:
        targets.append(target)
        return True, "HTTP 200"

    replies = _respond(
        {"chat": {"id": CHAT_ID}, "text": "/testdiscord"}, manager, send_test=delivery
    )
    assert replies == ["Test Discord notification sent."]
    assert targets == ["discord"]

    async def fail_delivery(target: str) -> tuple[bool, str]:
        return False, "HTTP 404"

    replies = _respond(
        {"chat": {"id": CHAT_ID}, "text": "/testdiscord"}, manager,
        send_test=fail_delivery,
    )
    assert replies == ["Test failed: HTTP 404"]


def test_watch_command_switches_on_found_stream() -> None:
    manager = _manager()

    async def good_watch(login: str) -> tuple[bool, str]:
        assert login == "xqc"
        return True, ""

    replies = _respond(
        {"chat": {"id": CHAT_ID}, "text": "/watch xqc"}, manager, watch=good_watch
    )
    assert replies == ["Switching to *xqc*..."]


def test_watch_command_reports_failure_reason() -> None:
    manager = _manager()

    async def bad_watch(login: str) -> tuple[bool, str]:
        return False, "Unknown stream 'xqc'."

    replies = _respond(
        {"chat": {"id": CHAT_ID}, "text": "/watch xqc"}, manager, watch=bad_watch
    )
    assert replies == ["Unknown stream 'xqc'."]


def test_watch_command_shows_usage_when_stream_missing() -> None:
    for message in ("/watch", "/watch  "):
        replies = _respond({"chat": {"id": CHAT_ID}, "text": message}, _manager())
        assert any("Usage:" in r for r in replies)


def test_watch_without_backend_is_graceful() -> None:
    replies = _respond({"chat": {"id": CHAT_ID}, "text": "/watch xqc"}, _manager())
    assert replies and "unavailable" in replies[0]


def test_status_reply_shows_terminated_reason() -> None:
    text = status_reply(
        {
            "logged_in": False,
            "status": "Fatal error - check the WebUI console",
            "terminated": True,
            "channels": 2,
            "watching": False,
        }
    )
    assert "Fatal error - check the WebUI console" in text
    assert "Watching: no" in text


def test_streams_command_lists_rows() -> None:
    manager = _manager()
    manager.streams_summary = lambda: [
        {
            "login": "xqc",
            "display": "xQc",
            "online": True,
            "viewers": 45123,
            "game": "Just Chatting",
            "drops": True,
        },
        {
            "login": "shroud",
            "display": "shroud",
            "online": False,
            "viewers": None,
            "game": None,
            "drops": False,
        },
    ]
    replies = _respond({"chat": {"id": CHAT_ID}, "text": "/streams"}, manager)
    assert len(replies) == 1
    text = replies[0]
    assert "xQc" in text and "ONLINE" in text and "drops: YES" in text
    assert "45.1k viewers" in text and "Just Chatting" in text
    assert "`/watch xqc`" in text
    assert "shroud" in text and "offline" in text and "drops: no" in text


def test_streams_reply_empty_state() -> None:
    text = streams_reply([])
    assert "None tracked yet" in text


def test_streams_reply_truncates_and_notes_limit() -> None:
    rows = [
        {
            "login": f"s{i}",
            "display": f"s{i}",
            "online": True,
            "viewers": 1000,
            "game": "G",
            "drops": True,
        }
        for i in range(25)
    ]
    text = streams_reply(rows)
    assert "…and 5 more" in text
    assert "Only streamers of your added games" in text


def test_unknown_command_hints_at_help() -> None:
    replies = _respond({"chat": {"id": CHAT_ID}, "text": "/nope"}, _manager())
    assert any("/help" in r for r in replies)


def test_foreign_chat_is_ignored() -> None:
    replies = _respond(
        {"chat": {"id": "someone-else"}, "text": "/help"}, _manager()
    )
    assert replies == []


def test_non_command_messages_are_ignored() -> None:
    replies = _respond({"chat": {"id": CHAT_ID}, "text": "hello"}, _manager())
    assert replies == []


def test_test_without_delivery_is_graceful() -> None:
    replies = _respond({"chat": {"id": CHAT_ID}, "text": "/test"}, _manager())
    assert replies and "not available" in replies[0]


def test_poller_start_is_a_noop_without_event_loop() -> None:
    """start() must not create a task when no loop is running (unit-test env)."""
    from webui.telegram_bot import TelegramCommandPoller

    poller = TelegramCommandPoller(_manager())
    poller.start()
    assert poller._task is None or poller._task.done()