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
# The current site exposes ordinary HTML links/buttons. This parser deliberately
# stays broad so small markup changes do not require a browser/WebDriver.
@dataclass
class LinkItem:
    href: str
    text: str = ""
    download_name: str = ""


@dataclass
class FormItem:
    action: str
    method: str = "GET"
    text: str = ""
    fields: dict[str, str] = field(default_factory=dict)


class BepisHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[LinkItem] = []
        self.forms: list[FormItem] = []
        self._a: dict | None = None
        self._a_text: list[str] = []
        self._form: dict | None = None
        self._form_text: list[str] = []

    @staticmethod
    def _attrs(attrs):
        return {str(k).lower(): (v or "") for k, v in attrs}

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        a = self._attrs(attrs)

        if tag == "a":
            self._a = a
            self._a_text = []

        if tag == "form":
            self._form = {
                "action": a.get("action", ""),
                "method": (a.get("method", "GET") or "GET").upper(),
                "fields": {},
            }
            self._form_text = []

        if self._form is not None and tag == "input":
            name = a.get("name", "")
            if name:
                input_type = a.get("type", "text").lower()
                if input_type in {"hidden", "submit"}:
                    self._form["fields"][name] = a.get("value", "")

        if self._form is not None and tag in {"button", "input"}:
            value = a.get("value", "")
            if value:
                self._form_text.append(value)

    def handle_data(self, data):
        if self._a is not None:
            self._a_text.append(data)
        if self._form is not None:
            self._form_text.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "a" and self._a is not None:
            self.links.append(LinkItem(
                href=self._a.get("href", ""),
                text=" ".join("".join(self._a_text).split()),
                download_name=self._a.get("download", ""),
            ))
            self._a = None
            self._a_text = []

        if tag == "form" and self._form is not None:
            self.forms.append(FormItem(
                action=self._form["action"],
                method=self._form["method"],
                text=" ".join("".join(self._form_text).split()),
                fields=dict(self._form["fields"]),
            ))
            self._form = None
            self._form_text = []


@dataclass(frozen=True)
class DownloadAction:
    url: str
    method: str = "GET"
    fields: tuple[tuple[str, str], ...] = ()
    suggested_name: str = ""


DETAIL_PATH_RE = re.compile(
    r"^/(?:koikatsu|kkscenes|aishoujo|aiscenes)/view/\d+/?$",
    flags=re.IGNORECASE,
)


def _parse_html(html: str) -> BepisHTMLParser:
    parser = BepisHTMLParser()
    parser.feed(html)
    return parser


def _valid_http_link(base_url: str, href: str) -> str:
    href = str(href or "").strip()
    if not href or href.startswith(("#", "javascript:", "mailto:")):
        return ""
    absolute = urljoin(base_url, href)
    parts = urlsplit(absolute)
    if parts.scheme not in {"http", "https"}:
        return ""
    return absolute


def _discover_download_actions(html: str, page_url: str) -> list[DownloadAction]:
    """Find normal Download links and Download forms on a BepisDB page."""
    parsed = _parse_html(html)
    actions: list[DownloadAction] = []
    seen: set[tuple] = set()

    for link in parsed.links:
        url = _valid_http_link(page_url, link.href)
        if not url:
            continue
        text = link.text.strip().casefold()
        href_folded = link.href.casefold()
        if "/download/" not in href_folded and not text.startswith("download"):
            continue
        key = ("GET", url, ())
        if key in seen:
            continue
        seen.add(key)
        actions.append(DownloadAction(url=url, suggested_name=link.download_name))

    for form in parsed.forms:
        text = form.text.strip().casefold()
        action_folded = form.action.casefold()
        if "/download/" not in action_folded and "download" not in text:
            continue
        url = _valid_http_link(page_url, form.action or page_url)
        if not url:
            continue
        fields = tuple(form.fields.items())
        key = (form.method, url, fields)
        if key in seen:
            continue
        seen.add(key)
        actions.append(DownloadAction(url=url, method=form.method, fields=fields))

    return actions


def _discover_detail_links(html: str, page_url: str) -> list[str]:
    """Find card/scene detail pages. User pages rely on this path."""
    parsed = _parse_html(html)
    result: list[str] = []
    seen: set[str] = set()
    for link in parsed.links:
        url = _valid_http_link(page_url, link.href)
        if not url:
            continue
        if urlsplit(url).netloc.lower() != "db.bepis.moe":
            continue
        if not DETAIL_PATH_RE.fullmatch(urlsplit(url).path):
            continue
        clean = urlunsplit((urlsplit(url).scheme, urlsplit(url).netloc, urlsplit(url).path, "", ""))
        if clean in seen:
            continue
        seen.add(clean)
        result.append(clean)
    return result


