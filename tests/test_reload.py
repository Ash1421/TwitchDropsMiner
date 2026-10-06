from __future__ import annotations

from types import SimpleNamespace

from constants import State
from webui.manager import WebUIManager


class _FakeTwitch:
    def __init__(self, state: State = State.IDLE) -> None:
        self._state = state
        self.calls: list[State] = []

    def state_change(self, state: State):
        def _call() -> None:
            self.calls.append(state)
        return _call


def _manager(state: State = State.IDLE) -> WebUIManager:
    manager = object.__new__(WebUIManager)
    manager._twitch = _FakeTwitch(state)
    manager._reload_requested = SimpleNamespace(set=lambda: None)
    return manager


def test_request_reload_queues_inventory_fetch() -> None:
    manager = _manager(State.IDLE)
    assert manager.request_reload() is True
    assert manager._twitch.calls == [State.INVENTORY_FETCH]


def test_request_reload_returns_false_when_exiting() -> None:
    manager = _manager(State.EXIT)
    assert manager.request_reload() is False
    assert manager._twitch.calls == []
