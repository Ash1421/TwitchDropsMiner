from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nicegui import ui

from translate import _
from webui import badges

from .game_list_section import GameListSection

if TYPE_CHECKING:
    from nicegui.elements.input import Input
    from webui.manager import WebUIManager


class BadgeSection(GameListSection):
    """
    Per-campaign list of badge/emote campaigns the account is treated as owning.

    Some badges and emotes are granted outside the drops system (events,
    purchases, subscription renewals), so they never appear in the account's
    claimed benefit edges. Listing a campaign here tells the miner to treat that
    campaign's badges as payable.

    Entries are stored as campaign IDs rather than display names, so renaming a
    campaign on Twitch's side cannot silently detach a user's assertion.
    """

    def __init__(self, manager: "WebUIManager") -> None:
        super().__init__(manager)
        self._selected: str | None = None
        # campaign id -> DropsCampaign, for the ownership verdict per row.
        self._campaigns: dict[str, Any] = {}

    def set_campaigns(self, campaigns: set) -> None:
        """Record the known campaigns so rows can show a live verdict."""
        self._campaigns = {c.id: c for c in campaigns if getattr(c, "id", None)}
        self._list_content.refresh()

    def build(self) -> None:
        settings = self._settings
        with (
            ui.card()
            .props("flat bordered")
            .classes("q-pa-sm flex flex-col grow shrink basis-80 min-w-0")
        ):
            ui.label(_("webui", "settings", "badges", "name")).classes("font-bold text-sm")
            ui.label(_("webui", "settings", "badges", "hint")).classes(
                "text-xs text-yellow-500 whitespace-pre-wrap"
            )
            # Kept here rather than in Advanced, where it read as a duplicate of
            # upstream's "enable badges and emotes" switch.
            with ui.row().classes("items-center gap-2 text-xs"):
                ui.label(
                    _("webui", "settings", "badges", "priority_badge_override")
                ).classes("flex-1")
                ui.switch(
                    value=settings.priority_badge_override,
                    on_change=lambda e: self._set_and_save(
                        settings, "priority_badge_override", e.value
                    ),
                ).bind_value_from(settings, "priority_badge_override")
            self._input_content()
            with ui.row().classes("w-full gap-1 items-start min-h-[200px]"):
                self._list_content()
                with ui.column().classes("gap-1"):
                    ui.button("✕", on_click=self._on_delete).props("flat").classes(
                        "text-red-500 text-xl p-0 min-h-0"
                    )

    @property
    def _owned(self) -> set[str]:
        """Campaign IDs the user has asserted, on either the current or legacy key."""
        settings = self._settings
        return set(
            getattr(settings, "owned_badge_campaigns", None)
            or set()
        ) | set(getattr(settings, "owned_badge_games", None) or set())

    def _campaign_options(self) -> list[tuple[str, str]]:
        """Badge/emote campaigns not yet in the list, as (id, label) pairs."""
        owned = self._owned
        options = [
            (cid, self._label_for(campaign))
            for cid, campaign in self._campaigns.items()
            if cid not in owned and self._is_badge_campaign(campaign)
        ]
        return sorted(options, key=lambda pair: pair[1].lower())

    def _label_for(self, campaign: Any) -> str:
        game = getattr(campaign, "game", None)
        game_name = getattr(game, "name", "") or ""
        name = getattr(campaign, "name", "") or ""
        return f"{game_name} - {name}" if game_name else name

    @staticmethod
    def _is_badge_campaign(campaign: Any) -> bool:
        return bool(badges.badge_benefits(campaign))

    def _verdict_for(self, campaign_id: str) -> badges.BadgeOwnership:
        """Ownership the miner would infer, ignoring the manual assertion."""
        campaign = self._campaigns.get(campaign_id)
        if campaign is None:
            return badges.BadgeOwnership.UNKNOWN
        return badges.registry.owns_campaign(campaign, manual_campaign_ids=None)

    @staticmethod
    def _verdict_label(verdict: badges.BadgeOwnership) -> str:
        return {
            badges.BadgeOwnership.OWNED: _("webui", "settings", "badges", "state_owned"),
            badges.BadgeOwnership.PARTIAL: _(
                "webui", "settings", "badges", "state_partial"
            ),
            badges.BadgeOwnership.UNKNOWN: _(
                "webui", "settings", "badges", "state_unknown"
            ),
            badges.BadgeOwnership.NOT_APPLICABLE: _(
                "webui", "settings", "badges", "state_unknown"
            ),
        }[verdict]

    @staticmethod
    def _verdict_class(verdict: badges.BadgeOwnership) -> str:
        return {
            badges.BadgeOwnership.OWNED: "text-green-500",
            badges.BadgeOwnership.PARTIAL: "text-yellow-500",
            badges.BadgeOwnership.UNKNOWN: "text-grey-500",
        }[verdict]

    def _options(self) -> list[str]:
        """Campaign IDs available to add."""
        return [cid for cid, _ in self._campaign_options()]

    def _option_labels(self) -> dict[str, str]:
        """id -> display label, so the dropdown shows names not opaque IDs."""
        return dict(self._campaign_options())

    def _items(self) -> list[str]:
        return list(self._owned)

    def _item_label(self, item: str) -> str:
        campaign = self._campaigns.get(item)
        if campaign is not None:
            return self._label_for(campaign)
        # Campaign no longer present; show the stored ID so it can be removed.
        return item

    def _is_selected(self, item: str) -> bool:
        return item == self._selected

    def _on_select(self, item: str) -> None:
        self._selected = None if self._selected == item else item
        self._list_content.refresh()

    def _on_delete(self) -> None:
        if self._selected is None:
            return
        item = self._selected
        for key in ("owned_badge_campaigns", "owned_badge_games"):
            values = getattr(self._settings, key, None)
            if values is not None and item in values:
                values.discard(item)
        self._settings.save(force=True)
        self._selected = None
        self._list_content.refresh()
        self._input_content.refresh()

    def _do_add(self, name: str, input_el: "Input") -> None:
        campaigns = getattr(self._settings, "owned_badge_campaigns", None)
        if campaigns is None:
            campaigns = set()
            self._settings.owned_badge_campaigns = campaigns
        if name not in campaigns:
            campaigns.add(name)
            self._settings.save(force=True)
        if input_el is not None:
            input_el.set_value("")
        self._list_content.refresh()
        self._input_content.refresh()

    def _item_detail(self, item: str) -> str:
        """Show what Twitch currently says, next to the user's override."""
        verdict = self._verdict_for(item)
        return _("webui", "settings", "badges", "state_detail").format(
            state=self._verdict_label(verdict)
        )

    def _item_detail_class(self, item: str) -> str:
        return self._verdict_class(self._verdict_for(item))

    @staticmethod
    def _set_and_save(settings, name: str, value) -> None:
        setattr(settings, name, value)
        settings.save(force=True)

    def _is_known(self, value: str) -> bool:
        """Campaign IDs are opaque, so accept any id we have actually seen."""
        return value in self._campaigns
