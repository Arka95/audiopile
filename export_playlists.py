"""Export visible Amazon Music playlists; no developer API credentials required.

Setup:
    python -m pip install -r requirements.txt
    python -m playwright install chromium

Examples (run from this directory):
    python export_playlists.py @arkabhowmik @abhowmik95
    python export_playlists.py --library
    python export_playlists.py --login @arkabhowmik

--library opens a browser: sign in on Amazon, open Library > Playlists, then
press Enter in the terminal. Run separately for each Amazon account.
Use --wait-for-library 600 to detect that page automatically instead.
Browser sessions are temporary; passwords, cookies and tokens are not exported.
Only metadata is exported, not audio or complete listening history.
"""

import argparse
import csv
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import parse_qs, quote, urljoin, urlsplit, urlunsplit


FIELDS = [
    "song_id", "song_title", "artist_name", "album_name", "playlist_name",
    "playlist_position", "duration", "song_url", "playlist_url", "source_profile",
]
PLAYLIST_PATH = re.compile(r"^/(?:playlists|user-playlists)/[^/]+/?$")
EMPTY_PROFILE = "There is no available public content on this profile."
LIBRARY_READY = """host => location.hostname === host &&
    /^\\/(?:my|library)(?:\\/|$)/.test(location.pathname) &&
    /(?:^|\\/)playlists(?:\\/|$)/.test(location.pathname)"""


def amazon_url(value, region="in"):
    value = value.strip()
    if "://" not in value:
        value = f"https://music.amazon.{region}/profiles/{quote(value, safe='@')}"
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"music.amazon.in", "music.amazon.com"}
        or parsed.username or parsed.password or parsed.port
    ):
        raise ValueError("Use an HTTPS music.amazon.in or music.amazon.com URL.")
    if not (
        re.fullmatch(r"/profiles/[^/]+/?", parsed.path)
        or PLAYLIST_PATH.fullmatch(parsed.path)
    ):
        raise ValueError("Expected a profile ID/link or a direct playlist link.")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def playlist_url(href, base):
    parsed = urlsplit(urljoin(base, href))
    if (
        parsed.scheme == "https"
        and parsed.netloc == urlsplit(base).netloc
        and PLAYLIST_PATH.fullmatch(parsed.path)
    ):
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))
    return None


def song_id(href):
    parsed = urlsplit(href)
    track = parse_qs(parsed.query).get("trackAsin", [""])[0]
    if track:
        return track
    match = re.fullmatch(r"/(?:tracks|songs)/([^/]+)/?", parsed.path)
    return match.group(1) if match else ""


def advertised_count(text):
    match = re.search(r"([\d,]+)\s+(?:songs?|tracks?)\b", text, re.IGNORECASE)
    return int(match.group(1).replace(",", "")) if match else None


def track_record(raw, name, url, source):
    href = raw.get("primary-href", "")
    return {
        "song_id": song_id(href),
        "song_title": raw.get("primary-text", ""),
        "artist_name": raw.get("secondary-text-1", ""),
        "album_name": raw.get("secondary-text-2", ""),
        "playlist_name": name,
        "playlist_position": raw.get("position", ""),
        "duration": raw.get("duration", ""),
        "song_url": urljoin(url, href) if href else "",
        "playlist_url": url,
        "source_profile": source,
    }


def row_key(raw):
    # Position/data-key preserves repeated songs in different playlist slots.
    return (
        raw.get("position")
        or raw.get("data-key")
        or tuple(raw.get(k, "") for k in (
            "primary-href", "primary-text", "secondary-text-1", "secondary-text-2"
        ))
    )


def spreadsheet_safe(value):
    value = str(value)
    if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
        return "'" + value
    return value


