"""
Fork-specific translations for the WebUI.

Imported for its side effects: merges fork strings into the Translator and
wraps ``set_language`` so ``webui/lang/<language>.json`` overrides are applied
on language switch.
"""

from __future__ import annotations

import copy
import json
from typing import Any

import translate as _translate
from constants import DEFAULT_LANG, IS_PACKAGED, _resource_path
from utils import json_save

# Source of truth for fork-specific strings.  In dev mode this is written to
# webui/lang/English.json so translators can copy it as a template.  At runtime
# it is deep-merged into the Translator so individual upstream keys (e.g.
# gui.*) can be overridden without wiping out siblings.  For other languages,
# set_language's json_load fills missing keys from the patched default
# translation (English fallback); we wrap set_language so
# webui/lang/<language>.json overrides are applied on top.
default_webui_translation: dict[str, Any] = {
    "webui": {
        "settings": {
            "advanced": {
                "priority_link_override": "Mine unlinked games from the Priority List: "
            },
            "general": {"language": "Language: ", "invalid_proxy": "Invalid proxy URL"},
            "webhooks": {
                "name": "Notifications",
                "hint": "Discord uses an incoming webhook and is one-way. "
                "Telegram can reply to messages once the bot is connected.",
                "bot_name": "Webhook / bot name:",
                "avatar_url": "Avatar URL:",
                "avatar_upload": "Upload avatar image",
                "avatar_rejected": "Unsupported image type",
                "avatar_hint": "PNG/JPG/GIF/WebP, up to 5 MB. An uploaded file is "
                "stored on this device and served from this app's `/avatar`, so "
                "Discord can fetch it only if this address is reachable from the "
                "internet (public host or port-forward). Leave empty to keep the "
                "icon configured on the webhook itself — the pickaxe.",
                "avatar_uploaded": "Avatar uploaded — served from {url}",
                "embed_color": "Embed color:",
                "color_hex": "Hex",
                "color_rgb": "RGB",
                "reset": "Reset to default",
                "secret_configured": "Already set — leave blank to keep the stored value",
                "discord_url": "Discord webhook URL:",
                "telegram_token": "Telegram bot token:",
                "telegram_chat": "Telegram chat ID:",
                "telegram_commands_hint": "Once both fields are set, the bot answers /start, /help, /status, /streams, /test, /testdiscord and /watch <stream> in that chat.",
                "telegram_guide": "How to create a Telegram bot",
                "telegram_guide_md": (
                    "1. Send `/newbot` to [@BotFather](https://t.me/BotFather) "
                    "on Telegram and follow the prompts.\n"
                    "2. Copy the token it gives you (`123456:ABC-DEF...`) into the "
                    "field above.\n"
                    "3. To find your chat ID, message [@userinfobot](https://t.me/userinfobot) "
                    "and read the `id` from its reply, or call "
                    "`https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser.\n\n"
                    "Once both fields are set, the bot answers slash commands in "
                    "that chat: `/help`, `/status`, `/streams`, `/test`, "
                    "`/testdiscord`, `/watch <stream>` and `/start`.\n\n"
                    "The official guide lives here: "
                    "[Bots: An introduction for developers](https://core.telegram.org/bots)."
                ),
                "events": "Send a message when:",
                "event_drop_claimed": "a drop is claimed",
                "event_campaign_complete": "a campaign is completed",
                "event_channel_switch": "the watched channel changes",
                "event_fatal_error": "the miner hits a fatal error",
                "event_startup": "the container starts up",
                "event_shutdown": "the container is stopping / restarting",
                "test_hint": "Secrets are stored in config/settings.json, which is "
                "gitignored. Fields show the stored value behind the eye toggle; "
                "clearing a secret field removes it.",
                "test_discord": "Test Discord",
                "test_telegram": "Test Telegram",
            },
        },
        "help": {
            "about": "About",
            "created_by": "Application created by:",
            "repository": "Repository:",
            "version": "Version:",
            "donate": "Donate:",
            "donate_text": "If you like the application and found it useful, please consider donating to DevilXD to support them!",
        },
        "auth": {
            "create_account": "Create an admin account",
            "username": "Username",
            "password": "Password",
            "confirm_password": "Confirm password",
            "username_required": "Username Required",
            "password_required": "Password Required",
            "password_mismatch": "Password Mismatch",
            "register": "Register",
            "sign_in": "Sign in",
        },
        "login": {
            "logout": "Logout",
            "browser_title": "Twitch login",
            "browser_login": "Browser login",
            "starting_browser": "Starting browser…",
            "show_browser": "Show login browser",
            "close_view": "Close view",
            "cancel_browser": "Cancel login",
            "restore_title": "Stuck on login? Restore a saved Twitch session",
            "restore_hint": (
                "Log in via the Login button and enter the device code shown "
                "in the box above. If that flow is unavailable, restore a "
                "saved browser session instead:\n"
                "1) Sign in to twitch.tv in a browser\n"
                "2) DevTools → Application → Cookies → www.twitch.tv\n"
                "3) Copy the \"auth-token\" value\n\n"
                "A token is a full session credential — never share it."
            ),
            "restore_token": "Paste the Twitch auth-token",
            "restore_button": "Restore & re-login",
            "restore_upload": "…or upload cookies.jar / cookies.txt",
            "restore_empty": "No auth-token entered.",
            "restore_invalid": "Twitch rejected that token. Export a fresh one.",
            "restore_no_token": "No auth-token cookie was found in that file.",
            "restore_client": (
                "That token belongs to a different Twitch client (got {actual})."
            ),
            "restore_ok": "Twitch session restored. Re-authenticating…",
            "device_code": "Enter this code on the Twitch device activation page:",
        },
        "inventory": {"no_campaigns": "No campaigns match the current filters."},
        "game_list": {
            "no_campaigns": '"{name}" has no active drop campaigns.',
            "add_anyway": "Add it anyway?",
            "cancel": "Cancel",
            "add": "Add",
        },
        "status": {"name": "Status:"},
    }
}

