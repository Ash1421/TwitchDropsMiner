"""
Tests for campaign-scoped badge ownership and the legacy game-keyed migration.

Badge benefits are game-level on Twitch, but the user's assertion belongs to a
campaign: a single game can host several unrelated badge campaigns, and
asserting "I own this game's badges" would claim all of them.
"""

from __future__ import annotations

import pytest

from webui.badges import BadgeOwnership, BadgeRegistry, badge_benefits


class _BenefitType:
    def is_badge_or_emote(self) -> bool:
        return True


class _Benefit:
    def __init__(self, bid: str) -> None:
        self.id = bid
        self.type = _BenefitType()


class _Game:
    def __init__(self, name: str) -> None:
        self.name = name


class _Drop:
    def __init__(self, benefits: list[str]) -> None:
        self.benefits = [_Benefit(b) for b in benefits]


class _Campaign:
    """Minimal stand-in for DropsCampaign: ID, game, and badge benefits."""

    def __init__(self, cid: str, game: str, benefits: list[str]) -> None:
        self.id = cid
        self.game = _Game(game)
        self.name = f"{game} badge campaign"
        # badge_benefits() walks campaign.drops, matching upstream's shape.
        self.drops = [_Drop(benefits)] if benefits else []


@pytest.fixture
def registry() -> BadgeRegistry:
    return BadgeRegistry()


def test_no_benefits_is_not_applicable(registry: BadgeRegistry) -> None:
    campaign = _Campaign("c1", "Chess", [])
    assert registry.owns_campaign(campaign) is BadgeOwnership.NOT_APPLICABLE


def test_no_claim_edges_is_unknown(registry: BadgeRegistry) -> None:
    campaign = _Campaign("c1", "Chess", ["b1", "b2"])
    assert registry.owns_campaign(campaign) is BadgeOwnership.UNKNOWN


def test_all_claimed_benefits_is_owned(registry: BadgeRegistry) -> None:
    campaign = _Campaign("c1", "Chess", ["b1", "b2"])
    registry.observe_claimed_benefits({"b1": object(), "b2": object()})  # type: ignore[dict-item]
    assert registry.owns_campaign(campaign) is BadgeOwnership.OWNED


def test_some_claimed_benefits_is_partial(registry: BadgeRegistry) -> None:
    campaign = _Campaign("c1", "Chess", ["b1", "b2"])
    registry.observe_claimed_benefits({"b1": object()})  # type: ignore[dict-item]
    assert registry.owns_campaign(campaign) is BadgeOwnership.PARTIAL


def test_manual_campaign_id_overrides_unknown(registry: BadgeRegistry) -> None:
    campaign = _Campaign("c1", "Chess", ["b1"])
    verdict = registry.owns_campaign(campaign, manual_campaign_ids={"c1"})
    assert verdict is BadgeOwnership.OWNED


def test_manual_campaign_id_does_not_match_other_campaigns(
    registry: BadgeRegistry,
) -> None:
    campaign = _Campaign("c1", "Chess", ["b1"])
    verdict = registry.owns_campaign(campaign, manual_campaign_ids={"c-other"})
    assert verdict is BadgeOwnership.UNKNOWN


def test_manual_game_list_still_works(registry: BadgeRegistry) -> None:
    """Configurations written before the campaign-scoped switch keep working."""
    campaign = _Campaign("c1", "Chess", ["b1"])
    verdict = registry.owns_campaign(campaign, manual_games={"Chess"})
    assert verdict is BadgeOwnership.OWNED


def test_campaign_ids_are_scoped_per_campaign(registry: BadgeRegistry) -> None:
    """
    Two badge campaigns under one game must be independently assertable.

    This is the reason the manual list is keyed by campaign: a game-level list
    would mark both as owned when the user only owns one.
    """
    first = _Campaign("c1", "Chess", ["b1"])
    second = _Campaign("c2", "Chess", ["b2"])
    assert registry.owns_campaign(first, manual_campaign_ids={"c1"}) is (
        BadgeOwnership.OWNED
    )
    assert registry.owns_campaign(second, manual_campaign_ids={"c1"}) is (
        BadgeOwnership.UNKNOWN
    )


def test_observe_claimed_benefits_accumulates() -> None:
    """
    Observed IDs accumulate rather than being replaced.

    observe_claimed_benefits is called once per campaign constructor with the
    same full mapping, and a campaign with no claims must not wipe what other
    campaigns already reported.
    """
    reg = BadgeRegistry()
    reg.observe_claimed_benefits({"b1": object()})  # type: ignore[dict-item]
    reg.observe_claimed_benefits({"b2": object()})  # type: ignore[dict-item]
    reg.observe_claimed_benefits({})
    assert reg.claimed_benefit_ids == frozenset({"b1", "b2"})


def test_clear_resets_observed_state() -> None:
    reg = BadgeRegistry()
    reg.observe_claimed_benefits({"b1": object()})  # type: ignore[dict-item]
    reg.clear()
    assert reg.claimed_benefit_ids == frozenset()


def test_badge_benefits_filters_non_badge(registry: BadgeRegistry) -> None:
    campaign = _Campaign("c1", "Chess", ["b1"])
    assert [b.id for b in badge_benefits(campaign)] == ["b1"]
