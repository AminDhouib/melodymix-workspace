# Session Handoff

Use this file first when resuming the Spirit Tracks work.

## Current State

- Project: Spirit Tracks extended OST uploads on the `MelodyMix [OSTs]` YouTube channel.
- API scope is intentionally narrow: `https://www.googleapis.com/auth/youtube.upload`.
- User removed the recent Spirit Tracks uploads in YouTube Studio, excluding older releases that existed before this batch.
- Use the corrected manifest and fresh corrected state for the next upload; do not resume from the old upload state.
- Playlist insertion, monetization, and post-upload fixes are Studio/browser tasks, not API tasks with the current no-delete scope.
- Corrected rerenders were generated in `Zelda Spirit Tracks Extended Corrected/`.
- Corrected upload manifest: `Zelda Spirit Tracks Metadata/upload_manifest_corrected.json`.
- Fresh corrected upload state: `Zelda Spirit Tracks Metadata/youtube_api_upload_state_corrected.json`.
- Fresh corrected Studio finish state: `Zelda Spirit Tracks Metadata/studio_finish_state_corrected.json`.
- Loop audit/candidate evidence is in `Zelda Spirit Tracks Metadata/waveform_loop_boundary_audit.md`, `Zelda Spirit Tracks Metadata/pymusiclooper_loop_candidates.md`, and `Zelda Spirit Tracks Metadata/corrected_audio_seam_audit.tsv`.

## Hard Rules

- Do not delete, replace, or rerender any uploaded video from title/context guesses, render logs, low loop score, skipped-tail heuristics, or the deprecated delete JSON.
- A loop decision must come from waveform inspection of the actual loop boundary, then a listening check. The waveform report is evidence, not a deletion manifest.
- PyMusicLooper scores are candidate evidence only. A high score does not override a waveform/tail mismatch.
- Treat `Zelda Spirit Tracks Metadata/delete_high_loop_risk_uploaded.json` as deprecated and unsafe. It is a heuristic-only list, not a deletion manifest.
- Keep monetization on for uploaded videos during the Studio finish pass.

## Next Work

1. Use the corrected upload manifest and fresh corrected state for the next API upload. Do not use the old `youtube_api_upload_state.json` skip state for this corrected pass.
2. Run the Studio finish pass for playlist, monetization, thumbnails, tags, and title repair.
3. For future soundtrack batches, follow the repeatable quality recipe in `VIDEO_EXTENSION_WORKFLOW.md`.

## Render QA Summary

- Corrected plan: 51 manual PyMusicLooper loop renders, 6 full-track repeats, 47 reused existing/full-track renders.
- Manifest verification passed for all 104 items in `Zelda Spirit Tracks Metadata/corrected_render_verification.tsv`.
- Rendered seam audit passed: 51 manual-loop renders checked, 0 failures in `Zelda Spirit Tracks Metadata/corrected_audio_seam_audit.tsv`.
- Accepted loop overrides are stored in `Zelda Spirit Tracks Metadata/manual_loop_overrides.tsv`.
- Override tracks: `062`, `074`, `083`, `099`, `100`, `101`, `102`, `103`, `112`, `121`, `137`, `140`, `142`.
- Important example: `112. Fleeing by Demon Train` had a click at the repeated seam near `0:01:18`; rank 4 fixed it. This is why rendered seam audit is required before upload.

## Useful Commands

Preview the next upload batch:

```powershell
python tools\youtube_api_manifest_uploader.py dry-run --manifest "Zelda Spirit Tracks Metadata\upload_manifest_corrected.json" --state "Zelda Spirit Tracks Metadata\youtube_api_upload_state_corrected.json" --limit 5
```

Upload corrected videos:

```powershell
python tools\youtube_api_manifest_uploader.py upload --manifest "Zelda Spirit Tracks Metadata\upload_manifest_corrected.json" --state "Zelda Spirit Tracks Metadata\youtube_api_upload_state_corrected.json"
```

Run corrected Studio finish pass after upload:

```powershell
python tools\finish_youtube_studio_metadata.py --manifest "Zelda Spirit Tracks Metadata\upload_manifest_corrected.json" --api-state "Zelda Spirit Tracks Metadata\youtube_api_upload_state_corrected.json" --state "Zelda Spirit Tracks Metadata\studio_finish_state_corrected.json" --port 58926
```

Check the saved OAuth token is still narrow-scoped:

```powershell
python tools\youtube_api_manifest_uploader.py token-info
```

Run the rendered seam audit:

```powershell
python tools\audit_rendered_loop_seams.py
```

## Reference Files

- `VIDEO_EXTENSION_WORKFLOW.md`: source download, exact render length, fade, verification, and waveform-based loop judgment.
- `YOUTUBE_API_UPLOAD_WORKFLOW.md`: YouTube API upload scope, auth, dry run, upload, and Studio finish pass.
- `Zelda Spirit Tracks Metadata/youtube_api_upload_state.json`: old upload state; keep for audit only, not for corrected upload resume.
- `Zelda Spirit Tracks Metadata/loop_reconsideration_audit.md`: waveform inspection queue.
- `Zelda Spirit Tracks Metadata/waveform_loop_boundary_audit.md`: decoded waveform pass with per-track classifications and PNG links.
- `Zelda Spirit Tracks Metadata/pymusiclooper_loop_candidates.md`: PyMusicLooper top loop candidates for the waveform queue.
- `Zelda Spirit Tracks Metadata/manual_loop_overrides.tsv`: accepted loop-point overrides to preserve on rebuild.
- `Zelda Spirit Tracks Metadata/corrected_audio_seam_audit.tsv`: rendered seam QA result.
- `Zelda Spirit Tracks Metadata/corrected_loop_render_plan.tsv`: per-track loop mode and corrected output path.
- `Zelda Spirit Tracks Metadata/corrected_render_verification.tsv`: corrected manifest ffprobe verification.
