"""YouTube matching, audio downloads and bounded batch execution."""

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from threading import Lock
from time import perf_counter

from imageio_ffmpeg import get_ffmpeg_exe
from yt_dlp import YoutubeDL

from .cache import AudioCache
from .inputs import Song, as_song, cache_youtube_urls, unique_songs, video_url
from .metadata import tag_audio


DOWNLOADS = Path(__file__).resolve().parents[2] / "downloads"
LOG_LOCK = Lock()


@dataclass(frozen=True)
class DownloadResult:
    song: Song
    path: Path | None = None
    youtube_url: str = ""
    error: str | None = None
    cached: bool = False


@dataclass(frozen=True)
class BatchResult:
    results: list[DownloadResult]
    elapsed_seconds: float
    bytes_downloaded: int
    log_path: Path

    @property
    def average_mib_per_second(self):
        return self.bytes_downloaded / (1024 * 1024 * self.elapsed_seconds) if self.elapsed_seconds else 0

    @property
    def average_seconds_per_song(self):
        return self.elapsed_seconds / len(self.results) if self.results else 0


def ffmpeg_executable():
    return shutil.which("ffmpeg") or get_ffmpeg_exe()


def find_video(song):
    song = as_song(song)
    if song.youtube_url:
        return song.youtube_url
    query = " ".join(part.strip() for part in (song.title, song.artist) if part.strip())
    with YoutubeDL({
        "quiet": True, "extract_flat": True, "js_runtimes": {"node": {}},
        "socket_timeout": 20, "retries": 2,
    }) as search:
        info = search.extract_info(f"ytsearch1:{query}", download=False)
    entries = info.get("entries") if info else None
    entry = next((entry for entry in entries or [] if entry), None)
    if not entry:
        raise RuntimeError(f"No YouTube match found for {query}.")
    return video_url(
        entry.get("webpage_url") or entry.get("url")
        or f"https://www.youtube.com/watch?v={entry.get('id', '')}"
    )


def _reuse_cached(entry, song, cache):
    provided = any((song.title, song.artist, song.album, song.song_id))
    if provided and (song.song_id or not entry.song.song_id):
        fields = ("title", "artist", "album", "song_id")
        if any(getattr(song, field) != getattr(entry.song, field) for field in fields):
            tag_audio(entry.path, replace(song, youtube_url=entry.song.youtube_url or song.youtube_url))
            cache.remember(entry.path)
    return entry.path


def download_audio(url, output_dir=DOWNLOADS, song=None, on_bytes=None, _cache=None):
    url = video_url(url)
    song = as_song(song) if song is not None else Song(youtube_url=url)
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    song = replace(song, youtube_url=url)
    cache = _cache if _cache is not None else AudioCache(output_dir)
    existing = cache.find(song)
    if existing is not None:
        return _reuse_cached(existing, song, cache)
    signature = (song.title, song.artist, song.album, song.song_id)
    suffix = ""
    if any(signature):
        digest = hashlib.sha256(json.dumps(signature).encode("utf-8")).hexdigest()[:12]
        suffix = f" [{digest}]"
    last_bytes = 0

    def progress(event):
        nonlocal last_bytes
        if event.get("status") == "downloading":
            current = event.get("downloaded_bytes") or 0
            delta = max(0, current - last_bytes)
            last_bytes = current
            if on_bytes is not None:
                on_bytes(delta)

    options = {
        "format": "bestaudio[ext=m4a]/bestaudio",
        "outtmpl": str(output_dir / ("%(title)s [%(id)s]" + suffix + ".%(ext)s")),
        "windowsfilenames": True,
        "noplaylist": True,
        "overwrites": False,
        "final_ext": "mp3",
        "quiet": True,
        "noprogress": True,
        "js_runtimes": {"node": {}},
        "socket_timeout": 20,
        "retries": 2,
        "fragment_retries": 2,
        "ffmpeg_location": ffmpeg_executable(),
        "postprocessors": [{
            "key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192",
        }],
        "progress_hooks": [progress],
    }
    with YoutubeDL(options) as downloader:
        info = downloader.extract_info(url, download=True)
        if not info or info.get("_type") == "playlist":
            raise RuntimeError("No individual recording was downloaded.")
        path = Path(downloader.prepare_filename(info)).with_suffix(".mp3").resolve()
    if not path.is_relative_to(output_dir) or not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError("The downloaded audio file could not be verified.")
    tag_audio(path, song, info)
    cache.remember(path)
    return path


