from __future__ import annotations

from typing import TYPE_CHECKING

from nicegui import ui

from .base_panel import BasePanel
from .settings import (
    GeneralSection,
    PrioritySection,
    ExcludeSection,
    BadgeSection,
    WebhookSection,
)

if TYPE_CHECKING:
    from webui.manager import WebUIManager
    from utils import Game


class SettingsPanel(BasePanel):
    """
    Three-column settings layout.

    Priority and Exclude share the middle column and stack vertically, so the
    two orderings can be compared directly; a single wide row left them side by
    side and pushed the badge list off screen. The columns are explicit
    elements rather than relying on flex-wrap so the grouping is stable at any
    viewport width.
    """

    def __init__(self, manager: "WebUIManager"):
        super().__init__(manager)
        self._general_section = GeneralSection(manager)
        self._priority_section = PrioritySection(manager)
        self._exclude_section = ExcludeSection(manager)
        self._badge_section = BadgeSection(manager)
        self._webhook_section = WebhookSection(manager)

    def build(self) -> None:
        # Columns use inline flex styles rather than Tailwind basis-[300px]:
        # arbitrary-value classes were being dropped on some loads, letting the
        # middle column collapse to content width. flex 320px / min 260px keeps
        # them equal and readable while still wrapping on narrow viewports.
        with ui.row().classes("w-full gap-2 items-start flex-wrap"):
            # Column 1 - general settings and notification targets.
            with ui.column().style("flex: 1 1 320px; min-width: 260px").classes(
                "gap-2"
            ):
                self._general_section.build()
                self._webhook_section.build()
            # Column 2 - the two orderings, stacked so they read as a pair.
            with ui.column().style("flex: 1 1 320px; min-width: 260px").classes(
                "gap-2"
            ):
                self._priority_section.build()
                self._exclude_section.build()
                self._badge_section.build()
            # Column 3 - advanced and reload stay together for now.
            with ui.column().style("flex: 1 1 320px; min-width: 260px").classes(
                "gap-2"
            ):
                self._advanced_column()

    def _advanced_column(self) -> None:
        # Advanced and Reload are emitted by GeneralSection today; this hook
        # exists so the third column has a single place to grow.
        self._general_section.build_advanced()

    def set_games(self, games: set["Game"]) -> None:
        self._priority_section.set_games(games)
        self._exclude_section.set_games(games)
        self._badge_section.set_games(games)

    def set_campaigns(self, campaigns: set) -> None:
        self._badge_section.set_campaigns(campaigns)
