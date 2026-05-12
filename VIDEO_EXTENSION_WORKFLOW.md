# Video Extension Workflow

This project downloads short OST videos, preserves the best available source quality, and renders exact-length looped MP4 versions for YouTube upload.

## Source Download Rules

Use `yt-dlp` through Python so it works even when `yt-dlp` is not on `PATH`:

```powershell
python -m yt_dlp --version
```

For a channel, first inspect titles without downloading:

```powershell
python -m yt_dlp --flat-playlist --ignore-errors --no-warnings --print "%(playlist_index)s`t%(id)s`t%(title)s`t%(webpage_url)s" "https://www.youtube.com/@Gabochililinkle/videos"
```

For Star Fox OST videos, use this title filter:

```text
(?i)(star\s*fox|starfox).*ost
```

Download full videos at the highest available quality, up to 4K:

```powershell
python -m yt_dlp --ignore-errors --no-warnings --match-title "(?i)(star\s*fox|starfox).*ost" -f "bestvideo[height<=2160]+bestaudio/best[height<=2160]/best" --merge-output-format webm --embed-metadata --download-archive ".yt-dlp-starfox-4k-archive.txt" -o "StarFox OST 4K/%(playlist_index)02d - %(title).200B [%(id)s].%(ext)s" "https://www.youtube.com/@Gabochililinkle/videos"
```

Do not assume every upload has 4K. Confirm with:

```powershell
python -m yt_dlp -F --no-warnings "https://www.youtube.com/watch?v=VIDEO_ID"
```

In the current batch, Area 6 only has `2560x1440`; the rest have `3840x2160`.

## Extension Target

For these Star Fox videos, the target `14:29:24` means:

```text
14 minutes, 29 seconds, frame 24
```

At `30 fps`, that is:

```text
869.800 seconds
26,094 frames
```

Do not interpret this as `14 hours, 29 minutes, 24 seconds`.

## Render Tool

Use:

```text
tools/extend_starfox_video.py
```

The renderer:

- detects a repeated audio section automatically
- keeps any intro once, then loops the detected body
- loops video to the exact frame count
- fades audio and video during the final 5 seconds
- renders MP4 with HEVC video and AAC audio
- supports exact `MM:SS:frames` targets with `--target-format mmssff`

## Looping Judgment

Do not decide loop quality from title, context, duration, PyMusicLooper score, or render logs alone. Those only create a review queue. A keep/rerender/delete decision needs waveform inspection of the actual boundary plus a listening check.

Check:

- waveform continuity at `loop_end -> loop_start`: shape, phase, amplitude, transients, and stereo channels
- whether the phrase resolves naturally or is cut mid-phrase
- whether a source already contains a partial repeat followed by a unique ending/coda
- whether the rendered MP4 repeats a click/transient at every seam

If no clean musical loop exists, let the track play through its natural ending, then restart the full track:

```powershell
--audio-loop full
```

Known caution case: `69. Restoring the Spirit Tracks` behaves like a story cue; use full-track repeat unless a manual loop point is confirmed.

## PyMusicLooper Candidate Pass

For MP3/YouTube-derived audio, use PyMusicLooper as a candidate generator, not the final authority. Run it on decoded WAV cache through Python 3.11:

```powershell
python tools\run_pymusiclooper_spirit_tracks.py --workers 1 --top 10 --timeout 900
```

The batch recipe below scores the candidates and validates the rendered MP4 seams.

Rules:

- score `>= 0.90` is normally enough to render a manual candidate for review
- weak, poor, or missing candidates should be reviewed as full-track repeats
- do not blindly use rank 1; compare top candidates by source seam jump and rendered seam transient
- final upload candidates must pass the rendered seam audit

## Repeatable Quality Recipe

Assume the local YouTube/MP3/WebM source is the source of truth. Do not wait for original game files or embedded loop metadata. Those are ideal when available, but they are not consistent enough for this channel workflow.

Batch checklist:

1. Download or confirm all source audio files exist.
2. Run the waveform audit to identify risky auto loops.
3. Run PyMusicLooper on decoded WAV cache, not direct WebM.
4. Score PyMusicLooper candidates by source seam risk.
5. Build a corrected render plan.
6. Render corrected files into a separate output folder.
7. Verify every manifest item before upload.
8. Audit rendered loop seams before upload.

Commands for the Spirit Tracks-style workflow:

```powershell
python tools\audit_spirit_tracks_loop_waveforms.py
python tools\run_pymusiclooper_spirit_tracks.py --workers 1 --top 10 --timeout 900
python tools\score_pymusiclooper_candidate_seams.py
python tools\build_spirit_tracks_corrected_plan.py --use-candidate-scores
python tools\render_spirit_tracks_from_plan.py --visual "Zelda Spirit Tracks Visual\♫1. Opening Theme - Spirit Tracks [OST] - Extended! [wBnN1ijol0w].mp4"
python tools\verify_spirit_tracks_manifest.py
python tools\audit_rendered_loop_seams.py
```

Keep confirmed loop choices in `Zelda Spirit Tracks Metadata\manual_loop_overrides.tsv`. `build_spirit_tracks_corrected_plan.py` uses manual overrides by default; pass `--use-candidate-scores` only when intentionally rebuilding from the scorer output.

Current Spirit Tracks result:

- 51 manual PyMusicLooper loop renders, all passing rendered seam audit
- 6 full-track repeats: `029`, `069`, `111`, `126`, `130`, `132`
- 47 existing unflagged/full-track renders reused
- 13 accepted manual loop overrides: `062`, `074`, `083`, `099`, `100`, `101`, `102`, `103`, `112`, `121`, `137`, `140`, `142`

Render corrected batches into a new folder such as:

```text
Zelda Spirit Tracks Extended Corrected
```

Do not overwrite the previous render folder until the corrected manifest passes verification and sample listening. Keep corrected manifests and states separate:

```text
Zelda Spirit Tracks Metadata\upload_manifest_corrected.json
Zelda Spirit Tracks Metadata\youtube_api_upload_state_corrected.json
Zelda Spirit Tracks Metadata\studio_finish_state_corrected.json
```

Key lessons:

- PyMusicLooper on WAV is better than the old local detector, but it still needs waveform/listening review.
- A lower-ranked candidate can beat rank 1; `112. Fleeing by Demon Train` was fixed by rank 4 after rank 1 produced a repeated seam click.
- The source seam scorer chooses candidates; the rendered seam audit is the pass/fail gate.
- Final upload manifests must pass ffprobe verification and rendered seam audit.

Example:

```powershell
python tools\extend_starfox_video.py --input "StarFox OST 4K\03 - Area 6   StarFox Switch 2 OST [1vMJi-bJCSg].webm" --output "StarFox OST Extended\03 - Area 6 - StarFox Switch 2 OST [14-29-24 timecode].mp4" --target 14:29:24 --target-format mmssff --fade 5 --audio-loop auto --video-codec hevc_nvenc --cq 24
```

For future videos, keep the same output naming convention:

```text
NN - Title - Game OST [14-29-24 timecode].mp4
```

## Verification

Every final render should pass these checks.

Check duration, frame count, video codec, and resolution:

```powershell
ffprobe -v error -show_entries format=duration -select_streams v:0 -show_entries stream=codec_name,width,height,avg_frame_rate,nb_frames -of default=noprint_wrappers=1 "OUTPUT.mp4"
```

Expected for this batch:

```text
duration=869.800000
nb_frames=26094
codec_name=hevc
```

Check audio:

```powershell
ffprobe -v error -select_streams a:0 -show_entries stream=codec_name,sample_rate,channels,duration -of default=noprint_wrappers=1 "OUTPUT.mp4"
```

Expected:

```text
codec_name=aac
sample_rate=48000
channels=2
duration=869.800000
```

Check the final frame is black:

```powershell
ffmpeg -hide_banner -sseof -0.05 -i "OUTPUT.mp4" -vf "signalstats,metadata=print:key=lavfi.signalstats.YAVG" -frames:v 1 -an -f null -
```

A `YAVG` near `16` means video black in limited-range YUV.

Check the audio tail is faded down:

```powershell
ffmpeg -hide_banner -sseof -0.1 -i "OUTPUT.mp4" -af "volumedetect" -vn -f null -
```

The final tail should be very quiet, typically around `-39 dB` or lower for these renders.

## Cleanup

After final MP4s verify, temporary files in `.render-work` can be deleted. Keep:

- source downloads in `StarFox OST 4K`
- final outputs in `StarFox OST Extended`
- render logs in `render-logs` if useful for audit/debugging
- `tools/extend_starfox_video.py`

## YouTube Upload Plan

The next step is uploading the finished MP4s through the stealth browser MCP.

Use the stealth browser MCP when the user asks to upload, because it can operate through a browser profile and preserve normal site session behavior.

For each upload:

1. Open YouTube Studio in the stealth browser session.
2. If login is required, ask the user to complete authentication.
3. Upload one final MP4 from `StarFox OST Extended`.
4. Before filling metadata, inspect another comparable video from the same style/category.
5. Use that reference video's title and description to infer presentation style, not to copy it verbatim.
6. Draft a title that includes the track name, game/source label, loop/extended duration, and relevant OST terms.
7. Draft a description that clearly states the track/source context, loop/extended nature, and any relevant credit/source notes.
8. Set visibility only as requested by the user.
9. After upload processing starts, capture or report the final YouTube Studio status.

Metadata guidance:

- Preserve the track name exactly enough to be searchable.
- Include `Star Fox`, `OST`, and `Extended` where natural.
- Mention the exact duration target as `14:29:24 timecode` only if that matters for the series. For normal viewer-facing titles, `14 Minute Extended` or `Extended Loop` may read better.
- Do not fabricate official status. If the source video is fanmade, concept, unofficial, or ambiguous, use accurate wording.
- Do not copy a reference description wholesale. Use it to understand structure, tone, tags, and credit conventions.

Example title pattern:

```text
Area 6 - Star Fox Switch 2 OST Extended Loop
```

Example description pattern:

```text
Extended loop version of "Area 6" from the Star Fox Switch 2 OST upload.

Rendered from the highest available YouTube source, looped to 14:29:24 timecode with a final fade-out.
```

## Current Output Set

The corrected final videos are in:

```text
StarFox OST Extended
```

All current timecode outputs were verified at:

```text
00:14:29.800
26,094 frames
AAC 48 kHz stereo
HEVC MP4
```
