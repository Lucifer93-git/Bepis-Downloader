"""
Interactive terminal UI for BepisDB Downloader.

Original project:
    BepisDB-downloader by 0AwsD0
    https://github.com/0AwsD0/BepisDB-downloader

Updated version by:
    LuC!f3r

This compatibility update uses a selectable installed browser to render BepisDB's
JavaScript pages, then downloads the resolved card files safely.
"""

from __future__ import annotations

import re

from download import (
    APP_VERSION,
    DEFAULT_CONFIG,
    load_config,
    normalize_gender,
    normalize_tags,
    parse_card_id_input,
    parse_numeric_id_input,
    restore_default_config,
    run_download,
    save_config_value,
    validate_search_url,
    validate_user_url,
)


# ---------------------------------------------------------------------------
# Shared terminal input helpers
# ---------------------------------------------------------------------------
def ask_yes_no(prompt: str, default_no: bool = True, allow_back: bool = False) -> bool | None:
    """Accept Y/Yes and N/No case-insensitively; Enter means No by default."""
    while True:
        value = input(f"{prompt} [Y/N]:\n> ").strip().casefold()
        if allow_back and value == "b":
            return None
        if not value and default_no:
            return False
        if value in {"y", "yes"}:
            return True
        if value in {"n", "no"}:
            return False
        print("Please enter Y or N, or press Enter for No.\n")


def ask_start_page(allow_back: bool = False) -> int | None:
    """Only positive whole-number pages are accepted; Enter starts at page 1."""
    while True:
        value = input("Start from page [1]:\n> ").strip()
        if allow_back and value.casefold() == "b":
            return None
        if not value:
            return 1
        try:
            page = int(value)
        except ValueError:
            page = 0
        if page >= 1:
            return page
        print("Please enter a positive whole number, or press Enter for page 1.\n")


def ask_user_page_range(allow_back: bool = False):
    """Accept 2 (page 2 onward) or 2-4 (only pages 2 through 4)."""
    while True:
        value = input("Start from page [1]:\n> " ).strip()
        if allow_back and value.casefold() == "b":
            return None
        if not value:
            return (1, None)
        if value.isdigit() and int(value) >= 1:
            return (int(value), None)
        match = re.fullmatch(r"(\d+)\s*-\s*(\d+)", value)
        if match:
            start, end = int(match.group(1)), int(match.group(2))
            if start >= 1 and end >= start:
                return (start, end)
        print("Please enter a page such as 2, a range such as 2-4, or press Enter for page 1.\n")


def ask_gender() -> str:
    """Accept M/Male and F/Female without caring about capitalization."""
    while True:
        value = input("Gender (Male, Female):\n> ").strip()
        try:
            return normalize_gender(value)
        except ValueError:
            print("Please enter Male (M) or Female (F), or press Enter to skip.\n")


def _is_back(value: str) -> bool:
    """The displayed back command is 'B'; input is intentionally case-insensitive."""
    return str(value or "").strip().casefold() == "b"


def search_note() -> None:
    """Show the shared URL/search-mode rules for KK and AI/HS2."""
    print("\nNOTE:")
    print("- All options are OPTIONAL. Press Enter to skip.")
    print("- Use this option to download using a BepisDB URL, tags, or other search filters.")
    print("- To download specific IDs, use Card or Scene from the game menu.")
    print("- Multiple tags can be separated with commas.")
    print("- Y/N answers are not case-sensitive. Press Enter for No.")
    print("- Gender is not case-sensitive. M/Male and F/Female are accepted.")
    print("- Existing folders will be reused.")
    print("- Existing completed cards will be skipped.")
    print("- Incomplete .part files do not count as completed downloads.")
    print("- Enter 'B' to go back. (Not case sensitive).\n")
    print()


# ---------------------------------------------------------------------------
# Pasted search URL mode
# ---------------------------------------------------------------------------
def ask_search_url(game: str) -> tuple[str, dict[str, str]] | None:
    """Ask for a BepisDB search URL; blank continues and 'B' goes back."""
    while True:
        print("BepisDB search URL:")
        raw = input("> ").strip()
        if _is_back(raw):
            return None
        if not raw:
            return "", {}

        ok, message, normalized, detected = validate_search_url(raw, game)
        if ok:
            return normalized, detected

        print(f"\n{message}")
        print("Press Enter at the URL prompt for other search methods, or enter 'B' to go back.\n")


