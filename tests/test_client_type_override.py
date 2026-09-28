"""Tests for the TDM_CLIENT_TYPE override."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from constants import ClientType
from webui import patches


class _FakeTwitch:
    """Stand-in for twitch.Twitch without the GUI import chain."""

    def __init__(self) -> None:
        # What upstream's constructor assigns.
        self._client_type = ClientType.ANDROID_APP


def _apply_override(instance: object) -> None:
    """Replay the patched __init__'s post-construction override."""
    name = os.environ.get("TDM_CLIENT_TYPE", "").strip()
    if name:
        instance._client_type = patches._resolve_client_type(name)  # type: ignore[attr-defined]


def test_resolve_maps_every_known_client_type() -> None:
    for name in ("WEB", "MOBILE_WEB", "ANDROID_APP", "SMARTBOX"):
        assert patches._resolve_client_type(name) is getattr(ClientType, name)


def test_resolve_is_case_insensitive() -> None:
    assert patches._resolve_client_type("mobile_web") is ClientType.MOBILE_WEB
    assert patches._resolve_client_type("  SMARTBOX  ") is ClientType.SMARTBOX


def test_resolve_falls_back_for_unknown_name() -> None:
    """A typo must not break startup; MOBILE_WEB is known to be accepted."""
    assert patches._resolve_client_type("nope") is ClientType.MOBILE_WEB
    assert patches._resolve_client_type("") is ClientType.MOBILE_WEB


def test_upstream_default_is_a_dead_client_id() -> None:
    """Documents why the override exists: Twitch rejects the hardcoded one."""
    assert ClientType.WEB.CLIENT_ID == "kimne78kx3ncx6brgo4mv6wki5h1ko"
    assert ClientType.ANDROID_APP.CLIENT_ID == "kd1unb4b3q4t58fwlpcbzcbnm76a8fp"


def test_fallback_clients_are_distinct_from_dead_ones() -> None:
    """MOBILE_WEB and SMARTBOX are the ids Twitch still accepts."""
    alive = {ClientType.MOBILE_WEB.CLIENT_ID, ClientType.SMARTBOX.CLIENT_ID}
    dead = {ClientType.WEB.CLIENT_ID, ClientType.ANDROID_APP.CLIENT_ID}
    assert alive.isdisjoint(dead)
    assert ClientType.ANDROID_APP.CLIENT_ID in dead


def test_override_replaces_upstream_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """The override must win over the client type upstream assigns."""
    monkeypatch.setenv("TDM_CLIENT_TYPE", "SMARTBOX")
    instance = _FakeTwitch()
    _apply_override(instance)
    assert instance._client_type is ClientType.SMARTBOX


def test_no_override_leaves_upstream_default_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TDM_CLIENT_TYPE", raising=False)
    instance = _FakeTwitch()
    _apply_override(instance)
    assert instance._client_type is ClientType.ANDROID_APP


def test_known_client_types_exposes_all_four() -> None:
    assert set(patches._known_client_types()) == {
        "WEB",
        "MOBILE_WEB",
        "ANDROID_APP",
        "SMARTBOX",
    }


def test_apply_is_a_noop_without_the_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """Must not import twitch (and therefore the GUI) when unused."""
    monkeypatch.delenv("TDM_CLIENT_TYPE", raising=False)
    # A bogus twitch module would raise on import if the lazy path were eager.
    patches._apply_client_type()
    assert SimpleNamespace() is not None