# ---------------------------------------------------------------------------
# Selenium browser layer for JavaScript-rendered BepisDB pages
# ---------------------------------------------------------------------------
class BepisBrowser:
    """Launch and control only the browser instance created by this downloader."""

    def __init__(self, browser_name: str, download_dir: Path):
        if webdriver is None:
            raise RuntimeError("Selenium is not installed. Run: pip install -r requirements.txt")
        self.browser_name = str(browser_name or "chrome").casefold()
        self.download_dir = str(Path(download_dir).resolve())
        self.driver = self._create_driver(self.browser_name, self.download_dir)
        self.driver.set_page_load_timeout(45)

    @staticmethod
    def _create_driver(browser_name: str, download_dir: str):
        try:
            if browser_name == "chrome":
                options = webdriver.ChromeOptions()
                options.add_argument("--disable-notifications")
                options.add_experimental_option("excludeSwitches", ["enable-logging"])
                options.add_experimental_option("prefs", {
                    "download.default_directory": download_dir,
                    "download.prompt_for_download": False,
                    "download.directory_upgrade": True,
                    "safebrowsing.enabled": True,
                })
                return webdriver.Chrome(options=options)
            if browser_name == "edge":
                options = webdriver.EdgeOptions()
                options.add_argument("--disable-notifications")
                options.add_experimental_option("prefs", {
                    "download.default_directory": download_dir,
                    "download.prompt_for_download": False,
                    "download.directory_upgrade": True,
                    "safebrowsing.enabled": True,
                })
                return webdriver.Edge(options=options)
            if browser_name == "firefox":
                options = webdriver.FirefoxOptions()
                options.set_preference("dom.webnotifications.enabled", False)
                options.set_preference("browser.download.folderList", 2)
                options.set_preference("browser.download.dir", download_dir)
                options.set_preference("browser.download.useDownloadDir", True)
                options.set_preference("browser.helperApps.neverAsk.saveToDisk", "image/png;application/octet-stream")
                return webdriver.Firefox(options=options)
            raise RuntimeError(f"Unsupported browser setting: {browser_name}")
        except WebDriverException as exc:
            label = BROWSER_LABELS.get(browser_name, browser_name)
            raise RuntimeError(
                f"{label} could not be started.\nMake sure the browser is installed and connected to the internet the first time Selenium Manager resolves its driver.\nError: {exc}"
            ) from exc

    def open_rendered(self, url: str, wait_seconds: int) -> tuple[str, str]:
        self.driver.get(url)
        try:
            WebDriverWait(self.driver, max(10, wait_seconds)).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
        except TimeoutException:
            pass
        time.sleep(max(5, int(wait_seconds)))
        return self.driver.page_source, self.driver.current_url

    def cookies(self) -> list[dict]:
        try: return self.driver.get_cookies()
        except Exception: return []

    def find_download_control(self):
        xpaths = [
            "//a[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'download')]",
            "//button[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'download')]",
            "//*[@download]",
            "//*[contains(translate(@title,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'download')]",
            "//*[contains(translate(@aria-label,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'download')]",
            "//*[contains(translate(@onclick,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'download')]",
            "//input[contains(translate(@value,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'download')]",
        ]
        for xpath in xpaths:
            try: elements=self.driver.find_elements(By.XPATH, xpath)
            except Exception: continue
            for e in elements:
                try:
                    if e.is_displayed() and e.is_enabled(): return e
                except Exception: pass
        return None

    def click_download_and_wait(self, idle_timeout: int = 180, absolute_timeout: int = 900):
        """Click Download and wait while the browser is still making progress.

        A slow but active download should not fail just because it takes more than
        three minutes. The idle timer resets whenever the browser download file
        changes size or modification time.
        """
        destination = Path(self.download_dir)
        before = {}
        for path in destination.iterdir():
            if path.is_file():
                try:
                    before[path.name] = (path.stat().st_size, path.stat().st_mtime_ns)
                except OSError:
                    pass

        control = self.find_download_control()
        if control is None:
            return "failed", "No visible Download control was found on the rendered page.", []

        try:
            self.driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'});", control
            )
            time.sleep(.3)
            try:
                control.click()
            except Exception:
                self.driver.execute_script("arguments[0].click();", control)
        except Exception as exc:
            return "failed", f"Could not click Download control: {exc}", []

        temps = (".crdownload", ".part", ".tmp", ".download")
        start_time = time.time()
        last_progress = start_time
        last_state = {}
        seen = set()

        while True:
            now = time.time()
            current = [p for p in destination.iterdir() if p.is_file()]
            changed = []

            for path in current:
                try:
                    state = (path.stat().st_size, path.stat().st_mtime_ns)
                except OSError:
                    continue

                old_state = before.get(path.name)
                if old_state is None or state != old_state:
                    changed.append(path)
                    seen.add(path.name)

                    if last_state.get(path.name) != state:
                        last_progress = now

                last_state[path.name] = state

            tmp = [p for p in changed if p.name.casefold().endswith(temps)]
            png = [p for p in changed if p.suffix.casefold() == ".png"]

            if png and not tmp:
                newest = max(png, key=lambda p: p.stat().st_mtime)
                return "downloaded", newest.name, newest

            # Only fail when the download has stopped changing for 3 minutes.
            if now - last_progress >= idle_timeout:
                break

            # Safety cap for pathological cases.
            if now - start_time >= absolute_timeout:
                break

            time.sleep(.5)

        leftovers = [
            destination / name
            for name in seen
            if (destination / name).exists()
            and name.casefold().endswith(temps)
        ]

        if not seen:
            reason = "Download control was clicked, but no new file appeared."
        elif time.time() - start_time >= absolute_timeout:
            reason = "Download exceeded the 15-minute safety limit."
        else:
            reason = "Download stopped making progress for 3 minutes."

        return "failed", reason, leftovers

    def close(self) -> None:
        try: self.driver.quit()
        except Exception: pass


