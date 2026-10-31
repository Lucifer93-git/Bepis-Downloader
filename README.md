# BepisDB Downloader r36

Original project: **BepisDB-downloader by 0AwsD0**  
https://github.com/0AwsD0/BepisDB-downloader

Updated by **LuC!f3r**.

## r32

- Windows GUI now includes a Bepis-style top banner and matching application/EXE icon.
- Windows packaging now collects the full Selenium package and explicit Firefox/Chrome/Edge webdriver modules, fixing missing browser-module errors in the EXE.
- Firefox remains the default browser.
- User Page's proven direct-listing workflow is now reused by all listing/search downloads:
  - read the item ID from the rendered tile URL without opening every detail page;
  - skip exact existing PNGs locally;
  - hover missing tiles and click their Download button directly;
  - wait as long as the browser download is still making progress;
  - show elapsed download time;
  - keep 3-second normal pacing plus the visible 5-second pause every 10 processed items.
- User Page, URL/search listing modes support page selections such as `2` or `2-4`.
- Direct Card/Scene ID mode remains available for exact numeric IDs and ranges.
- User Page hidden-card URLs continue using `uploaderId=<id>&includeHidden=true/false`.
- Browser stays open by default. Only the downloader-created browser session is closed when that option is enabled.
- Source users can run `updater.py` to update from GitHub without downloading another ZIP.
- A GitHub Actions workflow builds the Windows EXE package with the Bepis icon.

## Source

```text
python -m pip install -r requirements.txt
python gui.py
```

The legacy terminal interface is still available:

```text
python main.py
```

## Windows package

The Windows build contains:

```text
BepisDB-Downloader.exe
config.ini
version.txt
README.md
```

Chrome, Edge, or Firefox must already be installed. Firefox is the default.


## r34

- Added true self-update support for the packaged Windows build.
- Update check now offers **Update now**, **Later**, and **Open release**.
- **Update now** downloads the matching Windows ZIP from the GitHub Release.
- The main app launches `BepisDB-Updater.exe`, exits, and the helper replaces the installed files.
- `config.ini` is preserved during updates.
- The helper relaunches `BepisDB-Downloader.exe` automatically when replacement finishes.
- The Windows package now includes `BepisDB-Updater.exe`.
- r34 must be installed manually once if upgrading from an older EXE build that does not yet contain the helper. Future updates can then install themselves.


## r35

- User Page downloads now recognize Koikatsu Clothing entries at `/kkclothing/view/<id>`.
- Koikatsu Clothing items use the `KKCLOTHING` prefix for local completed-file checks.
- Shared GUI listing detection also recognizes Koikatsu Clothing tiles.
- Replaced the circular header placeholder with the BepisDB face/logo.
- Reworked the top banner to follow the approved rendered UI: dark navy/indigo background with a cropped character-face composition on the right instead of the oversized single-eye graphic.
- r34 Windows self-update support remains in place, so installed r34+ builds can update to r35 automatically once the r35 Windows release asset is published.


## r36

- Fixed Windows self-update failures caused by files still being locked after the main GUI closed.
- The updater now waits on the exact Windows process handle before replacing files.
- File replacements are staged beside the installed files and retried for up to 120 seconds when Windows, antivirus, or Explorer temporarily holds a file handle.
- Onedir subfolders are merged safely instead of deleting the entire directory first.
- `config.ini` remains preserved.
- The GUI now fully terminates after handing control to `BepisDB-Updater.exe`, preventing lingering background threads from keeping the packaged EXE/DLLs locked.
- Update errors now show a concise BepisDB message instead of a raw PyInstaller traceback.


### r36 additional setting

- Added **Default save location** in Settings.
- The setting is stored in `config.ini` and automatically pre-fills every download form.
- **Browse** still overrides the path for individual downloads.
- If no default save location is configured, the GUI falls back to the normal Windows Downloads folder.


### r36 usability improvements

- Automatic updates now show real download progress in the main console and bottom status bar using the release ZIP's actual byte count.
- Update stages are shown as **Checking release**, **Downloading update**, **Extracting update**, **Preparing installer**, and **Closing application**.
- Right-click context menus are available on text-entry fields with **Cut**, **Copy**, **Paste**, and **Select All**.
- The console/log area supports right-click **Copy** and **Select All**.


## Headless test branch

This branch is for testing background browser operation before merging it into the main release.

- Settings now includes **Browser mode** with `visible` and `headless`.
- `visible` keeps the current behavior.
- `headless` runs Firefox, Chrome, or Edge without showing a browser window.
- Headless browser sessions are always closed automatically when a download job finishes.
- Existing pacing remains unchanged: 3 seconds between downloaded cards and the 5-second batch pause.
- Test User Page, direct Card/Scene IDs, URL/Search, hidden cards, and Koikatsu Clothing before merging.
