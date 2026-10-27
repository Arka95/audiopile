"""Write CSV metadata into standard MP3 ID3 tags."""

from mutagen.id3 import ID3, ID3NoHeaderError, TALB, TIT2, TPE1, TXXX

from .inputs import as_song


def tag_audio(path, song, fallback=None):
    song = as_song(song)
    fallback = fallback or {}
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()
    fields = (
        (TIT2, song.title or fallback.get("track") or fallback.get("title")),
        (TPE1, song.artist or fallback.get("artist") or fallback.get("uploader")),
        (TALB, song.album or fallback.get("album")),
    )
    for frame, value in fields:
        if value:
            tags.setall(frame.__name__, [frame(encoding=3, text=[value])])
    if song.song_id:
        tags.setall("TXXX:song_id", [TXXX(encoding=3, desc="song_id", text=[song.song_id])])
    tags.save(path, v2_version=3)
