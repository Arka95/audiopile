import argparse
import sys

from . import download_songs, load_songs_from_csv, unique_songs


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Download authorized YouTube audio into audiopile\\downloads."
    )
    parser.add_argument("songs", nargs="*", help="Video URLs or quoted title-and-artist search queries")
    parser.add_argument("--csv", help="CSV containing song_title/artist_name or youtube_url")
    parser.add_argument("--workers", type=int, choices=range(1, 11), default=10)
    parser.add_argument("--limit", type=int, help="Download only the first N unique input songs")
    args = parser.parse_args(argv)
    if not args.songs and not args.csv:
        parser.error("Provide songs or --csv.")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive.")
    try:
        songs = list(args.songs)
        if args.csv:
            songs.extend(load_songs_from_csv(args.csv))
        songs = unique_songs(songs)
        if args.limit:
            songs = songs[:args.limit]
        batch = download_songs(songs, max_workers=args.workers, source_csv=args.csv)
    except (ValueError, OSError) as error:
        parser.exit(1, f"Download input or CSV update failed: {error}\n")
    failures = 0
    for result in batch.results:
        label = result.song.title or result.song.youtube_url
        if result.error is not None:
            failures += 1
            print(f"FAILED {label}: {result.error}")
        else:
            print(f"SAVED {label}: {result.path} (YouTube: {result.youtube_url})")
    print(f"{len(batch.results) - failures} succeeded; {failures} failed.")
    print(
        f"Batch: {batch.elapsed_seconds:.2f}s; "
        f"average {batch.average_mib_per_second:.2f} MiB/s; "
        f"{batch.average_seconds_per_song:.2f}s/song. Log: {batch.log_path}"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
