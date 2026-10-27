# Audiopile

Export Amazon Music playlist metadata to searchable CSVs using a local
Playwright browser. This exports neither audio nor complete listening history.

## Files

| File | Purpose |
|---|---|
| `src\export_playlists.py` | Command-line exporter. |
| `src\test_export_playlists.py` | Unit and browser-fixture tests. |
| `requirements.txt` | Python dependency: Playwright. |
| `playlists.csv` | Playlist catalog: `playlist_name,playlist_url`. Include empty playlists too. |
| `all_songs.partial.csv` | Main combined song export; one row per playlist occurrence. |
| `amazon_music_public_playlists.partial.csv` | Older snapshot of the first two playlists; not the main dataset. |

CSVs are intentionally **not Git-ignored**. Review their contents before pushing.

## Setup and use

Run these PowerShell commands from `C:\projects\audiopile`:

```powershell
python -m pip install -r .\requirements.txt
python -m playwright install chromium

# Refresh every playlist in the catalog.
$links = @(Import-Csv .\playlists.csv | ForEach-Object { $_.playlist_url })
python .\src\export_playlists.py @links --headless --output .\all_songs.csv

# Run tests.
python -m unittest discover -s .\src -p 'test_*.py' -v
```

For private-library access, use `python .\src\export_playlists.py --library`.
Sign in directly on Amazon, open **Library > Playlists**, then press Enter in
the terminal. Browser sessions are temporary. Never save credentials, cookies,
tokens or SSH passphrases in this repository.

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