_WEBUI_LANG_DIR = _resource_path("webui/lang")


def _deep_merge_into(dst: dict[str, Any], src: dict[str, Any]) -> None:
    for k, v in src.items():
        if k in dst and isinstance(dst[k], dict) and isinstance(v, dict):
            _deep_merge_into(dst[k], v)
        else:
            dst[k] = v


def _deep_merge(dst: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]:
    """Non-destructive deep merge; *src* wins. Returns a new dict."""
    result = copy.deepcopy(dst)
    _deep_merge_into(result, src)
    return result


# In dev mode, write the English template so translators can copy it.
if not IS_PACKAGED:
    _WEBUI_LANG_DIR.mkdir(parents=True, exist_ok=True)
    json_save(
        _WEBUI_LANG_DIR / f"{DEFAULT_LANG}.json", default_webui_translation, sort=True
    )

# Merge fork strings into the live Translator and default_translation.
_deep_merge_into(_translate.default_translation, default_webui_translation)  # type: ignore[arg-type]
_deep_merge_into(_translate._._translation, default_webui_translation)  # type: ignore[arg-type]

_original_set_language = _translate.Translator.set_language


def _set_language(self: Any, language: str) -> None:
    _original_set_language(self, language)
    _lang_path = _WEBUI_LANG_DIR / f"{language}.json"
    if _lang_path.exists():
        with _lang_path.open(encoding="utf-8") as _f:
            # Non-destructive merge: json_load's merge_json copies references from
            # default_translation into self._translation, so an in-place merge
            # would corrupt default_translation. _deep_merge returns a new dict.
            self._translation = _deep_merge(  # type: ignore[assignment, arg-type]
                self._translation, json.load(_f)
            )


setattr(_translate.Translator, "set_language", _set_language)
