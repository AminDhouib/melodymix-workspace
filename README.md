# MelodyMix Workspace

Reusable workspace for making exact-length extended OST videos and preparing YouTube uploads.

The repo stores workflow, scripts, manifests, and QA rules. It intentionally does **not** store source audio, rendered videos, OAuth secrets, upload tokens, screenshots, or local render caches.

## Directory Layout

```text
inputs/audio/       Put source MP3/M4A/WebM/WAV files here.
inputs/visuals/     Put visual template videos or artwork here.
inputs/thumbnails/  Put upload thumbnails here.
manifests/          Batch render/upload manifest templates.
outputs/extended/   Rendered MP4 outputs.
metadata/           Local QA reports and generated metadata.
state/              Local upload state and OAuth-related state; ignored by git.
tools/              Render, loop-audit, verification, and upload helpers.
```

## Basic Render Flow

Install Python dependencies:

```powershell
python -m pip install -r requirements.txt
```

Install `ffmpeg` separately and make sure `ffmpeg` and `ffprobe` are on `PATH`.

1. Put source audio in `inputs/audio/`.
2. Put the visual template in `inputs/visuals/`.
3. Copy `manifests/render_manifest.example.tsv` to a new TSV and fill one row per video.
4. Render:

```powershell
python tools\render_batch_manifest.py --manifest "manifests\render_manifest.example.tsv" --no-skip-existing
```

5. Verify duration/codec/frame count with the relevant verifier.
6. Run rendered seam QA before upload:

```powershell
python tools\audit_rendered_loop_seams.py --plan "metadata\corrected_loop_render_plan.tsv"
```

For the detailed workflow and the Spirit Tracks lessons learned, read `VIDEO_EXTENSION_WORKFLOW.md`.

## YouTube Upload Flow

Use the corrected/upload manifest workflow documented in `YOUTUBE_API_UPLOAD_WORKFLOW.md`. Keep OAuth client secrets and refresh tokens out of git; this repo ignores them by default.

The current YouTube API scope is intentionally narrow:

```text
https://www.googleapis.com/auth/youtube.upload
```

Playlist insertion, monetization, thumbnails after quota failures, and Studio-only fixes are handled through browser/Studio workflows.
