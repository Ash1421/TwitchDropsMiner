from __future__ import annotations

from typing import Any, TypedDict, TYPE_CHECKING

from yarl import URL

from utils import json_load, json_save
from constants import CONFIG_PATH, SETTINGS_PATH, DEFAULT_LANG, PriorityMode

if TYPE_CHECKING:
    from main import ParsedArgs


class SettingsFile(TypedDict):
    proxy: URL
    language: str
    dark_mode: bool
    exclude: set[str]
    priority: list[str]
    autostart_tray: bool
    connection_quality: int
    tray_notifications: bool
    enable_badges_emotes: bool
    available_drops_check: bool
    priority_mode: PriorityMode


# Declaration order is meaningful: Settings.save() writes config/settings.json
# in this order, so related keys stay together instead of being scattered by an
# alphabetical sort. webui/patches.py appends its own groups after these.
default_settings: SettingsFile = {
    # Network
    "proxy": URL(),
    # Language and appearance
    "language": DEFAULT_LANG,
    "dark_mode": False,
    "tray_notifications": True,
    # Game selection and drop priority
    "priority": [],
    "exclude": set(),
    "priority_mode": PriorityMode.PRIORITY_ONLY,
    # Drop tracking behaviour
    "enable_badges_emotes": False,
    "available_drops_check": False,
    # Not exposed in any GUI - edit here (connection_quality is also clamped
    # back into 1-6 on read, autostart_tray is Windows-only)
    "connection_quality": 1,
    "autostart_tray": False,
}


class Settings:
    # from args
    log: bool
    stdlog: bool
    tray: bool
    dump: bool
    # args properties
    debug_ws: int
    debug_gql: int
    logging_level: int
    # from settings file
    proxy: URL
    language: str
    dark_mode: bool
    exclude: set[str]
    priority: list[str]
    autostart_tray: bool
    connection_quality: int
    tray_notifications: bool
    enable_badges_emotes: bool
    available_drops_check: bool
    priority_mode: PriorityMode

    PASSTHROUGH = ("_settings", "_args", "_altered")

    def __init__(self, args: ParsedArgs):
        CONFIG_PATH.mkdir(parents=True, exist_ok=True)
        self._settings: SettingsFile = json_load(SETTINGS_PATH, default_settings)
        self._args: ParsedArgs = args
        self._altered: bool = False

    # default logic of reading settings is to check args first, then the settings file
    def __getattr__(self, name: str, /) -> Any:
        if name in self.PASSTHROUGH:
            # passthrough
            return getattr(super(), name)
        elif hasattr(self._args, name):
            return getattr(self._args, name)
        elif name in self._settings:
            return self._settings[name]  # type: ignore[literal-required]
        return getattr(super(), name)

    def __setattr__(self, name: str, value: Any, /) -> None:
        if name in self.PASSTHROUGH:
            # passthrough
            return super().__setattr__(name, value)
        elif name in self._settings:
            self._settings[name] = value  # type: ignore[literal-required]
            self._altered = True
            return
        raise TypeError(f"{name} is missing a custom setter")

    def __delattr__(self, name: str, /) -> None:
        raise RuntimeError("settings can't be deleted")

    def alter(self) -> None:
        self._altered = True

    def save(self, *, force: bool = False) -> None:
        if self._altered or force:
            # Write in default_settings' declaration order rather than sorted,
            # so the file reads in groups instead of alphabetically.
            # merge_json() on load guarantees every template key is present.
            json_save(
                SETTINGS_PATH, {key: self._settings[key] for key in default_settings}
            )
