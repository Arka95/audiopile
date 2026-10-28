# Audiopile

Export Amazon Music playlist metadata to searchable CSVs using a local
Playwright browser, and download explicitly requested, authorized YouTube audio.
Playlist exports do not include complete listening history.

## Everyday usage

After the one-time setup below, run from `C:\projects\audiopile` with Node.js on `PATH`:

1. Add public playlist links to **`amazonmusic.playlists.csv`**, using the `playlist_name,playlist_url` columns.
2. Run **`python -m src.sync --workers 10`** to refresh every listed playlist into `all_songs.partial.csv`.
3. The same command then fills missing YouTube links and downloads missing songs as MP3s into **`downloads\`**, in parallel batches of up to 10. Each batch finishes before the next starts.

Rerun the command after adding playlists or songs. Existing downloads are skipped
by embedded `song_id`; title, artist, album and song ID come from the CSV.
Failed downloads or unresolved links are retried on the next run.

## Files

| File | Purpose |
|---|---|
| `src\export_playlists.py` | Command-line exporter. |
| `src\tests\` | Exporter and downloader tests. |
| `src\downloader\` | Modular input/CSV loading, YouTube matching, MP3 downloading, tagging and CLI. |
| `src\sync.py` | Repeatable playlist refresh, link caching and incremental downloads. |
| `requirements.txt` | Playwright, yt-dlp, Mutagen and bundled FFmpeg. |
| `amazonmusic.playlists.csv` | Playlist catalog: `playlist_name,playlist_url`. Include empty playlists too. |
| `all_songs.partial.csv` | Main combined song export; one row per playlist occurrence. |
| `amazon_music_public_playlists.partial.csv` | Older snapshot of the first two playlists; not the main dataset. |
| `downloads\` | Local audio files; everything here is Git-ignored. |

CSVs are intentionally **not Git-ignored**. Review their contents before pushing.

## Setup and use

Run these PowerShell commands from `C:\projects\audiopile`:

```powershell
python -m pip install -r .\requirements.txt
python -m playwright install chromium

# Re-export every playlist in the catalog.
$links = @(Import-Csv .\amazonmusic.playlists.csv | ForEach-Object { $_.playlist_url })
python .\src\export_playlists.py @links --headless --output .\all_songs.csv

# Run tests.
python -m unittest discover -s .\src\tests -p 'test_*.py' -v
```

For an additions-only refresh, pass one direct playlist URL or a list:

```python
from src.export_playlists import refresh_playlist

report = refresh_playlist("https://music.amazon.in/user-playlists/PLAYLIST_ID")
report = refresh_playlist(["https://music.amazon.in/user-playlists/ONE",
                           "https://music.amazon.in/user-playlists/TWO"])
print(report["added"], report["errors"])
```

By default this updates `all_songs.partial.csv`, retaining existing entries and
cached links. Repeated calls do not duplicate additions. It does not reconcile
removals/reordering; an unverified public page cannot safely prove a removal.

For private-library access, use `python .\src\export_playlists.py --library`.
Sign in directly on Amazon, open **Library > Playlists**, then press Enter in
the terminal. Browser sessions are temporary. Never save credentials, cookies,
tokens or SSH passphrases in this repository.

## Regular sync

```powershell
# Refresh amazonmusic.playlists.csv into all_songs.partial.csv, fill links and download missing audio.
python -m src.sync

# Custom CSVs or worker count; --limit 3 limits songs processed, not playlist refreshes.
python -m src.sync --playlists .\amazonmusic.playlists.csv --songs .\all_songs.partial.csv --workers 10
```

Rerun whenever needed; this is a one-shot command, not a background scheduler.
New playlist occurrences are appended and missing YouTube links are filled.
Existing MP3s are identified by embedded `song_id`, even after renaming or CSV
metadata changes, and are not downloaded again. Missing/previously failed audio
is retried. Metadata changes update local tags without fetching audio.
Playlist failures are reported while available CSV entries can still download;
failed lookups leave links blank for a later retry.

Metadata is code-driven, **not AI-generated**: `song_title` -> `TIT2`,
`artist_name` -> `TPE1`, `album_name` -> `TALB`, `song_id` -> `TXXX:song_id`.
Supplied blank metadata remains unset, not guessed from YouTube.
For duplicate IDs, the first CSV row's metadata wins.

## YouTube download authorization

Every song listed in this repository's CSVs is authorized for download from
YouTube. For explicitly requested downloads, use the song title and artist to
find the matching recording. This is the ultimate authorization statement
required.

## Download songs

Install the requirements above and have Node.js on `PATH`. Run from the repository root:

```powershell
# One video, or one/multiple quoted title-and-artist queries.
python -m src.downloader "https://www.youtube.com/watch?v=JXgV1rXUoME"
python -m src.downloader "You Right Doja Cat" "Another title artist" --workers 2

