# Audiopile

Export Amazon Music playlist metadata to searchable CSVs using a local
Playwright browser, and download explicitly requested, authorized YouTube audio.
Playlist exports do not include complete listening history.

## Files

| File | Purpose |
|---|---|
| `src\export_playlists.py` | Command-line exporter. |
| `src\tests\` | Exporter and downloader tests. |
| `src\downloader\` | Modular input/CSV loading, YouTube matching, MP3 downloading, tagging and CLI. |
| `requirements.txt` | Playwright, yt-dlp, Mutagen and bundled FFmpeg. |
| `playlists.csv` | Playlist catalog: `playlist_name,playlist_url`. Include empty playlists too. |
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
$links = @(Import-Csv .\playlists.csv | ForEach-Object { $_.playlist_url })
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

## YouTube download authorization

The repository owner states that every song listed in this repository's CSVs
is authorized for download from YouTube. For explicitly requested downloads,
use the song title and artist to find the matching recording. This records the
owner's authorization statement, not independent verification of licensing.
Do not bypass DRM, paywalls or access controls.

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

CSV columns: `song_title`, `artist_name`, `album_name`, `song_id`, `youtube_url`.
Title, artist, album and song ID are embedded as ID3 tags. Missing values use
available YouTube metadata, never invented values. Without a cached URL, the top
title + artist search result is used: **verify the recording if accuracy matters**.
Resolved links are saved to the input CSV after the batch, even if a download
fails. Later runs skip search; Amazon metadata refreshes preserve the links.
Edit or clear a cached URL to correct a match.

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
Reported MiB/s is transferred bytes / total wall time, including search,
conversion and tagging, **not an internet speed test**. Cached audio adds zero
transfer bytes. The custom Amazon song ID tag is `TXXX:song_id`.

The first downloaded recording was **"You Right" by Doja Cat & The Weeknd**,
YouTube ID `JXgV1rXUoME`, approximately **3:10**. It was moved from Windows
Downloads into this repository's `downloads\` directory and converted locally
to MP3; the original M4A is retained as a source copy. It is not in the current
CSV: no CSV album or song ID was invented.
Audio files and batch logs stay local; CSV metadata remains versioned.

## Notes for future sessions

- Prefer direct playlist links. The supplied profile pages showed no public
  content even though direct public playlist links worked.
- Add new playlist names and canonical links to `playlists.csv`, then refresh
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
