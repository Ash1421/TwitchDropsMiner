"""
WebUI-only monkey-patches that extend core classes without editing them.

Imported once from ``main_webui.py`` after the core modules are loaded, so the
fork keeps its diff against upstream minimal.
"""

from __future__ import annotations

import os

import settings as _settings
import inventory as _inventory
from constants import ClientType as _ClientType

import webui.translations  # noqa
from webui.badges import BadgeOwnership, registry as _badge_registry
from webui.notifications import DEFAULT_AVATAR_URL

_settings.default_settings["priority_link_override"] = False  # type: ignore[typeddict-unknown-key]
_settings.default_settings["priority_badge_override"] = False  # type: ignore[typeddict-unknown-key]
_settings.default_settings["owned_badge_games"] = set()  # type: ignore[typeddict-unknown-key]
_settings.default_settings["owned_badge_campaigns"] = set()  # type: ignore[typeddict-unknown-key]
_settings.default_settings["theme"] = "dark"  # type: ignore[typeddict-unknown-key]

# The browser tab title normally follows the bot name; the optional custom
# value decouples the tab name from the webhook identity.
_settings.default_settings["custom_tab_title"] = False  # type: ignore[typeddict-unknown-key]
_settings.default_settings["tab_title"] = ""  # type: ignore[typeddict-unknown-key]

# Display identity: the browser tab/name shown on outgoing notifications. An
# empty bot name falls back to the packaged default; the embed tint starts as
# the app's signature purple so messages match the rest of the UI out of the
# box. The avatar default is the official pickaxe icon, hosted on this fork's
# GitHub blob so Discord can fetch it once the branch is public.
_settings.default_settings["bot_name"] = ""  # type: ignore[typeddict-unknown-key]
_settings.default_settings["webhook_avatar"] = DEFAULT_AVATAR_URL  # type: ignore[typeddict-unknown-key]
_settings.default_settings["embed_color"] = "#7d46ff"  # type: ignore[typeddict-unknown-key]

# Notification settings. Secrets default to empty so nothing is sent until the
# user supplies a target; the per-event toggles default to on so adding a
# webhook starts delivering without a second trip through the UI.
_settings.default_settings["discord_webhook_url"] = ""  # type: ignore[typeddict-unknown-key]
_settings.default_settings["telegram_bot_token"] = ""  # type: ignore[typeddict-unknown-key]
_settings.default_settings["telegram_chat_id"] = ""  # type: ignore[typeddict-unknown-key]
for _event in ("drop_claimed", "campaign_complete", "channel_switch", "fatal_error"):
    _settings.default_settings[f"notify_{_event}"] = True  # type: ignore[typeddict-unknown-key]


def _known_client_types() -> dict[str, object]:
    return {
        name: getattr(_ClientType, name)
        for name in ("WEB", "MOBILE_WEB", "ANDROID_APP", "SMARTBOX")
    }


def _resolve_client_type(name: str) -> object:
    """
    Look up a client type by name, falling back to MOBILE_WEB.

    MOBILE_WEB is the fallback because Twitch rejected the WEB and ANDROID_APP
    client IDs with "invalid client", which made the hardcoded default in
    ``Twitch.__init__`` unable to start a login at all.
    """
    types = _known_client_types()
    return types.get(name.strip().upper(), _ClientType.MOBILE_WEB)


def _apply_client_type() -> None:
    """
    Let TDM_CLIENT_TYPE override the client ID used for auth and GQL.

    Upstream hardcodes ClientType.ANDROID_APP, so when Twitch retires a client
    ID the app cannot log in and there is no supported way to change it. This
    keeps the override in the fork instead of editing core.

    ``twitch`` is imported lazily: it pulls in the tkinter GUI, which needs
    Pillow, and the test suite runs without the GUI dependencies installed.
    The patch is installed at most once even if this is called again.
    """
    if not os.environ.get("TDM_CLIENT_TYPE", "").strip():
        return

    import twitch as _twitch

    original_init = _twitch.Twitch.__init__
    if getattr(original_init, "_tdm_client_type_patched", False):
        return

    def patched_init(self: object, *args: object, **kwargs: object) -> None:
        original_init(self, *args, **kwargs)
        name = os.environ.get("TDM_CLIENT_TYPE", "").strip()
        if name:
            self._client_type = _resolve_client_type(name)  # type: ignore[attr-defined]

    patched_init._tdm_client_type_patched = True  # type: ignore[attr-defined]
    _twitch.Twitch.__init__ = patched_init  # type: ignore[method-assign]


_apply_client_type()


