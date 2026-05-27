# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running dl.py

```bash
python dl.py <url>               # download audio (m4a)
python dl.py --video <url>       # download video (mp4)
python dl.py --album <url>       # playlist/album with numbered tracks
python dl.py --cookies <url>     # use Chrome cookies for restricted content
python dl.py --dry-run <url>     # preview without downloading
python dl.py --recatalog         # regenerate all catalog notes from .info.json files
python dl.py --recatalog --force # overwrite even notes with personal edits
python dl.py --index             # rebuild catalog/home.md dashboard
python dl.py --organize          # move flat catalog notes into per-artist subdirs
python dl.py --delete "<title>"  # fuzzy-search and delete a track + its catalog note
python dl.py --note "<filename>" # open a catalog note in Obsidian
```

Dependencies: `yt-dlp`, `ffprobe` (via ffmpeg), Python 3.9+

## Architecture

Everything is rooted at `VAULT` (the repo root). The script treats the whole directory as an Obsidian vault.

**Two parallel directory trees** mirror each other by stem name:

- `library/` — metadata only (`.info.json`, thumbnails `.jpg`/`.webp`). Audio lives in `library/media/` (gitignored).
- `catalog/` — Obsidian markdown notes, auto-generated from `library/*.info.json`.

**Download flow** (`download_and_catalog`): yt-dlp writes audio to `library/media/` and metadata to `library/`. After yt-dlp exits, the script walks any `.info.json` files newer than the run start time and calls `catalog_info_json` on each.

**Catalog flow** (`catalog_info_json` → `make_note`): Reads an `.info.json`, resolves the corresponding audio file in `library/media/`, classifies it as `music` or `podcast`, determines the output path via `catalog_note_path`, and writes a markdown note with YAML frontmatter. Skips existing notes unless `--force` is passed (so personal notes in `## Notes` are preserved).

**Note placement logic** (`catalog_note_path`): Notes go into `catalog/music/<channel>/` for standard tracks. Collection directories (`djsets`, `billystringsradio`, `loukeman`, `playlists`, `podcasts`, `albums`) are treated differently — tracks in those directories are filed flat (no artist subfolder). Album detection: if >50% of files in a folder have numeric prefixes, it's treated as an album and gets an index note.

**Artist notes** (`catalog/artists/`): One note per channel, auto-generated with a list of `[[wikilinks]]` to that artist's track notes. Rebuilt on `--recatalog` or after a download.

**`catalog/home.md`** (`--index`): Dashboard note with 30 most-recently-added tracks, all artists with track counts, and album index links.

**`catalog/index.md`**: Static landing page for the vault, not auto-generated.

**Thumbnail handling**: yt-dlp embeds thumbnails in audio files AND writes sidecar `.jpg`/`.webp` to `library/`. The `THUMB_PPA` post-processor arg crops/pads thumbnails to square. `--extract-thumbs` pulls embedded thumbnails from audio files that are missing sidecars.
