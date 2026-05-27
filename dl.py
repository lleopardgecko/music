#!/usr/bin/env python3
"""dl — terminal music library manager"""

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

VAULT = Path(__file__).resolve().parent
LIBRARY = VAULT / "library"
MEDIA = LIBRARY / "media"
CATALOG_MUSIC = VAULT / "catalog" / "music"
CATALOG_PODCASTS = VAULT / "catalog" / "podcasts"
CATALOG_ARTISTS = VAULT / "catalog" / "artists"

THUMB_PPA = (
    "ThumbnailsConvertor+ffmpeg_o:-vf "
    "split[a][b];[b]scale=ih:ih,boxblur=20:20[bg];"
    "[bg][a]overlay=(W-w)/2:(H-h)/2,crop=ih:ih"
)

AUDIO_EXTS = {".m4a", ".mp4", ".mp3", ".webm"}
COLLECTION_DIRS = {"djsets", "billystringsradio", "loukeman", "playlists", "podcasts", "albums", "apple library"}
_GENERIC_CATEGORIES = {"music", "entertainment", "film & animation"}

# ── Terminal styling ────────────────────────────────────────────────────────

_TTY = sys.stdout.isatty()
_e = lambda c: c if _TTY else ""

RST  = _e("\033[0m")
BOLD = _e("\033[1m")
DIM  = _e("\033[2m")
GRN  = _e("\033[32m")
BLU  = _e("\033[34m")
CYN  = _e("\033[36m")
YLW  = _e("\033[33m")
MAG  = _e("\033[35m")
RED  = _e("\033[31m")

_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


class Spinner:
    def __init__(self):
        self._stop = threading.Event()
        self._thread = None
        self.msg = ""

    def start(self, msg=""):
        self.msg = msg
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        i = 0
        while not self._stop.is_set():
            f = _FRAMES[i % len(_FRAMES)] if _TTY else "."
            sys.stdout.write(f"\r  {CYN}{f}{RST} {DIM}{self.msg}{RST}")
            sys.stdout.flush()
            time.sleep(0.08)
            i += 1

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join()
        if _TTY:
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()


def _tag(label, color=GRN):
    return f"  {color}[{label}]{RST}"


# ── Classification ─────────────────────────────────────────────────────────

def classify(title="", categories=None, rel_path=""):
    parts = Path(rel_path).parts if rel_path else []
    if "podcasts" in [p.lower() for p in parts]:
        return "podcast"
    if re.search(r'\bep\.?\s*\d+|\bepisode\s*\d+|\bpodcast\b', title.lower()):
        return "podcast"
    if categories and "Podcasts" in categories:
        return "podcast"
    return "music"


# ── Genre extraction ───────────────────────────────────────────────────────

def extract_genre(info):
    g = (info.get("genre") or "").strip()
    if g:
        return g
    for cat in (info.get("categories") or []):
        if cat.lower() not in _GENERIC_CATEGORIES:
            return cat
    return ""


# ── Tag filtering ──────────────────────────────────────────────────────────

_GARBAGE = re.compile(
    r"^(official|video|hd|4k|hq|audio|lyrics?|music|live|full|new|best|top|"
    r"free|download|stream(?:ing)?|watch|youtube|vevo|mv|"
    r"official\s+(video|audio|music\s+video)|lyric\s+video|official\s+music\s+video)$",
    re.I,
)


def filter_tags(raw):
    if not raw:
        return []
    kept = []
    for tag in raw:
        slug = re.sub(r"[\s_]+", "-", tag.strip().lower())
        slug = re.sub(r"[^\w-]", "", slug)
        if not slug or len(slug) < 2 or len(slug) > 40:
            continue
        if slug in kept:
            continue
        if slug.startswith("#") or _GARBAGE.match(tag.strip()):
            continue
        # drop if it's a superstring or substring of something already kept
        if any(slug in k or k in slug for k in kept):
            continue
        kept.append(slug)
        if len(kept) == 8:
            break
    return kept