def _priority_link_override_get(self) -> bool:
    """
    True when the user has enabled the advanced "priority link override"
    setting and explicitly added this (unlinked) game to the Priority List.

    This does not change Twitch's reported account-link state; Twitch may
    still refuse to award drops for a campaign the account isn't linked to.
    """
    return (
        self._twitch.settings.priority_link_override
        and not self.linked
        and self.game.name in self._twitch.settings.priority
    )


setattr(
    _inventory.DropsCampaign,
    "priority_link_override",
    property(_priority_link_override_get),
)


def _priority_badge_override_get(self) -> bool:
    """
    True when the user has enabled the advanced "priority badge override"
    setting and explicitly added this game's badge/emote campaign to the
    Priority List.

    Badge and emote campaigns are only payable when the account already owns
    the badge/emote being awarded, which is why upstream gates them behind the
    broad ``enable_badges_emotes`` switch instead of the account-link state.
    This narrows that gate to the games the user opted into.

    Like the link override above, this does not change Twitch's own rules: if
    the account is not actually linked, or does not own the badge, Twitch will
    still refuse to award the drop.
    """
    return (
        self._twitch.settings.priority_badge_override
        and self.game.name in self._twitch.settings.priority
    )


setattr(
    _inventory.DropsCampaign,
    "priority_badge_override",
    property(_priority_badge_override_get),
)


def _badge_ownership_get(self) -> BadgeOwnership:
    """
    What we know about whether the account owns this campaign's badge/emote.

    Non-badge campaigns report NOT_APPLICABLE. For badge campaigns this layers
    the free signals (previously awarded benefit edges, then the user-declared
    "Badge campaigns I own" list) and reports UNKNOWN when neither can confirm
    it, so the UI can prompt instead of quietly assuming "not owned".

    Manual entries are matched by campaign ID. The legacy game-keyed list is
    still consulted so configurations written before the switch keep working.
    """
    settings = self._twitch.settings
    return _badge_registry.owns_campaign(
        self,
        manual_campaign_ids=getattr(settings, "owned_badge_campaigns", None),
        manual_games=getattr(settings, "owned_badge_games", None),
    )


setattr(
    _inventory.DropsCampaign,
    "badge_ownership",
    property(_badge_ownership_get),
)


_original_init = _inventory.DropsCampaign.__dict__["__init__"]


def _campaign_init(self, twitch, data, claimed_benefits):
    """
    Capture the claimed-benefit map, then build the campaign as upstream does.

    ``Twitch.fetch_inventory`` builds ``claimed_benefits`` as a local variable and
    only passes it to campaign constructors, so this wrapper is the only place a
    WebUI-side module can observe it without editing core.
    """
    _badge_registry.observe_claimed_benefits(claimed_benefits)
    _original_init(self, twitch, data, claimed_benefits)


setattr(_inventory.DropsCampaign, "__init__", _campaign_init)


def _eligible_get(self) -> bool:
    return (
        _original_eligible(self)
        or (
            not self.has_badge_or_emote
            and self.priority_link_override
        )
        or (
            self.has_badge_or_emote
            and self.priority_badge_override
        )
    )


_original_eligible = _inventory.DropsCampaign.__dict__["eligible"].fget

setattr(
    _inventory.DropsCampaign,
    "eligible",
    property(_eligible_get),
)


# ---------------------------------------------------------------------------
# Outbound notification hooks
#
# Wrapping rather than editing core keeps these changes WebUI-only and avoids
# merge conflicts with upstream.
# ---------------------------------------------------------------------------

# Campaign completion: the only place a campaign learns it just lost its last
# drop is the claim that consumed it, so compare the count before and after.
# ``DropsCampaign`` exposes ``finished``/``claimed_drops``; the parent campaign
# link is reached through the drop's ``campaign`` attribute.
_original_drop_claim = _inventory.TimedDrop.claim


async def _timed_drop_claim(self) -> bool:  # type: ignore[no-untyped-def]
    campaign = getattr(self, "campaign", None)
    before_finished = bool(getattr(campaign, "finished", False)) if campaign else False
    claimed = await _original_drop_claim(self)
    if claimed and campaign is not None and not before_finished:
        if getattr(campaign, "finished", False):
            try:
                from .notifications import notifications

                notifications.send(
                    "campaign_complete",
                    "Campaign completed",
                    f"{getattr(campaign, 'name', 'Unknown campaign')} "
                    "is now fully claimed.",
                )
            except Exception:
                # A notification failure must never break the claim path.
                pass
    return claimed


_inventory.TimedDrop.claim = _timed_drop_claim  # type: ignore[method-assign]

