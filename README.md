# BepisDB Downloader r32

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
