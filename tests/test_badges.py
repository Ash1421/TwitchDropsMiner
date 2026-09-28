"""Tests for webui/badges.py - badge/emote ownership tracking.

Covers the three ownership states and the DropsCampaign.__init__ wrapper in
webui/patches.py that captures Twitch's claimed-benefit map.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import inventory
import webui.patches  # noqa: F401  - applies the patches under test
from inventory import BenefitType
from webui.badges import BadgeOwnership, BadgeRegistry, normalize_title

_CAMPAIGN_DATA = {
    "id": "campaign-1",
    "name": "Test campaign",
    "game": {"id": "1", "displayName": "Rust", "boxArtURL": "https://x/game-285x380.jpg"},
    "self": {"isAccountConnected": True},
    "accountLinkURL": "https://x/link",
    "allow": {"isEnabled": False, "channels": []},
    "startAt": "2024-01-01T00:00:00Z",
    "endAt": "2030-01-01T00:00:00Z",
    "status": "ACTIVE",
    "timeBasedDrops": [
        {
            "id": "drop-1",
            "name": "Drop 1",
            "startAt": "2024-01-01T00:00:00Z",
            "endAt": "2030-01-01T00:00:00Z",
            "requiredMinutesWatched": 60,
            "preconditionDrops": [],
            "benefitEdges": [
                {
                    "benefit": {
                        "id": "benefit-badge-1",
                        "name": "Rust Prime",
                        "distributionType": "BADGE",
                        "imageAssetURL": "https://x/badge.png",
                    }
                }
            ],
        }
    ],
}

_TWITCH = SimpleNamespace(
    settings=SimpleNamespace(
        enable_badges_emotes=False,
        priority=[],
        priority_link_override=False,
        priority_badge_override=False,
        owned_badge_games=set(),
    )
)


def _campaign(data=None):
    return inventory.DropsCampaign(
        _TWITCH, json.loads(json.dumps(data or _CAMPAIGN_DATA)), {}
    )


@pytest.fixture(autouse=True)
def _clean_registry():
    from webui import badges

    badges.registry.clear()
    yield
    badges.registry.clear()


def test_normalize_title_strips_case_and_punctuation() -> None:
    assert normalize_title("Rust Prime") == normalize_title("rust-prime")
    assert normalize_title("  Rust  Prime!  ") == "rustprime"


def test_owns_campaign_reports_owned_from_claimed_benefits() -> None:
    registry = BadgeRegistry()
    registry.observe_claimed_benefits({"benefit-badge-1": datetime.now(timezone.utc)})
    assert registry.owns_campaign(_campaign()) is BadgeOwnership.OWNED


def test_owns_campaign_reports_unknown_without_signals() -> None:
    registry = BadgeRegistry()
    assert registry.owns_campaign(_campaign()) is BadgeOwnership.UNKNOWN


def test_owns_campaign_honours_manual_list() -> None:
    registry = BadgeRegistry()
    assert (
        registry.owns_campaign(_campaign(), manual_games={"Rust"}) is BadgeOwnership.OWNED
    )


def test_manual_list_does_not_apply_to_other_games() -> None:
    registry = BadgeRegistry()
    assert (
        registry.owns_campaign(_campaign(), manual_games={"Dota 2"})
        is BadgeOwnership.UNKNOWN
    )


def test_non_badge_campaign_is_not_applicable() -> None:
    data = json.loads(json.dumps(_CAMPAIGN_DATA))
    data["timeBasedDrops"][0]["benefitEdges"][0]["benefit"]["distributionType"] = "DIRECT_ENTITLEMENT"
    registry = BadgeRegistry()
    assert registry.owns_campaign(_campaign(data)) is BadgeOwnership.NOT_APPLICABLE


def test_registry_records_multiple_observed_maps() -> None:
    registry = BadgeRegistry()
    registry.observe_claimed_benefits({"a": datetime.now(timezone.utc)})
    registry.observe_claimed_benefits({"b": datetime.now(timezone.utc)})
    assert registry.claimed_benefit_ids == frozenset({"a", "b"})


def test_observe_ignores_empty_map() -> None:
    registry = BadgeRegistry()
    registry.observe_claimed_benefits({})
    assert registry.claimed_benefit_ids == frozenset()


def test_campaign_init_populates_registry() -> None:
    """The __init__ wrapper must capture claimed_benefits handed to campaigns."""
    from webui import badges

    campaign = _campaign()
    inventory.DropsCampaign(
        _TWITCH,
        json.loads(json.dumps(_CAMPAIGN_DATA)),
        {"benefit-badge-1": datetime.now(timezone.utc)},
    )
    assert "benefit-badge-1" in badges.registry.claimed_benefit_ids
    assert badges.registry.owns_campaign(campaign) is BadgeOwnership.OWNED


def test_badge_ownership_property_is_wired_onto_campaigns() -> None:
    from webui import badges

    badges.registry.observe_claimed_benefits({"benefit-badge-1": datetime.now(timezone.utc)})
    assert _campaign().badge_ownership is BadgeOwnership.OWNED


def test_campaign_init_still_builds_drops_normally() -> None:
    """Regression guard: wrapping __init__ must not disturb construction."""
    campaign = _campaign()
    assert campaign.id == "campaign-1"
    assert campaign.game.name == "Rust"
    assert campaign.has_badge_or_emote is True
    drops = list(campaign.drops)
    assert len(drops) == 1
    assert drops[0].benefits[0].type is BenefitType.BADGE
