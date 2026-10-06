"""Extract the Twitch session cookie from exported cookie files.

Twitch authenticates web sessions with an HttpOnly ``auth-token`` cookie minted
for the WEB client. The device login flow is retired upstream (see
fireph/docker-twitch-drops-miner issues #64/#66), so this fork lets the user
restore a token from the browser instead. Accepted formats:

* aiohttp ``CookieJar.save`` JSON output (as this app writes to cookies.jar)
* Netscape ``cookies.txt`` (tab-separated, as exported by browser extensions)
"""

from __future__ import annotations

import json

_COOKIE_NAME = "auth-token"


def extract_auth_token(data: bytes) -> str | None:
    """Return the auth-token value from raw cookie file bytes, or None."""
    text = _decode(data)
    if text is None:
        return None
    stripped = text.lstrip()
    if stripped.startswith(("{", "[")):
        return _from_json(stripped)
    return _from_http(text)


def _decode(data: bytes) -> str | None:
    for encoding in ("utf-8", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


def _prefer(tokens: list[str]) -> str | None:
    if not tokens:
        return None
    for token in tokens:
        if "www.twitch.tv" in token[0]:
            return token[1]
    return tokens[0][1]


def _from_json(text: str) -> str | None:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    domains = parsed.items() if isinstance(parsed, dict) else ((str(parsed), parsed),)
    candidates: list[tuple[str, str]] = []
    for domain, container in domains:
        if not isinstance(container, dict):
            continue
        for name, entry in container.items():
            if name.lower() != _COOKIE_NAME:
                continue
            value: object
            if isinstance(entry, dict):
                value = entry.get("value")
            else:
                value = entry
            if isinstance(value, str):
                candidates.append((str(domain).lower(), value))
    return _prefer(candidates)


def _from_http(text: str) -> str | None:
    candidates: list[tuple[str, str]] = []
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 7 and parts[5].lower() == _COOKIE_NAME:
            candidates.append((parts[0], parts[6]))
    return _prefer(candidates)