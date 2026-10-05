"""
BepisDB Downloader compatibility update.

Original project:
    BepisDB-downloader by 0AwsD0
    https://github.com/0AwsD0/BepisDB-downloader

Updated version by:
    LuC!f3r

r15 restores browser automation for JavaScript-rendered BepisDB pages while keeping
numeric-only Card/Scene modes, batching, completion verification, and safe cleanup.
"""

from __future__ import annotations

import configparser
import http.cookiejar
import os
import re
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener

try:
    from selenium import webdriver
    from selenium.common.exceptions import TimeoutException, WebDriverException
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.support.ui import WebDriverWait
except ImportError:
    webdriver = None
    TimeoutException = WebDriverException = Exception
    By = WebDriverWait = None


APP_VERSION = "2026.09.28-r29"
PROJECT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = PROJECT_DIR / "config.ini"
BASE_URL = "https://db.bepis.moe"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# r11 no longer has browser settings. The two original 5-second delays remain:
# one between card downloads and one between BepisDB page requests.
DEFAULT_CONFIG = {
    "browser": "firefox",
    "website_load_interval": "5",
    "close_browser_after_download": "0",
}

CARD_DELAY_SECONDS = 3
BATCH_SIZE = 10
BATCH_DELAY_SECONDS = 5

BROWSER_LABELS = {
    "chrome": "Google Chrome",
    "edge": "Microsoft Edge",
    "firefox": "Firefox",
}



def ensure_config() -> None:
    """Create config.ini when missing and make sure all r11 keys exist."""
    parser = configparser.ConfigParser()
    if CONFIG_PATH.exists():
        parser.read(CONFIG_PATH, encoding="utf-8")

    if "DEFAULT" not in parser:
        parser["DEFAULT"] = {}
    if "USER" not in parser:
        parser["USER"] = {}

    changed = False
    for key, value in DEFAULT_CONFIG.items():
        if key not in parser["DEFAULT"]:
            parser["DEFAULT"][key] = value
            changed = True
        if key not in parser["USER"]:
            parser["USER"][key] = value
            changed = True

    if changed or not CONFIG_PATH.exists():
        with CONFIG_PATH.open("w", encoding="utf-8") as handle:
            parser.write(handle)


def load_config() -> dict[str, str]:
    """Load saved options and clamp both request delays to at least 5 seconds."""
    ensure_config()
    parser = configparser.ConfigParser()
    parser.read(CONFIG_PATH, encoding="utf-8")
    user = parser["USER"]

    values = {key: user.get(key, default) for key, default in DEFAULT_CONFIG.items()}
    try:
        values["website_load_interval"] = str(max(5, int(values["website_load_interval"])))
    except (TypeError, ValueError):
        values["website_load_interval"] = DEFAULT_CONFIG["website_load_interval"]
    return values


def save_config_value(key: str, value: str) -> None:
    """Persist one Options-menu value."""
    if key not in DEFAULT_CONFIG:
        raise KeyError(f"Unknown config key: {key}")
    ensure_config()
    parser = configparser.ConfigParser()
    parser.read(CONFIG_PATH, encoding="utf-8")
    parser["USER"][key] = str(value)
    with CONFIG_PATH.open("w", encoding="utf-8") as handle:
        parser.write(handle)


def restore_default_config() -> None:
    """Restore all r11 user options."""
    ensure_config()
    parser = configparser.ConfigParser()
    parser.read(CONFIG_PATH, encoding="utf-8")
    parser["USER"] = dict(DEFAULT_CONFIG)
    with CONFIG_PATH.open("w", encoding="utf-8") as handle:
        parser.write(handle)


# ---------------------------------------------------------------------------
# Search input normalization and URL handling
# ---------------------------------------------------------------------------
GAME_URLS = {
    "KK": f"{BASE_URL}/koikatsu",
    "AI_HS2": f"{BASE_URL}/aishoujo",
}
GAME_PATHS = {
    "KK": "/koikatsu",
    "AI_HS2": "/aishoujo",
}


def normalize_tags(raw: str) -> list[str]:
    """Split comma-separated tags, trim them, and de-duplicate case-insensitively."""
    result: list[str] = []
    seen: set[str] = set()
    for value in str(raw or "").split(","):
        tag = value.strip()
        if not tag:
            continue
        folded = tag.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        result.append(tag)
    return result


