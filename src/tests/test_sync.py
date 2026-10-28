import csv
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mutagen.id3 import ID3

from src.downloader import Song, tag_audio
from src.export_playlists import write_csv
from src.sync import sync_playlists


class SyncTests(unittest.TestCase):
    @patch("src.sync.refresh_playlist")
    @patch("src.downloader.core.download_audio")
    @patch("src.downloader.core.find_video", return_value="https://www.youtube.com/watch?v=abcdefghijk")
    def test_regular_sync_downloads_only_new_songs_and_fills_links(self, find, download, refresh):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "downloads"
            output.mkdir()
            catalog = root / "amazonmusic.playlists.csv"
            catalog.write_text("playlist_name,playlist_url\nList,https://music.amazon.in/playlists/P\n")
            songs = root / "songs.partial.csv"
            old = {
                "song_id": "OLD", "song_title": "Old title", "artist_name": "Artist",
                "album_name": "Album", "playlist_url": "https://music.amazon.in/playlists/P",
            }
            new = dict(old, song_id="NEW", song_title="New title")
            write_csv(songs, [old])
            existing = output / "Old [JXgV1rXUoME] [123456789012].mp3"
            existing.write_bytes(b"fixture")
            tag_audio(existing, Song(
                title="Old title", artist="Artist", album="Album", song_id="OLD",
            ))

            def fake_refresh(urls, csv_path):
                with Path(csv_path).open(encoding="utf-8-sig", newline="") as file:
                    rows = list(csv.DictReader(file))
                added = int(not any(row["song_id"] == "NEW" for row in rows))
                if added:
                    write_csv(csv_path, rows + [new])
                return {"added": added, "errors": {}}

            def fake_download(url, directory, song, on_bytes, _cache=None):
                path = Path(directory) / f"{song.song_id}.mp3"
                path.write_bytes(b"fixture")
                tag_audio(path, song, {"webpage_url": url})
                on_bytes(1000)
                _cache.remember(path)
                return path

            refresh.side_effect = fake_refresh
            download.side_effect = fake_download
            first = sync_playlists(catalog, songs, max_workers=1, output_dir=output)
            self.assertEqual(first.refresh["added"], 1)
            self.assertEqual(sum(item.cached for item in first.batch.results), 1)
            download.assert_called_once()
            self.assertEqual(ID3(output / "NEW.mp3")["TXXX:song_id"].text, ["NEW"])
            with songs.open(encoding="utf-8-sig", newline="") as file:
                rows = list(csv.DictReader(file))
            self.assertTrue(all(row["youtube_url"] for row in rows))
            find.reset_mock()
            download.reset_mock()
            second = sync_playlists(catalog, songs, output_dir=output)
            self.assertEqual(second.refresh["added"], 0)
            self.assertTrue(all(item.cached for item in second.batch.results))
            self.assertEqual(second.batch.bytes_downloaded, 0)
            find.assert_not_called()
            download.assert_not_called()

    @patch("src.sync.refresh_playlist")
    def test_invalid_catalog_fails_before_network(self, refresh):
        with tempfile.TemporaryDirectory() as directory:
            catalog = Path(directory) / "catalog.csv"
            catalog.write_text("name\nList\n")
            with self.assertRaisesRegex(ValueError, "playlist_url"):
                sync_playlists(catalog)
            refresh.assert_not_called()


if __name__ == "__main__":
    unittest.main()