# ── Note generation ────────────────────────────────────────────────────────

def artist_slug(name):
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f\[\]]', "", name).strip()
    return re.sub(r"\s+", " ", safe)[:80]


def fmt_duration(seconds):
    s = int(seconds or 0)
    return f"{s // 60}:{s % 60:02d}"


def note_filename(title):
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", title).strip()
    safe = re.sub(r"\s+", " ", safe)
    return safe[:80] + ".md"


def make_note(info, audio_path, file_type, incomplete=False, thumb=None):
    title = info.get("title") or Path(str(audio_path or "")).stem
    artist = info.get("uploader") or info.get("channel") or ""
    source_url = info.get("webpage_url") or info.get("original_url") or ""
    channel = info.get("channel") or info.get("uploader") or ""
    genre = extract_genre(info)

    raw_date = info.get("upload_date") or ""
    upload_date = (
        f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
        if len(raw_date) == 8 else ""
    )

    duration_str = fmt_duration(info.get("duration") or 0)
    tags = filter_tags(info.get("tags") or [])
    desc = (info.get("description") or "")
    desc = desc[:500] + ("…" if len(desc) > 500 else "")

    rel = (
        str(Path(str(audio_path)).relative_to(VAULT))
        if audio_path and Path(str(audio_path)).exists()
        else ""
    )

    def q(s):
        return s.replace('"', "'")

    extra = "\nincomplete_metadata: true" if incomplete else ""

    thumb_line = f'![[{thumb.name}]]\n\n' if thumb else ''

    link_parts = []
    if channel:
        link_parts.append(f"[[{artist_slug(channel)}]]")
    link_parts.extend(f"[[{t}]]" for t in tags)
    links_line = " · ".join(link_parts) + "\n\n" if link_parts else ""

    return (
        f'---\n'
        f'title: "{q(title)}"\n'
        f'artist: "{q(artist)}"\n'
        f'type: {file_type}\n'
        f'genre: "{q(genre)}"\n'
        f'source_url: "{source_url}"\n'
        f'channel: "{q(channel)}"\n'
        f'upload_date: {upload_date}\n'
        f'duration: "{duration_str}"\n'
        f'tags: {json.dumps(tags)}\n'
        f'file_path: "{rel}"{extra}\n'
        f'date_added: {date.today().isoformat()}\n'
        f'---\n\n'
        + thumb_line
        + links_line
        + (f'[[{Path(str(audio_path)).name}]]\n\n' if audio_path else '')
        + f'## Description\n{desc}\n\n'
        f'## Notes\n\n'
    )


def make_album_note(album_name, track_notes):
    links = "\n".join(f"- [[{p.stem}]]" for p in sorted(track_notes))
    return (
        f"---\n"
        f'title: "{album_name}"\n'
        f"type: music\n"
        f"date_added: {date.today().isoformat()}\n"
        f"---\n\n"
        f"## Tracks\n{links}\n\n"
        f"## Notes\n\n"
    )


def make_artist_note(name, track_note_paths):
    links = "\n".join(f"- [[{p.stem}]]" for p in sorted(track_note_paths, key=lambda p: p.stem))
    return (
        f"---\n"
        f'title: "{name}"\n'
        f"type: artist\n"
        f"date_added: {date.today().isoformat()}\n"
        f"---\n\n"
        f"## Tracks\n{links}\n\n"
        f"## Notes\n\n"
    )


# ── Catalog path logic ─────────────────────────────────────────────────────

def is_album_folder(folder):
    media_folder = MEDIA / folder.relative_to(LIBRARY)
    search = media_folder if media_folder.exists() else folder
    audio = [f for f in search.iterdir() if f.is_file() and f.suffix.lower() in AUDIO_EXTS]
    if not audio:
        return False
    numbered = sum(1 for f in audio if re.match(r"^\d+", f.name))
    return numbered / len(audio) > 0.5


