"""Public API for downloading authorized individual songs and batches."""

from .core import BatchResult, DOWNLOADS, DownloadResult, download_audio, download_songs, find_video
from .inputs import Song, cache_youtube_urls, load_songs_from_csv, unique_songs, video_url
from .metadata import tag_audio

__all__ = [
    "BatchResult", "DOWNLOADS", "DownloadResult", "Song", "download_audio", "download_songs",
    "cache_youtube_urls", "find_video", "load_songs_from_csv", "tag_audio", "unique_songs", "video_url",
]
