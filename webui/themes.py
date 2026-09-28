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
    accent: str
    on_accent: str
    positive: str
    negative: str


LIGHT = Theme(
    name="light",
    dark=False,
    page="#f4f4f5",
    surface="#ffffff",
    surface_alt="#fafafa",
    border="#d4d4d8",
    # Not pure black: #000 on white is harsh and smears on LCD panels.
    text="#1c1c1e",
    text_dim="#5b5b60",
    accent="#2f2f34",
    on_accent="#f7f7f8",
    positive="#1a7f43",
    negative="#c0392b",
)

# Neutral greys, no blue cast. Comfortable for long unattended runs.
DARK = Theme(
    name="dark",
    dark=True,
    page="#141414",
    surface="#1c1c1c",
    surface_alt="#242424",
    border="#3a3a3a",
    # Not pure white: it halates against near-black backgrounds.
    text="#e2e2e2",
    text_dim="#a3a3a3",
    accent="#e2e2e2",
    on_accent="#1a1a1a",
    positive="#4ade80",
    negative="#f87171",
)

# True black page so pixels switch off entirely; near-black cards stay
# distinguishable from the page.
OLED = Theme(
    name="oled",
    dark=True,
    page="#000000",
    surface="#0b0b0b",
    surface_alt="#161616",
    border="#2f2f2f",
    text="#dcdcdc",
    text_dim="#9a9a9a",
    accent="#dcdcdc",
    on_accent="#0a0a0a",
    positive="#4ade80",
    negative="#f87171",
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

    Quasar derives button text from the ``primary`` colour, so ``primary`` is
    the accent and buttons get an explicit ``on_accent`` foreground. Using the
    body text colour as ``primary`` made light-theme buttons render as light
    text on a light background.
    """
    ui.dark_mode(theme.dark)
    ui.colors(
        primary=theme.accent,
        secondary=theme.text_dim,
        dark=theme.page,
        positive=theme.positive,
        negative=theme.negative,
    )
    ui.card.default_classes(f"bg-[{theme.surface}]")
    ui.table.default_classes(f"bg-[{theme.surface}]")
    ui.button.default_classes("text-xs")
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
        .q-card, .q-table thead tr, .q-field--outlined .q-field__control {{
            border-color: {theme.border};
        }}
        .q-field--outlined .q-field__control:before {{
            border-color: {theme.border};
        }}
        .q-table thead, .q-field__label, .q-field__native, .q-item__label {{
            color: {theme.text_dim};
        }}
        .q-field__native, .q-item, .q-list, .q-menu {{
            color: {theme.text};
        }}
        .q-field__native, .q-item {{
            background-color: {theme.surface_alt};
        }}
        .q-menu, .q-dialog__inner > .q-card {{
            background-color: {theme.surface_alt};
        }}

        /* Buttons: Quasar picks the label colour from `primary`, which is the
           accent here, so set the foreground explicitly to stay readable. */
        .q-btn.bg-primary, .q-btn.bg-primary:hover, .q-btn.bg-primary:focus {{
            background-color: {theme.accent};
            color: {theme.on_accent};
        }}
        .q-btn.bg-primary .q-icon, .q-btn.bg-primary .q-btn__content {{
            color: {theme.on_accent};
        }}
        /* Flat/outline buttons sit on our surfaces, so use body text. Scoped to
           bg-white only: including .text-white here would outrank the
           .bg-primary rule above and strip the accent. */
        .q-btn.bg-white, .q-btn.bg-white:hover {{
            background-color: {theme.surface_alt};
            color: {theme.text};
        }}
        .q-btn.bg-white .q-icon, .q-btn.bg-white .q-btn__content {{
            color: {theme.text};
        }}
        .q-btn:disabled, .q-btn.bg-primary:disabled {{
            opacity: 0.45;
        }}

        /* Ticks: emoji glyphs render thin on dark backgrounds, so colour the
           character itself instead of relying on the emoji's own colours. */
        .tdm-tick-yes {{ color: {theme.positive}; font-weight: 700; }}
        .tdm-tick-no {{ color: {theme.negative}; font-weight: 700; }}

        /* Switches: a checked toggle fills with the accent, so the thumb and
           any label drawn inside it must use the accent's foreground. Left
           alone, Quasar keeps its own white thumb, which vanishes against the
           light accent in the dark themes. */
        .q-toggle--checked .q-toggle__inner, .q-toggle--checked .q-toggle__label {{
            color: {theme.on_accent};
        }}
        .q-toggle__inner, .q-toggle__label {{
            color: {theme.text};
        }}
        .q-checkbox__inner--checked, .q-checkbox__inner--indeterminate {{
            color: {theme.on_accent};
        }}
        .q-checkbox__inner--unchecked {{
            color: {theme.text_dim};
        }}

        /* Active list selection used bg-primary + text-white, which is the
           same light-on-light problem as the buttons. */
        .q-item.active {{
            background-color: {theme.accent};
            color: {theme.on_accent};
        }}
        .q-item.active .q-item__label {{
            color: {theme.on_accent};
        }}

        /* File uploader: Quasar keeps its own pale surface regardless of the
           active palette, so pin it to the theme surfaces. Without this the
           upload zone text is light-on-light in the dark themes. */
        .q-uploader {{
            background-color: {theme.surface_alt};
            color: {theme.text};
        }}
        .q-uploader__header {{
            background-color: {theme.accent};
            color: {theme.on_accent};
        }}
        .q-uploader__title, .q-uploader__subtitle {{
            color: inherit;
        }}
        .q-uploader__list, .q-uploader__file, .q-uploader__file--uploaded {{
            background-color: {theme.surface};
            color: {theme.text};
            border-color: {theme.border};
        }}
        .q-uploader__file .q-icon, .q-uploader__file--uploaded .q-icon {{
            color: {theme.text_dim};
        }}
        {_slate_overrides(theme)}
        """
    )
