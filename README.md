# music

Terminal music library manager. Downloads audio from YouTube via yt-dlp, stores files in `library/`, and auto-generates Obsidian notes in `catalog/`.

The whole directory is an Obsidian vault — open it with `music` from any terminal.

## Shell commands

```
music          # cd here and open in Obsidian
dl <url>       # download and catalog a track
```

## Download modes

```
dl <url>              # audio (m4a, default)
dl --cookies <url>    # audio with Chrome cookies (age-restricted / region-locked)
dl --video <url>      # video (mp4)
dl --album <url>      # playlist or album — numbered tracks in a subfolder
dl --dry-run <url>    # preview what would happen without downloading
```

## Catalog

```
dl --recatalog        # regenerate all catalog notes from existing .info.json files
```

Running `--recatalog` is safe — it skips notes you've already written personal notes in.

## Directory layout

```
music/
  library/            # audio files, syncs to phone via iCloud
    albums/
    billystringsradio/
    DJsets/
    loukeman/
    playlists/
    podcasts/
  catalog/            # auto-generated Obsidian notes
    music/
    podcasts/
  player/             # PWA source — don't touch
  dl.py               # this script
```

## Catalog note format

Each note has a YAML frontmatter block with title, artist, type, source URL, upload date, duration, filtered tags, and a relative path to the audio file. The `## Notes` section is yours to fill in — `--recatalog` will never overwrite an existing note.

Files where the YouTube metadata couldn't be fetched (video unavailable, etc.) are marked `incomplete_metadata: true` in frontmatter so you can find and fix them in Obsidian.

## Dependencies

- [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- ffprobe (via ffmpeg)
- Python 3.9+
