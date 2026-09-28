"""Tests for the WebUI eligibility patches in webui/patches.py.

``patches.py`` wraps ``DropsCampaign.eligible`` with two opt-in overrides:

* ``priority_link_override``  - mine *unlinked* games that are on the Priority List
* ``priority_badge_override`` - mine *badge/emote* games that are on the Priority List

Upstream ``eligible`` returns ``enable_badges_emotes`` for badge/emote campaigns
and the account-link state otherwise, so these tests pin down the combination
matrix for both overrides.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import inventory
import webui.patches  # noqa: F401  - applies the patches under test

_DropsCampaign = inventory.DropsCampaign


class FakeCampaign:
    """Minimal stand-in exposing only what the patched properties touch."""

    # Borrow the real patched properties so we test the shipped logic.
    priority_link_override = _DropsCampaign.priority_link_override
    priority_badge_override = _DropsCampaign.priority_badge_override
    eligible = _DropsCampaign.eligible

    def __init__(
        self,
        *,
        game: str,
        linked: bool = True,
        has_badge_or_emote: bool = False,
        enable_badges_emotes: bool = False,
        priority: list[str] | None = None,
        priority_link_override: bool = False,
        priority_badge_override: bool = False,
    ) -> None:
        self.game = SimpleNamespace(name=game)
        self.linked = linked
        self.has_badge_or_emote = has_badge_or_emote
        self._twitch = SimpleNamespace(
            settings=SimpleNamespace(
                enable_badges_emotes=enable_badges_emotes,
                priority=priority or [],
                priority_link_override=priority_link_override,
                priority_badge_override=priority_badge_override,
            )
        )


def test_patch_registers_new_settings_defaults() -> None:
    """Both overrides must exist as settings keys, or __getattr__ raises."""
    import settings

    assert settings.default_settings["priority_link_override"] is False
    assert settings.default_settings["priority_badge_override"] is False
    assert settings.default_settings["owned_badge_games"] == set()
    assert settings.default_settings["theme"] == "dark"


def test_patches_imported_before_settings_construction() -> None:
    """
    Guard the import order that every fork-injected setting depends on.

    ``Settings.__setattr__`` raises TypeError for any key absent from the loaded
    settings dict, and that dict is seeded from ``default_settings`` at
    construction time. So ``webui.patches`` must be imported before
    ``Settings(...)`` runs, or every new setting becomes unsettable at runtime.
    """
    from pathlib import Path

    source = (Path(__file__).resolve().parent.parent / "main_webui.py").read_text(
        encoding="utf-8"
    )
    patch_at = source.index("import webui.patches")
    settings_at = source.index("Settings(args)")
    assert patch_at < settings_at, (
        "webui.patches must be imported before Settings() is constructed, "
        "otherwise injected settings keys become unsettable"
    )


def test_badge_campaign_blocked_by_default() -> None:
    """Default config must not mine badge campaigns, even on the priority list."""
    campaign = FakeCampaign(game="Rust", linked=False, has_badge_or_emote=True)
    assert campaign.eligible is False


def test_badge_campaign_allowed_via_badge_override_on_priority_list() -> None:
    """The badge override should admit a badge game that is on the Priority List."""
    campaign = FakeCampaign(
        game="Rust",
        linked=False,
        has_badge_or_emote=True,
        priority=["Rust", "Dota 2"],
        priority_badge_override=True,
    )
    assert campaign.priority_badge_override is True
    assert campaign.eligible is True


def test_badge_override_ignores_games_off_the_priority_list() -> None:
    """The badge override must stay scoped to the Priority List."""
    campaign = FakeCampaign(
        game="Rust",
        linked=False,
        has_badge_or_emote=True,
        priority=["Dota 2"],
        priority_badge_override=True,
    )
    assert campaign.priority_badge_override is False
    assert campaign.eligible is False


def test_link_override_does_not_admit_badge_campaigns() -> None:
    """priority_link_override must keep its non-badge restriction.

    The property itself only reports link state plus Priority List membership,
    so it can legitimately be True here. The badge guard lives in the patched
    ``eligible``, which is what must stay False.
    """
    campaign = FakeCampaign(
        game="Rust",
        linked=False,
        has_badge_or_emote=True,
        priority=["Rust"],
        priority_link_override=True,
    )
    assert campaign.eligible is False


def test_link_override_still_works_for_plain_unlinked_games() -> None:
    """Regression guard: existing behaviour must be untouched."""
    campaign = FakeCampaign(
        game="Rust",
        linked=False,
        has_badge_or_emote=False,
        priority=["Rust"],
        priority_link_override=True,
    )
    assert campaign.priority_link_override is True
    assert campaign.eligible is True


def test_badge_override_does_not_bypass_linked_for_plain_games() -> None:
    """The badge override must not admit unlinked non-badge campaigns."""
    campaign = FakeCampaign(
        game="Rust",
        linked=False,
        has_badge_or_emote=False,
        priority=["Rust"],
        priority_badge_override=True,
    )
    assert campaign.eligible is False


def test_upstream_badges_emotes_switch_still_wins() -> None:
    """The broad upstream switch must keep admitting every badge campaign."""
    campaign = FakeCampaign(
        game="Rust", linked=False, has_badge_or_emote=True, enable_badges_emotes=True
    )
    assert campaign.eligible is True


@pytest.mark.parametrize("badge_override", [False, True])
@pytest.mark.parametrize("link_override", [False, True])
def test_linked_campaign_is_always_eligible(link_override, badge_override) -> None:
    """A linked campaign needs no override at all."""
    campaign = FakeCampaign(
        game="Rust",
        linked=True,
        has_badge_or_emote=False,
        priority_link_override=link_override,
        priority_badge_override=badge_override,
    )
    assert campaign.eligible is True