def write_csv(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8-sig", newline="", dir=path.parent,
            prefix=path.name + ".", suffix=".tmp", delete=False,
        ) as file:
            temp_path = Path(file.name)
            writer = csv.DictWriter(file, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows({
                key: spreadsheet_safe(row.get(key, "")) for key in FIELDS
            } for row in rows)
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def scroll_down(page):
    return page.locator("*").evaluate_all("""elements => {
        let moved = false;
        const scrollers = new Set([document.scrollingElement, ...elements.filter(e =>
            e.clientHeight > 0 && e.scrollHeight > e.clientHeight + 4 &&
            ["auto", "scroll"].includes(getComputedStyle(e).overflowY)
        )]);
        for (const e of scrollers) {
            if (!e) continue;
            const before = e.scrollTop;
            e.scrollTop += Math.max(100, e.clientHeight * 0.8);
            moved = moved || e.scrollTop > before;
        }
        return moved;
    }""")


def collect_scrolling(page, read, max_scrolls):
    collected = {}
    stable = 0
    for _ in range(max_scrolls):
        before = len(collected)
        collected.update(read())
        moved = scroll_down(page)
        stable = stable + 1 if not moved and len(collected) == before else 0
        if stable >= 4:
            return collected, False
        page.wait_for_timeout(750)
    return collected, True


def wait_for_content(page):
    page.locator(
        "music-detail-header[headline], music-vertical-item[primary-href], "
        "music-image-row[primary-text], .music-primary-text"
    ).first.wait_for(state="attached", timeout=30000)
    page.wait_for_timeout(1500)


def discover_playlists(page, max_scrolls):
    def read():
        elements = page.locator(
            "a[href], music-vertical-item[primary-href]"
        ).evaluate_all("""es => es.map(e => ({
            href: e.getAttribute("primary-href") || e.getAttribute("href"),
            title: e.getAttribute("primary-text") || e.textContent.trim()
        }))""")
        found = {}
        for element in elements:
            url = playlist_url(element["href"], page.url)
            if url:
                found[url] = element["title"]
        return found

    return collect_scrolling(page, read, max_scrolls)


def extract_playlist(page, url, fallback_name, source, max_scrolls):
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    wait_for_content(page)
    header = page.locator("music-detail-header[headline]").first
    name = fallback_name
    expected = None
    if header.count():
        name = header.get_attribute("headline") or name
        expected = advertised_count(header.get_attribute("tertiary-text") or "")
    if not name:
        name = page.title()

    def read():
        raw_rows = page.locator(
            "music-image-row[primary-text][primary-href]"
        ).evaluate_all("""es => es.map(e => {
            const data = Object.fromEntries([...e.attributes].map(a => [a.name, a.value]));
            data.position = e.querySelector(".index")?.textContent.trim() || "";
            data.duration = e.querySelector(".col4")?.textContent.trim() || "";
            return data;
        })""")
        return {
            row_key(raw): track_record(raw, name, url, source)
            for raw in raw_rows
            if song_id(raw.get("primary-href", ""))
            or re.match(r"^/(?:albums|tracks|songs)/", raw.get("primary-href", ""))
        }

    collected, capped = collect_scrolling(page, read, max_scrolls)
    rows = list(collected.values())
    rows.sort(key=lambda row: (
        int(row["playlist_position"]) if row["playlist_position"].isdigit() else sys.maxsize
    ))
    complete = expected is not None and len(rows) == expected and not capped
    print(f"  {name}: {len(rows)} tracks; displayed total: {expected}; "
          f"{'count matched' if complete else 'INCOMPLETE / unverified'}")
    return rows, complete


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("profiles", nargs="*", help="Profile IDs, handles, profile URLs or playlist URLs")
    parser.add_argument("--region", choices=("in", "com"), default="in")
    parser.add_argument(
        "--output", type=Path,
        default=Path(__file__).with_name("amazon_music.csv"),
    )
    parser.add_argument("--login", action="store_true", help="Pause for manual sign-in on Amazon")
    parser.add_argument("--library", action="store_true", help="Sign in and discover playlists from your library")
    parser.add_argument(
        "--wait-for-library", type=int, default=0, metavar="SECONDS",
        help="Wait for the library playlists page instead of requiring terminal input",
    )
    parser.add_argument("--headless", action="store_true", help="Public pages only; no manual sign-in")
    parser.add_argument("--max-scrolls", type=int, default=300)
    args = parser.parse_args(argv)
    if not args.profiles and not args.library:
        parser.error("Provide at least one profile/playlist, or use --library.")
    if args.headless and (args.login or args.library):
        parser.error("--headless cannot be combined with --login or --library.")
    if args.max_scrolls < 1:
        parser.error("--max-scrolls must be positive.")
    if args.wait_for_library < 0 or (args.wait_for_library and not args.library):
        parser.error("--wait-for-library requires --library and a positive timeout.")
    try:
        sources = [amazon_url(value, args.region) for value in args.profiles]
    except ValueError as error:
        parser.error(str(error))

    try:
        from playwright.sync_api import Error as BrowserError, sync_playwright
    except ImportError:
        parser.exit(1, "Install dependencies: python -m pip install -r requirements.txt\n")

    rows = []
    seen = set()
    incomplete = False
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=args.headless, chromium_sandbox=True
        )
        try:
            context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="en-IN")
            page = context.new_page()
            library_source = None
            if args.login or args.library:
                page.goto(f"https://music.amazon.{args.region}", wait_until="domcontentloaded")
                action = "sign in and open Library > Playlists" if args.library else "sign in"
                if args.wait_for_library:
                    print(f"In the browser, {action}. Enter credentials only on Amazon. "
                          f"Waiting up to {args.wait_for_library} seconds for Library > Playlists.")
                    try:
                        page.wait_for_function(
                            LIBRARY_READY, arg=f"music.amazon.{args.region}",
                            timeout=args.wait_for_library * 1000,
                        )
                    except BrowserError:
                        parser.exit(1, "The library playlists page was not reached. "
                                    "No export was written.\n")
                else:
                    input(f"In the browser, {action}. Enter credentials only on Amazon. "
                          "Then press Enter here: ")
                if args.library:
                    location = urlsplit(page.url)
                    if location.hostname != f"music.amazon.{args.region}":
                        parser.exit(1, "Return to Amazon Music after signing in, then try again.\n")
                    if (
                        location.path in {"", "/"}
                        or location.path.startswith("/profiles/")
                        or PLAYLIST_PATH.fullmatch(location.path)
                    ):
                        parser.exit(
                            1, "Open Library > Playlists, not the home/profile page "
                            "or an individual playlist, then try again.\n"
                        )
                    library_source = urlunsplit((
                        location.scheme, location.netloc, location.path, "", ""
                    ))

            work = [(source, False) for source in sources]
            if library_source:
                work.insert(0, (library_source, True))
            for source, library in work:
                print(f"Reading {'signed-in library' if library else source}")
                try:
                    if not library and PLAYLIST_PATH.fullmatch(urlsplit(source).path):
                        playlists = {source: ""}
                    else:
                        if not library:
                            page.goto(source, wait_until="domcontentloaded", timeout=45000)
                        wait_for_content(page)
                        playlists, capped = discover_playlists(page, args.max_scrolls)
                        print(f"  Discovered {len(playlists)} playlist(s).")
                        incomplete |= capped
                        if not playlists:
                            empty = EMPTY_PROFILE in page.locator("body").inner_text()
                            print("  No public content on this profile." if empty else
                                  "  No playlists discovered. Check the browser, permissions, "
                                  "and that Library > Playlists is open.")
                            incomplete |= not empty
                    for url, name in playlists.items():
                        if url in seen:
                            continue
                        seen.add(url)
                        try:
                            result, complete = extract_playlist(
                                page, url, name, source, args.max_scrolls
                            )
                            rows.extend(result)
                            incomplete |= not complete
                        except BrowserError as error:
                            incomplete = True
                            print(f"  Could not read {url}: {type(error).__name__}", file=sys.stderr)
                except BrowserError as error:
                    incomplete = True
                    print(f"  Could not read source: {type(error).__name__}", file=sys.stderr)
        finally:
            browser.close()

    if not rows:
        print("No tracks retrieved. No CSV was written; any existing export is unchanged.")
        return 2
    output = args.output
    if incomplete:
        output = output.with_name(output.stem + ".partial" + output.suffix)
    write_csv(output, rows)
    print(f"Saved {len(rows)} playlist entries to {output.resolve()}")
    print("Playlist discovery is best-effort, not a complete listening-history export. "
          "Unavailable metadata is blank; repeated songs in different slots are retained.")
    return 2 if incomplete else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit("\nCancelled.")