# ---------------------------------------------------------------------------
# Direct HTTP client and safe file downloads
# ---------------------------------------------------------------------------
class BepisHTTPClient:
    """Small cookie-aware HTTP client using only Python's standard library."""

    def __init__(self):
        self.cookies = http.cookiejar.CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.cookies))
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/140.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }

    def open(self, url: str, method: str = "GET", fields: tuple[tuple[str, str], ...] = (), timeout: int = 45):
        data = None
        actual_url = url
        method = (method or "GET").upper()

        if fields:
            encoded = urlencode(list(fields))
            if method == "GET":
                parts = urlsplit(url)
                existing = parse_qsl(parts.query, keep_blank_values=True)
                actual_url = urlunsplit((
                    parts.scheme,
                    parts.netloc,
                    parts.path,
                    urlencode(existing + list(fields)),
                    parts.fragment,
                ))
            else:
                data = encoded.encode("utf-8")

        headers = dict(self.headers)
        if data is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        req = Request(actual_url, data=data, headers=headers, method=method)
        return self.opener.open(req, timeout=timeout)

    def sync_browser_cookies(self, cookies: list[dict]) -> None:
        """Copy the automated browser session cookies into this HTTP client."""
        for item in cookies or []:
            name = item.get("name")
            value = item.get("value")
            if not name:
                continue
            domain = item.get("domain") or "db.bepis.moe"
            path = item.get("path") or "/"
            secure = bool(item.get("secure", False))
            cookie = http.cookiejar.Cookie(
                version=0,
                name=name,
                value=value or "",
                port=None,
                port_specified=False,
                domain=domain,
                domain_specified=True,
                domain_initial_dot=domain.startswith("."),
                path=path,
                path_specified=True,
                secure=secure,
                expires=item.get("expiry"),
                discard=item.get("expiry") is None,
                comment=None,
                comment_url=None,
                rest={},
                rfc2109=False,
            )
            try:
                self.cookies.set_cookie(cookie)
            except Exception:
                pass

    def get_text(self, url: str, timeout: int = 45) -> tuple[str, str]:
        with self.open(url, timeout=timeout) as response:
            raw = response.read()
            content_type = response.headers.get_content_type()
            charset = response.headers.get_content_charset() or "utf-8"
            if content_type not in {"text/html", "application/xhtml+xml", "text/plain"}:
                # Decode anyway for tolerant error pages, but caller can still inspect.
                charset = charset or "utf-8"
            return raw.decode(charset, errors="replace"), response.geturl()


def _sanitize_filename(name: str) -> str:
    name = Path(str(name or "").replace("\\", "/")).name.strip()
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = name.rstrip(" .")
    return name or "bepis_download"


def _filename_from_response(response, action: DownloadAction) -> str:
    """Prefer Content-Disposition, then HTML download=, then URL basename."""
    try:
        filename = response.headers.get_filename() or ""
    except Exception:
        filename = ""
    if not filename:
        filename = action.suggested_name
    if not filename:
        filename = Path(urlsplit(response.geturl()).path).name
    if not filename:
        filename = "bepis_download"
    return _sanitize_filename(filename)


