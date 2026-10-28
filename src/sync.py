"""Refresh the playlist catalog, cache YouTube links and download missing audio."""

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
import sys

from .downloader import BatchResult, DOWNLOADS, download_songs, load_songs_from_csv
from .export_playlists import refresh_playlist


ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class SyncResult:
    refresh: dict
    batch: BatchResult


def sync_playlists(
    catalog_path=ROOT / "playlists.csv",
    songs_path=ROOT / "all_songs.partial.csv",
    max_workers=10,
    output_dir=DOWNLOADS,
    limit=None,
):
    if not isinstance(max_workers, int) or not 1 <= max_workers <= 10:
        raise ValueError("max_workers must be an integer from 1 to 10.")
    if limit is not None and (not isinstance(limit, int) or limit < 1):
        raise ValueError("limit must be a positive integer.")
    with Path(catalog_path).open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if "playlist_url" not in (reader.fieldnames or []):
            raise ValueError("Playlist catalog needs a playlist_url column.")
        urls = [
            row["playlist_url"].strip()
            for row in reader if (row.get("playlist_url") or "").strip()
        ]
    if not urls:
        raise ValueError("Playlist catalog is empty.")
    songs_path = Path(songs_path)
    refreshed = refresh_playlist(urls, csv_path=songs_path)
    songs = load_songs_from_csv(songs_path) if songs_path.exists() else []
    if limit is not None:
        songs = songs[:limit]
    batch = download_songs(
        songs, max_workers=max_workers, output_dir=output_dir,
        source_csv=songs_path if songs_path.exists() else None,
    )
    return SyncResult(refreshed, batch)


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--playlists", type=Path, default=ROOT / "playlists.csv")
    parser.add_argument("--songs", type=Path, default=ROOT / "all_songs.partial.csv")
    parser.add_argument("--workers", type=int, choices=range(1, 11), default=10)
    parser.add_argument("--limit", type=int, help="Process only the first N unique songs after refreshing")
    args = parser.parse_args(argv)
    try:
        result = sync_playlists(args.playlists, args.songs, args.workers, limit=args.limit)
    except (ValueError, OSError) as error:
        parser.exit(1, f"Sync failed: {error}\n")
    failed = [item for item in result.batch.results if item.error is not None]
    cached = sum(item.cached for item in result.batch.results)
    downloaded = sum(not item.cached and item.error is None for item in result.batch.results)
    print(f"Refresh: {result.refresh['added']} new song entries; "
          f"{len(result.refresh['errors'])} playlist errors.")
    print(f"Audio: {downloaded} downloaded; {cached} reused; {len(failed)} failed.")
    print(f"Time: {result.batch.elapsed_seconds:.2f}s; "
          f"average {result.batch.average_mib_per_second:.2f} MiB/s.")
    for item in failed:
        print(f"FAILED {item.song.title}: {item.error}")
    return 1 if failed or result.refresh["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
