import csv
import json
import io
from pathlib import Path
import tempfile
from threading import Event, Lock
import unittest
from unittest.mock import patch

from mutagen.id3 import ID3

from src.downloader import (
    BatchResult, DownloadResult, Song, cache_youtube_urls, download_audio, download_songs, find_video, load_songs_from_csv,
    tag_audio, unique_songs, video_url,
)


class DownloaderTests(unittest.TestCase):
    def test_video_links_drop_playlist_and_tracking_parameters(self):
        expected = "https://www.youtube.com/watch?v=JXgV1rXUoME"
        self.assertEqual(video_url("https://youtu.be/JXgV1rXUoME?si=share"), expected)
        self.assertEqual(
            video_url("https://music.youtube.com/watch?v=JXgV1rXUoME&list=PL123"),
            expected,
        )

    def test_rejects_non_video_and_offsite_links(self):
        for value in (
            "https://youtube.com.evil.test/watch?v=JXgV1rXUoME",
            "https://www.youtube.com/playlist?list=PL123",
            "https://youtu.be/JXgV1rXUoME/extra",
            "http://www.youtube.com/watch?v=JXgV1rXUoME",
            "https://www.youtube.com/watch?v=bad",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                video_url(value)

    @patch("src.downloader.core.tag_audio")
    @patch("src.downloader.core.YoutubeDL")
    def test_download_returns_verified_audio_in_selected_directory(self, factory, tag):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Recording [JXgV1rXUoME].mp3"
            downloader = factory.return_value.__enter__.return_value

            def extract(url, download):
                self.assertEqual(url, "https://www.youtube.com/watch?v=JXgV1rXUoME")
                self.assertTrue(download)
                hook = factory.call_args.args[0]["progress_hooks"][0]
                hook({"status": "downloading", "downloaded_bytes": 1024})
                hook({"status": "downloading", "downloaded_bytes": 2048})
                hook({"status": "finished", "downloaded_bytes": 2048})
                path.write_bytes(b"fixture audio")
                return {"id": "JXgV1rXUoME", "ext": "m4a"}

            downloader.extract_info.side_effect = extract
            downloader.prepare_filename.return_value = str(path.with_suffix(".m4a"))
            transferred = []
            self.assertEqual(
                download_audio("https://youtu.be/JXgV1rXUoME", directory, on_bytes=transferred.append),
                path.resolve(),
            )
            self.assertEqual(transferred, [1024, 1024])
            tag.assert_called_once()

    @patch("src.downloader.core.YoutubeDL")
    def test_does_not_claim_success_for_missing_download(self, factory):
        with tempfile.TemporaryDirectory() as directory:
            downloader = factory.return_value.__enter__.return_value
            downloader.extract_info.return_value = {"id": "JXgV1rXUoME"}
            downloader.prepare_filename.return_value = str(Path(directory) / "missing.m4a")
            with self.assertRaisesRegex(RuntimeError, "could not be verified"):
                download_audio("https://youtu.be/JXgV1rXUoME", directory)

    def test_csv_metadata_and_deduplication(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "songs.csv"
            fields = ["song_id", "song_title", "artist_name", "album_name", "song_url"]
            with path.open("w", encoding="utf-8-sig", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=fields)
                writer.writeheader()
                row = dict(zip(fields, ["ID1", 'Title, "Live"', "Artist", "\u0997\u09be\u09a8", "https://music.amazon.in/tracks/ID1"]))
                writer.writerows([row, row, dict(zip(fields, ["", "Other", "Artist", "", ""]))])
            songs = load_songs_from_csv(path)
            self.assertEqual(songs, [
                Song(title='Title, "Live"', artist="Artist", album="\u0997\u09be\u09a8", song_id="ID1"),
                Song(title="Other", artist="Artist"),
            ])
            self.assertEqual(
                len(unique_songs([Song(title=" Other ", artist="ARTIST"), songs[1]])), 1
            )
            path.write_text("playlist_name,playlist_url\nName,https://example.com\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "CSV needs"):
                load_songs_from_csv(path)

    @patch("src.downloader.core.YoutubeDL")
    def test_search_uses_top_title_and_artist_match(self, factory):
        search = factory.return_value.__enter__.return_value
        search.extract_info.return_value = {"entries": [
            {"id": "JXgV1rXUoME"},
            {"id": "abcdefghijk"},
        ]}
        self.assertEqual(find_video(Song(title="You Right", artist="Doja Cat")),
                         "https://www.youtube.com/watch?v=JXgV1rXUoME")
        search.extract_info.assert_called_once_with("ytsearch1:You Right Doja Cat", download=False)
        search.extract_info.return_value = {"entries": []}
        with self.assertRaisesRegex(RuntimeError, "No YouTube match"):
            find_video("Missing song")
        factory.reset_mock()
        cached = unique_songs([
            Song(title="You Right", song_id="S"),
            Song(title="You Right", song_id="S", youtube_url="https://youtu.be/JXgV1rXUoME"),
        ])
        self.assertEqual(find_video(cached[0]), "https://www.youtube.com/watch?v=JXgV1rXUoME")
        factory.assert_not_called()

    def test_csv_link_cache_preserves_rows_and_existing_links(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "songs.csv"
            fields = ["song_id", "song_title", "artist_name", "playlist_name", "notes"]
            with path.open("w", encoding="utf-8-sig", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=fields)
                writer.writeheader()
                writer.writerows([
                    dict(zip(fields, ["A", "Title", "Artist", "First", 'Unicode \u0997\u09be\u09a8, "note"'])),
                    dict(zip(fields, ["A", "Title", "Artist", "Second", ""])),
                    dict(zip(fields, ["B", "Other", "Artist", "First", "leave blank"])),
                ])
            changed = cache_youtube_urls(path, [
                (Song(title="Title", song_id="A"), "https://youtu.be/JXgV1rXUoME"),
            ])
            self.assertEqual(changed, 2)
            with path.open(encoding="utf-8-sig", newline="") as file:
                rows = list(csv.DictReader(file))
            self.assertEqual(len(rows), 3)
            self.assertEqual(rows[0]["notes"], 'Unicode \u0997\u09be\u09a8, "note"')
            self.assertEqual(rows[1]["youtube_url"], rows[0]["youtube_url"])
            self.assertEqual(rows[2]["youtube_url"], "")
            self.assertEqual(cache_youtube_urls(path, [
                (Song(title="Title", song_id="A"), "https://youtu.be/abcdefghijk"),
            ]), 0)
            original = path.read_bytes()
            with self.assertRaises(ValueError):
                cache_youtube_urls(path, [
                    (Song(title="Other", song_id="B"), "https://example.com/not-youtube"),
                ])
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(len(unique_songs([
                Song(title="One", youtube_url="https://youtu.be/JXgV1rXUoME"),
                Song(title="Two", youtube_url="https://youtu.be/JXgV1rXUoME"),
            ])), 2)

    @patch("src.downloader.core.download_audio")
    def test_batch_saves_resolved_link_and_next_run_skips_search(self, download):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "songs.csv"
            path.write_text("song_id,song_title,artist_name\nA,Title,Artist\n", encoding="utf-8")
            download.side_effect = RuntimeError("temporary download failure")
            with patch("src.downloader.core.find_video", return_value="https://www.youtube.com/watch?v=JXgV1rXUoME"):
                first = download_songs(
                    load_songs_from_csv(path), output_dir=directory, source_csv=path,
                )
            self.assertIsNotNone(first.results[0].error)
            cached = load_songs_from_csv(path)
            self.assertEqual(cached[0].youtube_url, "https://www.youtube.com/watch?v=JXgV1rXUoME")
            download.side_effect = None
            download.return_value = Path(directory) / "audio.mp3"
            with patch("src.downloader.core.YoutubeDL") as search:
                second = download_songs(cached, output_dir=directory, source_csv=path)
            self.assertIsNone(second.results[0].error)
            search.assert_not_called()

    def test_csv_values_override_youtube_metadata_in_id3(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "song.mp3"
            path.write_bytes(b"fixture")
            tag_audio(
                path, Song(title="CSV title", artist="CSV artist", album="CSV album", song_id="AMAZON1"),
                {"title": "Video title", "artist": "Video artist", "album": "Video album"},
            )
            tags = ID3(path)
            self.assertEqual(tags["TIT2"].text, ["CSV title"])
            self.assertEqual(tags["TPE1"].text, ["CSV artist"])
            self.assertEqual(tags["TALB"].text, ["CSV album"])
            self.assertEqual(tags["TXXX:song_id"].text, ["AMAZON1"])

    @patch("src.downloader.core.download_audio")
    @patch("src.downloader.core.find_video")
    def test_parallelism_caps_at_ten_and_logs_transfer_metrics(self, find, download):
        lock = Lock()
        ready = Event()
        active = 0
        peak = 0
        find.side_effect = lambda song: f"https://www.youtube.com/watch?v={int(song.title):011d}"

        def fake_download(url, directory, song, on_bytes, _cache=None):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
                if active == 10:
                    ready.set()
            try:
                if not ready.wait(5):
                    raise RuntimeError("Workers did not start concurrently")
                on_bytes(1024 * 1024)
                return Path(directory) / f"{song.title}.mp3"
            finally:
                with lock:
                    active -= 1

        download.side_effect = fake_download
        with tempfile.TemporaryDirectory() as directory:
            batch = download_songs([Song(title=str(i)) for i in range(12)], output_dir=directory)
            self.assertEqual(peak, 10)
            self.assertTrue(all(result.error is None for result in batch.results))
            self.assertEqual([result.song.title for result in batch.results], [str(i) for i in range(12)])
            record = json.loads(batch.log_path.read_text(encoding="utf-8"))
            self.assertEqual(record["bytes_downloaded"], 12 * 1024 * 1024)
            self.assertEqual(record["succeeded"], 12)
            self.assertGreater(record["elapsed_seconds"], 0)
            self.assertGreater(record["average_mib_per_second"], 0)
            progress = json.loads((Path(directory) / "progress.json").read_text())
            self.assertEqual(progress["status"], "completed")
            self.assertEqual(progress["completed"], 12)
            self.assertEqual(progress["succeeded"], 12)
            self.assertEqual(progress["failed"], 0)
            waves = [
                json.loads(line)
                for line in (Path(directory) / "worker_batches.jsonl").read_text().splitlines()
            ]
            self.assertEqual([wave["songs"] for wave in waves], [10, 2])
            self.assertEqual(progress["current_batch"], 2)
        with self.assertRaisesRegex(ValueError, "1 to 10"):
            download_songs("song", max_workers=11)

    @patch("src.downloader.core.download_audio")
    @patch("src.downloader.core.find_video", return_value="https://www.youtube.com/watch?v=JXgV1rXUoME")
    def test_failure_isolation_and_metadata_specific_outputs(self, find, download):
        def fake_download(url, directory, song, on_bytes, _cache=None):
            if song.title == "bad":
                raise RuntimeError("unavailable")
            on_bytes(500)
            return Path(directory) / f"{song.song_id}.mp3"

        download.side_effect = fake_download
        with tempfile.TemporaryDirectory() as directory:
            songs = [
                Song(title="good", album="First", song_id="A"),
                Song(title="bad", song_id="B"),
                Song(title="good", album="Second", song_id="C"),
                Song(title="good", album="First", song_id="A"),
            ]
            batch = download_songs(songs, output_dir=directory)
            self.assertEqual(len(batch.results), 3)
            self.assertEqual(batch.results[1].error, "unavailable")
            self.assertNotEqual(batch.results[0].path, batch.results[2].path)
            self.assertEqual(batch.bytes_downloaded, 1000)
            snapshot = json.loads((Path(directory) / "results.json").read_text())
            self.assertEqual(snapshot[1]["error"], "unavailable")
            self.assertEqual(snapshot[0]["song"]["song_id"], "A")
            download_songs("bad", output_dir=directory)
            logs = [json.loads(line) for line in batch.log_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(logs), 2)
            self.assertEqual(logs[0]["failed"], 1)
            self.assertEqual(logs[1]["succeeded"], 0)

    @patch("src.downloader.__main__.download_songs")
    def test_cli_reports_unicode_titles_on_windows_console(self, download):
        from src.downloader.__main__ import main

        title = "\u66f2\u76ee\uff1aLive"
        download.return_value = BatchResult(
            [DownloadResult(Song(title=title), path=Path("downloads") / f"{title}.mp3")],
            1.0, 100, Path("downloads") / "batches.jsonl",
        )
        buffer = io.BytesIO()
        stream = io.TextIOWrapper(buffer, encoding="cp1252")
        try:
            with patch("sys.stdout", stream), patch("sys.stderr", stream):
                self.assertEqual(main([title]), 0)
                stream.flush()
            self.assertIn(title, buffer.getvalue().decode("utf-8"))
        finally:
            stream.close()

    @patch("src.downloader.core.download_audio")
    @patch("src.downloader.core.find_video")
    def test_existing_song_id_skips_network_even_after_filename_and_metadata_changes(self, find, download):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "renamed.mp3"
            path.write_bytes(b"fixture")
            url = "https://www.youtube.com/watch?v=JXgV1rXUoME"
            tag_audio(path, Song(title="Old", artist="Artist", album="Old album", song_id="S", youtube_url=url))
            song = Song(title="Updated", artist="Artist", album="New album", song_id="S")
            batch = download_songs([song, song], output_dir=directory)
            self.assertEqual(len(batch.results), 1)
            self.assertTrue(batch.results[0].cached)
            self.assertEqual(batch.results[0].path, path.resolve())
            self.assertEqual(batch.bytes_downloaded, 0)
            self.assertEqual(ID3(path)["TXXX:song_id"].text, ["S"])
            self.assertEqual(ID3(path)["TALB"].text, ["New album"])
            find.assert_not_called()
            download.assert_not_called()

    @patch("src.downloader.core.YoutubeDL")
    def test_direct_download_reuses_embedded_id_without_touching_existing_file(self, factory):
        from src.downloader.cache import AudioCache

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "arbitrary.mp3"
            path.write_bytes(b"fixture")
            song = Song(title="Title", artist="Artist", album="Album", song_id="S",
                        youtube_url="https://www.youtube.com/watch?v=JXgV1rXUoME")
            tag_audio(path, song)
            before = path.read_bytes()
            self.assertEqual(download_audio(song.youtube_url, directory, song), path.resolve())
            self.assertEqual(path.read_bytes(), before)
            factory.assert_not_called()
            self.assertIsNone(AudioCache(directory).find(
                Song(title="Title", artist="Artist", song_id="Different")
            ))

    @patch("src.downloader.core.download_audio")
    @patch("src.downloader.core.find_video", return_value="https://www.youtube.com/watch?v=JXgV1rXUoME")
    def test_next_worker_batch_waits_for_all_current_workers(self, find, download):
        next_started = Event()
        slow_finished = Event()

        def fake_download(url, directory, song, on_bytes, _cache=None):
            if song.title == "slow":
                next_started.wait(0.2)
                slow_finished.set()
            elif song.title in {"third", "fourth"}:
                if not slow_finished.is_set():
                    raise RuntimeError("Next batch overlapped the previous batch")
                next_started.set()
            return Path(directory) / f"{song.title}.mp3"

        download.side_effect = fake_download
        with tempfile.TemporaryDirectory() as directory:
            batch = download_songs(
                ["slow", "fast", "third", "fourth"], max_workers=2, output_dir=directory,
            )
            self.assertTrue(all(result.error is None for result in batch.results))
            self.assertEqual(download.call_count, 4)

    def test_missing_csv_metadata_is_not_guessed_from_youtube(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "song.mp3"
            path.write_bytes(b"fixture")
            tag_audio(path, Song(title="Title", artist="Old artist", album="Old album", song_id="S"))
            tag_audio(path, Song(title="Title", song_id="S"),
                      {"artist": "YouTube guess", "album": "YouTube guess"})
            tags = ID3(path)
            self.assertNotIn("TPE1", tags)
            self.assertNotIn("TALB", tags)
            self.assertEqual(tags["TXXX:song_id"].text, ["S"])

    @patch("src.downloader.core.download_audio")
    @patch("src.downloader.core.find_video", side_effect=RuntimeError("unavailable"))
    def test_missing_link_failure_does_not_redownload_existing_audio(self, find, download):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "renamed.mp3"
            path.write_bytes(b"fixture")
            tag_audio(path, Song(title="Old title", song_id="S"))
            batch = download_songs(Song(title="Current title", song_id="S"), output_dir=directory)
            result = batch.results[0]
            self.assertTrue(result.cached)
            self.assertEqual(result.path, path.resolve())
            self.assertIn("YouTube link lookup failed", result.error)
            self.assertEqual(ID3(path)["TIT2"].text, ["Current title"])
            download.assert_not_called()


if __name__ == "__main__":
    unittest.main()
