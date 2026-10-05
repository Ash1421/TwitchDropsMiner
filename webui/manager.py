# WebUIManager — NiceGUI-based drop-in replacement for the tkinter GUIManager.
#
# Architecture overview
# ---------------------
# The application core (twitch.py) is written against a "GUIManager" interface
# that was originally implemented with tkinter widgets. WebUIManager reimplements
# that same interface so that twitch.py never needs to know whether it is talking
# to a desktop window or a browser tab.
#
# The interface is satisfied in two layers:
#
#   1. *Adapter objects (see adapters/*.py) – one per tkinter widget class
#      (StatusBar, ChannelList, LoginForm, …). They are stored as attributes on
#      WebUIManager (self.status, self.channels, self.login, …) so that every
#      call site in twitch.py keeps working unchanged.
#
#   2. WebUIManager itself – owns the NiceGUI server, the shared UI state, and all
#      top-level methods (print, close, display_drop, …) that twitch.py calls
#      directly on the manager object.
#
# Single-threaded architecture
# ----------------------------
# Since the backend now runs within NiceGUI's event loop, everything operates on
# the same asyncio loop. This eliminates the need for thread synchronization.
# UI updates can be made directly since we're always on the NiceGUI loop.
#
# Late-joining clients
# --------------------
# Multiple browser tabs can connect at any time, even after the miner has been
# running for a while. Mutable UI state is persisted on each panel object, with
# a small amount of global state (status text, console log) on the manager, so
# that a fresh page load can show up to date information.

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import datetime
from http.cookies import SimpleCookie
from pathlib import Path
from typing import TYPE_CHECKING

from nicegui import ui, Client, app

from fastapi import HTTPException
from fastapi.responses import FileResponse

from constants import CONFIG_PATH, COOKIES_PATH, OUTPUT_FORMATTER, FILE_FORMATTER, State
from translate import _
from .adapters import (
    TrayIconAdapter,
    StatusBarAdapter,
    CampaignProgressAdapter,
    ConsoleOutputAdapter,
    ChannelListAdapter,
    InventoryOverviewAdapter,
    LoginFormAdapter,
    WebsocketStatusAdapter,
    SettingsAdapter,
    TabsAdapter,
    HelpTabAdapter,
)
from .handlers import WebUIOutputHandler
from .notifications import (
    AVATAR_EXTENSIONS,
    DEFAULT_BOT_NAME,
    bot_display_name,
    notifications,
)
from .html_utils import favicon_js, request_notification_permission_js
from . import themes
from .components import (
    BasePanel,
    MainPanel,
    InventoryPanel,
    HelpPanel,
    SettingsPanel,
    HeaderBar,
)

if TYPE_CHECKING:
    from twitch import Twitch
    from utils import Game

logger = logging.getLogger("TwitchDrops")


