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

    if pasted_url:
        show_detected_search(game, detected)
        show_hidden = ask_yes_no("Show hidden cards?", allow_back=True)
        if show_hidden is None: return
        print()
        start_page = ask_start_page(allow_back=True)
        if start_page is None: return
        run_download({
            "mode": "game", "game": game, "label": label,
            "search_source": "BepisDB URL", "url": pasted_url,
            "name": detected.get("name", ""), "tags": detected.get("tags", ""),
            "author": detected.get("author", ""), "gender": detected.get("gender", ""),
            "personality": detected.get("personality", ""), "show_hidden": show_hidden,
            "start_from": start_page,
        })
        return

    name = _manual_value("Name")
    if name is None: return
    tags_raw = _manual_value("Tags")
    if tags_raw is None: return
    tags = ", ".join(normalize_tags(tags_raw))
    author = ""
    if game == "KK":
        author = _manual_value("Card Author")
        if author is None: return

    # Gender needs validation while still allowing 'B'.
    while True:
        print("\nGender (Male, Female):")
        raw_gender = input("> ").strip()
        if _is_back(raw_gender): return
        try:
            gender = normalize_gender(raw_gender)
            break
        except ValueError:
            print("Please enter Male (M) or Female (F), press Enter to skip, or 'B' to go back.")

    personality = _manual_value("Personality")
    if personality is None: return
    print()
    show_hidden = ask_yes_no("Show hidden cards?", allow_back=True)
    if show_hidden is None: return
    print()
    start_page = ask_start_page(allow_back=True)
    if start_page is None: return
    run_download({
        "mode": "game", "game": game, "label": label, "search_source": "Manual",
        "url": "", "name": name, "tags": tags, "author": author,
        "gender": gender, "personality": personality, "show_hidden": show_hidden,
        "start_from": start_page,
    })


def run_game(game: str) -> None:
    """Game submenu keeps URL, Card, and Scene downloads separate."""
    label = _game_label(game)
    while True:
        print(f"\n{label}")
        print("\n1. URL")
        print("2. Card")
        print("3. Scene")
        print("4. Back")
        choice = input("\n> ").strip()
        if choice == "1":
            run_url_mode(game)
        elif choice == "2":
            run_direct_mode(game, "card")
        elif choice == "3":
            run_direct_mode(game, "scene")
        elif choice == "4":
            return
        else:
            print("\nPlease select an option from 1 to 4.")


# ---------------------------------------------------------------------------
# User Page workflow
# ---------------------------------------------------------------------------
def run_user_page() -> None:
    """Validate a BepisDB /user/<id> URL before any browser/folder work begins."""
    print("\nUser Page")
    print("\nNOTE:")
    print("- Paste a BepisDB user profile URL.")
    print("- Y/N answers are not case-sensitive. Press Enter for No.")
    print("- Existing folders will be reused.")
    print("- Existing completed cards will be skipped.")
    print("- Incomplete .part files will not count as completed downloads.")
    print("- Enter 'B' to go back. (Not case sensitive).\n")

    while True:
        print("User Page URL:")
        raw = input("> ").strip()
        if _is_back(raw):
            return
        ok, message, normalized = validate_user_url(raw)
        if ok:
            break
        print(f"\n{message}\n")

    print()
    show_hidden = ask_yes_no("Show hidden cards?", allow_back=True)
    if show_hidden is None:
        return
    print()
    page_selection = ask_user_page_range(allow_back=True)
    if page_selection is None:
        return
    start_page, end_page = page_selection

    run_download(
        {
            "mode": "user",
            "url": normalized,
            "show_hidden": show_hidden,
            "start_from": start_page,
            "end_at": end_page,
        }
    )


# ---------------------------------------------------------------------------
# Options menu and persistent config editing
# ---------------------------------------------------------------------------
BROWSER_OPTIONS = {
    "1": ("chrome", "Google Chrome"),
    "2": ("edge", "Microsoft Edge"),
    "3": ("firefox", "Firefox"),
}


