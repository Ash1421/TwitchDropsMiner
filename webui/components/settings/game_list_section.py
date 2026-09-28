from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from nicegui import ui

from translate import _

if TYPE_CHECKING:
    from nicegui.elements.input import Input
    from webui.manager import WebUIManager


class GameListSection(ABC):
    """
    Abstract base for the Priority and Exclude sections.

    Both sections show a filterable, selectable list of game names backed by
    a settings collection. Subclasses supply the data model (_options, _items,
    selection logic, add/delete) and their own build() layout with buttons;
    this base provides the shared input row, list UI, and game-name helpers.
    """

    def __init__(self, manager: "WebUIManager") -> None:
        self._manager = manager
        self._game_names: set[str] = set()

    @property
    def _settings(self):
        return self._manager._twitch.settings

    def set_games(self, games: set) -> None:
        self._game_names = {game.name for game in games}
        self._input_content.refresh()

    # -------------------------------------------------------------------------
    # Abstract — subclasses supply the data model
    # -------------------------------------------------------------------------

    @abstractmethod
    def _options(self) -> list[str]:
        """Games available to add (not already in the list)."""
        ...

    @abstractmethod
    def _items(self) -> list:
        """Current items to render in the list."""
        ...

    @abstractmethod
    def _item_label(self, item) -> str:
        """Display text for a list item."""
        ...

    @abstractmethod
    def _is_selected(self, item) -> bool: ...

    @abstractmethod
    def _on_select(self, item) -> None: ...

    @abstractmethod
    def _on_delete(self) -> None: ...

    @abstractmethod
    def _do_add(self, name: str, input_el: "Input") -> None:
        """Persist the addition and refresh the UI."""
        ...

    def _option_labels(self) -> dict:
        """Optional value -> display label map for the picker.

        Defaults to identity, which suits the game lists. Overridden where the
        stored value is not what the user should read (e.g. campaign IDs).
        """
        return {option: option for option in self._options()}

    def _item_detail(self, item) -> str:
        """Optional secondary text shown under a list row."""
        return ""

    def _item_detail_class(self, item) -> str:
        """Optional extra classes for the secondary text."""
        return ""

    def _is_known(self, value: str) -> bool:
        """Whether *value* may be added without the unknown-item warning."""
        return value in self._game_names

    # -------------------------------------------------------------------------
    # Shared refreshable UI
    # -------------------------------------------------------------------------

    def _input_label(self) -> str:
        """
        Label for the game-name input.

        Overridden by the Badges section, where a plain "Game name" reads as if
        it were adding the game to the inventory rather than to the badge list.
        """
        return _("gui", "settings", "game_name")

    @ui.refreshable
    def _input_content(self) -> None:
        labels = self._option_labels()
        with ui.row().classes("w-full gap-1 items-center"):
            input_el = (
                ui.input(
                    label=self._input_label(),
                    autocomplete=list(labels.values()) or None,
                )
                .classes("flex-1 text-xs")
                .props("dense")
                .on("keydown.enter", lambda: self._add_game(input_el))
            )
            with (
                ui.button(icon="expand_more").props("dense flat").classes("p-0 min-h-0")
            ):
                with ui.menu():
                    for name in labels.values():
                        ui.menu_item(
                            name,
                            on_click=lambda _, n=name: input_el.set_value(
                                self._value_for_label(n, labels)
                            ),
                        ).classes("text-xs")
            ui.button("➕", on_click=lambda: self._add_game(input_el)).props(
                "dense flat"
            ).classes("text-xl p-0 min-h-0")

    @staticmethod
    def _value_for_label(label: str, labels: dict) -> str:
        for value, text in labels.items():
            if text == label:
                return value
        return label

    @ui.refreshable
    def _list_content(self) -> None:
        with (
            ui.list()
            .props("dense bordered")
            .classes("flex-1 text-xs overflow-y-auto min-h-[200px]")
        ):
            for item in self._items():
                active = self._is_selected(item)
                with (
                    ui.item()
                    .props(f"clickable {'active' if active else ''}")
                    .classes("bg-primary" if active else "")
                    .on("click", lambda _, i=item: self._on_select(i))
                ):
                    with ui.item_section():
                        ui.item_label(self._item_label(item)).classes("text-xs")
                        detail = self._item_detail(item)
                        if detail:
                            ui.label(detail).classes(
                                "text-xxs " + self._item_detail_class(item)
                            )

    # -------------------------------------------------------------------------
    # Shared helpers
    # -------------------------------------------------------------------------

    def _add_game(self, input_el: "Input") -> None:
        name = input_el.value
        if not name or not str(name).strip():
            return
        name = str(name).strip()
        name = self._correct_game_case(name)
        if not self._is_known(name):
            self._confirm_unknown_game(name, lambda: self._do_add(name, input_el))
            return
        self._do_add(name, input_el)

    def _correct_game_case(self, value: str) -> str:
        lower = value.lower()
        for name in self._game_names:
            if name.lower() == lower:
                return name
        return value

    def _confirm_unknown_game(self, name: str, on_confirm) -> None:
        with ui.dialog() as dialog, ui.card().classes("q-pa-sm"):
            ui.label(_("webui", "game_list", "no_campaigns").format(name=name)).classes(
                "text-sm font-bold"
            )
            ui.label(_("webui", "game_list", "add_anyway")).classes("text-xs")
            with ui.row().classes("gap-2 justify-end w-full"):

                def _cancel():
                    dialog.close()
                    dialog.delete()

                def _confirm():
                    dialog.close()
                    dialog.delete()
                    on_confirm()

                ui.button(_("webui", "game_list", "cancel"), on_click=_cancel).props(
                    "dense flat"
                ).classes("text-xs")
                ui.button(_("webui", "game_list", "add"), on_click=_confirm).props(
                    "dense"
                ).classes("text-xs")
        dialog.open()
