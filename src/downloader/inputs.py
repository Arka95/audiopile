"""Song inputs, CSV loading and deduplication."""

import csv
from dataclasses import dataclass, replace
import os
from pathlib import Path
import re
from collections.abc import Mapping
import tempfile
from threading import Lock
from urllib.parse import parse_qs, urlsplit


CSV_LOCK = Lock()


@dataclass(frozen=True)
class Song:
    title: str = ""
    artist: str = ""
    album: str = ""
    song_id: str = ""
    youtube_url: str = ""


def video_url(value):
    parsed = urlsplit(value.strip())
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port:
        raise ValueError("Provide an HTTPS YouTube video link.")
    if parsed.hostname == "youtu.be":
        video_id = parsed.path.removeprefix("/")
    elif parsed.hostname in {"youtube.com", "www.youtube.com", "music.youtube.com", "m.youtube.com"}:
        if parsed.path != "/watch":
            raise ValueError("Provide a single video link, not a playlist or channel.")
        video_id = parse_qs(parsed.query).get("v", [""])[0]
    else:
        raise ValueError("Only YouTube video links are supported.")
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ValueError("The link must contain a valid YouTube video ID.")
    return f"https://www.youtube.com/watch?v={video_id}"


def as_song(value):
    if isinstance(value, Song):
        song = value
    elif isinstance(value, str):
        value = value.strip()
        song = Song(youtube_url=value) if "://" in value else Song(title=value)
    elif isinstance(value, Mapping):
        song = Song(
            title=(value.get("song_title") or value.get("title") or "").strip(),
            artist=(value.get("artist_name") or value.get("artist") or "").strip(),
            album=(value.get("album_name") or value.get("album") or "").strip(),
            song_id=(value.get("song_id") or "").strip(),
            youtube_url=(value.get("youtube_url") or "").strip(),
        )
    else:
        raise ValueError("Each song must be a Song, search string, video URL or CSV-style mapping.")
    if song.youtube_url:
        return Song(
            title=song.title, artist=song.artist, album=song.album,
            song_id=song.song_id, youtube_url=video_url(song.youtube_url),
        )
    if not song.title.strip():
        raise ValueError("Each song needs a title or a YouTube video URL.")
    return song


def song_key(song):
    song = as_song(song)
    if song.song_id:
        return ("id", song.song_id.strip().casefold())
    if song.title.strip():
        return (
            "title", " ".join(song.title.casefold().split()),
            " ".join(song.artist.casefold().split()),
        )
    return ("youtube", song.youtube_url)


def unique_songs(values):
    if isinstance(values, (Song, str, Mapping)):
        values = [values]
    result = []
    seen = {}
    for value in values:
        song = as_song(value)
        key = song_key(song)
        if key not in seen:
            seen[key] = len(result)
            result.append(song)
        elif song.youtube_url and not result[seen[key]].youtube_url:
            result[seen[key]] = replace(result[seen[key]], youtube_url=song.youtube_url)
    return result


def load_songs_from_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if not {"song_title", "title", "youtube_url"}.intersection(reader.fieldnames or []):
            raise ValueError("CSV needs a song_title, title or youtube_url column.")
        rows = []
        for row in reader:
            try:
                rows.append(as_song(row))
            except ValueError as error:
                raise ValueError(f"CSV line {reader.line_num}: {error}") from error
    return unique_songs(rows)


def cache_youtube_urls(path, matches):
    """Persist resolved (song, URL) pairs without dropping playlist duplicates."""
    updates = {song_key(song): video_url(url) for song, url in matches if url}
    path = Path(path)
    with CSV_LOCK:
        with path.open(encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            fields = list(reader.fieldnames or [])
            rows = list(reader)
        if not {"song_title", "title", "youtube_url"}.intersection(fields):
            raise ValueError("CSV needs a song_title, title or youtube_url column.")
        if "youtube_url" not in fields:
            fields.append("youtube_url")
        changed = 0
        for row in rows:
            row.setdefault("youtube_url", "")
            if not row["youtube_url"].strip():
                url = updates.get(song_key(row), "")
                row["youtube_url"] = url
                changed += bool(url)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8-sig", newline="", dir=path.parent,
                prefix=path.name + ".", suffix=".tmp", delete=False,
            ) as file:
                temporary = Path(file.name)
                writer = csv.DictWriter(file, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return changed
