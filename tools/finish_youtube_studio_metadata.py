import argparse
import asyncio
import pathlib
from datetime import datetime
from zoneinfo import ZoneInfo

from upload_youtube_manifest import (
    DEFAULT_PLAYLIST_TITLE,
    ROOT,
    add_to_playlist,
    complete_self_certification,
    connect,
    load_json,
    manifest_key,
    save_json,
    set_metadata,
    set_monetization_on,
    set_tags,
)
from youtube_upload_metadata import TITLE_PREFIX, YOUTUBE_TAG_LIMIT, display_title, item_tags, tags_cost


DEFAULT_MANIFEST = ROOT / "Zelda Spirit Tracks Metadata" / "upload_manifest.json"
DEFAULT_API_STATE = ROOT / "Zelda Spirit Tracks Metadata" / "youtube_api_upload_state.json"
DEFAULT_STATE = ROOT / "Zelda Spirit Tracks Metadata" / "studio_finish_state.json"
DEFAULT_STUDIO_VIDEO_URL = "https://studio.youtube.com/video/{video_id}/edit"


def load_state(path):
    path = pathlib.Path(path)
    if not path.exists():
        return {"items": {}}
    return load_json(path)


def select_items(manifest, args):
    items = [
        item
        for item in manifest["items"]
        if int(item["upload_order"]) >= args.start_order and int(item["source_track_number"]) >= args.min_track
    ]
    if args.only_track:
        wanted = {int(value.strip()) for value in args.only_track.split(",") if value.strip()}
        items = [item for item in items if int(item["source_track_number"]) in wanted]
    if args.limit is not None:
        items = items[: args.limit]
    return items


def uploaded_video_id(api_state, item):
    record = api_state.get("items", {}).get(manifest_key(item), {})
    if record.get("status") != "completed":
        return None
    return record.get("video_id")


async def navigate_to_video_editor(cdp, video_id):
    await cdp.send("Page.bringToFront")
    await cdp.send("Page.navigate", {"url": DEFAULT_STUDIO_VIDEO_URL.format(video_id=video_id)}, timeout=10)
    await asyncio.sleep(4)
    await cdp.assert_not_login_blocked()
    await cdp.wait_for_text(["Title (required)", "Details"], timeout=90)


async def click_save(cdp):
    if await cdp.click_text("Save", prefer_bottom=True, timeout=8, required=False):
        await asyncio.sleep(5)
        return True
    return False


async def finish_item(cdp, item, video_id, args):
    title = display_title(item, args.title_prefix)
    tags = item_tags(item, extra_tags=args.extra_tag, include_defaults=not args.no_default_tags)

    print(f"Opening Studio editor: {video_id} {title}", flush=True)
    await navigate_to_video_editor(cdp, video_id)
    if args.screenshot_dir:
        await cdp.screenshot(pathlib.Path(args.screenshot_dir) / f"{manifest_key(item)}-edit-open.png")

    print("Updating title, description, and tags", flush=True)
    await set_metadata(cdp, title, item["description"], thumbnail_path=None)
    tags_set = False
    if not args.no_tags:
        print(f"Setting tags: {len(tags)} tags, {tags_cost(tags)}/{YOUTUBE_TAG_LIMIT} chars", flush=True)
        tags_set = await set_tags(cdp, tags)
        print(f"Tags set: {tags_set}", flush=True)
        if not tags_set and not args.allow_missing_tags:
            raise RuntimeError("Could not confirm tags were set.")

    playlist_added = await add_to_playlist(cdp, args.playlist_title)
    print(f"Playlist selected: {playlist_added}", flush=True)
    if not playlist_added and not args.allow_missing_playlist:
        raise RuntimeError(f"Could not confirm playlist selection: {args.playlist_title}")
    await click_save(cdp)

    monetization_on = False
    if not args.skip_monetization:
        print("Opening monetization tab", flush=True)
        clicked = await cdp.click_text("Monetization", contains=True, timeout=12, required=False)
        if not clicked and not args.allow_monetization_off:
            raise RuntimeError("Could not open the Studio monetization tab.")
        if clicked:
            await asyncio.sleep(2)
            print("Setting monetization on", flush=True)
            await set_monetization_on(cdp)
            await complete_self_certification(cdp)
            await click_save(cdp)
            monetization_on = True

    return {
        "status": "completed",
        "title": title,
        "video_id": video_id,
        "video_url": f"https://www.youtube.com/watch?v={video_id}",
        "tags": tags,
        "tags_set": tags_set,
        "playlist_selected": playlist_added,
        "monetization_on": monetization_on,
        "completed_at": datetime.now(ZoneInfo(args.timezone)).isoformat(),
    }