def download_songs(songs, max_workers=10, output_dir=DOWNLOADS, source_csv=None):
    if not isinstance(max_workers, int) or not 1 <= max_workers <= 10:
        raise ValueError("max_workers must be an integer from 1 to 10.")
    songs = unique_songs(songs)
    started_at = datetime.now(timezone.utc).isoformat()
    started = perf_counter()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    cache = AudioCache(output_dir)
    resolved = {}
    guard = Lock()
    bytes_downloaded = 0
    completed = 0
    succeeded = 0
    failed = 0
    cached = 0
    current_batch = 0
    total_batches = (len(songs) + max_workers - 1) // max_workers
    progress_path = output_dir / "progress.json"

    def save_progress(status, latest=None, error=None):
        elapsed = perf_counter() - started
        with guard:
            transferred = bytes_downloaded
        record = {
            "status": status, "started_at": started_at, "total": len(songs),
            "completed": completed, "succeeded": succeeded, "failed": failed,
            "cached": cached, "current_batch": current_batch, "total_batches": total_batches,
            "workers": max_workers, "elapsed_seconds": elapsed,
            "bytes_downloaded": transferred,
            "average_mib_per_second": transferred / (1024 * 1024 * elapsed) if elapsed else 0,
            "latest_song": latest.song.title if latest else "",
            "error": error,
        }
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=output_dir,
                prefix="progress.", suffix=".tmp", delete=False,
            ) as file:
                temporary = Path(file.name)
                json.dump(record, file)
            os.replace(temporary, progress_path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def count_bytes(delta):
        nonlocal bytes_downloaded
        with guard:
            bytes_downloaded += delta

    def worker(song):
        url = ""
        try:
            existing = cache.find(song)
            if existing is not None:
                url = existing.song.youtube_url or song.youtube_url
                path = _reuse_cached(existing, song, cache)
                if not url:
                    try:
                        url = find_video(song)
                    except Exception as error:
                        return DownloadResult(
                            song, path=path, cached=True,
                            error=f"Audio reused, but YouTube link lookup failed: {error}",
                        )
                return DownloadResult(song, path=path, youtube_url=url, cached=True)
            url = find_video(song)
            existing = cache.find(replace(song, youtube_url=url))
            if existing is not None:
                path = _reuse_cached(existing, song, cache)
                return DownloadResult(song, path=path, youtube_url=url, cached=True)
            key = (
                ("id", song.song_id.strip().casefold()) if song.song_id
                else (url, song.title, song.artist, song.album)
            )
            with guard:
                owner = key not in resolved
                if owner:
                    resolved[key] = Future()
                shared = resolved[key]
            if owner:
                try:
                    shared.set_result(download_audio(url, output_dir, song, count_bytes, _cache=cache))
                except Exception as error:
                    shared.set_exception(error)
            return DownloadResult(song, path=shared.result(), youtube_url=url)
        except Exception as error:
            return DownloadResult(song, youtube_url=url, error=str(error))

    save_progress("running")
    results = [None] * len(songs)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for offset in range(0, len(songs), max_workers):
            current_batch += 1
            wave_started = perf_counter()
            wave_bytes = bytes_downloaded
            wave_results = []
            save_progress("running")
            futures = {
                pool.submit(worker, song): offset + index
                for index, song in enumerate(songs[offset:offset + max_workers])
            }
            for future in as_completed(futures):
                result = future.result()
                results[futures[future]] = result
                wave_results.append(result)
                completed += 1
                succeeded += result.error is None
                failed += result.error is not None
                cached += result.cached
                save_progress("running", result)
            elapsed = perf_counter() - wave_started
            transferred = bytes_downloaded - wave_bytes
            with LOG_LOCK, (output_dir / "worker_batches.jsonl").open("a", encoding="utf-8") as file:
                file.write(json.dumps({
                    "started_at": started_at, "batch": current_batch, "songs": len(wave_results),
                    "succeeded": sum(result.error is None for result in wave_results),
                    "cached": sum(result.cached for result in wave_results),
                    "failed": sum(result.error is not None for result in wave_results),
                    "elapsed_seconds": elapsed, "bytes_downloaded": transferred,
                    "average_mib_per_second": transferred / (1024 * 1024 * elapsed) if elapsed else 0,
                }) + "\n")
    batch = BatchResult(
        results, perf_counter() - started, bytes_downloaded,
        output_dir / "batches.jsonl",
    )
    record = {
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "workers": max_workers,
        "songs": len(results),
        "succeeded": sum(result.error is None for result in results),
        "failed": sum(result.error is not None for result in results),
        "cached": sum(result.cached for result in results),
        "elapsed_seconds": batch.elapsed_seconds,
        "average_seconds_per_song": batch.average_seconds_per_song,
        "bytes_downloaded": bytes_downloaded,
        "average_mib_per_second": batch.average_mib_per_second,
    }
    with LOG_LOCK, batch.log_path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record) + "\n")
    (output_dir / "results.json").write_text(json.dumps([
        {
            "song": asdict(result.song), "youtube_url": result.youtube_url,
            "path": str(result.path) if result.path else None, "error": result.error,
            "cached": result.cached,
        }
        for result in results
    ], ensure_ascii=False, indent=2), encoding="utf-8")
    if source_csv is not None:
        try:
            cache_youtube_urls(
                source_csv, [(result.song, result.youtube_url) for result in results if result.youtube_url]
            )
        except (OSError, ValueError) as error:
            save_progress("failed", error=str(error))
            raise
    save_progress("completed")
    return batch