def select_browser() -> None:
    """Choose which installed browser Selenium will control."""
    while True:
        current = load_config().get("browser", "firefox")
        labels = {"chrome": "Google Chrome", "edge": "Microsoft Edge", "firefox": "Firefox"}
        print("\nSelect browser")
        print(f"\nCurrent: {labels.get(current, current)}\n")
        print("1. Google Chrome")
        print("2. Microsoft Edge")
        print("3. Firefox")
        print("4. Back")

        choice = input("\n> ").strip()
        if choice == "4":
            return
        if choice in BROWSER_OPTIONS:
            value, label = BROWSER_OPTIONS[choice]
            save_config_value("browser", value)
            print(f"\nBrowser set to {label}.")
            print("Setting saved.")
            return
        print("\nPlease select an option from 1 to 4.")


def change_page_delay() -> None:
    """Keep the original page-load delay configurable with a 5-second minimum."""
    current = load_config()["website_load_interval"]
    print(f"\nCurrent page load delay: {current} seconds")
    print("Minimum allowed: 5 seconds")
    while True:
        value = input("\nEnter new delay in seconds:\n> ").strip()
        if not value:
            print("\nNo changes made.")
            return
        try:
            seconds = int(value)
        except ValueError:
            print("\nPlease enter a whole number of 5 or higher.")
            continue
        if seconds < 5:
            print("\nDelay cannot be less than 5 seconds.")
            continue
        save_config_value("website_load_interval", str(seconds))
        print(f"\nPage load delay is now {seconds} seconds.")
        print("Setting saved.")
        return


def options_menu() -> None:
    labels = {"chrome": "Google Chrome", "edge": "Microsoft Edge", "firefox": "Firefox"}
    while True:
        config = load_config()
        browser = labels.get(config.get("browser", "firefox"), "Firefox")

        print("\nOptions")
        print("\nNOTE:")
        print("- The selected browser is used for the downloader session.")
        print("- The browser stays open after downloading by default.")
        print("- Changes are saved and remembered the next time you run the downloader.\n")
        close_browser = str(config.get("close_browser_after_download", "0")).strip() == "1"
        print(f"1. Browser: {browser}")
        print(f"2. Page load delay: {config['website_load_interval']} seconds")
        print(f"3. Close browser after download: {'Yes' if close_browser else 'No'}")
        print("4. Restore defaults")
        print("5. Back")

        choice = input("\n> ").strip()
        if choice == "1":
            select_browser()
        elif choice == "2":
            change_page_delay()
        elif choice == "3":
            save_config_value("close_browser_after_download", "0" if close_browser else "1")
            print(f"\nClose browser after download: {'No' if close_browser else 'Yes'}")
            print("Setting saved.")
        elif choice == "4":
            print()
            if ask_yes_no("Restore all downloader options to their defaults?"):
                restore_default_config()
                print("\nDefaults restored.")
            else:
                print("\nNo changes made.")
        elif choice == "5":
            return
        else:
            print("\nPlease select an option from 1 to 5.")


# ---------------------------------------------------------------------------
# Main menu
# ---------------------------------------------------------------------------
def menu() -> None:
    """Top-level menu intentionally contains only the two requested games."""
    while True:
        print(f"\nBepisDB Downloader {APP_VERSION}")
        print("Original project by 0AwsD0 | Updated by LuC!f3r")
        print("-" * 38)
        print("1. Koikatsu (KK)")
        print("2. AI Shoujo / Honey Select 2 (AI/HS2)")
        print("3. User Page")
        print("4. Exit")
        print("5. Options")

        choice = input("\n> ").strip()
        if choice == "1":
            run_game("KK")
        elif choice == "2":
            run_game("AI_HS2")
        elif choice == "3":
            run_user_page()
        elif choice == "4":
            print("Goodbye.")
            return
        elif choice == "5":
            options_menu()
        else:
            print("\nPlease select an option from 1 to 5.")


if __name__ == "__main__":
    menu()
