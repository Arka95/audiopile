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
    provided = any((song.title, song.artist, song.album, song.song_id))
    fields = (
        (TIT2, song.title if provided else fallback.get("track") or fallback.get("title")),
        (TPE1, song.artist if provided else fallback.get("artist") or fallback.get("uploader")),
        (TALB, song.album if provided else fallback.get("album")),
    )
    for frame, value in fields:
        if value:
            tags.setall(frame.__name__, [frame(encoding=3, text=[value])])
        elif provided:
            tags.delall(frame.__name__)
    if song.song_id:
        tags.setall("TXXX:song_id", [TXXX(encoding=3, desc="song_id", text=[song.song_id])])
    url = song.youtube_url or fallback.get("webpage_url")
    if url:
        tags.setall("TXXX:youtube_url", [TXXX(encoding=3, desc="youtube_url", text=[url])])
    tags.save(path, v2_version=3)
