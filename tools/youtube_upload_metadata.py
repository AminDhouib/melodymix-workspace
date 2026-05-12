import re


TITLE_PREFIX = "♫"
YOUTUBE_TAG_LIMIT = 500

DEFAULT_SEO_TAGS = (
    "Zelda Spirit Tracks",
    "Spirit Tracks OST",
    "Spirit Tracks Extended",
    "Spirit Tracks Music Extended",
    "The Legend of Zelda Spirit Tracks",
    "Legend of Zelda Spirit Tracks",
    "Zelda OST",
    "Zelda Music",
    "Nintendo DS Music",
    "Nintendo DS OST",
    "Nintendo Music",
    "Video Game Music",
    "VGM",
    "OST Extended",
    "Extended OST",
    "Extended Music",
    "MelodyMix",
)


def display_title(item, title_prefix=TITLE_PREFIX):
    title = str(item["title"]).strip()
    prefix = title_prefix or ""
    if prefix and not title.startswith(prefix):
        return f"{prefix}{title}"
    return title


def clean_tag(value):
    tag = re.sub(r"\s+", " ", str(value or "")).strip().strip(",")
    return tag


def tag_cost(tag):
    # YouTube counts commas between list items, and quoted spaces count toward
    # the 500-character API tag limit.
    return len(tag) + (2 if any(ch.isspace() for ch in tag) else 0)


def tags_cost(tags):
    return sum(tag_cost(tag) for tag in tags) + max(0, len(tags) - 1)


def add_tag(out, seen, tag, limit):
    tag = clean_tag(tag)
    if not tag:
        return
    key = tag.casefold()
    if key in seen:
        return
    proposed = out + [tag]
    if tags_cost(proposed) > limit:
        return
    seen.add(key)
    out.append(tag)


def item_tags(item, extra_tags=(), include_defaults=True, limit=YOUTUBE_TAG_LIMIT):
    track_title = clean_tag(item.get("source_title")) or clean_tag(item.get("title"))
    candidates = []
    if track_title:
        candidates.extend(
            (
                f"{track_title} Spirit Tracks",
                f"{track_title} Extended",
                f"{track_title} OST",
                track_title,
            )
        )
    if include_defaults:
        candidates.extend(DEFAULT_SEO_TAGS)
    candidates.extend(item.get("tags", ()) or ())
    candidates.extend(extra_tags or ())

    out = []
    seen = set()
    for tag in candidates:
        add_tag(out, seen, tag, limit)
    return out
