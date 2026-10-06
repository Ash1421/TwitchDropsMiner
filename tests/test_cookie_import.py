"""Tests for webui.cookie_import.extract_auth_token."""

from __future__ import annotations

import json

from webui.cookie_import import extract_auth_token


def test_netscape_cookies_txt() -> None:
    data = (
        "www.twitch.tv\tTRUE\t/\tTRUE\t1750000000\tauth-token\tTOKEN_ABC\n"
        "www.twitch.tv\tTRUE\t/\tTRUE\t1750000000\tunique_id\t0000-0000\n"
    ).encode()
    assert extract_auth_token(data) == "TOKEN_ABC"


def test_netscape_ignores_comments_and_blank_lines() -> None:
    data = (
        "# Netscape HTTP Cookie File\n"
        "\n"
        ".twitch.tv\tTRUE\t/\tTRUE\t0\tsome_other\tx\n"
        ".twitch.tv\tTRUE\t/\tTRUE\t1750000000\tauth-token\tPAYLOAD\n"
    ).encode()
    assert extract_auth_token(data) == "PAYLOAD"


def test_json_aiohttp_jar() -> None:
    jar = {
        ".twitch.tv|/unique_id": {
            "unique_id": {
                "key": "unique_id",
                "value": "aa-bb",
                "coded_value": "aa-bb",
                "expires_timestamp": "0",
                "host_only": "false",
            }
        },
        ".twitch.tv|/": {
            "auth-token": {
                "key": "auth-token",
                "value": "JWT_ISH_TOKEN",
                "coded_value": "JWT_ISH_TOKEN",
                "expires_timestamp": "1750000000",
                "host_only": "false",
            }
        },
    }
    assert extract_auth_token(json.dumps(jar).encode()) == "JWT_ISH_TOKEN"


def test_json_prefers_www_twitch_tv_domain() -> None:
    jar = {
        "m.twitch.tv|/": {
            "auth-token": {
                "value": "MOBILE_TOKEN",
                "expires_timestamp": "1750000000",
                "host_only": "true",
            }
        },
        "www.twitch.tv|/": {
            "auth-token": {
                "value": "WEB_TOKEN",
                "expires_timestamp": "1750000000",
                "host_only": "false",
            }
        },
    }
    assert extract_auth_token(json.dumps(jar).encode()) == "WEB_TOKEN"


def test_no_auth_token_returns_none() -> None:
    assert extract_auth_token(b"www.twitch.tv\tTRUE\t/\tTRUE\t0\tunique_id\tx\n") is None
    assert extract_auth_token(json.dumps({"a": {"b": {"value": "c"}}}).encode()) is None


def test_gibberish_returns_none() -> None:
    assert extract_auth_token(b"\xff\xfe not a cookie file \x00") is None
    assert extract_auth_token(b"") is None