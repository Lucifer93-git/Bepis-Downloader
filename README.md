# BepisDB Downloader — compatibility update r30

Original project: **BepisDB-downloader by 0AwsD0**  
https://github.com/0AwsD0/BepisDB-downloader

Updated version by: **LuC!f3r**

## Browser-based JavaScript rendering

BepisDB currently returns a minimal HTML shell to direct HTTP requests for
some pages/download endpoints. r15 restores browser automation so BepisDB's
JavaScript can render normally before the downloader resolves the real
Download link.

Supported browser choices:

```text
1. Google Chrome
2. Microsoft Edge
3. Firefox
4. Back
```

Firefox is the default.

Selenium Manager is used so users do not need to manually download and point
the program at ChromeDriver, EdgeDriver, or GeckoDriver. The selected browser
itself must already be installed.

Install the Python requirement once:

```bash
pip install -r requirements.txt
```

Then run:

```bash
python main.py
```

## Direct Card / Scene modes

Card and Scene remain separate. Enter numbers only:

```text
1234
1234-1236
1236-1234
1234,1236,1243
12345-12348,1210-1215
```

The game and selected mode determine KK / KKSCENE / AI / AISCENE automatically.

## Download behavior

- Pages are rendered in the selected browser.
- The downloader reads the real rendered Download link.
- Files are transferred with the browser session cookies.
- A file is written to `.part` until the transfer is fully complete.
- Only then is it renamed to `.png`.
- Existing completed files are skipped.
- Failed IDs do not stop the remaining downloads.
- Failed `.part` files created by the current run are cleaned up after the run.
- 3 seconds between individual cards is silent.
- After each 10 processed items, the downloader displays:
  `Waiting 5 seconds to avoid overloading the website...`
- No unnecessary final 5-second wait is added.
- Direct Card/Scene modes end with Restart / Back.

## Browser safety

The downloader calls `driver.quit()` only for the browser session that it
created. It does not intentionally terminate unrelated Chrome, Edge, or
Firefox processes.


## r16 download-control fix

r16 clicks the visible rendered Download control instead of requiring a conventional download URL. Chrome/Edge `.crdownload` and Firefox `.part` files are monitored. A card counts as complete only when a final `.png` exists and the temporary download file is gone.


## r17 option changes

- Microsoft Edge is now the default browser.
- The browser stays open after downloading by default.
- Options includes `Close browser after download: No/Yes`.
- User-facing Options text no longer mentions Selenium.


## r18 fixes

- Fixed duplicate downloads in browser-click mode by checking the exact canonical
  BepisDB filename (`PREFIX_000000.png`) before clicking Download.
- Hidden cards are now explicitly opened with `hidden=true`.
- Direct ID mode includes hidden cards automatically; normal cards are unaffected.
- URL/User Page modes preserve the user's Show hidden cards choice when opening
  individual detail pages.

## r19 skip timing

- Existing completed cards wait only 1 second before moving on.
- The normal 3-second delay is applied only after an actual downloaded card.
- The 5-second anti-overload batch pause is counted from actual downloads, not skipped cards.


## r20 fixes

- Firefox is now the default browser.
- The browser still stays open after downloads by default.
- User Page hidden-card URLs now follow BepisDB's current format:
  - `?uploaderId=<id>&includeHidden=true`
  - `?uploaderId=<id>&includeHidden=false`
- Removed the obsolete `hidden=true` parameter from User Page/detail navigation.


## r21 slow-download fix

- Slow downloads no longer fail after a fixed 3-minute total timer.
- The 3-minute timer is now an idle/stall timer and resets whenever the
  browser download file changes.
- Active downloads may continue for up to 15 minutes.
- The 1-second delay for already-existing cards is unchanged.


## r22 last-page fix

- Pagination now checks the rendered page for a real next-page link/control.
- If page 4 is the last page, the downloader stops on page 4.
- It no longer opens `&page=5` merely to discover that page 5 is empty or repeats
  the previous page.


## r23 pacing adjustment

- Existing/skipped cards now wait 3 seconds instead of 1 second.
- Downloaded cards keep the 3-second delay.
- Every 10 processed cards triggers the visible 5-second anti-overload pause.
- Skipped existing cards now count toward that batch of 10.
- No delay is added when the caller marks the item as the final item.


