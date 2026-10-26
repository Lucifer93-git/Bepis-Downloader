"""GUI backend using the direct-listing workflow across all listing modes."""
from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

import download as core

APP_VERSION = "2026.10.26-r34"

# In a PyInstaller onedir build, keep user-editable config.ini next to the EXE.
if getattr(sys, "frozen", False):
    core.PROJECT_DIR = Path(sys.executable).resolve().parent
    core.CONFIG_PATH = core.PROJECT_DIR / "config.ini"


def prepare_destination(base_path: str | Path, folder_name: str = "") -> Path | None:
    base = Path(os.path.expandvars(os.path.expanduser(str(base_path or "")))).resolve()
    folder_name = str(folder_name or "").strip().strip("\\/")
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
        existing = core._find_existing_child_case_insensitive(base, folder_name)
        if existing:
            destination = existing
            print("Folder already exists. Skipping folder creation.")
            print(f"Using: {destination}")
        else:
            destination = base / folder_name
            print(f"Creating folder: {destination}")
            try:
                destination.mkdir(parents=False, exist_ok=False)
            except FileExistsError:
                destination = core._find_existing_child_case_insensitive(base, folder_name) or destination
            except OSError as exc:
                print(f"Could not create folder: {exc}")
                return None
    core.scan_destination(destination)
    return destination


def _listing_rows(browser):
    """Read IDs from listing tiles without navigating to each detail page."""
    selector = ",".join([
        "a[href*='/koikatsu/view/']",
        "a[href*='/aishoujo/view/']",
        "a[href*='/kkscenes/view/']",
        "a[href*='/aiscenes/view/']",
    ])
    prefixes = {"koikatsu":"KK", "kkscenes":"KKSCENE", "aishoujo":"AI", "aiscenes":"AISCENE"}
    rows, seen = [], set()
    for link in browser.driver.find_elements(core.By.CSS_SELECTOR, selector):
        try:
            href = link.get_attribute("href") or ""
            match = re.search(r"/(koikatsu|aishoujo|kkscenes|aiscenes)/view/(\d+)", href, re.I)
            if not match:
                continue
            route, number = match.group(1).casefold(), int(match.group(2))
            key = (route, number)
            if key in seen:
                continue
            container = browser.driver.execute_script("""
                let e=arguments[0];
                for(let i=0;e&&i<8;i++,e=e.parentElement){
                  if(e.querySelector("a.btn,button,a[download],a[href*='/download/']")) return e;
                }
                return arguments[0].parentElement;
            """, link)
            rows.append({"number": number, "prefix": prefixes[route], "container": container})
            seen.add(key)
        except Exception:
            pass
    return rows


def _download_tile(browser, container):
    """Hover a tile, click Download, and wait while the browser is progressing."""
    destination = Path(browser.download_dir)
    before = {}
    for path in destination.iterdir():
        if path.is_file():
            try:
                before[path.name] = (path.stat().st_size, path.stat().st_mtime_ns)
            except OSError:
                pass

    try:
        browser.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", container)
        core.ActionChains(browser.driver).move_to_element(container).pause(.4).perform()
    except Exception:
        pass

    control = None
    for xpath in (
        ".//a[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'download')]",
        ".//button[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'download')]",
        ".//*[@download]", ".//a[contains(@href,'/download/')]",
    ):
        try:
            for element in container.find_elements(core.By.XPATH, xpath):
                if element.is_displayed() and element.is_enabled():
                    control = element
                    break
        except Exception:
            pass
        if control is not None:
            break
    if control is None:
        return "failed", "No Download button appeared for this item.", [], 0.0

    clicked = time.time()
    try:
        try:
            control.click()
        except Exception:
            browser.driver.execute_script("arguments[0].click();", control)
    except Exception:
        return "failed", "Could not click the Download button.", [], 0.0

    temps = (".crdownload", ".part", ".tmp", ".download")
    last_progress = time.time()
    states, seen = {}, set()
    while True:
        now = time.time()
        changed = []
        try:
            files = [x for x in destination.iterdir() if x.is_file()]
        except OSError:
            files = []
        for path in files:
            try:
                state = (path.stat().st_size, path.stat().st_mtime_ns)
            except OSError:
                continue
            old = before.get(path.name)
            if old is None or state != old:
                changed.append(path)
                seen.add(path.name)
                if states.get(path.name) != state:
                    last_progress = now
            states[path.name] = state
        temp_files = [x for x in changed if x.name.casefold().endswith(temps)]
        png_files = [x for x in changed if x.suffix.casefold() == ".png"]
        if png_files and not temp_files:
            newest = max(png_files, key=lambda x: x.stat().st_mtime)
            return "downloaded", newest.name, newest, time.time() - clicked
        if now - last_progress >= 180:
            break
        time.sleep(.5)

    leftovers = [destination/name for name in seen if (destination/name).exists() and name.casefold().endswith(temps)]
    reason = "Download did not start within 3 minutes." if not seen else "Download stopped making progress for 3 minutes."
    return "failed", reason, leftovers, time.time() - clicked


