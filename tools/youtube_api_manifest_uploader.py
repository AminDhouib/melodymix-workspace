import argparse
import json
import mimetypes
import pathlib
import sys
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from youtube_upload_metadata import TITLE_PREFIX, YOUTUBE_TAG_LIMIT, display_title, item_tags, tags_cost


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "Zelda Spirit Tracks Metadata" / "upload_manifest.json"
DEFAULT_STATE = ROOT / "Zelda Spirit Tracks Metadata" / "youtube_api_upload_state.json"
DEFAULT_TOKEN = ROOT / "secrets" / "youtube-upload-token.json"
UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
SCOPES = [UPLOAD_SCOPE]
KNOWN_BROAD_YOUTUBE_SCOPES = {
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/youtubepartner",
}
MONTHS = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
]


class UnsafeScopeError(RuntimeError):
    pass


def load_json(path):
    path = pathlib.Path(path)
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def save_json(path, value):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(value, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    tmp.replace(path)


def find_client_secret():
    matches = sorted(ROOT.glob("client_secret*.json"))
    if not matches:
        raise FileNotFoundError("No client_secret*.json file found in the workspace root.")
    if len(matches) > 1:
        names = "\n".join(f"  - {match}" for match in matches)
        raise RuntimeError(f"Multiple client secret files found; pass --client-secret explicitly:\n{names}")
    return matches[0]


def load_state(path):
    path = pathlib.Path(path)
    if not path.exists():
        return {"items": {}}
    return load_json(path)


def has_completed_items(state):
    return any(item.get("status") == "completed" for item in state.get("items", {}).values())


def manifest_key(item):
    return f"{int(item['upload_order']):03d}-{int(item['source_track_number']):03d}"


def parse_base_time(value, timezone, state):
    tz = ZoneInfo(timezone)
    if value:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=tz)
        return parsed.astimezone(tz)
    if state.get("schedule_base") and has_completed_items(state):
        parsed = datetime.fromisoformat(state["schedule_base"])
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=tz)
        return parsed.astimezone(tz)
    return datetime.now(tz).replace(second=0, microsecond=0)


def schedule_time(base_dt, item):
    return base_dt + timedelta(hours=int(item.get("schedule_offset_hours", 0)))


def iso_for_youtube(dt):
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def friendly_time(dt):
    month = MONTHS[dt.month - 1]
    hour = dt.hour % 12 or 12
    suffix = "AM" if dt.hour < 12 else "PM"
    return f"{month} {dt.day}, {dt.year} {hour}:{dt.minute:02d} {suffix}"


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


def request_token_scopes(access_token):
    url = "https://oauth2.googleapis.com/tokeninfo?access_token=" + urllib.parse.quote(access_token)
    with urllib.request.urlopen(url, timeout=15) as response:
        token_info = json.load(response)
    return set(token_info.get("scope", "").split())


def assert_safe_scopes(credentials):
    credentials_scopes = set(credentials.scopes or [])
    token_scopes = set()
    if credentials.token:
        try:
            token_scopes = request_token_scopes(credentials.token)
        except Exception as exc:
            print(f"Warning: could not verify granted scopes from tokeninfo: {exc}", file=sys.stderr)
    granted = token_scopes or credentials_scopes
    extra_youtube_scopes = {
        scope
        for scope in granted
        if scope.startswith("https://www.googleapis.com/auth/youtube") and scope != UPLOAD_SCOPE
    }
    if extra_youtube_scopes:
        scopes = "\n".join(f"  - {scope}" for scope in sorted(extra_youtube_scopes))
        raise UnsafeScopeError(
            "Refusing to use a token with extra YouTube scopes:\n"
            f"{scopes}\n"
            "Delete the token file or revoke the app grant, then authorize with youtube.upload only."
        )
    if UPLOAD_SCOPE not in granted and credentials_scopes and UPLOAD_SCOPE not in credentials_scopes:
        raise UnsafeScopeError(f"Token does not include required scope: {UPLOAD_SCOPE}")
    return granted


def authorize(client_secret, token_path):
    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), SCOPES)
    credentials = flow.run_local_server(
        host="localhost",
        port=0,
        open_browser=True,
        authorization_prompt_message=(
            "\nOpen this URL in your browser if it did not open automatically:\n{url}\n\n"
        ),
        success_message="YouTube upload authorization complete. You can close this tab.",
        prompt="consent",
        include_granted_scopes="false",
    )
    assert_safe_scopes(credentials)
    save_json(token_path, json.loads(credentials.to_json()))
    print(f"Saved narrow-scope token: {token_path}")
    print(f"Granted scopes: {', '.join(sorted(credentials.scopes or SCOPES))}")
    return credentials


def load_credentials(client_secret, token_path, authorize_if_missing):
    token_path = pathlib.Path(token_path)
    credentials = None
    if token_path.exists():
        credentials = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        save_json(token_path, json.loads(credentials.to_json()))
    if not credentials or not credentials.valid:
        if not authorize_if_missing:
            raise RuntimeError(f"No valid token at {token_path}. Run the auth command first.")
        credentials = authorize(client_secret, token_path)
    assert_safe_scopes(credentials)
    return credentials