## r24 pagination fix

- Reworked pagination detection so large profiles are not stopped after the first
  few pages.
- The downloader now reads visible page numbers, `?page=N` links, pagination
  labels/data attributes, and enabled Next controls.
- A profile with 12 pages can continue through page 12.
- Once page 12 is identified as the last page, page 13 is not opened.
- The final card on the final page no longer receives an unnecessary delay.


## r25 pagination fix

- Fixed another User Page pagination case where a full 24-card page could be
  mistaken for the final page.
- Pagination is now read from the live DOM using hrefs, data attributes,
  aria/title labels, Next controls, and page-summary text.
- If BepisDB hides its pagination metadata, a full 24-card page continues to the
  next page instead of stopping early.
- The repeated-page guard remains in place to prevent endless pagination.


## r26 pagination fallback fix

- Fixed the case where page 2 could still be mistaken for the last page.
- Any full 24-card page now continues unless BepisDB exposes a definite disabled
  Next control.
- A partial page with no enabled Next control is treated as the final page.
- If pagination markup is incomplete, the downloader no longer stops merely
  because it detected the current page number.
- Existing repeated-page protection is retained.

## r27 User Page direct-download test
- User Page mode stays on the listing; it does not open individual card detail pages.
- Card IDs are read from each tile's `/view/<id>` href.
- Existing PNGs are skipped locally.
- Missing cards are hovered and their Download button is clicked directly.
- Shows `Page X of Y` when the total is visible and uses the site's actual Next (`>`) control.
- Waits for each PNG to finish; one failure does not stop the run.
- Normal pacing is 3 seconds, plus the existing 5-second pause every 10 processed cards.
- Other modes retain r26 behavior.


## r28 User Page slow-download diagnostics
- Prints `ID: Downloading directly from User Page...` before each missing card.
- Successful User Page downloads show elapsed download time.
- Removed the absolute timeout for direct User Page downloads.
- Active downloads keep waiting while Firefox's download file continues changing.
- A download fails only after 3 minutes with no progress.
- Direct User Page failures use concise messages rather than WebDriver stack traces.
- 3-second normal pacing and the separate 5-second pause every 10 processed cards remain.
- Other modes are unchanged.


## r29 User Page pagination and page ranges
- User Page pagination no longer depends on clicking the site's Next button.
- The total page count is derived primarily from BepisDB's `N cards found` count (24 cards per page), with visible pagination numbers as a fallback.
- Pages are opened explicitly with `&page=N` and stop at the detected final page.
- `Start from page` accepts `2` (page 2 through the last page) or `2-4` (only pages 2 through 4).
- Removed the temporary `Downloading directly from User Page...` troubleshooting line.
- Successful downloads retain the useful elapsed time, e.g. `Downloaded (3.1s)`.
- Direct User Page download behavior, 3-second pacing, 5-second every-10 pause, hidden-card handling, and other modes are otherwise unchanged.


## r30 automatic GitHub updater

A new `updater.py` launcher can check this GitHub repository before starting the downloader.

Recommended startup:

```bash
python updater.py
```

Behavior:

- Checks `version.txt` on GitHub.
- Shows the installed and latest version.
- Offers **Update now**, **Skip this update**, or **Exit**.
- Downloads the new program files directly from GitHub; users do not need to download a release ZIP for normal updates.
- Updates `main.py`, `download.py`, `requirements.txt`, `README.md`, `updater.py`, and `version.txt`.
- **Never overwrites `config.ini`**, so browser choice, delay, and other user settings are preserved.
- Downloads the complete update before replacing installed files.
- Attempts to roll back replaced files if an update fails midway.
- If `requirements.txt` changed, runs the current Python interpreter with `-m pip install -r requirements.txt`.
- If GitHub is unavailable, starts the currently installed downloader normally.
- The updater itself can be updated by future releases.

### First-time setup

Existing users only need to download/copy `updater.py` and `version.txt` once (or get r30 normally). After that, run `updater.py` instead of `main.py` for routine updates.