def catalog_note_path(info_path, file_type, channel=""):
    rel = info_path.parent.relative_to(LIBRARY)
    parts = rel.parts
    base = CATALOG_PODCASTS if file_type == "podcast" else CATALOG_MUSIC
    title = info_path.name.replace(".info.json", "")
    slug = artist_slug(channel) if channel and file_type == "music" else ""

    if not parts:
        if slug:
            return base / slug / note_filename(title), None
        return base / note_filename(title), None

    top = parts[0].lower()

    if top in COLLECTION_DIRS and top != "albums":
        return base / note_filename(title), None

    if top == "albums":
        if len(parts) >= 2:
            album_name = parts[1]
            return base / album_name / note_filename(title), album_name
        return base / note_filename(title), None

    folder = LIBRARY / parts[0]
    if folder.is_dir() and is_album_folder(folder):
        album_name = parts[0]
        return base / album_name / note_filename(title), album_name

    if slug:
        return base / slug / note_filename(title), None
    return base / note_filename(title), None


# ── Catalog a single info.json ─────────────────────────────────────────────

def catalog_info_json(info_path, dry_run=False, incomplete=False, force=False):
    info_path = Path(info_path)
    try:
        info = json.loads(info_path.read_text())
    except Exception as e:
        print(f"{_tag('error', RED)} parse {info_path.name}: {e}")
        return None

    stem = info_path.name.replace(".info.json", "")
    media_dir = MEDIA / info_path.parent.relative_to(LIBRARY)
    audio = next(
        (media_dir / (stem + ext) for ext in AUDIO_EXTS
         if (media_dir / (stem + ext)).exists()),
        None,
    )
    if not audio:
        candidates = [
            p for p in media_dir.iterdir()
            if p.is_file() and p.suffix.lower() in AUDIO_EXTS
        ] if media_dir.exists() else []
        if candidates:
            best = max(candidates, key=lambda p: SequenceMatcher(None, stem, p.stem).ratio())
            if SequenceMatcher(None, stem, best.stem).ratio() > 0.6:
                audio = best

    title = info.get("title") or stem
    cats = info.get("categories") or []
    rel = str(audio.relative_to(VAULT)) if audio else ""
    ftype = classify(title, cats, rel)
    channel = info.get("channel") or info.get("uploader") or ""

    note_p, album_name = catalog_note_path(info_path, ftype, channel=channel)

    if note_p.exists() and not force:
        print(f"{_tag('skip', DIM)} {note_p.name}")
        return {"type": ftype, "note_path": note_p, "album": album_name, "title": title, "audio": audio, "channel": channel, "created": False}

    thumb = next(
        (info_path.parent / (stem + ext) for ext in (".webp", ".jpg", ".png")
         if (info_path.parent / (stem + ext)).exists()),
        None,
    )
    content = make_note(info, audio, ftype, incomplete=incomplete, thumb=thumb)

    if dry_run:
        print(f"{_tag('dry-run', YLW)} {ftype}: {note_p.relative_to(VAULT)}")
    else:
        note_p.parent.mkdir(parents=True, exist_ok=True)
        note_p.write_text(content)
        color = BLU if ftype == "podcast" else GRN
        print(f"{_tag(ftype, color)} {note_p.name}")

    return {"type": ftype, "note_path": note_p, "album": album_name, "title": title, "audio": audio, "channel": channel, "created": True}


# ── Catalog from embedded metadata (no info.json) ──────────────────────────

