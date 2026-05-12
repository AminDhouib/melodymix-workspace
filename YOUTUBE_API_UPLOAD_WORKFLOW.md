# YouTube API Upload Workflow

This workspace uses `tools/youtube_api_manifest_uploader.py` for official YouTube Data API uploads.

## Current Spirit Tracks State

As of 2026-05-11, the previous recent Spirit Tracks API upload batch should be considered obsolete.

- The user removed the recent Spirit Tracks uploads in YouTube Studio, excluding older releases that existed before this batch.
- Do not use `youtube_api_upload_state.json` to skip corrected uploads.
- Corrected rerenders were generated in `Zelda Spirit Tracks Extended Corrected/`.
- Corrected upload manifest: `Zelda Spirit Tracks Metadata/upload_manifest_corrected.json`.
- Fresh corrected upload state: `Zelda Spirit Tracks Metadata/youtube_api_upload_state_corrected.json`.
- Fresh corrected Studio finish state: `Zelda Spirit Tracks Metadata/studio_finish_state_corrected.json`.
- Corrected render verification passed for all 104 manifest items.
- Playlist insertion, monetization, and post-upload fixes still need the Studio/browser finish pass.

Start a resumed session with `SESSION_HANDOFF.md`.

## Scope Policy

Use only:

```text
https://www.googleapis.com/auth/youtube.upload
```

The script refuses tokens that contain broader YouTube scopes:

```text
https://www.googleapis.com/auth/youtube
https://www.googleapis.com/auth/youtube.force-ssl
https://www.googleapis.com/auth/youtubepartner
```

This is intentional. `youtube.force-ssl` and `youtube` allow delete-capable access, which we do not want.

With `youtube.upload`, the script can upload a video, set metadata during upload, set scheduled publish time, set SEO tags, and set the custom thumbnail. API playlist insertion, monetization, and post-upload video edits require broader scopes, so those remain Studio/browser tasks.

## Setup

Install the dependencies:

```powershell
python -m pip install -r requirements.txt
```

The OAuth client secret file should stay local and must not be committed. It is ignored by `.gitignore`.

Authorize once:

```powershell
python tools\youtube_api_manifest_uploader.py auth
```

The saved token goes to:

```text
secrets/youtube-upload-token.json
```

Verify the saved token stays narrow-scoped:

```powershell
python tools\youtube_api_manifest_uploader.py token-info
```

## Dry Run

Preview the schedule from the corrected Spirit Tracks manifest:

```powershell
python tools\youtube_api_manifest_uploader.py dry-run --manifest "Zelda Spirit Tracks Metadata\upload_manifest_corrected.json" --state "Zelda Spirit Tracks Metadata\youtube_api_upload_state_corrected.json" --limit 5
```

The dry run prints the final upload title with the leading `♫` prefix and the tag count/character usage. Add `--show-tags` to print the full tag list for each item.

The first manifest item publishes immediately. Later items are uploaded as private with `publishAt` set every four hours after the base time.

## Upload

Upload a single test video first:

```powershell
python tools\youtube_api_manifest_uploader.py upload --manifest "Zelda Spirit Tracks Metadata\upload_manifest_corrected.json" --state "Zelda Spirit Tracks Metadata\youtube_api_upload_state_corrected.json" --limit 1
```

Resume or continue the batch:

```powershell
python tools\youtube_api_manifest_uploader.py upload --manifest "Zelda Spirit Tracks Metadata\upload_manifest_corrected.json" --state "Zelda Spirit Tracks Metadata\youtube_api_upload_state_corrected.json"
```

The uploader writes progress to:

```text
Zelda Spirit Tracks Metadata/youtube_api_upload_state_corrected.json
```

Completed items are skipped automatically unless `--force` is passed.

## Studio Finish Pass

After API upload, run the Studio finish pass from an authenticated Studio browser profile:

```powershell
python tools\finish_youtube_studio_metadata.py --port 58926 --limit 1
```

For the corrected Spirit Tracks pass, include the corrected manifest and state files:

```powershell
python tools\finish_youtube_studio_metadata.py --manifest "Zelda Spirit Tracks Metadata\upload_manifest_corrected.json" --api-state "Zelda Spirit Tracks Metadata\youtube_api_upload_state_corrected.json" --state "Zelda Spirit Tracks Metadata\studio_finish_state_corrected.json" --port 58926 --limit 1
```

For the corrected command above, this reads `Zelda Spirit Tracks Metadata/youtube_api_upload_state_corrected.json`, opens each uploaded video in YouTube Studio, and applies the Studio-only pieces: playlist selection, monetization `On`, and any post-upload metadata correction. It also reapplies the final `♫` title and tags, which is useful for repairing a test upload.

Run a preview first:

```powershell
python tools\finish_youtube_studio_metadata.py --manifest "Zelda Spirit Tracks Metadata\upload_manifest_corrected.json" --api-state "Zelda Spirit Tracks Metadata\youtube_api_upload_state_corrected.json" --state "Zelda Spirit Tracks Metadata\studio_finish_state_corrected.json" --port 58926 --dry-run --limit 5
```

## Metadata Defaults

Both upload scripts format titles as:

```text
♫23. Zelda Taken Away - Spirit Tracks [OST] - Extended!
```

Tags are generated from the track name, Spirit Tracks soundtrack terms, Nintendo/Zelda music terms, and `MelodyMix`. The helper keeps the generated list under YouTube's 500-character tag limit.

The Studio/browser uploader requires playlist selection, tags, and monetization `On` by default. Use the `--allow-missing-*` flags only for manual recovery runs where you intend to inspect Studio yourself afterward.

## Important YouTube API Caveat

YouTube documents that uploads from unverified API projects created after July 28, 2020 may be restricted to private viewing until the API project passes YouTube's audit. If that happens, the API can still create the video records, but public/scheduled publishing needs to be handled through Studio or an audited project.
