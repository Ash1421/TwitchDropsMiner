"""Tests for WebUIManager integration helpers (status/watch/streams/terminated)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from webui.manager import WebUIManager


class _FakeAuth:
    def __init__(self) -> None:
        self._logged_in = asyncio.Event()
        self.user_id = None


class _FakeTwitch:
    def __init__(self, channels=None) -> None:
        self._auth_state = _FakeAuth()
        self.channels = channels or {}
        self._watching_task = None
        self._state_count = 0

    def state_change(self, state):
        def trigger():
            self._state_count += 1

        return trigger


def _manager(channels=None, *, terminated: str | None = None) -> WebUIManager:
    manager = object.__new__(WebUIManager)
    manager._twitch = _FakeTwitch(channels)
    manager._status_text = "Fetching inventory..."
    manager._terminated_reason = terminated
    manager.main_panel = SimpleNamespace(select_channel=lambda channel: None)
    return manager


def test_status_summary_is_plain_when_running() -> None:
    summary = _manager({"1": SimpleNamespace()}).status_summary()
    assert summary["status"] == "Fetching inventory..."
    assert summary["terminated"] is False
    assert summary["logged_in"] is False
    assert summary["channels"] == 1
    assert summary["watching"] is False


def test_status_summary_overrides_stale_text_when_terminated() -> None:
    summary = _manager(
        {"1": SimpleNamespace()}, terminated="Fatal error - check the WebUI console"
    ).status_summary()
    assert summary["status"] == "Fatal error - check the WebUI console"
    assert summary["terminated"] is True


def test_mark_terminated_sets_reason() -> None:
    manager = _manager()
    assert manager._terminated_reason is None
    manager.mark_terminated("Fatal error - check the WebUI console")
    assert manager._terminated_reason == "Fatal error - check the WebUI console"
    assert manager.status_summary()["terminated"] is True


def test_mark_terminated_defaults_for_empty_reason() -> None:
    manager = _manager()
    manager.mark_terminated("")
    assert manager._terminated_reason == "Terminated"


async def _run_watch(manager: WebUIManager, login: str):
    return await manager.watch_channel(login)


def test_watch_channel_selects_and_triggers_switch() -> None:
    channels = {"1": SimpleNamespace(name="Xqc", iid="1")}
    manager = _manager(channels)
    selected: list[str] = []
    manager.main_panel = SimpleNamespace(select_channel=lambda channel: selected.append(channel.name))

    ok, detail = asyncio.run(_run_watch(manager, "xqc"))
    assert ok and detail == ""
    assert selected == ["Xqc"]
    assert manager._twitch._state_count == 1


def test_watch_channel_is_ignored_when_terminated() -> None:
    manager = _manager(
        {"1": SimpleNamespace(name="Xqc", iid="1")},
        terminated="Fatal error - check the WebUI console",
    )
    ok, detail = asyncio.run(_run_watch(manager, "xqc"))
    assert ok is False
    assert "not running" in detail
    assert manager._twitch._state_count == 0


def test_watch_channel_rejects_unknown_stream() -> None:
    manager = _manager({"1": SimpleNamespace(name="Xqc", iid="1")})
    ok, detail = asyncio.run(_run_watch(manager, "nobody"))
    assert ok is False
    assert "Unknown stream 'nobody'" in detail


def test_watch_channel_rejects_blank_stream() -> None:
    manager = _manager({"1": SimpleNamespace(name="Xqc", iid="1")})
    ok, detail = asyncio.run(_run_watch(manager, "  "))
    assert ok is False
    assert "No stream given." in detail


def test_streams_summary_lists_tracked_channels() -> None:
    game = SimpleNamespace(name="Just Chatting")
    channels = {
        "1": SimpleNamespace(
            _login="xqc",
            name="xQc",
            online=True,
            viewers=45123,
            game=game,
            drops_enabled=True,
        ),
        "2": SimpleNamespace(
            _login="shroud",
            name="shroud",
            online=False,
            viewers=None,
            game=None,
            drops_enabled=False,
        ),
    }
    rows = _manager(channels).streams_summary()
    assert [row["login"] for row in rows] == ["xqc", "shroud"]
    assert rows[0]["online"] is True and rows[0]["viewers"] == 45123
    assert rows[0]["drops"] is True and rows[0]["game"] == "Just Chatting"
    assert rows[1]["display"] == "shroud"


def test_streams_summary_sorts_online_eligible_first() -> None:
    channels = {
        "1": SimpleNamespace(
            _login="a",
            name="A",
            online=True,
            viewers=None,
            game=None,
            drops_enabled=False,
        ),
        "2": SimpleNamespace(
            _login="b",
            name="B",
            online=False,
            viewers=None,
            game=None,
            drops_enabled=True,
        ),
        "3": SimpleNamespace(
            _login="c",
            name="C",
            online=True,
            viewers=None,
            game=None,
            drops_enabled=True,
        ),
    }
    rows = _manager(channels).streams_summary()
    assert [row["login"] for row in rows] == ["c", "a", "b"]
