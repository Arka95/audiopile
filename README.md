# Audiopile

## Documentation index

- [Usage manual](README.md)
- [Development and pipeline](dev.readme.md)
- [Debugging and TODO](debug.readme.md)

Export public Amazon Music playlists to searchable CSVs and download authorized
YouTube recordings as tagged MP3s. This does not export complete listening history.

## Everyday usage

Run from `C:\projects\audiopile` after setup:

1. Add playlist names and direct public links to **`amazonmusic.playlists.csv`**
   using its `playlist_name,playlist_url` columns.
2. Run **`python -m src.sync --workers 10`**.
3. Sync appends newly visible playlist entries to **`all_songs.partial.csv`**,
   resolves missing YouTube links, and downloads untracked songs into **`downloads\`**.

Downloads run in parallel batches of up to 10; each batch finishes before the
next starts. Rerun after changing your playlists. Refresh is additions-only:
it does not remove old songs or reconcile reordered positions.

**Already downloaded?** Songs in `downloads\downloaded.json` are skipped by
song ID without checking or changing their files or tags, even if a file was
moved or deleted. New MP3s get title, artist, album and song ID from the CSV.
Run only one sync/download process at a time.

## One-time setup

Use Python (tested with 3.12) and Node.js on `PATH`:

```powershell
python -m pip install -r .\requirements.txt
python -m playwright install chromium
```

FFmpeg is bundled through the Python dependencies; a system FFmpeg is preferred
when available.

## Sync everything

```powershell
python -m src.sync

# Custom inputs and lower concurrency.
python -m src.sync --playlists .\amazonmusic.playlists.csv --songs .\all_songs.partial.csv --workers 2
```

`--limit 3` processes the first three unique input songs, not necessarily three
new downloads; every playlist is still refreshed. Sync is a one-shot command,
not a background scheduler.

## Scan playlists without downloading

```powershell
# Additions-only refresh of the catalog into the default song CSV.
$links = @(Import-Csv .\amazonmusic.playlists.csv | ForEach-Object { $_.playlist_url })
python -c "import sys; from src.export_playlists import refresh_playlist; print(refresh_playlist(sys.argv[1:]))" @links

# Additions-only refresh of one playlist.
python -c "from src.export_playlists import refresh_playlist; print(refresh_playlist('https://music.amazon.in/user-playlists/PLAYLIST_ID'))"

# Standalone fresh export of one playlist to a separate CSV (replaces its output).
python .\src\export_playlists.py "https://music.amazon.in/user-playlists/PLAYLIST_ID" --headless --output .\playlist.csv
```

Public playlist totals may be unverified. The standalone exporter can write
`playlist.partial.csv` instead of `playlist.csv`; use the printed output path.
An empty scan writes no export and leaves any existing export unchanged.
Private-library discovery is experimental; see `debug.readme.md`.

## Download without scanning Amazon again

```powershell
# Resume from the existing CSV, skipping tracked songs.
python -m src.downloader --csv .\all_songs.partial.csv --workers 2

# Process a small selection from the CSV.
python -m src.downloader --csv .\all_songs.partial.csv --workers 2 --limit 3

# One video, one query, or multiple queries.
python -m src.downloader "https://www.youtube.com/watch?v=JXgV1rXUoME"
python -m src.downloader "You Right Doja Cat"
python -m src.downloader "You Right Doja Cat" "Another title artist" --workers 2
```

Defaults: **192 kbps MP3**, **10 workers**, `downloads\` output. Without a cached
link, the top title + artist search result is selected automatically:
**verify the recording if accuracy matters**. CSV columns are `song_id`,
`song_title`, `artist_name`, `album_name`, and `youtube_url`; playlist duplicates
stay in the CSV but are deduplicated for downloads.

Supplied blank metadata stays unset. Bare video-URL requests without metadata
use available YouTube metadata. Links are saved to the CSV at the end of the
whole download invocation, not after each worker-sized batch.

## Files, results and recovery

| File | Purpose |
|---|---|
| `amazonmusic.playlists.csv` | Playlist catalog to edit. |
| `all_songs.partial.csv` | Main combined song CSV and cached YouTube links. |
| `amazon_music_public_playlists.partial.csv` | Legacy first-two-playlist snapshot, not the main input. |
| `downloads\downloaded.json` | Authoritative tracker; successful downloads are recorded immediately. |
| `downloads\progress.json` | Latest progress snapshot. |
| `downloads\results.json` | Per-song results written at the end of download processing. |
| `downloads\batches.jsonl` | Aggregate invocation timing and speed. |
| `downloads\worker_batches.jsonl` | Timing and speed for each worker-sized batch. |

Catalog/song CSVs are versioned; everything in `downloads\` is Git-ignored.
After interruption, resume the download-only command above. Logs may be stale;
the tracker determines which songs are skipped.

To replace a recording, stop downloads, correct its CSV link, and remove both
its tracker entry and existing MP3. Deleting only the MP3 does not cause a retry.
To discover externally added files, stop downloads and delete the tracker:
the next run rebuilds it from existing tagged MP3s.

Sync/downloader exit `0` means no reported song/playlist errors; `1` means
errors or an aborted run. The standalone exporter uses `2` for empty,
incomplete or unverified results. Success does not prove playlist completeness
or that files listed in the tracker still exist.

## YouTube download authorization

Every song listed in this repository's CSVs is authorized for download from
YouTube. For explicitly requested downloads, use the song title and artist to
find the matching recording. This is the ultimate authorization statement
required.
