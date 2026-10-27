"""Run from the repository root: python -m unittest discover -s src -v."""

import csv
from pathlib import Path
import tempfile
import unittest

from export_playlists import (
    LIBRARY_READY, advertised_count, amazon_url, collect_scrolling,
    discover_playlists, playlist_url, row_key,
    song_id, track_record, write_csv,
)


class ExportTests(unittest.TestCase):
    def test_profile_and_playlist_links(self):
        self.assertEqual(
            amazon_url("@arkabhowmik"),
            "https://music.amazon.in/profiles/@arkabhowmik",
        )
        self.assertEqual(
            amazon_url("https://music.amazon.in/user-playlists/abc?ref=share"),
            "https://music.amazon.in/user-playlists/abc",
        )
        for value in (
            "https://example.com/profiles/me",
            "https://music.amazon.in.evil.test/profiles/me",
            "https://music.amazon.in/profiles/me/followers",
            "http://music.amazon.in/profiles/me",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                amazon_url(value)
        self.assertIsNone(playlist_url(
            "https://example.com/playlists/test", "https://music.amazon.in"
        ))

    def test_extract_real_page_attributes_and_ids(self):
        raw = {
            "primary-text": 'A song, "live"',
            "primary-href": "/albums/ALBUM?trackAsin=SONG",
            "secondary-text-1": "Artist A & Artist B",
            "secondary-text-2": "Album",
            "position": "2",
            "duration": "04:30",
        }
        row = track_record(raw, "My playlist", "https://music.amazon.in/playlists/P", "profile")
        self.assertEqual(row["song_id"], "SONG")
        self.assertEqual(row["artist_name"], "Artist A & Artist B")
        self.assertEqual(row["album_name"], "Album")
        self.assertEqual(row["playlist_position"], "2")
        self.assertEqual(song_id("/tracks/SONG"), "SONG")
        self.assertEqual(song_id("/albums/ALBUM"), "")
        self.assertEqual(advertised_count("1,234 SONGS • 4 HOURS"), 1234)
        self.assertIsNone(advertised_count("Music playlist"))

    def test_duplicate_songs_keep_separate_slots(self):
        first = {"position": "1", "primary-href": "/tracks/S"}
        second = {"position": "2", "primary-href": "/tracks/S"}
        self.assertNotEqual(row_key(first), row_key(second))
        self.assertEqual(row_key(first), row_key(dict(first)))

    def test_csv_unicode_quotes_blanks_and_formula_safety(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "songs.csv"
            write_csv(path, [
                {"song_title": 'Bengali \u0997\u09be\u09a8, "live"', "artist_name": "=HYPERLINK(1)"},
                {"song_title": "+formula", "playlist_name": "@profile"},
            ])
            with path.open(encoding="utf-8-sig", newline="") as file:
                reader = csv.DictReader(file)
                rows = list(reader)
                self.assertEqual(reader.fieldnames[0], "song_id")
            self.assertEqual(rows[0]["song_title"], 'Bengali \u0997\u09be\u09a8, "live"')
            self.assertEqual(rows[0]["artist_name"], "'=HYPERLINK(1)")
            self.assertEqual(rows[0]["album_name"], "")
            self.assertEqual(rows[1]["playlist_name"], "'@profile")
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_scrolling_accumulates_virtual_rows_and_reports_cap(self):
        class Page:
            def __init__(self):
                self.index = 0

            def locator(self, _):
                return self

            def evaluate_all(self, _):
                self.index = min(self.index + 1, 3)
                return self.index < 3

            def wait_for_timeout(self, _):
                pass

        page = Page()
        result, capped = collect_scrolling(page, lambda: {page.index: page.index}, 20)
        self.assertEqual(set(result), {0, 1, 2, 3})
        self.assertFalse(capped)
        _, capped = collect_scrolling(Page(), lambda: {"a": 1}, 1)
        self.assertTrue(capped)


class BrowserDiscoveryTests(unittest.TestCase):
    def test_discovers_cards_and_links_without_duplicates_or_offsite_links(self):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(chromium_sandbox=True)
            try:
                page = browser.new_page()
                page.route("https://music.amazon.in/profiles/fixture", lambda route: route.fulfill(
                    content_type="text/html",
                    body="""
                        <music-vertical-item primary-href="/user-playlists/one"
                            primary-text="My playlist"></music-vertical-item>
                        <a href="/user-playlists/one?ref=share">My playlist</a>
                        <a href="/playlists/two">Another playlist</a>
                        <a href="/albums/not-a-playlist">Album</a>
                        <a href="https://example.com/playlists/offsite">Offsite</a>
                    """,
                ))
                page.goto("https://music.amazon.in/profiles/fixture")
                playlists, capped = discover_playlists(page, 10)
                self.assertEqual(playlists, {
                    "https://music.amazon.in/user-playlists/one": "My playlist",
                    "https://music.amazon.in/playlists/two": "Another playlist",
                })
                self.assertFalse(capped)
                self.assertFalse(page.evaluate(LIBRARY_READY, "music.amazon.in"))
                for url in (
                    "https://music.amazon.in/my/playlists",
                    "https://music.amazon.in/my/library/playlists",
                ):
                    page.route(url, lambda route: route.fulfill(body="Library"))
                    page.goto(url)
                    page.wait_for_function(LIBRARY_READY, arg="music.amazon.in", timeout=1000)
                    self.assertFalse(page.evaluate(LIBRARY_READY, "music.amazon.com"))
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