def build_youtube(credentials):
    return build("youtube", "v3", credentials=credentials, cache_discovery=False)


def thumbnail_media(path):
    path = pathlib.Path(path)
    mime_type, _ = mimetypes.guess_type(path.name)
    if mime_type not in {"image/jpeg", "image/png"}:
        mime_type = "image/jpeg"
    return MediaFileUpload(str(path), mimetype=mime_type, resumable=False)


def video_media(path, chunk_mb):
    path = pathlib.Path(path)
    return MediaFileUpload(
        str(path),
        mimetype="video/*",
        chunksize=chunk_mb * 1024 * 1024,
        resumable=True,
    )


def video_body(item, publish_at, args):
    scheduled = int(item["upload_order"]) != 1
    privacy_status = "private" if scheduled else args.first_privacy
    tags = item_tags(
        item,
        extra_tags=args.extra_tag,
        include_defaults=not args.no_default_tags,
    )
    snippet = {
        "title": display_title(item, args.title_prefix),
        "description": item["description"],
        "categoryId": args.category_id,
        "defaultLanguage": args.default_language,
        "defaultAudioLanguage": args.default_audio_language,
    }
    if tags:
        snippet["tags"] = tags
    status = {
        "privacyStatus": privacy_status,
        "selfDeclaredMadeForKids": False,
        "embeddable": True,
        "license": "youtube",
        "publicStatsViewable": True,
    }
    if scheduled:
        status["publishAt"] = iso_for_youtube(publish_at)
    return {
        "snippet": snippet,
        "status": status,
    }


def resumable_execute(request, title, max_retries):
    response = None
    retries = 0
    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                print(f"  {title}: {status.progress() * 100:.1f}%")
        except HttpError as exc:
            retryable = exc.resp.status in {500, 502, 503, 504}
            if not retryable or retries >= max_retries:
                raise
            retries += 1
            delay = min(2**retries, 60)
            print(f"  transient HTTP {exc.resp.status}; retry {retries}/{max_retries} after {delay}s")
            time.sleep(delay)
    return response


def upload_item(youtube, item, publish_at, args):
    video_path = pathlib.Path(item["file"])
    thumb_path = pathlib.Path(item.get("thumbnail", ""))
    title = display_title(item, args.title_prefix)
    if not video_path.exists():
        raise FileNotFoundError(video_path)
    if not args.skip_thumbnail and thumb_path and not thumb_path.exists():
        raise FileNotFoundError(thumb_path)

    body = video_body(item, publish_at, args)
    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        notifySubscribers=args.notify_subscribers,
        media_body=video_media(video_path, args.chunk_mb),
    )
    response = resumable_execute(request, title, args.max_retries)
    video_id = response["id"]
    print(f"Uploaded video id: {video_id}")

    thumbnail_set = False
    if not args.skip_thumbnail and thumb_path:
        youtube.thumbnails().set(videoId=video_id, media_body=thumbnail_media(thumb_path)).execute()
        thumbnail_set = True
        print("Thumbnail set")

    return {
        "video_id": video_id,
        "video_url": f"https://www.youtube.com/watch?v={video_id}",
        "upload_response_status": response.get("status", {}),
        "thumbnail_set": thumbnail_set,
    }


def print_scope_policy():
    print("OAuth scope policy:")
    print(f"  allowed: {UPLOAD_SCOPE}")
    print("  refused: any other https://www.googleapis.com/auth/youtube* scope")
    print("  known broad examples:")
    for scope in sorted(KNOWN_BROAD_YOUTUBE_SCOPES):
        print(f"    - {scope}")


def command_auth(args):
    client_secret = args.client_secret or find_client_secret()
    print_scope_policy()
    authorize(client_secret, args.token)


def command_token_info(args):
    client_secret = args.client_secret or find_client_secret()
    credentials = load_credentials(client_secret, args.token, authorize_if_missing=False)
    granted = assert_safe_scopes(credentials)
    print("Token is valid and narrow-scoped.")
    for scope in sorted(granted):
        print(f"  - {scope}")


def command_dry_run(args):
    manifest = load_json(args.manifest)
    state = load_state(args.state)
    base_dt = parse_base_time(args.schedule_base, args.timezone, state)
    for item in select_items(manifest, args):
        publish_at = schedule_time(base_dt, item)
        release = "now" if int(item["upload_order"]) == 1 else friendly_time(publish_at)
        status = "public" if int(item["upload_order"]) == 1 else "scheduled/private-until-release"
        title = display_title(item, args.title_prefix)
        tags = item_tags(item, extra_tags=args.extra_tag, include_defaults=not args.no_default_tags)
        print(f"{manifest_key(item)}\t{release}\t{status}\t{title}\ttags={len(tags)}/{tags_cost(tags)}")
        if args.show_tags:
            print("  " + ", ".join(tags))


