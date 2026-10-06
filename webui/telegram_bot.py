"""
Two-way Telegram bot for the TDM: long-polls getUpdates and answers commands.

Outbound notifications are one-way (``sendMessage``). For the miner to answer
slash commands such as ``/help`` or ``/status``, something must listen for
inbound updates, so this module runs a lightweight long-poll loop against the
Bot API. It only ever replies to the configured chat - every other chat is
ignored.

Loop design
-----------
* Each ``getUpdates`` call blocks up to POLL_TIMEOUT seconds on Telegram's side
  (long polling). The network call rides ``asyncio.to_thread`` so it never
  blocks the NiceGUI event loop, and ``_poll_loop`` is itself an asyncio task.
* The loop reads the token and chat id from settings on every iteration, so an
  edit in the WebUI is picked up without a restart.
* ``offset`` is kept in memory; a process restart may re-read a handful of
  already-answered updates and re-answer them, which is harmless.
* The loop stops itself as soon as the manager starts closing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Awaitable, Callable

from webui.notifications import DEFAULT_BOT_NAME, bot_display_name, notifications

logger = logging.getLogger(__name__)

# Seconds Telegram should keep a getUpdates request open before returning.
POLL_TIMEOUT = 25
_HTTP_TIMEOUT = POLL_TIMEOUT + 15


def _api_url(token: str, method: str) -> str:
    return f"https://api.telegram.org/bot{token}/{method}"


# (command, one-line summary) - kept in one place so /help always matches the
# dispatch table and the two can be tested against each other.
COMMANDS: list[tuple[str, str]] = [
    ("/start", "Show this menu"),
    ("/help", "Show this menu"),
    ("/status", "Current miner status"),
    ("/streams", "Tracked streamers with drop status"),
    ("/test", "Send a test notification to this chat"),
    ("/testdiscord", "Send a test Discord notification"),
    ("/watch <stream>", "Force the miner to watch a stream"),
]


def help_text(name: str = DEFAULT_BOT_NAME) -> str:
    """The /help reply: every command in COMMANDS plus a login note."""
    lines = [f"*[{name}] - Available commands*"]
    for command, summary in COMMANDS:
        lines.append(f"`{command}` - {summary}")
    lines.append(
        "_Device login is retired - sign in from the WebUI, "
        "or restore a saved browser session._"
    )
    return "\n".join(lines)


def _format_viewers(viewers: Any) -> str:
    if not viewers:
        return ""
    viewer_count = int(viewers)
    if viewer_count >= 1000:
        return f"{viewer_count / 1000:.1f}k"
    return str(viewer_count)


def streams_reply(streams: list[dict[str, Any]], name: str = DEFAULT_BOT_NAME) -> str:
    """Render a :meth:`~webui.manager.WebUIManager.streams_summary` snapshot.

    Online/eligible streamers are listed first, each with a copy-pasteable
    ``/watch <login>`` line so the caller can jump straight to one.
    """
    lines = [f"*[{name}] - Tracked streamers ({len(streams)})*"]
    if not streams:
        lines.append("None tracked yet - add games in the WebUI game list first.")
        return "\n".join(lines)
    for row in streams[:20]:
        display = row.get("display") or row.get("login") or "-"
        login = row.get("login") or ""
        state = "ONLINE" if row.get("online") else "offline"
        drops = "drops: YES" if row.get("drops") else "drops: no"
        extras = []
        viewers = _format_viewers(row.get("viewers"))
        if viewers:
            extras.append(f"{viewers} viewers")
        game = row.get("game")
        if game:
            extras.append(str(game))
        detail = f" - {', '.join(extras)}" if extras else ""
        lines.append(
            f"{'•' if row.get('online') else '–'} {display} ({state}, {drops}{detail})"
        )
        if row.get("online"):
            lines.append(f"  `/watch {login}`")
    if len(streams) > 20:
        lines.append(f"_…and {len(streams) - 20} more._")
    lines.append("_Only streamers of your added games appear here._")
    return "\n".join(lines)


def status_reply(summary: dict[str, Any], name: str = DEFAULT_BOT_NAME) -> str:
    """Render a :meth:`~webui.manager.WebUIManager.status_summary` snapshot."""
    logged_in = bool(summary.get("logged_in"))
    lines = [f"*[{name}] - Status*"]
    if logged_in:
        user_id = summary.get("user_id")
        lines.append("Login: yes" + (f" (user {user_id})" if user_id else ""))
    else:
        lines.append("Login: no")
    lines.extend(
        [
            f"State: {summary.get('status') or '-'}",
            f"Channels tracked: {summary.get('channels', 0)}",
            f"Watching: {'yes' if summary.get('watching') else 'no'}",
        ]
    )
    if not logged_in:
        lines.append("_Log in from the WebUI, or restore a Twitch session cookie._")
    return "\n".join(lines)


# -- low-level Bot API ------------------------------------------------

def _parse_json(body: str) -> dict[str, Any]:
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _http_request(url: str, *, payload: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    """POST JSON (or GET when payload is None) and return (status, parsed)."""
    kwargs: dict[str, Any] = {"headers": {"User-Agent": "TDM-WebUI"}}
    if payload is not None:
        kwargs["data"] = json.dumps(payload).encode("utf-8")
        kwargs["headers"]["Content-Type"] = "application/json"
    request = urllib.request.Request(url, **kwargs)
    try:
        with urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT) as response:
            body = response.read().decode("utf-8", "replace")
            return response.status, _parse_json(body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        return exc.code, _parse_json(body)
    except Exception as exc:  # network errors, timeouts, malformed replies
        raise RuntimeError(f"{type(exc).__name__}: {exc}") from exc


def get_updates(token: str, offset: int, *, timeout: int = POLL_TIMEOUT) -> list[dict[str, Any]]:
    """Long-poll Telegram for new messages; returns the list of updates."""
    params = {
        "timeout": timeout,
        "offset": offset,
        "allowed_updates": json.dumps(["message", "edited_message"]),
    }
    url = f"{_api_url(token, 'getUpdates')}?{urllib.parse.urlencode(params)}"
    status, data = _http_request(url)
    if status != 200:
        raise RuntimeError(f"getUpdates HTTP {status}")
    return data.get("result") or []


def send_message(token: str, chat_id: str, text: str) -> bool:
    """Send one plain text reply and report success."""
    status, data = _http_request(
        _api_url(token, "sendMessage"),
        payload={
            "chat_id": chat_id,
            "text": text[:4000],
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        },
    )
    if status != 200:
        logger.warning("sendMessage failed: HTTP %s (%s)", status, data)
        return False
    return True


# -- message handling -------------------------------------------------

async def respond(
    message: dict[str, Any],
    *,
    manager: Any,
    chat_id: str,
    name: str | None = None,
    send_test: Callable[[str], Awaitable[tuple[bool, str]]] | None = None,
    watch: Callable[[str], Awaitable[tuple[bool, str]]] | None = None,
) -> list[str]:
    """
    Turn one inbound Telegram message into reply texts (possibly none).

    Only messages from ``chat_id`` (the configured owner chat) are answered.
    ``send_test`` is an async callable taking a channel target (``"telegram"``
    or ``"discord"``) and returning (ok, detail); it is invoked only for
    ``/test`` and ``/testdiscord`` so unit tests can inject a fake instead of
    the network. ``watch`` is an async callable taking a stream login and
    returning (ok, detail); it is invoked only for ``/watch``.
    """
    if str((message.get("chat") or {}).get("id", "")) != str(chat_id).strip():
        return []
    text = (message.get("text") or "").strip()
    if not text.startswith("/"):
        return []
    command, _, argument = text.partition(" ")
    command = command.lower()
    if name is None:
        name = bot_display_name(getattr(getattr(manager, "_twitch", None), "settings", None))
    if command in ("/start", "/help"):
        return [help_text(name)]
    if command == "/status":
        return [status_reply(manager.status_summary(), name)]
    if command == "/streams":
        return [streams_reply(manager.streams_summary(), name)]
    if command == "/testdiscord":
        if send_test is None:
            return ["Test delivery is not available right now."]
        ok, detail = await send_test("discord")
        return ["Test Discord notification sent." if ok else f"Test failed: {detail}"]
    if command == "/test":
        if send_test is None:
            return ["Test delivery is not available right now."]
        ok, detail = await send_test("telegram")
        return ["Test notification sent." if ok else f"Test failed: {detail}"]
    if command == "/watch":
        login = argument.strip()
        if not login or login.startswith("/"):
            return ["Usage: `{0} <stream>` - sign a stream login, e.g. `{0} xqc`".format(command)]
        if watch is None:
            return ["Watching from Telegram is unavailable right now."]
        ok, detail = await watch(login)
        return [f"Switching to *{login}*..." if ok else detail]
    return [f"Unknown command `{command}`. Send /help for the list."]


# -- polling loop -----------------------------------------------------

class TelegramCommandPoller:
    """Long-polls the Bot API and answers commands from the owner chat."""

    def __init__(self, manager: Any) -> None:
        self._manager = manager
        self._offset: int = 0
        self._task: asyncio.Task[None] | None = None

    @property
    def _settings(self) -> Any:
        return self._manager._twitch.settings

    def _credentials(self) -> tuple[str, str]:
        token = str(getattr(self._settings, "telegram_bot_token", "") or "").strip()
        chat_id = str(getattr(self._settings, "telegram_chat_id", "") or "").strip()
        return token, chat_id

    def start(self) -> None:
        """Spawn the poll task once (idempotent). No-op without an event loop."""
        if self._task is not None and not self._task.done():
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        self._task = asyncio.create_task(self._poll_loop(), name="telegram-poller")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _poll_loop(self) -> None:
        logger.info("Telegram command polling started")
        try:
            while not self._manager.close_requested:
                token, chat_id = self._credentials()
                if not (token and chat_id):
                    await asyncio.sleep(10)
                    continue
                try:
                    updates = await asyncio.wait_for(
                        asyncio.to_thread(get_updates, token, self._offset),
                        timeout=_HTTP_TIMEOUT + 10,
                    )
                except asyncio.TimeoutError:
                    continue
                except Exception as exc:
                    logger.warning("Telegram getUpdates failed: %s", exc)
                    await asyncio.sleep(30)
                    continue
                for update in updates or []:
                    update_id = update.get("update_id")
                    if update_id is not None and update_id + 1 > self._offset:
                        self._offset = update_id + 1
                    message = update.get("message") or update.get("edited_message")
                    if not isinstance(message, dict):
                        continue
                    replies = await respond(
                        message,
                        manager=self._manager,
                        chat_id=chat_id,
                        send_test=lambda target: asyncio.to_thread(notifications.test, target),
                        watch=self._manager.watch_channel,
                    )
                    for text in replies:
                        try:
                            await asyncio.to_thread(send_message, token, chat_id, text)
                        except Exception as exc:
                            logger.warning("Telegram reply failed: %s", exc)
        except asyncio.CancelledError:
            raise
        logger.info("Telegram command polling stopped")