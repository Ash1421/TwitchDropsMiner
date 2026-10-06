"""
Outbound notifications for the WebUI.

Two transports share one dispatcher:

* Discord - an incoming webhook, which is a plain HTTPS POST carrying JSON.
  Cheap and reliable, but strictly one-way: Discord does not accept button
  interactions on a plain webhook, so anything needing a reply has to come
  from the WebUI or a real bot.
* Telegram - Bot API ``sendMessage``. Two-way work (inline buttons, callbacks)
  is possible but needs a long-poll loop, which is deliberately not started
  here yet.

Failures are swallowed and logged: a dead webhook must never stop the miner.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

_TIMEOUT = 10

# Display identity sent with outgoing messages. An empty bot name falls back to
# this default, and the tint is the app's signature purple.
DEFAULT_BOT_NAME = "Twitch Drops Miner"
DEFAULT_EMBED_COLOR = "#7d46ff"

# The official avatar: the pickaxe icon the AppImage already ships, served as
# a GitHub raw blob so Discord can fetch it. It lives upstream on the webui
# branch, so the URL resolves as soon as this lands - no new binary needed.
DEFAULT_AVATAR_URL = (
    "https://raw.githubusercontent.com/fireph/TwitchDropsMiner/"
    "webui/appimage/pickaxe.png"
)

# Avatar uploads are stored under config/ and served from /avatar. Discord
# fetches the avatar server-side, so the dependable raster formats win.
AVATAR_EXTENSIONS = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def normalize_hex_color(text: str) -> str | None:
    """
    Coerce a user-entered color into ``"#rrggbb"``, or ``None`` if unparseable.

    Accepts ``#rrggbb``, ``rrggbb``, ``0xRRGGBB``, 3-digit shorthand and
    ``rgb(r, g, b)``. Case does not matter.
    """
    cleaned = (text or "").strip().lower()
    if cleaned.startswith("rgb(") and cleaned.endswith(")"):
        try:
            parts = [int(part) for part in cleaned[4:-1].split(",")]
        except ValueError:
            return None
        if len(parts) != 3 or any(part < 0 or part > 255 for part in parts):
            return None
        cleaned = f"{parts[0]:02x}{parts[1]:02x}{parts[2]:02x}"
    else:
        if cleaned.startswith("#"):
            cleaned = cleaned[1:]
        elif cleaned.startswith("0x"):
            cleaned = cleaned[2:]
        if len(cleaned) == 3:
            cleaned = "".join(ch * 2 for ch in cleaned)
        if len(cleaned) != 6:
            return None
    try:
        int(cleaned, 16)
    except ValueError:
        return None
    return f"#{cleaned}"


def format_color(hex_value: str | None, mode: str = "hex") -> str:
    """Render a normalized hex value as ``#rrggbb`` or ``rgb(r, g, b)``."""
    normalized = normalize_hex_color(hex_value or "")
    if normalized is None:
        normalized = DEFAULT_EMBED_COLOR
    if mode != "rgb":
        return normalized
    value = normalized.lstrip("#")
    r, g, b = (int(value[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgb({r}, {g}, {b})"


def parse_discord_color(text: str) -> int:
    """Discord embeds want the color as an integer; fall back to the default."""
    normalized = normalize_hex_color(text or "")
    if normalized is None:
        return int(DEFAULT_EMBED_COLOR.lstrip("#"), 16)
    return int(normalized.lstrip("#"), 16)


def bot_display_name(settings: Any) -> str:
    """The name to present as the miner; empty settings fall back to the default."""
    value = getattr(settings, "bot_name", "") or ""
    return value.strip() or DEFAULT_BOT_NAME


class NotificationError(RuntimeError):
    """Raised when a transport is not configured or rejects a message."""


def _post_json(url: str, payload: dict[str, Any]) -> tuple[bool, str]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "TDM-WebUI"},
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            body = response.read().decode("utf-8", "replace")
            if 200 <= response.status < 300:
                return True, f"HTTP {response.status}"
            return False, f"HTTP {response.status}: {body[:200]}"
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        return False, f"HTTP {exc.code}: {body[:200]}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


class NotificationDispatcher:
    """
    Fan a single event out to every configured transport.

    The dispatcher is intentionally tolerant: each transport is attempted
    independently and failures are collected rather than raised, because the
    call sites run inside the miner's main loop.
    """

    def __init__(self) -> None:
        self._settings: Any = None

    def bind(self, settings: Any) -> None:
        """Attach the settings object whose values drive delivery."""
        self._settings = settings

    # -- transports ----------------------------------------------------

    def _discord_configured(self) -> bool:
        return bool(self._get("discord_webhook_url"))

    def _telegram_configured(self) -> bool:
        return bool(self._get("telegram_bot_token") and self._get("telegram_chat_id"))

    def _get(self, name: str, default: str = "") -> Any:
        if self._settings is None:
            return default
        value = getattr(self._settings, name, default)
        return default if value is None else value

    def _send_discord(self, title: str, body: str) -> tuple[bool, str]:
        url = str(self._get("discord_webhook_url"))
        if not url:
            return False, "Discord webhook URL is not set."
        # Discord renders an empty "content" as an error, so always send embed.
        name = bot_display_name(self._settings)
        embed = {
            "title": title[:256],
            "description": body[:4000],
            "color": parse_discord_color(self._get("embed_color", DEFAULT_EMBED_COLOR)),
            "author": {"name": name},
        }
        payload: dict[str, Any] = {
            "username": name,
            "embeds": [embed],
        }
        avatar = str(self._get("webhook_avatar") or "").strip()
        if avatar:
            payload["avatar_url"] = avatar
            embed["author"]["icon_url"] = avatar
        return _post_json(url, payload)

    def _send_telegram(self, title: str, body: str) -> tuple[bool, str]:
        token = str(self._get("telegram_bot_token"))
        chat_id = str(self._get("telegram_chat_id"))
        if not token or not chat_id:
            return False, "Telegram bot token or chat id is not set."
        name = bot_display_name(self._settings)
        return _post_json(
            f"https://api.telegram.org/bot{token}/sendMessage",
            {
                "chat_id": chat_id,
                "text": f"*[{name}] {title}*\n{body}"[:4000],
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            },
        )

    # -- public API ----------------------------------------------------

    def enabled_for(self, event: str) -> bool:
        return bool(self._get(f"notify_{event}", True))

    def send(self, event: str, title: str, body: str) -> dict[str, tuple[bool, str]]:
        """
        Deliver *title*/*body* for *event* to every configured transport.

        Returns a per-transport result mapping for callers that surface detail
        (the test button does; the event hooks ignore it).
        """
        if not self.enabled_for(event):
            return {}
        results: dict[str, tuple[bool, str]] = {}
        if self._discord_configured():
            results["discord"] = self._send_discord(title, body)
        if self._telegram_configured():
            results["telegram"] = self._send_telegram(title, body)
        for name, (ok, detail) in results.items():
            if not ok:
                logger.warning("Notification to %s failed: %s", name, detail)
        return results

    def test(self, target: str) -> tuple[bool, str]:
        """Send a probe to one transport and report the outcome verbatim."""
        if target == "discord":
            if not self._discord_configured():
                return False, "Set a Discord webhook URL first."
            return self._send_discord(
                "Twitch Drops Miner",
                "Test notification. If you can read this, Discord delivery works.",
            )
        if not self._telegram_configured():
            return False, "Set a Telegram bot token and chat id first."
        return self._send_telegram(
            "Twitch Drops Miner",
            "Test notification. If you can read this, Telegram delivery works.",
        )

    def any_configured(self) -> bool:
        return self._discord_configured() or self._telegram_configured()


notifications = NotificationDispatcher()