def catalog_from_tags(audio_path, dry_run=False, force=False):
    audio_path = Path(audio_path)
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:format_tags",
         "-of", "json", str(audio_path)],
        capture_output=True, text=True,
    )
    try:
        data = json.loads(result.stdout)
    except Exception:
        data = {}

    raw_tags = {k.lower(): v for k, v in data.get("format", {}).get("tags", {}).items()}
    duration = float(data.get("format", {}).get("duration") or 0)

    info = {
        "title": raw_tags.get("title") or audio_path.stem,
        "uploader": raw_tags.get("artist") or "",
        "channel": raw_tags.get("artist") or "",
        "genre": raw_tags.get("genre") or "",
        "upload_date": re.sub(r"[-/]", "", raw_tags.get("date") or ""),
        "duration": duration,
        "description": raw_tags.get("description") or raw_tags.get("comment") or "",
        "tags": [],
        "webpage_url": raw_tags.get("comment") or "",
    }

    title = info["title"]
    rel = str(audio_path.relative_to(VAULT))
    ftype = classify(title, [], rel)
    base = CATALOG_PODCASTS if ftype == "podcast" else CATALOG_MUSIC
    note_p = base / note_filename(title)

    if note_p.exists() and not force:
        print(f"  [skip] {note_p.name}")
        return

    content = make_note(info, audio_path, ftype, incomplete=True)

    if dry_run:
        print(f"{_tag('dry-run', YLW)} partial {ftype}: {note_p.name}")
    else:
        note_p.parent.mkdir(parents=True, exist_ok=True)
        note_p.write_text(content)
        print(f"{_tag(f'{ftype}:partial', YLW)} {note_p.name}")


# ── --index ────────────────────────────────────────────────────────────────

def _parse_frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return {}
    result = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            v = v.strip().strip('"')
            result[k.strip()] = v
    return result


def _info_json_mtime(fm):
    """Return the mtime of the source .info.json for a note — stable across recatalogs."""
    file_path = fm.get("file_path", "")
    if not file_path:
        return 0.0
    audio = VAULT / file_path
    try:
        rel = audio.parent.relative_to(MEDIA)
    except ValueError:
        return 0.0
    info_json = (LIBRARY / rel) / (audio.stem + ".info.json")
    return info_json.stat().st_mtime if info_json.exists() else 0.0


def build_index(dry_run=False):
    home = VAULT / "catalog" / "home.md"

    # Collect all track notes (music + podcast, exclude artist/album index notes)
    track_notes = []
    for p in sorted(CATALOG_MUSIC.rglob("*.md")):
        fm = _parse_frontmatter(p.read_text())
        if fm.get("type") not in ("music", "podcast"):
            continue
        # Skip album/collection index notes (stem == parent dir name)
        if p.parent != CATALOG_MUSIC and p.stem.startswith(p.parent.name[:10]):
            continue
        track_notes.append((p, fm))
    for p in sorted(CATALOG_PODCASTS.rglob("*.md")):
        fm = _parse_frontmatter(p.read_text())
        if fm.get("type") == "podcast":
            track_notes.append((p, fm))

    # Recently added — sort by date_added, break ties with info.json mtime (download time)
    recent = sorted(
        track_notes,
        key=lambda x: (x[1].get("date_added", ""), _info_json_mtime(x[1])),
        reverse=True,
    )[:30]
    recent_lines = []
    for p, fm in recent:
        ch = fm.get("channel", "")
        slug = artist_slug(ch) if ch else ""
        artist_link = f" · [[{slug}]]" if slug else ""
        recent_lines.append(f"- [[{p.stem}]]{artist_link} — {fm.get('date_added', '')}")

    # Artists — from catalog/artists/, with track counts
    artist_notes = sorted(CATALOG_ARTISTS.glob("*.md"), key=lambda p: p.stem.lower())
    artist_lines = []
    for ap in artist_notes:
        count = ap.read_text().count("- [[")
        artist_lines.append(f"- [[{ap.stem}]] ({count})")

    # Albums — subdirectory index notes in catalog/music/
    album_lines = []
    for d in sorted(CATALOG_MUSIC.iterdir()):
        if not d.is_dir():
            continue
        idx = d / note_filename(d.name)
        if idx.exists():
            fm = _parse_frontmatter(idx.read_text())
            if fm.get("type") in ("music", "album"):
                album_lines.append(f"- [[{idx.stem}]]")

    content = (
        f"---\ntitle: Music Library\ntype: index\n"
        f"date_updated: {date.today().isoformat()}\n---\n\n"
        f"## Recently Added\n" + "\n".join(recent_lines) + "\n\n"
        f"## Artists\n" + "\n".join(artist_lines) + "\n\n"
    )
    if album_lines:
        content += "## Albums\n" + "\n".join(album_lines) + "\n\n"

    if dry_run:
        print(f"{_tag('dry-run', YLW)} catalog/home.md ({len(recent)} recent, {len(artist_lines)} artists)")
        return

    home.write_text(content)
    print(f"{_tag('index', MAG)} catalog/home.md  ({len(recent)} recent · {len(artist_lines)} artists · {len(album_lines)} albums)")


