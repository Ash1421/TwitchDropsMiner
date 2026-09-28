"""Tests for webui/themes.py - theme resolution and palette integrity.

The palettes are pure data, so these tests do not need a NiceGUI context. They
pin the two properties that matter: every theme resolves, and the dark/OLED
palettes carry no blue cast (which was the original complaint).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from webui import themes
from webui.themes import Theme


def test_all_three_themes_registered() -> None:
    assert set(themes.THEMES) == {"light", "dark", "oled"}
    assert themes.DEFAULT_THEME in themes.THEMES


def test_dark_themes_are_marked_dark() -> None:
    assert themes.LIGHT.dark is False
    assert themes.DARK.dark is True
    assert themes.OLED.dark is True


def _channels(hex_color: str) -> tuple[int, int, int]:
    value = hex_color.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


@pytest.mark.parametrize("theme", [themes.DARK, themes.OLED])
def test_dark_palettes_have_neutral_channels(theme) -> None:
    """No blue cast: R, G and B must be equal for page and surface colours."""
    for color in (theme.page, theme.surface, theme.surface_alt):
        r, g, b = _channels(color)
        assert r == g == b, f"{theme.name} {color} is tinted: R={r} G={g} B={b}"


def test_oled_page_is_pure_black() -> None:
    assert themes.OLED.page == "#000000"


def test_dark_surfaces_are_lighter_than_page() -> None:
    """Cards must stay distinguishable from the page behind them."""
    for theme in (themes.DARK, themes.OLED):
        assert _channels(theme.surface) > _channels(theme.page)


def test_resolve_prefers_explicit_theme() -> None:
    settings = SimpleNamespace(theme="oled", dark_mode=False)
    assert themes.resolve(settings) is themes.OLED


def test_resolve_falls_back_to_legacy_dark_mode() -> None:
    """Existing settings.json files have dark_mode but no theme key."""
    assert themes.resolve(SimpleNamespace(dark_mode=True)) is themes.DARK
    assert themes.resolve(SimpleNamespace(dark_mode=False)) is themes.LIGHT


def test_resolve_ignores_unknown_theme_name() -> None:
    settings = SimpleNamespace(theme="neon", dark_mode=True)
    assert themes.resolve(settings) is themes.DARK


def test_resolve_handles_settings_without_any_theme_key() -> None:
    assert themes.resolve(SimpleNamespace()) is themes.LIGHT


def test_slate_overrides_only_emit_matching_mode() -> None:
    """Light themes must not pick up dark: prefixed rules and vice versa."""
    dark_css = themes._slate_overrides(themes.DARK)
    assert "dark\\:bg-slate-700" in dark_css
    assert ".bg-slate-100 " not in dark_css

    light_css = themes._slate_overrides(themes.LIGHT)
    assert ".bg-slate-100" in light_css
    assert "dark\\:bg-slate-700" not in light_css


def test_slate_overrides_use_theme_colours() -> None:
    css = themes._slate_overrides(themes.OLED)
    assert themes.OLED.page in css
    assert themes.OLED.surface in css
    assert themes.OLED.surface_alt in css


def test_every_slate_entry_maps_to_a_real_theme_field() -> None:
    for field in themes.SLATE_SURFACES.values():
        assert field in Theme._fields, f"unknown Theme field: {field}"


def test_every_theme_defines_accent_and_on_accent() -> None:
    """Buttons derive their label colour from primary, so both are required."""
    for theme in themes.THEMES.values():
        assert theme.accent
        assert theme.on_accent


def test_accent_and_on_accent_are_distinct() -> None:
    """The bug this guards: identical accent/foreground hides button labels."""
    for theme in themes.THEMES.values():
        assert theme.accent.lower() != theme.on_accent.lower(), theme.name


def test_accent_contrasts_with_its_foreground() -> None:
    """WCAG-ish check so no theme renders light-on-light or dark-on-dark."""
    for theme in themes.THEMES.values():
        a = _relative_luminance(theme.accent)
        b = _relative_luminance(theme.on_accent)
        ratio = (max(a, b) + 0.05) / (min(a, b) + 0.05)
        assert ratio >= 4.5, f"{theme.name}: accent/on_accent ratio {ratio:.2f}"


def test_body_text_contrasts_with_its_surface() -> None:
    for theme in themes.THEMES.values():
        a = _relative_luminance(theme.text)
        b = _relative_luminance(theme.surface)
        ratio = (max(a, b) + 0.05) / (min(a, b) + 0.05)
        assert ratio >= 7.0, f"{theme.name}: text/surface ratio {ratio:.2f}"


def test_dim_text_contrasts_with_its_surface() -> None:
    for theme in themes.THEMES.values():
        a = _relative_luminance(theme.text_dim)
        b = _relative_luminance(theme.surface)
        ratio = (max(a, b) + 0.05) / (min(a, b) + 0.05)
        assert ratio >= 4.5, f"{theme.name}: text_dim/surface ratio {ratio:.2f}"


def test_positive_and_negative_readable_on_every_surface() -> None:
    for theme in themes.THEMES.values():
        for field in ("positive", "negative"):
            a = _relative_luminance(getattr(theme, field))
            b = _relative_luminance(theme.surface)
            ratio = (max(a, b) + 0.05) / (min(a, b) + 0.05)
            assert ratio >= 3.0, f"{theme.name}: {field} ratio {ratio:.2f}"


def test_text_is_not_pure_black_or_pure_white() -> None:
    """Pure #000/#fff halates; the palettes use softened extremes."""
    for theme in themes.THEMES.values():
        assert theme.text.lower() not in ("#000", "#000000", "#fff", "#ffffff"), theme.name


def _relative_luminance(color: str) -> float:
    channels = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    red, green, blue = linear
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue
