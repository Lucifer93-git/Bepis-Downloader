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
}


def direct_download_url(prefix: str, number: int) -> str:
    """Build BepisDB's direct card-file URL, using its six-digit ID filenames."""
    return f"{BASE_URL}/card/download/{prefix}_{number:06d}.png"


def _direct_action_from_detail_url(detail_url: str):
    """Convert a known BepisDB detail URL into its direct card download URL."""
    path = urlsplit(detail_url).path
    folded = path.casefold()
    for route, prefix in DETAIL_PREFIXES.items():
        route_folded = route.casefold()
        if folded.startswith(route_folded):
            number_text = path[len(route):].strip("/")
            if number_text.isdigit():
                number = int(number_text)
                return DownloadAction(
                    url=direct_download_url(prefix, number),
                    suggested_name=f"{prefix}_{number:06d}.png",
                )
    return None


def parse_card_id_input(raw: str, game: str) -> list[dict]:
    """Expand singles, ranges (up/down), and comma-separated combinations."""
    routes = ID_ROUTES[game]
    allowed = tuple(sorted(routes, key=len, reverse=True))
    token_re = re.compile(r"^(" + "|".join(map(re.escape, allowed)) + r")(\d+)$", re.I)
    result: list[dict] = []
    seen: set[tuple[str, int]] = set()

    def parse_one(value: str):
        match = token_re.fullmatch(value.strip())
        if not match:
            names = " or ".join(allowed)
            raise ValueError(
                f"Invalid Card/Scene ID: {value.strip() or value!r}. "
                f"Use {names} followed by a number."
            )
        prefix = match.group(1).upper()
        number_text = match.group(2)
        return prefix, int(number_text), len(number_text)

    for part in str(raw or "").split(","):
        part = part.strip()
        if not part:
            continue

        if "-" in part:
            pieces = [piece.strip() for piece in part.split("-")]
            if len(pieces) != 2:
                raise ValueError(f"Invalid range: {part}")
            p1, n1, w1 = parse_one(pieces[0])
            p2, n2, w2 = parse_one(pieces[1])
            if p1 != p2:
                raise ValueError("A range cannot mix character and scene ID types.")
            step = 1 if n2 >= n1 else -1
            for number in range(n1, n2 + step, step):
                key = (p1, number)
                if key in seen:
                    continue
                seen.add(key)
                width = max(w1, w2)
                result.append({
                    "prefix": p1,
                    "number": number,
                    "display": f"{p1}{number:0{width}d}",
                    "url": BASE_URL + routes[p1].format(id=number),
                    "download_url": direct_download_url(p1, number),
                })
        else:
            prefix, number, width = parse_one(part)
            key = (prefix, number)
            if key in seen:
                continue
            seen.add(key)
            result.append({
                "prefix": prefix,
                "number": number,
                "display": f"{prefix}{number:0{width}d}",
                "url": BASE_URL + routes[prefix].format(id=number),
                "download_url": direct_download_url(prefix, number),
            })

    if not result:
        raise ValueError("No Card/Scene IDs were entered.")
    return result


def parse_numeric_id_input(raw: str, game: str, kind: str) -> list[dict]:
    """Parse numeric-only singles/ranges/lists for a selected Card or Scene mode."""
    kind = kind.casefold()
    if game == "KK":
        prefix = "KK" if kind == "card" else "KKSCENE"
    else:
        prefix = "AI" if kind == "card" else "AISCENE"

    routes = ID_ROUTES[game]
    result = []
    seen = set()

    def number(value: str) -> tuple[int, int]:
        value = value.strip()
        if not value.isdigit():
            raise ValueError("IDs must contain numbers only.")
        return int(value), len(value)

    for part in str(raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            pieces = [x.strip() for x in part.split("-")]
            if len(pieces) != 2:
                raise ValueError(f"Invalid range: {part}")
            n1, w1 = number(pieces[0])
            n2, w2 = number(pieces[1])
            step = 1 if n2 >= n1 else -1
            width = max(w1, w2)
            for n in range(n1, n2 + step, step):
                if n in seen:
                    continue
                seen.add(n)
                result.append({
                    "prefix": prefix,
                    "number": n,
                    "display": f"{n:0{width}d}",
                    "url": BASE_URL + routes[prefix].format(id=n),
                    "download_url": direct_download_url(prefix, n),
                })
        else:
            n, width = number(part)
            if n in seen:
                continue
            seen.add(n)
            result.append({
                "prefix": prefix,
                "number": n,
                "display": f"{n:0{width}d}",
                "url": BASE_URL + routes[prefix].format(id=n),
                "download_url": direct_download_url(prefix, n),
            })
    if not result:
        raise ValueError("No IDs were entered.")
    return result

def validate_user_url(url: str) -> tuple[bool, str, str]:
    """Accept current BepisDB user URLs such as /user/58112."""
    normalized = normalize_bepis_url(url)
    if not normalized:
        return False, "Please enter a BepisDB User Page URL.", ""
    parts = urlsplit(normalized)
    if parts.netloc.lower() != "db.bepis.moe":
        return False, "Invalid URL. Only db.bepis.moe URLs are supported.", ""
    if not re.fullmatch(r"/user/\d+/?", parts.path, flags=re.IGNORECASE):
        return False, (
            "This is not a User Page URL. Expected something like "
            "https://db.bepis.moe/user/58112"
        ), ""
    return True, "", normalized


def build_manual_search_url(game: str, data: dict[str, str]) -> str:
    """Build the current simplified BepisDB search URL from manual filters."""
    url = GAME_URLS[game]
    name = str(data.get("name", "") or "").strip()
    tags = normalize_tags(data.get("tags", ""))
    gender = str(data.get("gender", "") or "").strip()
    personality = str(data.get("personality", "") or "").strip()
    author = str(data.get("author", "") or "").strip()

    if name:
        url = set_query_value(url, "name", name)
    if tags:
        url = set_query_value(url, "tags", ",".join(tags))
    if gender:
        url = set_query_value(url, "gender", gender)
    if personality:
        url = set_query_value(url, "personality", personality)
    if game == "KK" and author:
        url = set_query_value(url, "author", author)
    return url


def apply_run_controls(url: str, show_hidden: bool, page: int) -> str:
    """Apply normal search-page controls while preserving the rest of the URL."""
    updated = set_query_value(url, "hidden", "true" if show_hidden else None)
    updated = set_query_value(updated, "page", page if page > 1 else None)
    return updated


def apply_user_page_controls(url: str, show_hidden: bool, page: int) -> str:
    """Build the current BepisDB user-page URL.

    Current BepisDB user pages use:
      /user/<id>?uploaderId=<id>&includeHidden=true
      /user/<id>?uploaderId=<id>&includeHidden=false
    """
    parts = urlsplit(url)
    match = re.fullmatch(r"/user/(\d+)/?", parts.path, flags=re.IGNORECASE)
    if not match:
        updated = url
    else:
        uploader_id = match.group(1)
        updated = set_query_value(url, "uploaderId", uploader_id)
        updated = set_query_value(
            updated, "includeHidden", "true" if show_hidden else "false"
        )

    # Remove the obsolete hidden parameter if it was present in a pasted URL.
    updated = set_query_value(updated, "hidden", None)
    updated = set_query_value(updated, "page", page if page > 1 else None)
    return updated


# ---------------------------------------------------------------------------
# Save location, folder reuse, and destination scan
# ---------------------------------------------------------------------------
def _find_existing_child_case_insensitive(parent: Path, name: str) -> Path | None:
    try:
        wanted = name.casefold()
        for child in parent.iterdir():
            if child.is_dir() and child.name.casefold() == wanted:
                return child
    except OSError:
        return None
    return None


def _default_download_directory() -> Path:
    return Path.home() / "Downloads"


def ask_save_location() -> Path | None:
    """Ask for save path/folder and reuse existing folders case-insensitively."""
    print("\nSave location:")
    base_raw = input("> ").strip()
    if base_raw:
        base = Path(os.path.expandvars(os.path.expanduser(base_raw))).resolve()
    else:
        base = _default_download_directory().resolve()
        print(f"Using default Downloads location: {base}")

    print("\nFolder name:")
    folder_name = input("> ").strip().strip("\\/")

    print("\nChecking destination...")
    try:
        if base.exists():
            print(f"Save location already exists. Using: {base}")
        else:
            print(f"Save location does not exist. Creating: {base}")
            base.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"Could not create/use save location: {exc}")
        return None

    if not folder_name:
        destination = base
    else:
        existing = _find_existing_child_case_insensitive(base, folder_name)
        if existing:
            destination = existing
            print("Folder already exists. Skipping folder creation.")
            print(f"Using: {destination}")
        else:
            destination = base / folder_name
            print("Folder does not exist.")
            print(f"Creating folder: {destination}")
            try:
                destination.mkdir(parents=False, exist_ok=False)
                print("Folder created successfully.")
            except FileExistsError:
                destination = _find_existing_child_case_insensitive(base, folder_name) or destination
                print("Folder already exists. Skipping folder creation.")
                print(f"Using: {destination}")
            except OSError as exc:
                print(f"Could not create folder: {exc}")
                return None

    scan_destination(destination)
    return destination


def scan_destination(destination: Path) -> tuple[int, int]:
    """Count completed and .part files before the run begins."""
    completed = 0
    partial = 0
    try:
        for child in destination.iterdir():
            if not child.is_file():
                continue
            if child.name.casefold().endswith(".part"):
                partial += 1
            else:
                completed += 1
    except OSError:
        pass

    print("\nScanning destination...")
    print(f"Found {completed} existing completed file(s).")
    if partial:
        print(f"Found {partial} incomplete .part file(s).")
    print("Incomplete .part files will be ignored.")
    print("Existing completed cards will be skipped.")
    return completed, partial


def _existing_file_case_insensitive(directory: Path, filename: str) -> Path | None:
    if not filename:
        return None
    wanted = filename.casefold()
    try:
        for child in directory.iterdir():
            if (
                child.is_file()
                and not child.name.casefold().endswith(".part")
                and child.name.casefold() == wanted
            ):
                return child
    except OSError:
        return None
    return None


# ---------------------------------------------------------------------------
# Lightweight HTML discovery
# ---------------------------------------------------------------------------
# The curren