def _total_pages(browser, current_page):
    total = current_page
    try:
        body = browser.driver.find_element(core.By.TAG_NAME, "body").text or ""
        match = re.search(r"([\d,]+)\s+(?:cards?|scenes?|results?|items?)\s+found", body, re.I)
        if match:
            count = int(match.group(1).replace(",", ""))
            if count > 0:
                total = max(total, (count + 23) // 24)
    except Exception:
        pass
    try:
        elements = browser.driver.find_elements(core.By.CSS_SELECTOR, "a,button")
    except Exception:
        elements = []
    for element in elements:
        try:
            if not element.is_displayed():
                continue
            text = (element.text or "").strip()
            href = element.get_attribute("href") or ""
            if text.isdigit() and 1 <= int(text) <= 100000:
                total = max(total, int(text))
            match = re.search(r"(?:[?&])page=(\d+)", href, re.I)
            if match:
                total = max(total, int(match.group(1)))
        except Exception:
            pass
    return total


def _run_listing(browser, session, data, page_delay, base_url, user_mode=False):
    page = max(1, int(data.get("start_from", 1)))
    requested_end = data.get("end_at")
    requested_end = int(requested_end) if requested_end is not None else None
    previous, detected_total = None, None

    while True:
        if user_mode:
            page_url = core.apply_user_page_controls(base_url, bool(data.get("show_hidden")), page)
        else:
            page_url = core.apply_run_controls(base_url, bool(data.get("show_hidden")), page)
            page_url = core.set_query_value(page_url, "page", page if page > 1 else None)
        browser.open_rendered(page_url, page_delay)
        rows = _listing_rows(browser)
        signature = tuple((r["prefix"], r["number"]) for r in rows)
        if not rows or signature == previous:
            break
        previous = signature
        page_total = _total_pages(browser, page)
        detected_total = page_total if detected_total is None else max(detected_total, page_total)
        effective_end = detected_total if requested_end is None else min(detected_total, requested_end)
        print(f"\nPage {page} of {detected_total}")
        print("----------------------------------------")

        for index, row in enumerate(rows):
            expected = core._expected_filename(row["prefix"], row["number"])
            existing = core._existing_expected_png(session.destination, expected)
            session.processed += 1
            if existing:
                session.skipped += 1
                status = "skipped"
                print(f'{row["number"]}: Already exists - skipped')
            else:
                status, message, payload, elapsed = _download_tile(browser, row["container"])
                if status == "downloaded":
                    session.downloaded += 1
                    session.completed_files.append(payload)
                    print(f'{row["number"]}: Downloaded ({elapsed:.1f}s)')
                else:
                    session.failed_ids.append(str(row["number"]))
                    if isinstance(payload, list):
                        session.cleanup_paths.extend(payload)
                    print(f'{row["number"]}: Download failed')
                    print(f"Reason: {message}")
            has_more = index < len(rows)-1 or page < effective_end
            session.wait_after_item(has_more, status)

        if page >= effective_end:
            break
        page += 1


def run_gui_download(data: dict, destination: Path) -> dict:
    """GUI entry point: direct IDs use core; all listing modes use direct tiles."""
    config = core.load_config()
    client = core.BepisHTTPClient()
    session = core.BatchSession(client, destination)
    page_delay = int(config["website_load_interval"])
    browser_name = config.get("browser", "firefox")
    core._print_summary(data, destination, config)

    try:
        print(f"Opening {core.BROWSER_LABELS.get(browser_name, browser_name)}...")
        browser = core.BepisBrowser(browser_name, destination)
    except Exception as exc:
        print(f"Browser could not be started.\nError: {exc}")
        return {"downloaded":0, "skipped":0, "failed_ids":[]}

    try:
        if data.get("mode") == "ids":
            items = data.get("id_items", [])
            for index, item in enumerate(items, 1):
                status = session.process_direct_id(browser, item, page_delay)
                session.wait_after_item(index < len(items), status)
        elif data.get("mode") == "user":
            _run_listing(browser, session, data, page_delay, data["url"], user_mode=True)
        else:
            base_url = data.get("url") or core.build_manual_search_url(data["game"], data)
            _run_listing(browser, session, data, page_delay, base_url, user_mode=False)
    except Exception as exc:
        print(f"\nUnexpected downloader error: {exc}")
    finally:
        if str(config.get("close_browser_after_download", "0")).strip() == "1":
            browser.close()

    session.cleanup(); session.verify(); result = session.result()
    print("\n" + "-"*40)
    print("Download failed.\n" if result["failed_ids"] else "Download complete.\n")
    print(f"Downloaded: {result['downloaded']}")
    print(f"Skipped existing: {result['skipped']}")
    if result["failed_ids"]:
        print(f"Failed: {len(result['failed_ids'])}\n\nFailed IDs:")
        for ident in result["failed_ids"]:
            print(f"  {ident}")
    print("-"*40)
    return result
