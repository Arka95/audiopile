# Audiopile development

## Documentation index

- [Usage manual](README.md)
- [Development and pipeline](dev.readme.md)
- [Debugging and TODO](debug.readme.md)

## Source map

| Source | Responsibility |
|---|---|
| `src\sync.py` | Read the playlist catalog, refresh the song CSV, invoke downloads. |
| `src\export_playlists.py` | Playwright discovery, virtualized-row extraction, CSV export and additions-only refresh. |
| `src\downloader\inputs.py` | `Song` inputs, URL normalization, deduplication, CSV loading and link persistence. |
| `src\downloader\cache.py` | Authoritative persistent download tracker and first-run MP3 discovery. |
| `src\downloader\core.py` | YouTube lookup, yt-dlp downloads, FFmpeg conversion, batches and metrics. |
| `src\downloader\metadata.py` | Deterministic ID3 attribution with Mutagen. |
| `src\downloader\__main__.py` | Download CLI. Public Python exports are in `__init__.py`. |
| `src\tests\` | Export, refresh, download, tracker and sync regression tests. |

## Pipeline and persistence

1. Read direct playlist URLs from `amazonmusic.playlists.csv`. Playwright reads
   public Amazon page components; this is not an authenticated Amazon API client.
   Scrolling accumulates virtualized track rows.
2. `refresh_playlist` compares occurrence counts per playlist and song identity,
   appending newly visible occurrences. It preserves old rows and cached links;
   removals/reordering are not reconciled. The standalone exporter instead
   replaces its output using an atomic, UTF-8-BOM, spreadsheet-safe CSV writer.
3. Load unique songs: `song_id` first, normalized title + artist otherwise;
   URL-only inputs fall back to their video URL. First duplicate metadata wins,
   with a later duplicate's nonblank URL adopted if needed.
4. Load `downloads\downloaded.json`. Only when absent, seed it from tagged MP3s,
   recovering older YouTube links from filenames where possible. Tracker hits
   are trusted without file checks, network downloads or metadata updates.
5. For untracked songs, reuse the supplied URL or search the top title + artist
   result. Use separate yt-dlp instances per worker. Execute strict batches of
   `max_workers` (1-10); wait for the whole batch before submitting the next.
6. Download audio, convert to 192 kbps MP3, verify a nonempty output within the
   target directory, tag it, then atomically persist its tracker entry. Tracker
   updates are thread-safe within one job, not coordinated across processes.
7. Record batch metrics and final results. CSV links are atomically persisted
   at the end of the whole invocation, including links for failed downloads.
   Interrupted jobs can therefore lose new CSV links but retain tracked successes.

## Requirements and contracts

- Runtime: Python (tested with 3.12), Node.js, Playwright Chromium, yt-dlp,
  Mutagen and imageio-ffmpeg; versions are constrained in `requirements.txt`.
  Prefer a system FFmpeg, otherwise use the bundled executable.
- Accept one `Song`, query, URL or mapping, or a list; support CSV inputs.
  Keep playlist occurrences in exports while scheduling each unique song once.
- Song ID is the primary idempotency key and must be embedded in new MP3s.
  Never merge different nonempty IDs merely because their YouTube URLs match.
- Supplied metadata is authoritative: `song_title` -> `TIT2`, `artist_name` ->
  `TPE1`, `album_name` -> `TALB`, `song_id` -> `TXXX:song_id`.
  Missing supplied fields remain unset. Only metadata-free video requests use
  YouTube fallback values. Store the source link in `TXXX:youtube_url`.
- Never alter tracked audio. A tracked file can be absent; that is an intentional
  assumption, not a verification result. A malformed tracker fails the job.
- Per-song errors are isolated. Infrastructure/CSV/logging errors can still abort
  a job; Windows progress-file replacement currently has bounded retries.
- Log elapsed time and aggregate bytes/elapsed MiB/s per invocation and worker
  batch, including lookup, conversion and tagging time. Cached songs add no
  transfer bytes; throughput is not a connection-speed measurement.
- Keep media, logs and tracker local under ignored `downloads\`. Keep credentials
  out of source, CSVs and Git. Public-page completeness must not be invented.

## Python API and validation

```python
from src.export_playlists import refresh_playlist
from src.downloader import Song, download_songs, load_songs_from_csv
from src.sync import sync_playlists

report = refresh_playlist(["https://music.amazon.in/user-playlists/PLAYLIST_ID"])
batch = download_songs(Song(title="Title", artist="Artist", album="Album", song_id="ID"))
batch = download_songs(
    load_songs_from_csv("all_songs.partial.csv"),
    max_workers=2, source_csv="all_songs.partial.csv",
)
result = sync_playlists(max_workers=2)
```

```powershell
python -W error -m unittest discover -s .\src\tests -p 'test_*.py' -v
git --no-pager diff --check
```