# ── --organize ──────────────────────────────────────────────────────────────

def organize_by_artist(dry_run=False):
    moved = skipped = 0
    for note_p in sorted(CATALOG_MUSIC.glob("*.md")):
        text = note_p.read_text()
        m = re.search(r'^channel:\s*"([^"]*)"', text, re.MULTILINE)
        channel = m.group(1) if m else ""
        if not channel:
            skipped += 1
            continue
        slug = artist_slug(channel)
        if not slug:
            skipped += 1
            continue
        dest_dir = CATALOG_MUSIC / slug
        dest = dest_dir / note_p.name
        if dest.exists():
            skipped += 1
            continue
        if dry_run:
            print(f"  {DIM}{note_p.name}{RST}  →  {slug}/")
            moved += 1
            continue
        dest_dir.mkdir(parents=True, exist_ok=True)
        note_p.rename(dest)
        print(f"{_tag('move', YLW)} {note_p.name}  →  {slug}/")
        moved += 1
    print(f"\n  {YLW}{BOLD}{moved}{RST} moved  {DIM}{skipped} unchanged{RST}\n")
    if moved and not dry_run:
        print(f"  {DIM}run  dl --recatalog --force  to rebuild artist notes{RST}\n")


# ── --extract-thumbs ───────────────────────────────────────────────────────

def extract_thumbs(dry_run=False):
    audio_files = sorted(
        p for p in MEDIA.rglob("*")
        if p.is_file() and p.suffix.lower() in AUDIO_EXTS
    )
    total = len(audio_files)
    extracted = skipped = 0
    spin = Spinner()
    print()
    for i, audio in enumerate(audio_files, 1):
        try:
            rel = audio.parent.relative_to(MEDIA)
        except ValueError:
            continue
        lib_dir = LIBRARY / rel
        stem = audio.stem
        if any((lib_dir / (stem + ext)).exists() for ext in (".webp", ".jpg", ".png")):
            skipped += 1
            continue
        out = lib_dir / (stem + ".jpg")
        short = stem[:55] + "…" if len(stem) > 55 else stem
        if dry_run:
            print(f"{_tag('dry-run', YLW)} {audio.name}")
            extracted += 1
            continue
        lib_dir.mkdir(parents=True, exist_ok=True)
        spin.start(f"{DIM}({i}/{total}){RST} {short}")
        r = subprocess.run(
            ["ffmpeg", "-i", str(audio), "-an", "-vcodec", "copy", str(out), "-y"],
            capture_output=True,
        )
        spin.stop()
        if r.returncode == 0 and out.exists() and out.stat().st_size > 0:
            print(f"{_tag('thumb', CYN)} {out.name}")
            extracted += 1
        elif out.exists():
            out.unlink()
    print(
        f"\n  {CYN}{BOLD}{extracted}{RST} extracted  "
        f"{DIM}{skipped} skipped{RST}\n"
    )
    if extracted and not dry_run:
        print(f"  {DIM}run  dl --recatalog --force  to update notes{RST}\n")


# ── --recatalog ────────────────────────────────────────────────────────────