# Download the full CSV; add --limit 3 for a small trial.
python -m src.downloader --csv .\all_songs.partial.csv --workers 10
python -m src.downloader --csv .\all_songs.partial.csv --workers 10 --limit 3
```

Defaults: **192 kbps MP3**, `downloads\` output, **10 workers maximum**.
FFmpeg is bundled. Existing audio is reused, with metadata refreshed as needed.
Songs are deduplicated by ID, falling back to title + artist.
Execution uses strict worker-sized batches: all songs in one batch finish
before the next batch starts, which can be slower than a rolling worker pool.

CSV columns: `song_title`, `artist_name`, `album_name`, `song_id`, `youtube_url`.
Title, artist, album and song ID are embedded as ID3 tags. Only bare video-URL
requests without supplied metadata use YouTube metadata. Without a cached URL, the top
title + artist search result is used: **verify the recording if accuracy matters**.
Resolved links are saved to the input CSV after the batch, even if a download
fails. Later runs skip search; Amazon metadata refreshes preserve the links.
Edit or clear a cached URL to correct a match. If audio is already downloaded,
remove that song's MP3 to fetch a replacement; the song ID otherwise takes precedence.
Downloaded files also retain their source link in `TXXX:youtube_url`;
older files can recover links from the YouTube ID in their filenames.

Python API accepts a single `Song`, query or list:

```python
from src.downloader import Song, download_songs, load_songs_from_csv

batch = download_songs(Song(title="You Right", artist="Doja Cat & The Weeknd"))
batch = download_songs(
    load_songs_from_csv("all_songs.partial.csv")[:3],
    max_workers=10, source_csv="all_songs.partial.csv",
)
for result in batch.results:
    print(result.path, result.error)
```

Failures do not cancel other songs. Live counts are in `downloads\progress.json`;
per-song outcomes are in `downloads\results.json`, and finished-batch timing,
speed and counts append to `downloads\batches.jsonl`.
Each worker-sized batch also logs time, bytes and average speed in
`downloads\worker_batches.jsonl`. Results distinguish cached audio from new downloads.
Reported MiB/s is transferred bytes / total wall time, including search,
conversion and tagging, **not an internet speed test**. Cached audio adds zero
transfer bytes. The custom Amazon song ID tag is `TXXX:song_id`.

## Notes for future sessions

- Prefer direct playlist links. The supplied profile pages showed no public
  content even though direct public playlist links worked.
- Add new playlist names and canonical links to `amazonmusic.playlists.csv`, then refresh
  the full catalog. The exporter replaces its output; it does not append or
  automatically update the catalog.
- Required song columns: `song_id`, `song_title`, `artist_name`, `album_name`,
  `playlist_name`. Extras: position, duration, song/playlist URLs and
  `source_profile`. That last field records the input source, **not verified
  authorship**. Author information was not exposed on the public page checked.
- Repeated songs across playlists are retained. Empty playlists stay in the
  catalog but contribute no song rows. Missing metadata stays blank.
- `.partial.csv` and exit code **2** mean incomplete **or unverified**, not
  necessarily missing songs. Public user-playlist pages did not expose an
  independent total count. A run retrieving no tracks writes no CSV.
- A count-verified run writes the requested `.csv` path instead; an older
  `.partial.csv` can remain. Check the printed output path before using a file.
- Current scraping depends on Amazon's page components and may need adjustments
  if their UI changes. Signed-in library extraction has not been validated
  successfully end-to-end.