class WebUIManager:
    """
    NiceGUI-based web interface that is a drop-in replacement for the tkinter GUIManager.

    WebUIManager owns:
    - The NiceGUI HTTP server (started in a daemon thread by _start_server).
    - All shared mutable UI state (status text, console log, channel map, …)
      that the *Adapter attribute objects write to and the NiceGUI timer reads from.
    - The top-level methods (print, close, display_drop, …) called directly by
      twitch.py on the manager object.

    The *Adapter objects stored as attributes mirror the tkinter widget classes that
    twitch.py expects (self.status → StatusBar, self.channels → ChannelList, …).
    See adapters/*.py for details.
    """

    def __init__(self, twitch: "Twitch"):
        self._twitch: "Twitch" = twitch
        self._close_requested = asyncio.Event()
        self._reload_requested = asyncio.Event()
        self._running = False

        # Outbound notifications read their targets from the same settings
        # object the UI writes to.
        notifications.bind(twitch.settings)

        # Shared UI state
        self._current_icon: str = "pickaxe"
        self._status_text: str = "Initializing..."
        self._bot_name_text: str = DEFAULT_BOT_NAME
        self._title_text: str = DEFAULT_BOT_NAME
        # Set by main_webui when the backend exits with an error (captcha or a
        # fatal exception); overrides the usually-finite status text so
        # integrations report the real state instead of a stale one.
        self._terminated_reason: str | None = None

        # Adapters - mirrors of classes in gui.py
        self.tray = TrayIconAdapter(self)
        self.status = StatusBarAdapter(self)
        self.progress = CampaignProgressAdapter(self)
        self.output = ConsoleOutputAdapter(self)
        self.channels = ChannelListAdapter(self)
        self.inv = InventoryOverviewAdapter(self)
        self.login = LoginFormAdapter(self)
        self.websockets = WebsocketStatusAdapter(self)
        self.settings = SettingsAdapter(self)
        self.tabs = TabsAdapter()
        self.help = HelpTabAdapter(self)

        # Panel objects - own all widget references and state for their tab
        self.header_bar: HeaderBar = HeaderBar(self)
        self.main_panel: MainPanel = MainPanel(self)
        self.inventory_panel: BasePanel = InventoryPanel(self)
        self.settings_panel: BasePanel = SettingsPanel(self)
        self.help_panel: BasePanel = HelpPanel(self)

        # Two-way Telegram integration (long-poll command bot).
        from .telegram_bot import TelegramCommandPoller

        self.telegram: TelegramCommandPoller = TelegramCommandPoller(self)

        self._setup_ui()

        # Use the same log formatter as gui.py's _TKOutputHandler so messages look identical.
        self._handler = WebUIOutputHandler(self)
        self._handler.setFormatter(OUTPUT_FORMATTER)
        logger.addHandler(self._handler)
        if (logging_level := logger.getEffectiveLevel()) < logging.ERROR:
            self.print(f"Logging level: {logging.getLevelName(logging_level)}")

    def _setup_ui(self):
        """Register the NiceGUI page handler. The inner index() function runs once
        per browser connection, building the full UI for that client."""
        app.add_static_files("/icons", str(Path(__file__).parent.parent / "icons"))

        @app.get("/avatar")
        def _avatar() -> FileResponse:
            """Serve a locally stored avatar upload so tests can embed it and
            a publicly reachable deployment can feed it to Discord."""
            for ext, mime in AVATAR_EXTENSIONS.items():
                path = CONFIG_PATH / f"avatar{ext}"
                if path.exists():
                    return FileResponse(path, media_type=mime)
            raise HTTPException(status_code=404, detail="no avatar uploaded")

        @ui.page("/")
        def index(tab: str = "main"):
            # The header always shows the bot identity; the browser tab title
            # follows the bot name unless a custom title is pinned. Header and
            # title text are broadcast through their own attributes so late
            # connections and multi-tab edits stay in sync.
            self._bot_name_text = bot_display_name(self._twitch.settings)
            self._title_text = self._effective_title()
            ui.page_title(self._title_text)
            themes.apply(themes.resolve(self._twitch.settings))

            ui.query(".nicegui-content").classes("p-0")

            # Fixed header + scrollable content below it only.
            # .q-page-container starts at y=0 (behind the fixed header) with
            # Quasar-injected padding-top equal to the header height. Putting
            # overflow-y-auto on it makes the scrollbar run from y=0 (behind the
            # header) downward. Moving scroll to .q-page fixes this: .q-page
            # begins after the padding, so its scrollbar starts below the header.
            ui.query("html").classes("!overflow-hidden !h-screen")
            ui.query("body").classes("!overflow-hidden !h-screen")
            ui.query(".q-page-container").classes(
                "!box-border !h-screen !overflow-hidden"
            )
            ui.query(".q-page").classes("!h-full !min-h-0 !overflow-y-auto")

            # Set favicon to current icon state for late-joining clients
            ui.run_javascript(favicon_js(self._current_icon))

            # Request notification permission on page load if enabled
            if self._twitch.settings.tray_notifications:
                ui.run_javascript(request_notification_permission_js())

            # Alias so nested closures below can reference the manager unambiguously.
            manager = self

            # Fall back to 'main' if the ?tab= query param is not a known tab name.
            initial_tab = (
                tab if tab in ("main", "inventory", "settings", "help") else "main"
            )

            def _on_tab_change(e):
                t = str(e.value)
                ui.run_javascript(f"history.replaceState(null, '', '?tab={t}')")

            tabs = manager.header_bar.build(initial_tab, _on_tab_change)

            with ui.tab_panels(tabs, value=initial_tab).classes("w-full h-full"):
                with ui.tab_panel("main"):
                    manager.main_panel.build()

                with ui.tab_panel("inventory"):
                    manager.inventory_panel.build()

                with ui.tab_panel("settings"):
                    manager.settings_panel.build()

                with ui.tab_panel("help"):
                    manager.help_panel.build()

    async def _invalidate_token(self) -> None:
        twitch = self._twitch
        auth_state = await twitch.get_auth()
        async with twitch.request(
            "POST",
            "https://id.twitch.tv/oauth2/revoke",
            data={
                "client_id": twitch._client_type.CLIENT_ID,
                "token": auth_state.access_token,
            },
        ) as response:
            if response.status != 200:
                logger.error(f"Failed to invalidate the auth token: {response.status}")
        auth_state.invalidate(delete_cookies=True)

    def set_dark_mode(self, enabled: bool) -> None:
        """Apply dark mode to all connected clients."""
        self._twitch.settings.dark_mode = enabled
        self._twitch.settings.save(force=True)

    def set_theme(self, name: str) -> None:
        """
        Persist the chosen theme and mirror the legacy ``dark_mode`` flag.

        Connected clients are reloaded because the palette is applied during page
        construction, so existing tabs would otherwise keep the old colours.
        """
        if name not in themes.THEMES:
            return
        settings = self._twitch.settings
        settings.theme = name  # type: ignore[attr-defined]
        settings.dark_mode = themes.THEMES[name].dark
        settings.save(force=True)
        for client in app.clients():
            with client:
                ui.run_javascript("location.reload()")

    def apply_bot_name(self, name: str) -> None:
        """Reflect a bot-name edit in the header and (unless a custom tab title
        is pinned) in every open tab's title."""
        self._refresh_title()
        self._refresh_header()

    def apply_tab_title(self) -> None:
        """Push a custom-tab-title toggle or text edit to every open tab."""
        self._refresh_title()

    def _effective_title(self) -> str:
        """The browser tab title: the pinned custom title, or the bot name."""
        settings = self._twitch.settings
        if getattr(settings, "custom_tab_title", False):
            custom = (getattr(settings, "tab_title", "") or "").strip()
            if custom:
                return custom[:128]
        return bot_display_name(self._twitch.settings)

    def _refresh_title(self) -> None:
        """Recompute and broadcast the tab title to every open tab."""
        self._title_text = self._effective_title()
        title = self._title_text.replace("'", "\\'")
        for client in app.clients():
            with client:
                with suppress(Exception):
                    ui.page_title(self._title_text)
                ui.run_javascript(f"document.title = '{title}'")

    def _refresh_header(self) -> None:
        """Recompute the header label, which always shows the bot identity."""
        self._bot_name_text = bot_display_name(self._twitch.settings)

    @property
    def running(self) -> bool:
        return self._running

    @property
    def close_requested(self) -> bool:
        return self._close_requested.is_set()

    def print(self, message: str):
        """Append a timestamped line to the in-browser console log.
        Matches gui.py ConsoleOutput.print(): each line of a multiline message gets its own stamp.
        """
        stamp = datetime.now().strftime("%X")
        lines = [f"{stamp}: {line}" for line in message.split("\n")]

        self.main_panel.push_console(lines)

        # Mirror to stdout/file when stdlog is enabled.
        if self._twitch.settings.stdlog:
            record = logging.LogRecord(
                name="GUI",
                level=logging.INFO,
                pathname="",
                lineno=0,
                msg=message,
                args=(),
                exc_info=None,
            )
            print(FILE_FORMATTER.format(record))

    def close(self, *args) -> int:
        """Signal the main loop to shut down (mirrors GUIManager.close).

        Runs on SIGTERM/SIGINT - i.e. ``docker stop`` or a watchtower/autoheal
        restart - so this is the one reliable place to tell the user the
        container is going down. Best-effort: a webhook must never block the
        shutdown.
        """
        try:
            notifications.send(
                "shutdown",
                "Miner is stopping",
                "The container is shutting down or being restarted "
                "(watchtower/autoheal update, or a `docker stop`).",
            )
        except Exception:
            pass
        self._close_requested.set()
        self._twitch.close()
        return 0

    async def wait_until_closed(self):
        """Wait until the user closes the window"""
        await self._close_requested.wait()

    def stop(self):
        self._running = False

    def close_window(self):
        logger.removeHandler(self._handler)
        app.shutdown()

    def grab_attention(self, *, sound: bool = True):
        """Browser equivalent of the desktop grab-attention (flash/sound). Logs a visible prompt instead."""
        self.print("⚠️ Attention: Application requires user interaction")

    def start(self):
        self._running = True
        self.telegram.start()

    async def coro_unless_closed(self, coro):
        """Run coro, but raise ExitRequest or ReloadRequest if those are signalled first."""
        from exceptions import ExitRequest, ReloadRequest

        tasks = [
            asyncio.create_task(coro),
            asyncio.create_task(self._close_requested.wait()),
            asyncio.create_task(self._reload_requested.wait()),
        ]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if self._close_requested.is_set():
            raise ExitRequest()
        if self._reload_requested.is_set():
            self._reload_requested.clear()
            raise ReloadRequest()
        return await next(iter(done))

    def clear_drop(self):
        """Clear the current drop display"""
        self.main_panel.clear_drop()

    def request_reload(self) -> bool:
        """Soft reload - same action as Settings -> Reload button."""
        if self._twitch._state is State.EXIT:
            return False
        self._twitch.state_change(State.INVENTORY_FETCH)()
        return True

    def restart(self) -> None:
        self._reload_requested.set()
        self._twitch.state_change(State.INVENTORY_FETCH)()

    async def logout(self) -> None:
        self.channels.clear()
        await self._invalidate_token()
        self.restart()

    async def import_auth_token(self, token: str) -> tuple[bool, str]:
        """Restore a Twitch session from an ``auth-token`` cookie value.

        The token is validated against id.twitch.tv/oauth2/validate *before*
        the persisted jar is touched, so a token minted for a different client
        can never put the app into the login crash loop (the cookie-client
        mismatch branch in ``twitch._validate`` deletes the jar and falls into
        the retired device flow). On success the jar is rewritten with just the
        auth-token cookie and the backend restarts, which re-runs ``_validate``
        in ``get_auth`` and completes the login.

        Returns (ok, message).
        """
        token = (token or "").strip()
        if not token:
            return False, _("webui", "login", "restore_empty")
        client = self._twitch._client_type
        async with self._twitch.request(
            "GET",
            "https://id.twitch.tv/oauth2/validate",
            headers={"Authorization": f"OAuth {token}"},
        ) as response:
            if response.status != 200:
                return False, _("webui", "login", "restore_invalid")
            validate_response = await response.json()
        if validate_response.get("client_id") != client.CLIENT_ID:
            return False, _("webui", "login", "restore_client").format(
                actual=validate_response.get("client_id")
            )
        session = await self._twitch.get_session()
        jar = session.cookie_jar
        jar.clear()
        auth_cookie = SimpleCookie()
        auth_cookie["auth-token"] = token
        auth_cookie["auth-token"]["domain"] = client.CLIENT_URL.host
        auth_cookie["auth-token"]["path"] = "/"
        jar.update_cookies(auth_cookie, client.CLIENT_URL)
        jar.save(COOKIES_PATH)
        self.print(_("webui", "login", "restore_ok"))
        self.restart()
        return True, _("webui", "login", "restore_ok")

    async def import_auth_token_file(self, data: bytes) -> tuple[bool, str]:
        """Restore a Twitch session from an exported cookie file."""
        from .cookie_import import extract_auth_token

        token = extract_auth_token(data)
        if token is None:
            return False, _("webui", "login", "restore_no_token")
        return await self.import_auth_token(token)

    def display_drop(self, drop, *, countdown: bool = True, subone: bool = False):
        """Display current drop information"""
        self.progress.display(drop, countdown=countdown, subone=subone)

    def set_games(self, games: set[Game]) -> None:
        """Set available games for settings"""
        self.settings_panel.set_games(games)

    def set_campaigns(self, campaigns: set) -> None:
        """
        Publish known campaigns so the Badges list can offer per-campaign choices.

        Upstream's ``gui.set_games`` call only forwards game objects, but badge
        ownership is tracked per campaign, so the campaigns are passed alongside.
        """
        self.settings_panel.set_campaigns(campaigns)

    def apply_theme(self, dark: bool) -> None:
        """Apply theme (no-op for web UI)"""
        pass

    def save(self, *, force: bool = False) -> None:
        """Save GUI state (no-op for web UI)"""
        pass

    def prevent_close(self):
        """Prevent the application from closing (used for error states)"""
        self._close_requested.clear()
        self.print("Application prevented from closing due to error state")

    def update_status(self, text: str) -> None:
        """Update status text — bindings propagate the new value to all connected clients."""
        self._status_text = text

    def mark_terminated(self, reason: str) -> None:
        """Record that the backend stopped abnormally (fatal error, captcha)."""
        self._terminated_reason = reason or "Terminated"

    def status_summary(self) -> dict[str, object]:
        """A plain snapshot for integrations (the Telegram /status command)."""
        twitch = self._twitch
        auth = getattr(twitch, "_auth_state", None)
        logged_in = bool(
            auth is not None
            and getattr(auth, "_logged_in", None) is not None
            and auth._logged_in.is_set()
        )
        watching_task = getattr(twitch, "_watching_task", None)
        return {
            "logged_in": logged_in,
            "user_id": getattr(auth, "user_id", None) if logged_in else None,
            "status": self._terminated_reason or self._status_text,
            "terminated": self._terminated_reason is not None,
            "channels": len(getattr(twitch, "channels", None) or ()),
            "watching": bool(
                self._terminated_reason is None
                and watching_task is not None
                and not watching_task.done()
            ),
        }

    async def watch_channel(self, login: str) -> tuple[bool, str]:
        """Force the miner toward a tracked stream (the Telegram /watch command).

        Returns (True, "") after selecting the channel and requesting a channel
        switch, or (False, reason) when the stream is unknown or the backend is
        not running (e.g. after a fatal error).
        """
        login = (login or "").strip().lower()
        if not login:
            return False, "No stream given."
        if self._terminated_reason is not None:
            return (
                False,
                f"The miner is not running ({self._terminated_reason}).",
            )
        twitch = self._twitch
        channel = next(
            (
                channel
                for channel in (getattr(twitch, "channels", None) or {}).values()
                if getattr(channel, "name", "").lower() == login
            ),
            None,
        )
        if channel is None:
            return (
                False,
                f"Unknown stream '{login}' - add its game in the WebUI game list first.",
            )
        self.main_panel.select_channel(channel)
        twitch.state_change(State.CHANNEL_SWITCH)()
        return True, ""

    def streams_summary(self) -> list[dict[str, object]]:
        """Snapshot of every tracked streamer for the Telegram /streams command."""
        channels = (getattr(self._twitch, "channels", None) or {}).values()
        rows: list[dict[str, object]] = []
        for channel in channels:
            game = getattr(channel, "game", None)
            rows.append(
                {
                    "login": getattr(channel, "_login", "")
                    or getattr(channel, "name", ""),
                    "display": getattr(channel, "name", ""),
                    "online": bool(getattr(channel, "online", False)),
                    "viewers": getattr(channel, "viewers", None),
                    "game": game.name if game is not None else None,
                    "drops": bool(getattr(channel, "drops_enabled", False)),
                }
            )
        rows.sort(key=lambda row: (not row["online"], not row["drops"], str(row["display"]).lower()))
        return rows
