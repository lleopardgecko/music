# Library
> Requires the [Dataview](https://github.com/blacksmithgu/obsidian-dataview) plugin.

## Music
```dataview
TABLE artist, genre, duration, upload_date
FROM "catalog/music"
WHERE type = "music"
SORT upload_date DESC
```

## Podcasts
```dataview
TABLE artist, duration, upload_date
FROM "catalog/podcasts"
WHERE type = "podcast"
SORT upload_date DESC
```