def _download_action(client, action, destination):
    """Download to .part; rename only after the full HTTP response is complete."""
    part_path = None
    try:
        response = client.open(action.url, action.method, action.fields)
    except HTTPError as exc:
        return "failed", f"HTTP {exc.code}", None, None
    except (URLError, OSError) as exc:
        return "failed", str(exc), None, None

    try:
        with response:
            ctype = (response.headers.get_content_type() or "").casefold()
            filename = _filename_from_response(response, action)
            if ctype in {"text/html", "application/xhtml+xml"}:
                return "failed", "Download link returned an HTML page.", None, None

            existing = _existing_file_case_insensitive(destination, filename)
            if existing:
                return "skipped", existing.name, None, existing

            final_path = destination / filename
            part_path = destination / f"{filename}.part"
            with part_path.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 128)
                    if not chunk:
                        break
                    handle.write(chunk)

            os.replace(part_path, final_path)
            if final_path.suffix.casefold() != ".png" or not final_path.exists():
                return "failed", "Completed file could not be verified as .png.", part_path, final_path
            return "downloaded", final_path.name, None, final_path
    except Exception as exc:
        # Intentionally leave this run's .part file in place until batch cleanup.
        return "failed", str(exc), part_path, None


def _fetch_page(client, url, page_delay):
    try:
        html, final_url = client.get_text(url)
    except HTTPError as exc:
        if exc.code == 404:
            return None
        print(f"Page request failed (HTTP {exc.code}): {url}")
        return None
    except (URLError, OSError) as exc:
        print(f"Page request failed: {exc}")
        return None
    time.sleep(page_delay)
    return html, final_url




def _expected_filename(prefix: str, number: int) -> str:
    """Return BepisDB's canonical PNG filename for a known card/scene ID."""
    return f"{prefix.upper()}_{int(number):06d}.png"


def _expected_filename_from_detail_url(url: str) -> str | None:
    """Infer the canonical BepisDB filename from a card/scene detail URL."""
    path = urlsplit(url).path.rstrip("/")
    match = re.search(
        r"/(koikatsu|kkscenes|aishoujo|aiscenes)/view/(\d+)$",
        path,
        flags=re.IGNORECASE,
    )
    if not match:
        return None

    route = match.group(1).casefold()
    number = int(match.group(2))
    prefixes = {
        "koikatsu": "KK",
        "kkscenes": "KKSCENE",
        "aishoujo": "AI",
        "aiscenes": "AISCENE",
    }
    return _expected_filename(prefixes[route], number)


def _existing_expected_png(destination: Path, expected_name: str | None):
    """Find an already completed expected PNG case-insensitively."""
    if not expected_name:
        return None
    return _existing_file_case_insensitive(destination, expected_name)


def _download_direct_id(browser, client, item, destination, page_delay):
    """Open one direct ID, skip exact existing PNGs, and include hidden cards."""
    expected_name = _expected_filename(item["prefix"], item["number"])
    existing = _existing_expected_png(destination, expected_name)
    if existing:
        return ("skipped", existing.name, None, existing)

    detail_url = item["url"]

    try:
        browser.open_rendered(detail_url, page_delay)
    except Exception as exc:
        return ("failed", f"Could not open detail page: {exc}", None, None)

    status, message, payload = browser.click_download_and_wait()
    if status == "downloaded":
        return ("downloaded", message, None, payload)

    temp_path = payload[0] if payload else None
    return ("failed", message, temp_path, None)



def _resolve_detail_download_action(client, detail_url: str):
    """Open one BepisDB detail page and return its real download action.

    Direct ID mode deliberately resolves the site's own Download control instead
    of guessing a /card/download/<prefix>_<id>.png URL.
    """
    try:
        html, final_url = client.get_text(detail_url)
    except HTTPError as exc:
        return None, f"HTTP {exc.code} while opening detail page"
    except (URLError, OSError) as exc:
        return None, f"Could not open detail page: {exc}"

    actions = _discover_download_actions(html, final_url)
    if not actions:
        return None, "No download link found on detail page"

    # Prefer the normal BepisDB card download endpoint when multiple controls exist.
    for action in actions:
        if "/card/download/" in urlsplit(action.url).path.casefold():
            return action, ""
    return actions[0], ""


def _numeric_id_from_url(url: str) -> str:
    m = re.search(r"(?:view/|_(\d+)\.png$)(\d+)?", urlsplit(url).path, re.I)
    if not m:
        m = re.search(r"(\d+)", urlsplit(url).path)
    return (m.group(1) or m.group(2)) if m else "Unknown"


class BatchSession:
    """Tracks failures, successful files, cleanup paths, and silent/visible waits."""
    def __init__(self, client, destination):
        self.client = client
        self.destination = destination
        self.downloaded = 0
        self.skipped = 0
        self.failed_ids = []
        self.cleanup_paths = []
        self.completed_files = []
        self.processed = 0

    def process(self, action, display_id):
        status, message, part_path, final_path = _download_action(self.client, action, self.destination)
        self.processed += 1

        if status == "downloaded":
            self.downloaded += 1
            self.completed_files.append(final_path)
            print(f"{display_id}: Downloaded")
        elif status == "skipped":
            self.skipped += 1
            print(f"{display_id}: Already exists - skipped")
        else:
            self.failed_ids.append(str(display_id))
           