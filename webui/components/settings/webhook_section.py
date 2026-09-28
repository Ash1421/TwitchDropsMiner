"""
Outbound notification settings for the WebUI.

Discord is delivered through an incoming webhook, which is a plain HTTPS POST
with no authentication beyond the URL itself. That makes it the cheapest useful
target and the right one to ship first.

Telegram needs a bot token and a chat id, and a long-poll loop for two-way
interaction, so it is configured here but delivered by the same dispatcher.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from nicegui import ui

from constants import CONFIG_PATH
from translate import _
from webui.notifications import (
    AVATAR_EXTENSIONS,
    DEFAULT_AVATAR_URL,
    DEFAULT_BOT_NAME,
    DEFAULT_EMBED_COLOR,
    format_color,
    normalize_hex_color,
)

if TYPE_CHECKING:
    from webui.manager import WebUIManager

# Events a user can opt into individually.
EVENT_KEYS = ("drop_claimed", "campaign_complete", "channel_switch", "fatal_error")

# The identity fields and what "reset to default" restores them to. The avatar
# default is the official pickaxe icon served from this fork's GitHub blob.
RESET_DEFAULTS = {
    "bot_name": "",
    "webhook_avatar": DEFAULT_AVATAR_URL,
    "embed_color": DEFAULT_EMBED_COLOR,
}


class WebhookSection:
    """Card holding the notification targets and the send-test button."""

    def __init__(self, manager: "WebUIManager") -> None:
        self._manager = manager
        self._discord_url: str = ""
        self._telegram_token: str = ""
        self._telegram_chat: str = ""
        self._color_mode: str = "hex"
        # Per-browser-client widget refs. An edit typed in one tab refreshes
        # that tab's widgets (and only that tab's); late-joining tabs rebuild
        # from the saved settings and register themselves here.
        self._el: dict[str, dict[str, object]] = {}

    @property
    def _settings(self):
        return self._manager._twitch.settings

    def build(self) -> None:
        settings = self._settings
        with (
            ui.card()
            .props("flat bordered")
            .classes("q-pa-sm flex flex-col w-full")
        ):
            ui.label(_("webui", "settings", "webhooks", "name")).classes(
                "font-bold text-sm"
            )
            ui.label(_("webui", "settings", "webhooks", "hint")).classes(
                "text-sm text-yellow-500 whitespace-pre-wrap"
            )

            client = ui.context.client
            self._el[client.id] = {
                # Quasar's q-color can echo a change event while mounting. Until
                # the page has been up long enough for a real click, pretend no
                # color was chosen so a reconnect never clobbers the saved value.
                "armed": False,
            }

            # Display identity. Empty fields keep the ghost placeholder and
            # delivery falls back to the same defaults.
            with ui.row().classes("items-center gap-2 w-full text-sm"):
                ui.label(
                    _("webui", "settings", "webhooks", "bot_name")
                ).classes("flex-1")
                self._reset_button("bot_name", client)
            name_input = ui.input(
                value=str(getattr(settings, "bot_name", "") or ""),
                placeholder=DEFAULT_BOT_NAME,
                on_change=lambda e: self._on_bot_name(e.value),
            ).classes("w-full text-sm").props("dense maxlength=64 counter")
            self._el[client.id]["bot_name"] = name_input

            with ui.row().classes("items-center gap-2 w-full text-sm"):
                ui.label(
                    _("webui", "settings", "webhooks", "avatar_url")
                ).classes("flex-1")
                self._reset_button("webhook_avatar", client)
            avatar_input = ui.input(
                value=str(getattr(settings, "webhook_avatar", "") or ""),
                placeholder="https://cdn.discordapp.com/avatars/...png",
                on_change=lambda e: self._on_avatar(e.value),
            ).classes("w-full text-sm").props("dense")
            self._el[client.id]["webhook_avatar"] = avatar_input
            ui.upload(
                label=_("webui", "settings", "webhooks", "avatar_upload"),
                auto_upload=True,
                max_file_size=5 * 1024 * 1024,
                on_upload=self._on_avatar_upload,
                on_rejected=lambda e: ui.notify(
                    _("webui", "settings", "webhooks", "avatar_rejected"),
                    type="negative",
                    position="top",
                    timeout=6000,
                ),
            ).classes("w-full text-sm")
            ui.label(
                _("webui", "settings", "webhooks", "avatar_hint")
            ).classes("text-xs text-grey-500 whitespace-pre-wrap")

            ui.label(_("webui", "settings", "webhooks", "embed_color")).classes(
                "text-sm"
            )
            with ui.row().classes("items-center gap-2 w-full text-sm"):
                ui.toggle(
                    {
                        "hex": _("webui", "settings", "webhooks", "color_hex"),
                        "rgb": _("webui", "settings", "webhooks", "color_rgb"),
                    },
                    value=self._color_mode,
                    on_change=lambda e: self._on_color_mode(e),
                ).props("dense no-caps")
                self._reset_button("embed_color", client)
            color_current = normalize_hex_color(
                str(getattr(settings, "embed_color", "") or "")
            ) or DEFAULT_EMBED_COLOR
            color_input = ui.input(
                value=format_color(color_current, self._color_mode),
                placeholder=DEFAULT_EMBED_COLOR,
                on_change=lambda e: self._on_color_text(e),
            ).classes("w-full text-sm").props("dense")
            picker = (
                ui.element("q-color")
                .props(f'dense no-header model-value="{color_current}"')
                .on("change", lambda e: self._on_color_pick(e))
            )
            self._el[client.id]["color_input"] = color_input
            self._el[client.id]["picker"] = picker
            ui.timer(
                1.0,
                lambda cid=client.id: self._el.get(cid, {}).__setitem__(
                    "armed", True
                ),
                once=True,
                immediate=False,
            )
            if hasattr(client, "on_disconnect"):
                client.on_disconnect(lambda cid=client.id: self._el.pop(cid, None))

            self._discord_url = str(getattr(settings, "discord_webhook_url", "") or "")
            with ui.row().classes("items-center gap-2 w-full text-sm"):
                ui.label(
                    _("webui", "settings", "webhooks", "discord_url")
                ).classes("flex-1")
                if self._discord_url:
                    ui.icon("check_circle").classes(
                        "text-positive text-md"
                    ).tooltip(
                        _("webui", "settings", "webhooks", "secret_configured")
                    )
            ui.input(
                value=self._discord_url,
                placeholder="https://discord.com/api/webhooks/...",
                password=True,
                password_toggle_button=True,
                on_change=lambda e: self._on_discord_url(e.value),
            ).classes("w-full text-sm").props("dense")

            self._telegram_token = str(
                getattr(settings, "telegram_bot_token", "") or ""
            )
            with ui.row().classes("items-center gap-2 w-full text-sm"):
                ui.label(
                    _("webui", "settings", "webhooks", "telegram_token")
                ).classes("flex-1")
                if self._telegram_token:
                    ui.icon("check_circle").classes(
                        "text-positive text-md"
                    ).tooltip(
                        _("webui", "settings", "webhooks", "secret_configured")
                    )
            ui.input(
                value=self._telegram_token,
                placeholder="123456:ABC-DEF...",
                password=True,
                password_toggle_button=True,
                on_change=lambda e: self._on_telegram_token(e.value),
            ).classes("w-full text-sm").props("dense")

            self._telegram_chat = str(
                getattr(settings, "telegram_chat_id", "") or ""
            )
            ui.label(_("webui", "settings", "webhooks", "telegram_chat")).classes(
                "text-sm"
            )
            ui.input(
                value=self._telegram_chat,
                placeholder="-1001234567890",
                on_change=lambda e: self._on_telegram_chat(e.value),
            ).classes("w-full text-xs").props("dense")

            with ui.expansion(
                _("webui", "settings", "webhooks", "telegram_guide"),
                icon="help_outline",
            ).classes("w-full text-sm"):
                ui.markdown(
                    _("webui", "settings", "webhooks", "telegram_guide_md")
                ).classes("text-sm")

            ui.label(_("webui", "settings", "webhooks", "events")).classes(
                "text-sm font-bold mt-1"
            )
            for key in EVENT_KEYS:
                with ui.row().classes("items-center gap-2 text-sm"):
                    ui.label(
                        _("webui", "settings", "webhooks", f"event_{key}")
                    ).classes("flex-1")
                    ui.switch(
                        value=bool(getattr(settings, f"notify_{key}", True)),
                        on_change=lambda e, k=key: self._on_event(k, e.value),
                    )

            ui.label(_("webui", "settings", "webhooks", "test_hint")).classes(
                "text-xxs text-grey-500"
            )
            with ui.row().classes("gap-2 w-full"):
                ui.button(
                    _("webui", "settings", "webhooks", "test_discord"),
                    on_click=lambda: self._on_test("discord"),
                ).props("no-caps").classes("text-sm q-px-md")
                ui.button(
                    _("webui", "settings", "webhooks", "test_telegram"),
                    on_click=lambda: self._on_test("telegram"),
                ).props("no-caps").classes("text-sm q-px-md")

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _reset_button(self, field: str, client) -> None:
        """Tiny restore-to-default button next to a display-identity field."""
        ui.button(
            icon="restart_alt",
            on_click=lambda e, f=field, c=client: self._on_reset(f, c),
        ).props("flat round dense").classes("text-sm").tooltip(
            _("webui", "settings", "webhooks", "reset")
        )

    def _on_reset(self, field: str, client) -> None:
        """Restore one display-identity field to its default."""
        default = RESET_DEFAULTS[field]
        self._save(field, default)
        if field == "bot_name":
            self._manager.apply_bot_name("")
        elif field == "webhook_avatar":
            # Also drop any locally stored upload so the /avatar endpoint 404s.
            for suffix in AVATAR_EXTENSIONS:
                (CONFIG_PATH / f"avatar{suffix}").unlink(missing_ok=True)
        elif field == "embed_color":
            self._refresh_color(client)
        widgets = self._el.get(getattr(client, "id", None), None)
        if widgets and field in widgets:
            widgets[field].set_value(str(default))  # type: ignore[attr-defined]

    def _on_avatar_upload(self, e) -> None:
        """Accept an image upload, store it under config/, and point the
        avatar setting at this app's /avatar endpoint."""
        ext = Path(e.name).suffix.lower()
        if ext not in AVATAR_EXTENSIONS:
            ui.notify(
                _("webui", "settings", "webhooks", "avatar_rejected"),
                type="negative",
                position="top",
                timeout=6000,
            )
            return
        (CONFIG_PATH / f"avatar{ext}").write_bytes(e.content.read())
        # Keep exactly one stored avatar; a later png upload replaces an older
        # jpg so /avatar never has to guess which file wins.
        for suffix in AVATAR_EXTENSIONS:
            stale = CONFIG_PATH / f"avatar{suffix}"
            if stale.name != f"avatar{ext}":
                stale.unlink(missing_ok=True)
        base = str(e.sender.client.request.base_url).rstrip("/")
        url = f"{base}/avatar"
        self._save("webhook_avatar", url)
        widgets = self._el.get(getattr(e.sender.client, "id", None), None)
        if widgets and "webhook_avatar" in widgets:
            widgets["webhook_avatar"].set_value(url)  # type: ignore[attr-defined]
        ui.notify(
            _("webui", "settings", "webhooks", "avatar_uploaded").format(url=url),
            type="positive",
            position="top",
            timeout=6000,
        )

    def _on_discord_url(self, value: str) -> None:
        self._save("discord_webhook_url", (value or "").strip())

    def _on_bot_name(self, value: str) -> None:
        self._save("bot_name", (value or "").strip()[:64])
        self._manager.apply_bot_name(value or "")

    def _on_avatar(self, value: str) -> None:
        self._save("webhook_avatar", (value or "").strip())

    def _on_color_mode(self, e) -> None:
        self._color_mode = "rgb" if e.value == "rgb" else "hex"
        self._refresh_color(e.sender.client)

    def _on_color_text(self, e) -> None:
        normalized = normalize_hex_color(e.value or "")
        if normalized is None:
            # Ignore what can't be parsed instead of clobbering the saved color.
            self._refresh_color(e.sender.client)
            return
        if str(getattr(self._settings, "embed_color", "") or "") == normalized:
            return
        self._save("embed_color", normalized)
        self._refresh_color(e.sender.client)

    def _on_color_pick(self, e) -> None:
        widgets = self._el.get(getattr(e.sender.client, "id", None), None)
        if not widgets or not widgets.get("armed", False):
            return
        args = e.args
        color = args.get("hex") if isinstance(args, dict) else str(args)
        normalized = normalize_hex_color(color)
        if normalized is None:
            return
        if str(getattr(self._settings, "embed_color", "") or "") == normalized:
            return
        self._save("embed_color", normalized)
        self._refresh_color(e.sender.client)

    def _refresh_color(self, client) -> None:
        """Re-render one browser's color widgets from the saved setting."""
        widgets = self._el.get(getattr(client, "id", None), None)
        if not widgets:
            return
        current = normalize_hex_color(
            str(getattr(self._settings, "embed_color", "") or "")
        ) or DEFAULT_EMBED_COLOR
        widgets["color_input"].set_value(format_color(current, self._color_mode))  # type: ignore[attr-defined]
        widgets["picker"].props(f'model-value="{current}"')  # type: ignore[attr-defined]

    def _on_telegram_token(self, value: str) -> None:
        self._save("telegram_bot_token", (value or "").strip())

    def _on_telegram_chat(self, value: str) -> None:
        self._save("telegram_chat_id", value.strip())

    def _on_event(self, key: str, value: bool) -> None:
        self._save(f"notify_{key}", bool(value))

    def _save(self, name: str, value: object) -> None:
        setattr(self._settings, name, value)
        self._settings.save(force=True)

    # ------------------------------------------------------------------
    # Test delivery
    # ------------------------------------------------------------------

    def _on_test(self, target: str) -> None:
        from webui.notifications import notifications

        try:
            if target == "discord":
                ok, detail = notifications.test("discord")
            else:
                ok, detail = notifications.test("telegram")
        except Exception as exc:  # delivery must never take the UI down
            ok, detail = False, str(exc)
        ui.notify(
            detail,
            type="positive" if ok else "negative",
            position="top",
            timeout=6000,
        )