async def run(args):
    manifest = load_json(args.manifest)
    api_state = load_json(args.api_state)
    state = load_state(args.state)
    state.setdefault("items", {})
    state.setdefault("playlist_title", args.playlist_title)
    save_json(args.state, state)

    items = select_items(manifest, args)
    planned = []
    for item in items:
        video_id = args.video_id if len(items) == 1 and args.video_id else uploaded_video_id(api_state, item)
        if not video_id:
            continue
        planned.append((item, video_id))

    if args.dry_run:
        for item, video_id in planned:
            title = display_title(item, args.title_prefix)
            tags = item_tags(item, extra_tags=args.extra_tag, include_defaults=not args.no_default_tags)
            print(f"{manifest_key(item)}\t{video_id}\t{title}\ttags={len(tags)}/{tags_cost(tags)}")
        return

    cdp = await connect(args.port, args.target_id)
    try:
        for item, video_id in planned:
            key = manifest_key(item)
            if not args.force and state["items"].get(key, {}).get("status") == "completed":
                print(f"Skipping completed Studio finish: {key}", flush=True)
                continue
            state["items"][key] = {
                "status": "started",
                "video_id": video_id,
                "started_at": datetime.now(ZoneInfo(args.timezone)).isoformat(),
            }
            save_json(args.state, state)
            try:
                result = await finish_item(cdp, item, video_id, args)
                state["items"][key] = result
                save_json(args.state, state)
                print(f"Completed Studio finish: {key}", flush=True)
            except Exception as exc:
                state["items"][key].update(
                    {
                        "status": "failed",
                        "error": str(exc),
                        "failed_at": datetime.now(ZoneInfo(args.timezone)).isoformat(),
                    }
                )
                save_json(args.state, state)
                if args.screenshot_dir:
                    await cdp.screenshot(pathlib.Path(args.screenshot_dir) / f"{key}-finish-failure.png")
                raise
    finally:
        await cdp.ws.close()


def main():
    parser = argparse.ArgumentParser(
        description="Finish narrow-API uploads in YouTube Studio: title prefix, tags, playlist, and monetization."
    )
    parser.add_argument("--manifest", type=pathlib.Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--api-state", type=pathlib.Path, default=DEFAULT_API_STATE)
    parser.add_argument("--state", type=pathlib.Path, default=DEFAULT_STATE)
    parser.add_argument("--port", type=int, required=True, help="Chrome remote debugging port.")
    parser.add_argument("--target-id", default=None)
    parser.add_argument("--playlist-title", default=DEFAULT_PLAYLIST_TITLE)
    parser.add_argument("--timezone", default="America/Toronto")
    parser.add_argument("--start-order", type=int, default=1)
    parser.add_argument("--min-track", type=int, default=0)
    parser.add_argument("--only-track", default=None, help="Comma-separated source track numbers.")
    parser.add_argument("--video-id", default=None, help="Manual video id for a single selected manifest item.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--title-prefix", default=TITLE_PREFIX)
    parser.add_argument("--extra-tag", action="append", default=[])
    parser.add_argument("--no-default-tags", action="store_true")
    parser.add_argument("--no-tags", action="store_true")
    parser.add_argument("--allow-missing-tags", action="store_true")
    parser.add_argument("--allow-missing-playlist", action="store_true")
    parser.add_argument("--allow-monetization-off", action="store_true")
    parser.add_argument("--skip-monetization", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--screenshot-dir", type=pathlib.Path, default=ROOT / "studio-finish-screenshots")
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
