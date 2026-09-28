"""
Light / Dark / OLED themes for the WebUI.

Upstream hardcodes a single slate palette in ``WebUIManager._setup_ui``
(``--color-slate-800`` pages, ``bg-slate-700`` cards). Slate carries a blue
hue, which is what makes the dark theme look washed-out and cold on OLED
panels.

This module replaces that with three named palettes and a single ``apply``
entry point, so ``manager.py`` only has to call ``apply(theme)`` per client.

The surface colours are applied with injected CSS rather than Tailwind
arbitrary-value classes, because those depend on the compiled stylesheet
actually containing the generated class.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

from nicegui import ui

if TYPE_CHECKING:
    from webui.manager import WebUIManager


class Theme(NamedTuple):
    """One named palette."""

    name: str
    dark: bool
    page: str
    surface: str
    surface_alt: str
    border: str
    text: str
    text_dim: str


LIGHT = Theme(
    name="light",
    dark=False,
    page="#f3f4f6",
    surface="#ffffff",
    surface_alt="#f9fafb",
    border="#e5e7eb",
    text="#111827",
    text_dim="#6b7280",
)

# Neutral greys, no blue cast. Comfortable for long unattended runs.
DARK = Theme(
    name="dark",
    dark=True,
    page="#141414",
    surface="#1c1c1c",
    surface_alt="#242424",
    border="#333333",
    text="#e5e5e5",
    text_dim="#9a9a9a",
)

# True black page so pixels switch off entirely; near-black cards stay
# distinguishable from the page.
OLED = Theme(
    name="oled",
    dark=True,
    page="#000000",
    surface="#0a0a0a",
    surface_alt="#141414",
    border="#262626",
    text="#e0e0e0",
    text_dim="#8a8a8a",
)

THEMES: dict[str, Theme] = {t.name: t for t in (LIGHT, DARK, OLED)}
DEFAULT_THEME = DARK.name

# Upstream hardcodes slate utility classes on individual elements (the header
# bar, the inventory panel) rather than going through default_classes, so
# those are overridden here by CSS selector instead. That keeps every palette
# decision inside this module instead of editing a dozen call sites.
#
# Maps the utility class to the Theme field that should colour it.
SLATE_SURFACES: dict[str, str] = {
    "bg-slate-100": "surface",
    "bg-slate-200": "surface_alt",
    "bg-slate-300": "surface_alt",
    "dark\\:bg-slate-500": "surface_alt",
    "dark\\:bg-slate-700": "surface",
    "dark\\:bg-slate-800": "surface_alt",
    "dark\\:bg-slate-900": "page",
}


def resolve(settings: Any) -> Theme:
    """
    Pick the effective theme for *settings*.

    Falls back to the legacy ``dark_mode`` boolean when no ``theme`` key is
    stored, so existing settings.json files keep their appearance.
    """
    name = getattr(settings, "theme", None)
    if name in THEMES:
        return THEMES[name]
    return DARK if getattr(settings, "dark_mode", False) else LIGHT


def _slate_overrides(theme: Theme) -> str:
    """
    CSS rules recolouring upstream's hardcoded slate utilities.

    Only the variant that matches the active mode is emitted, so light themes
    are not dragged dark by the ``dark:`` prefixed rules and vice versa.
    """
    rules = []
    for class_name, field in SLATE_SURFACES.items():
        is_dark_variant = class_name.startswith("dark\\:")
        if is_dark_variant != theme.dark:
            continue
        color = getattr(theme, field)
        rules.append(f".{class_name} {{ background-color: {color}; }}")
    return "\n".join(rules)


def apply(theme: Theme) -> None:
    """
    Apply *theme* to the client currently being built.

    Must be called inside the per-client page builder, because ``ui.colors`` and
    ``default_classes`` only affect the client being rendered.
    """
    ui.dark_mode(theme.dark)
    ui.colors(primary=theme.text, secondary=theme.text_dim, dark=theme.page)
    ui.card.default_classes(f"bg-[{theme.surface}]")
    ui.table.default_classes(f"bg-[{theme.surface}]")
    ui.add_css(
        f"""
        body, .nicegui-content, .q-page {{
            background-color: {theme.page};
            color: {theme.text};
        }}
        .q-card, .q-table__container, .q-table thead tr, .q-table tbody tr {{
            background-color: {theme.surface};
            color: {theme.text};
        }}
        .q-card, .q-table thead tr {{
            border-color: {theme.border};
        }}
        .q-table thead, .q-field__label, .q-field__native, .q-item__label {{
            color: {theme.text_dim};
        }}
        {_slate_overrides(theme)}
        """
    )
