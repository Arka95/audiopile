"""Local MP3 lookup using embedded song IDs, independent of filenames."""

from dataclasses import dataclass
from pathlib import Path
import re
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
        if self.directory.exists():
            for path in sorted(self.directory.rglob("*.mp3")):
                self.remember(path)

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
            for index in (self.by_id, self.by_text, self.by_video):
                for key in [key for key, value in index.items() if value.path == path]:
                    del index[key]
            if song.song_id:
                self.by_id[song.song_id.strip().casefold()] = entry
            if song.title:
                self.by_text.setdefault(_text_key(song), entry)
            if url:
                self.by_video.setdefault(url, entry)

    def find(self, song):
        song = as_song(song)
        with self.lock:
            if song.song_id:
                entry = self.by_id.get(song.song_id.strip().casefold())
            else:
                entry = self.by_text.get(_text_key(song)) if song.title else None
                if entry is None and song.youtube_url and (not song.title or not song.artist):
                    entry = self.by_video.get(song.youtube_url)
        return entry if entry is not None and entry.path.is_file() else None
