"""
Badge/emote ownership tracking for the WebUI fork.

Upstream decides badge-campaign eligibility from a single global switch
(``enable_badges_emotes``), because a badge drop can only be paid out when the
account already owns the badge being awarded. That switch is all-or-nothing: on
means watching campaigns whose badges you may not have, off means never
touching them.

This module answers a narrower question per campaign: *do we believe this
account owns the badge or emote this campaign requires?* Signals are layered
from cheapest to most expensive:

1. ``claimed_benefits`` - Twitch's inventory payload lists every benefit edge the
   account has ever been awarded. If a campaign's badge benefit ID appears there,
   the account owns it. This costs nothing extra; the miner already fetches it.
2. The manual "Badges I own" list - a user-declared escape hatch for badges
   granted outside the drops system (events, purchases, sub renewals).

A future signal - the ``currentUser.availableBadges`` GraphQL query - slots in
here without changing any caller.

Every lookup returns one of three states rather than a bool, so the UI can tell
the difference between "confirmed", "partially confirmed" and "we have no idea"
instead of silently treating unknown as false.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from inventory import DropsCampaign

_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")


class BadgeOwnership(Enum):
    """What we know about whether an account owns a campaign's badge/emote."""

    NOT_APPLICABLE = "NOT_APPLICABLE"
    OWNED = "OWNED"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"


def normalize_title(value: str) -> str:
    """Case- and punctuation-insensitive key for badge title matching."""
    return _NORMALIZE_RE.sub("", value.strip().lower())


def badge_benefits(campaign: "DropsCampaign") -> list[Any]:
    """Every badge/emote Benefit attached to *campaign*."""
    return [
        benefit
        for drop in campaign.drops
        for benefit in drop.benefits
        if benefit.type.is_badge_or_emote()
    ]


class BadgeRegistry:
    """Process-wide record of which badge benefits the account is known to own."""

    def __init__(self) -> None:
        self._claimed_benefit_ids: set[str] = set()

    def observe_claimed_benefits(self, claimed_benefits: dict[str, Any]) -> None:
        """
        Record benefit IDs from an inventory fetch.

        Called from a ``DropsCampaign.__init__`` wrapper, because
        ``Twitch.fetch_inventory`` builds this mapping as a local variable and
        only hands it to campaign constructors.
        """
        if claimed_benefits:
            self._claimed_benefit_ids.update(claimed_benefits.keys())

    def clear(self) -> None:
        """Drop all observed state. Used on logout so a new account starts clean."""
        self._claimed_benefit_ids.clear()

    @property
    def claimed_benefit_ids(self) -> frozenset[str]:
        return frozenset(self._claimed_benefit_ids)

    def owns_campaign(
        self, campaign: "DropsCampaign", manual_games: set[str] | None = None
    ) -> BadgeOwnership:
        """
        Best-effort ownership verdict for *campaign*.

        The manual list wins outright, because the user asserting they own a
        badge is more authoritative than any lookup we can perform.
        """
        benefits = badge_benefits(campaign)
        if not benefits:
            return BadgeOwnership.NOT_APPLICABLE
        if manual_games and campaign.game.name in manual_games:
            return BadgeOwnership.OWNED
        owned = [b for b in benefits if b.id in self._claimed_benefit_ids]
        if not owned:
            return BadgeOwnership.UNKNOWN
        if len(owned) == len(benefits):
            return BadgeOwnership.OWNED
        return BadgeOwnership.PARTIAL


registry = BadgeRegistry()