def recatalog(dry_run=False, force=False):
    CATALOG_MUSIC.mkdir(parents=True, exist_ok=True)
    CATALOG_PODCASTS.mkdir(parents=True, exist_ok=True)
    CATALOG_ARTISTS.mkdir(parents=True, exist_ok=True)

    info_files = sorted(LIBRARY.rglob("*.info.json"))
    print(f"\n  {BOLD}{len(info_files)}{RST} tracks\n")

    album_tracks = {}
    artist_tracks = {}
    stats = {"music": 0, "podcast": 0, "skipped": 0}
    covered_audio = set()

    for ip in info_files:
        result = catalog_info_json(ip, dry_run=dry_run, force=force)
        if not result:
            continue
        if result["audio"]:
            covered_audio.add(result["audio"].resolve())
        if result["created"]:
            stats[result["type"]] = stats.get(result["type"], 0) + 1
        else:
            stats["skipped"] += 1
        if result["album"]:
            album_tracks.setdefault(result["album"], []).append(result["note_path"])
        if result.get("channel") and result["type"] == "music":
            slug = artist_slug(result["channel"])
            if slug:
                artist_tracks.setdefault(slug, []).append(result["note_path"])

    for album_name, track_note_paths in album_tracks.items():
        parent_dir = CATALOG_MUSIC / album_name
        parent_note = parent_dir / note_filename(album_name)
        if parent_note.exists() and not force:
            print(f"{_tag('skip', DIM)} album: {parent_note.name}")
            continue
        content = make_album_note(album_name, track_note_paths)
        if dry_run:
            print(f"{_tag('dry-run', YLW)} album: {parent_note.name}")
        else:
            parent_dir.mkdir(parents=True, exist_ok=True)
            parent_note.write_text(content)
            print(f"{_tag('album', MAG)} {parent_note.name}")

    for slug, track_note_paths in sorted(artist_tracks.items()):
        artist_note = CATALOG_ARTISTS / note_filename(slug)
        if artist_note.exists() and not force:
            continue
        content = make_artist_note(slug, track_note_paths)
        if dry_run:
            print(f"{_tag('dry-run', YLW)} artist: {artist_note.name}")
        else:
            artist_note.write_text(content)
            print(f"{_tag('artist', CYN)} {artist_note.name}")

    all_audio = sorted(
        p for p in MEDIA.rglob("*")
        if p.is_file() and p.suffix.lower() in AUDIO_EXTS
    )
    missing = [a for a in all_audio if a.resolve() not in covered_audio]

    if missing:
        print(f"\n  {DIM}{len(missing)} files without .info.json — using embedded tags{RST}")
        for a in missing:
            catalog_from_tags(a, dry_run=dry_run, force=force)

    print(
        f"\n  {GRN}{BOLD}{stats['music']}{RST} music  "
        f"{BLU}{BOLD}{stats['podcast']}{RST} podcast  "
        f"{DIM}{stats['skipped']} skipped{RST}\n"
    )


# ── --note ─────────────────────────────────────────────────────────────────

def delete_track(query, dry_run=False):
    notes = list(VAULT.glob("catalog/**/*.md"))
    q = query.lower()
    ranked = sorted(notes, key=lambda p: SequenceMatcher(None, q, p.stem.lower()).ratio(), reverse=True)
    if not ranked:
        print(f"  {RED}no catalog notes found{RST}")
        return

    top = [n for n in ranked if SequenceMatcher(None, q, n.stem.lower()).ratio() > 0.6 or q in n.stem.lower()][:10]
    if not top:
        print(f"  {RED}no close matches for \"{query}\"{RST}")
        return

    if len(top) == 1:
        note = top[0]
    else:
        print()
        for i, n in enumerate(top):
            print(f"  {DIM}[{i+1}]{RST} {n.stem}")
        raw = input(f"\n  {BOLD}pick{RST} (1–{len(top)}, q to quit): ").strip()
        if raw.lower() == "q" or not raw.isdigit() or not (1 <= int(raw) <= len(top)):
            print(f"  {DIM}aborted{RST}")
            return
        note = top[int(raw) - 1]

    # Parse file_path from frontmatter
    text = note.read_text()
    m = re.search(r'^file_path:\s*"([^"]+)"', text, re.MULTILINE)
    audio = VAULT / m.group(1) if m and m.group(1) else None

    to_delete = [note]
    if audio and audio.exists():
        stem = audio.stem
        to_delete.append(audio)
        # metadata lives in LIBRARY at the mirrored path
        try:
            meta_dir = LIBRARY / audio.parent.relative_to(MEDIA)
        except ValueError:
            meta_dir = audio.parent
        for ext in (".info.json", ".webp", ".png"):
            candidate = meta_dir / (stem + ext)
            if candidate.exists():
                to_delete.append(candidate)

    print(f"\n  {BOLD}will delete{RST}")
    for p in to_delete:
        print(f"  {DIM}{p.relative_to(VAULT)}{RST}")

    if dry_run:
        return

    confirm = input(f"\n  {RED}confirm?{RST} [y/N] ").strip().lower()
    if confirm != "y":
        print(f"  {DIM}aborted{RST}")
        return

    print()
    for p in to_delete:
        p.unlink()
        print(f"{_tag('deleted', RED)} {p.relative_to(VAULT)}")