def show_detected_search(game: str, detected: dict[str, str]) -> None:
    """Display URL-derived search values as read-only terminal output."""
    print("\nDetected search")
    print("---------------\n")

    print("Name:")
    print(f"> {detected.get('name') or 'No character name found'}\n")

    print("Tags:")
    print(f"> {detected.get('tags') or 'No tags found'}\n")

    if game == "KK":
        print("Card Author:")
        print(f"> {detected.get('author') or 'No card author found'}\n")

    print("Gender:")
    print(f"> {detected.get('gender') or 'No gender found'}\n")

    print("Personality:")
    print(f"> {detected.get('personality') or 'No personality found'}\n")


# ---------------------------------------------------------------------------
# KK / AI-HS2 search workflow
# ---------------------------------------------------------------------------
def _game_label(game: str) -> str:
    return "Koikatsu (KK)" if game == "KK" else "AI Shoujo / Honey Select 2 (AI/HS2)"


def _direct_id_note(kind: str) -> None:
    """Numeric-only direct mode note; game/prefix is already known from the menu."""
    title = "Card" if kind == "card" else "Scene"
    print("\nNOTE:")
    print(f"- Enter a {title} ID, a range, or multiple specific IDs.")
    print("- Enter numbers only. The downloader already knows the selected game and type.")
    print("- Multiple specific IDs can be separated with commas.")
    print("- Ranges can go up or down, and can be combined with specific IDs.")
    print("- Enter 'B' to go back. (Not case sensitive).\n")
    print("Examples:")
    print("  1234")
    print("    Downloads 1 file.\n")
    print("  1234-1236")
    print("    Downloads 1234 through 1236.\n")
    print("  1234,1236,1243")
    print("    Downloads only the specified IDs.\n")
    print("  1234-1236,1243,1250-1252")
    print("    Downloads the range(s) and specified IDs.\n")


def _ask_numeric_ids(game: str, kind: str) -> list[dict] | None:
    """Read numeric-only direct IDs. None means Back."""
    while True:
        print(f"{'Card' if kind == 'card' else 'Scene'} ID, range, or multiple IDs:")
        raw = input("> ").strip()
        if _is_back(raw):
            return None
        if not raw:
            print("\nPlease enter an ID, or 'B' to go back.\n")
            continue
        try:
            return parse_numeric_id_input(raw, game, kind)
        except ValueError as exc:
            print(f"\n{exc}")
            print("Please enter a valid numeric ID, or 'B' to go back.\n")


def _post_download_menu() -> str:
    """After a direct batch, let the user restart the same mode or go back."""
    while True:
        print("\n1. Restart")
        print("2. Back")
        choice = input("\n> ").strip()
        if choice == "1":
            return "restart"
        if choice == "2":
            return "back"
        print("\nPlease select 1 or 2.")


def run_direct_mode(game: str, kind: str) -> None:
    """Separate Card and Scene modes; users enter numeric IDs only."""
    label = _game_label(game)
    title = "Card" if kind == "card" else "Scene"

    while True:
        print(f"\n{label} - {title}")
        _direct_id_note(kind)
        items = _ask_numeric_ids(game, kind)
        if items is None:
            return

        run_download({
            "mode": "ids",
            "game": game,
            "label": label,
            "id_kind": title,
            "search_source": f"{title} ID",
            "id_items": items,
            "id_display": ", ".join(item["display"] for item in items),
        })

        if _post_download_menu() == "back":
            return

def _manual_value(prompt: str) -> str | None:
    """Manual URL/search fields also honor the global 'B' back command."""
    print(f"\n{prompt}:")
    value = input("> ").strip()
    return None if _is_back(value) else value


def run_url_mode(game: str) -> None:
    """URL/search mode: pasted URL, direct IDs, or the normal manual filters."""
    label = _game_label(game)
    print(f"\n{label} - URL")
    search_note()

    result = ask_search_url(game)
    if result is None:
        return
    pasted_url, detected = result

    if pas