def normalize_gender(raw: str) -> str:
    """Accept M/Male and F/Female case-insensitively; blank means unspecified."""
    value = str(raw or "").strip().casefold()
    if not value:
        return ""
    if value in {"m", "male"}:
        return "Male"
    if value in {"f", "female"}:
        return "Female"
    raise ValueError("Gender must be Male (M), Female (F), or blank.")


def normalize_bepis_url(url: str) -> str:
    """Normalize common BepisDB URL spellings without discarding query values."""
    value = str(url or "").strip()
    if not value:
        return ""
    if "://" not in value:
        value = "https://" + value.lstrip("/")
    parts = urlsplit(value)
    host = parts.netloc.lower()
    if host in {"bepis.moe", "www.db.bepis.moe"}:
        host = "db.bepis.moe"
    path = re.sub(r"/+", "/", parts.path or "/")
    return urlunsplit((parts.scheme or "https", host, path, parts.query, parts.fragment))


def _query_pairs(url: str) -> list[tuple[str, str]]:
    return parse_qsl(urlsplit(url).query, keep_blank_values=True)


def _query_dict_casefold(url: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in _query_pairs(url):
        result[key.casefold()] = value
    return result


def set_query_value(url: str, key: str, value: str | int | None) -> str:
    """Replace one query key while preserving unknown BepisDB query parameters."""
    parts = urlsplit(url)
    pairs = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.casefold() != key.casefold()
    ]
    if value is not None and str(value) != "":
        pairs.append((key, str(value)))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(pairs), parts.fragment))


def _first_query_value(query: dict[str, str], *names: str) -> str:
    for name in names:
        value = query.get(name.casefold(), "").strip()
        if value:
            return value
    return ""


def validate_search_url(url: str, game: str) -> tuple[bool, str, str, dict[str, str]]:
    """Validate a pasted KK or AI/HS2 listing/search URL."""
    normalized = normalize_bepis_url(url)
    if not normalized:
        return False, "No URL entered.", "", {}

    parts = urlsplit(normalized)
    if parts.scheme.lower() not in {"http", "https"} or parts.netloc.lower() != "db.bepis.moe":
        return False, "Invalid URL. Only db.bepis.moe URLs are supported.", "", {}

    path = parts.path.rstrip("/").casefold()
    if re.fullmatch(r"/user/\d+", path):
        return False, 'User Page URL detected. Please use "User Page" from the main menu.', "", {}

    expected = GAME_PATHS[game]
    if path != expected:
        if path == GAME_PATHS["KK"]:
            owner = "Koikatsu"
        elif path == GAME_PATHS["AI_HS2"]:
            owner = "AI Shoujo / Honey Select 2"
        else:
            return False, "Invalid BepisDB search URL for this downloader.", "", {}
        requested = "Koikatsu" if game == "KK" else "AI Shoujo / Honey Select 2"
        return False, f"Wrong game URL. This URL belongs to {owner}. Please enter a {requested} URL.", "", {}

    query = _query_dict_casefold(normalized)
    detected_tags = normalize_tags(_first_query_value(query, "tags", "tag"))
    author = _first_query_value(query, "author", "cardauthor", "card_author", "card-author")
    detected = {
        "name": _first_query_value(query, "name"),
        "tags": ", ".join(detected_tags),
        "author": author,
        "gender": _first_query_value(query, "gender"),
        "personality": _first_query_value(query, "personality"),
    }
    return True, "", normalized, detected


# ---------------------------------------------------------------------------
# Direct Card/Scene ID parsing
# ---------------------------------------------------------------------------
ID_ROUTES = {
    "KK": {"KK": "/koikatsu/view/{id}", "KKSCENE": "/kkscenes/view/{id}"},
    "AI_HS2": {"AI": "/aishoujo/view/{id}", "AISCENE": "/aiscenes/view/{id}"},
}

DETAIL_PREFIXES = {
    "/koikatsu/view/": "KK",
    "/kkscenes/view/": "KKSCENE",
    "/aishoujo/view/": "AI",
    "/aiscenes/view/": "AISCENE",
