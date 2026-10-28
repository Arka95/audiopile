"""Persistent download tracker, seeded once from existing MP3 tags."""

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import tempfile
from threading import Lock

from mutagen import MutagenError
from mutagen.id3 import ID3

from .inputs import Song, as_song, video_url


def _text_key(song):
    return tuple(" ".join(value.casefold().split()) for value in (song.title, song.artist))


@dataclass(frozen=True)
class CachedAudio:
    path: Path
    song: Song


class AudioCache:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.by_id = {}
        self.by_text = {}
        self.by_video = {}
        self.lock = Lock()
        self.tracker = self.directory / "downloaded.json"
        self.entries = {}
        self.initializing = True
        if self.tracker.exists():
            records = json.loads(self.tracker.read_text(encoding="utf-8"))
            for record in records:
                path = (self.directory / record["path"]).resolve()
                if not path.is_relative_to(self.directory):
                    raise ValueError("Download tracker path must stay inside the downloads folder.")
                self._index(CachedAudio(path, Song(**record["song"])))
        elif self.directory.exists():
            for path in sorted(self.directory.rglob("*.mp3")):
                self.remember(path)
        self.initializing = False
        if not self.tracker.exists():
            self.directory.mkdir(parents=True, exist_ok=True)
            self._save()

    def _index(self, entry):
        path, song = entry.path, entry.song
        self.entries[path] = entry
        for index in (self.by_id, self.by_text, self.by_video):
            for key in [key for key, value in index.items() if value.path == path]:
                del index[key]
        if song.song_id:
            self.by_id[song.song_id.strip().casefold()] = entry
        if song.title:
            self.by_text.setdefault(_text_key(song), entry)
        if song.youtube_url:
            self.by_video.setdefault(song.youtube_url, entry)

    def _save(self):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.directory,
                prefix="downloaded.", suffix=".tmp", delete=False,
            ) as file:
                temporary = Path(file.name)
                json.dump([
                    {"path": str(entry.path.relative_to(self.directory)), "song": asdict(entry.song)}
                    for entry in self.entries.values()
                ], file, ensure_ascii=False, indent=2)
            os.replace(temporary, self.tracker)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def remember(self, path):
        path = Path(path).resolve()
        if not path.is_relative_to(self.directory):
            return
        try:
            if not path.is_file() or path.stat().st_size == 0:
                return
            tags = ID3(path)
        except (MutagenError, OSError):
            return

        def text(frame):
            value = tags.get(frame)
            return str(value.text[0]) if value is not None and value.text else ""

        url = text("TXXX:youtube_url")
        if not url:
            identifiers = re.findall(r"\[([A-Za-z0-9_-]{11})\]", path.stem)
            if identifiers:
                url = f"https://www.youtube.com/watch?v={identifiers[-1]}"
        if url:
            try:
                url = video_url(url)
            except ValueError:
                url = ""
        song = Song(
            title=text("TIT2"), artist=text("TPE1"), album=text("TALB"),
            song_id=text("TXXX:song_id"), youtube_url=url,
        )
        entry = CachedAudio(path, song)
        with self.lock:
            self._index(entry)
            if not self.initializing:
                self._save()

    def find(self, song):
        song = as_song(song)
        with self.lock:
            if song.song_id:
                entry = self.by_id.get(song.song_id.strip().casefold())
            else:
                entry = self.by_text.get(_text_key(song)) if song.title else None
                if entry is None and song.youtube_url and (not song.title or not song.artist):
                    entry = self.by_video.get(song.youtube_url)
        return entry