def command_upload(args):
    client_secret = args.client_secret or find_client_secret()
    manifest = load_json(args.manifest)
    state = load_state(args.state)
    base_dt = parse_base_time(args.schedule_base, args.timezone, state)
    credentials = load_credentials(client_secret, args.token, authorize_if_missing=args.authorize_if_missing)
    youtube = build_youtube(credentials)

    state.setdefault("schedule_base", base_dt.isoformat())
    state.setdefault("timezone", args.timezone)
    state.setdefault("items", {})
    save_json(args.state, state)

    for item in select_items(manifest, args):
        key = manifest_key(item)
        title = display_title(item, args.title_prefix)
        tags = item_tags(item, extra_tags=args.extra_tag, include_defaults=not args.no_default_tags)
        if state["items"].get(key, {}).get("status") == "completed" and not args.force:
            print(f"Skipping completed: {key} {title}")
            continue

        publish_at = schedule_time(base_dt, item)
        print(f"\nUploading {key}: {title}")
        print(f"Tags: {len(tags)} tags, {tags_cost(tags)}/{YOUTUBE_TAG_LIMIT} chars")
        if int(item["upload_order"]) == 1:
            print(f"Release: now, privacy={args.first_privacy}")
        else:
            print(f"Release: {friendly_time(publish_at)} ({iso_for_youtube(publish_at)})")

        started = datetime.now(ZoneInfo(args.timezone)).isoformat()
        state["items"][key] = {
            "status": "started",
            "title": title,
            "tags": tags,
            "source_track_number": item["source_track_number"],
            "started_at": started,
            "scheduled_for": None if int(item["upload_order"]) == 1 else publish_at.isoformat(),
        }
        save_json(args.state, state)
        try:
            result = upload_item(youtube, item, publish_at, args)
            state["items"][key].update(
                {
                    "status": "completed",
                    "completed_at": datetime.now(ZoneInfo(args.timezone)).isoformat(),
                    **result,
                }
            )
            save_json(args.state, state)
        except Exception as exc:
            state["items"][key].update(
                {
                    "status": "failed",
                    "failed_at": datetime.now(ZoneInfo(args.timezone)).isoformat(),
                    "error": str(exc),
                }
            )
            save_json(args.state, state)
            raise


def add_common_manifest_args(parser):
    parser.add_argument("--manifest", type=pathlib.Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--state", type=pathlib.Path, default=DEFAULT_STATE)
    parser.add_argument("--timezone", default="America/Toronto")
    parser.add_argument("--schedule-base", default=None, help="ISO datetime for upload_order 1; defaults to now.")
    parser.add_argument("--start-order", type=int, default=1)
    parser.add_argument("--min-track", type=int, default=0)
    parser.add_argument("--only-track", default=None, help="Comma-separated source track numbers.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--title-prefix", default=TITLE_PREFIX)
    parser.add_argument("--extra-tag", action="append", default=[])
    parser.add_argument("--no-default-tags", action="store_true")
    parser.add_argument("--show-tags", action="store_true")


def build_parser():
    parser = argparse.ArgumentParser(
        description="Narrow-scope YouTube API uploader for manifest-rendered videos."
    )
    parser.add_argument("--client-secret", type=pathlib.Path, default=None)
    parser.add_argument("--token", type=pathlib.Path, default=DEFAULT_TOKEN)

    subparsers = parser.add_subparsers(dest="command", required=True)

    auth = subparsers.add_parser("auth", help="Authorize with youtube.upload only and save a token.")
    auth.set_defaults(func=command_auth)

    token_info = subparsers.add_parser("token-info", help="Verify saved token scopes.")
    token_info.set_defaults(func=command_token_info)

    dry_run = subparsers.add_parser("dry-run", help="Print upload schedule from the manifest.")
    add_common_manifest_args(dry_run)
    dry_run.set_defaults(func=command_dry_run)

    upload = subparsers.add_parser("upload", help="Upload videos from the manifest.")
    add_common_manifest_args(upload)
    upload.add_argument("--authorize-if-missing", action="store_true")
    upload.add_argument("--force", action="store_true")
    upload.add_argument("--skip-thumbnail", action="store_true")
    upload.add_argument("--first-privacy", choices=["public", "unlisted", "private"], default="public")
    upload.add_argument("--notify-subscribers", action=argparse.BooleanOptionalAction, default=False)
    upload.add_argument("--category-id", default="10", help="YouTube category id; 10 is Music.")
    upload.add_argument("--default-language", default="en")
    upload.add_argument("--default-audio-language", default="en")
    upload.add_argument("--chunk-mb", type=int, default=8)
    upload.add_argument("--max-retries", type=int, default=5)
    upload.set_defaults(func=command_upload)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except UnsafeScopeError as exc:
        print(f"UNSAFE_SCOPE: {exc}", file=sys.stderr)
        sys.exit(3)
    except HttpError as exc:
        print(f"HTTP_ERROR {exc.resp.status}: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