def open_note(query):
    notes = list(VAULT.glob("catalog/**/*.md"))
    q = re.sub(r"^\d+\s*-\s*", "", Path(query).stem).lower()
    ranked = sorted(notes, key=lambda p: SequenceMatcher(None, q, p.stem.lower()).ratio(), reverse=True)
    if not ranked:
        print("No catalog notes found")
        return
    best = ranked[0]
    rel = str(best.relative_to(VAULT))
    uri = f"obsidian://open?vault={VAULT.name}&file={rel}"
    subprocess.run(["open", uri])
    print(f"Opening: {best.name}")


# ── yt-dlp download commands ───────────────────────────────────────────────

def build_cmd(url, mode, cookies, start=None):
    out_audio = str(MEDIA / "%(title)s.%(ext)s")
    out_album = str(MEDIA / "%(playlist_title)s" / "%(playlist_index)02d - %(title)s.%(ext)s")
    info_audio = str(LIBRARY / "%(title)s.%(ext)s")
    info_album = str(LIBRARY / "%(playlist_title)s" / "%(playlist_index)02d - %(title)s.%(ext)s")

    if mode == "video":
        cmd = [
            "yt-dlp",
            "--no-playlist",
            "-f", "bestvideo+bestaudio/best",
            "--merge-output-format", "mp4",
            "--embed-metadata",
            "--write-info-json",
            "-o", out_audio,
            "-o", f"infojson:{info_audio}",
        ]
    elif mode == "album":
        cmd = [
            "yt-dlp",
            "-f", "bestaudio[ext=m4a]",
            "--embed-metadata", "--embed-thumbnail",
            "--write-info-json", "--write-thumbnail",
            "--no-overwrites",
            "-o", out_album,
            "-o", f"infojson:{info_album}",
            "-o", f"thumbnail:{info_album}",
            "--ppa", THUMB_PPA,
        ]
    else:
        cmd = [
            "yt-dlp",
            "--no-playlist",
            "-f", "bestaudio[ext=m4a]",
            "--embed-metadata", "--embed-thumbnail",
            "--write-info-json", "--write-thumbnail",
            "-o", out_audio,
            "-o", f"infojson:{info_audio}",
            "-o", f"thumbnail:{info_audio}",
            "--ppa", THUMB_PPA,
        ]

    if cookies:
        cmd += ["--cookies-from-browser", "chrome"]

    if start:
        cmd += ["--download-sections", f"*{start}-inf"]

    cmd.append(url)
    return cmd


def download_and_catalog(url, mode, cookies, dry_run, start=None):
    cmd = build_cmd(url, mode, cookies, start=start)

    if dry_run:
        print(f"[dry-run] {' '.join(cmd)}")
        return

    import time
    before = time.time() - 2

    print(f"\n  {CYN}{BOLD}↓{RST}  {url}\n")
    r = subprocess.run(cmd)
    if r.returncode != 0:
        print(f"{_tag('error', RED)} yt-dlp exited {r.returncode}")
        return

    album_tracks = {}
    artist_tracks = {}
    CATALOG_ARTISTS.mkdir(parents=True, exist_ok=True)
    for root, _, files in os.walk(LIBRARY):
        for fn in sorted(files):
            if not fn.endswith(".info.json"):
                continue
            p = Path(root) / fn
            if p.stat().st_mtime < before:
                continue
            result = catalog_info_json(p)
            if not result:
                continue
            if result["album"]:
                album_tracks.setdefault(result["album"], []).append(result["note_path"])
            if result.get("channel") and result["type"] == "music":
                slug = artist_slug(result["channel"])
                if slug:
                    artist_tracks.setdefault(slug, []).append(result["note_path"])

    for album_name, track_note_paths in album_tracks.items():
        parent_dir = CATALOG_MUSIC / album_name
        parent_note = parent_dir / note_filename(album_name)
        if not parent_note.exists():
            content = make_album_note(album_name, track_note_paths)
            parent_dir.mkdir(parents=True, exist_ok=True)
            parent_note.write_text(content)
            print(f"{_tag('album', MAG)} {parent_note.name}")

    for slug, track_note_paths in artist_tracks.items():
        artist_note = CATALOG_ARTISTS / note_filename(slug)
        existing = artist_note.read_text() if artist_note.exists() else ""
        existing_links = set(re.findall(r'\[\[([^\]]+)\]\]', existing))
        new_links = {p.stem for p in track_note_paths} - existing_links
        if not new_links:
            continue
        all_paths = track_note_paths if not existing_links else list(track_note_paths)
        content = make_artist_note(slug, all_paths)
        artist_note.write_text(content)
        print(f"{_tag('artist', CYN)} {artist_note.name}")


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(prog="dl", description="Music library manager")
    parser.add_argument("urls", nargs="*", metavar="URL")
    parser.add_argument("--video", action="store_true", help="Download as video (mp4)")
    parser.add_argument("--album", action="store_true", help="Download playlist/album with numbered tracks")
    parser.add_argument("--cookies", action="store_true", help="Use Chrome cookies (age-restricted content)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen without doing it")
    parser.add_argument("--recatalog", action="store_true", help="Regenerate catalog notes from .info.json files")
    parser.add_argument("--extract-thumbs", action="store_true", help="Extract embedded thumbnails from audio files into library/")
    parser.add_argument("--organize", action="store_true", help="Move flat catalog notes into per-artist subfolders")
    parser.add_argument("--index", action="store_true", help="Regenerate catalog/home.md dashboard note")
    parser.add_argument("--force", action="store_true", help="Overwrite existing catalog notes (use with --recatalog)")
    parser.add_argument("--note", metavar="FILENAME", help="Open catalog note for a file in Obsidian")
    parser.add_argument("--delete", metavar="TITLE", help="Delete a track and its catalog note")
    parser.add_argument("--start", metavar="TIME", help="Start download at this timestamp (e.g. 22:00)")

    args = parser.parse_args()

    if args.delete:
        delete_track(args.delete, dry_run=args.dry_run)
        return

    if args.note:
        open_note(args.note)
        return

    if args.extract_thumbs:
        extract_thumbs(dry_run=args.dry_run)
        return

    if args.organize:
        organize_by_artist(dry_run=args.dry_run)
        return

    if args.index:
        build_index(dry_run=args.dry_run)
        return

    if args.recatalog:
        recatalog(dry_run=args.dry_run, force=args.force)
        return

    if not args.urls:
        parser.print_help()
        return

    mode = "video" if args.video else "album" if args.album else "audio"
    cookies = args.cookies

    for url in args.urls:
        download_and_catalog(url, mode=mode, cookies=cookies, dry_run=args.dry_run, start=args.start)


if __name__ == "__main__":
    main()
