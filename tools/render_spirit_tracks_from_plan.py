#!/usr/bin/env python3
import argparse
import csv
import subprocess
import sys
from pathlib import Path

from render_spirit_tracks_batch import download_audio, find_audio, read_missing_tracks


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = ROOT / "Zelda Spirit Tracks Metadata" / "corrected_loop_render_plan.tsv"
DEFAULT_METADATA = ROOT / "Zelda Spirit Tracks Metadata" / "missing_tracks.tsv"
DEFAULT_AUDIO_DIR = ROOT / "Zelda Spirit Tracks Source Audio"
DEFAULT_WORK_DIR = ROOT / ".render-work-corrected"
DEFAULT_LOG_DIR = ROOT / "render-logs" / "zelda-spirit-tracks-corrected"


def read_plan(path):
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def run_logged(cmd, log_path):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        log.write("+ " + " ".join(str(c) for c in cmd) + "\n")
        log.flush()
        proc = subprocess.Popen(
            cmd,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            log.write(line)
        return proc.wait()


def parse_only(value):
    if not value:
        return None
    wanted = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = (int(item) for item in part.split("-", 1))
            wanted.update(range(start, end + 1))
        else:
            wanted.add(int(part))
    return wanted


def render_row(row, track, audio_path, args):
    output = Path(row["output_file"])
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and args.skip_existing:
        return "skipped"

    cmd = [
        sys.executable,
        str(ROOT / "tools" / "extend_with_visual_template.py"),
        "--audio-input",
        str(audio_path),
        "--video-input",
        str(args.visual),
        "--output",
        str(output),
        "--target",
        args.target,
        "--target-format",
        "mmssff",
        "--fade",
        str(args.fade),
        "--output-fps",
        str(args.output_fps),
        "--audio-sample-rate",
        str(args.audio_sample_rate),
        "--video-codec",
        args.video_codec,
        "--cq",
        str(args.cq),
        "--work-dir",
        str(args.work_dir),
    ]
    if row["loop_mode"] == "manual_pymusiclooper":
        cmd.extend(["--loop-start", row["loop_start"], "--loop-end", row["loop_end"]])
    elif row["loop_mode"] == "full_track":
        cmd.extend(["--audio-loop", "full"])
    else:
        raise ValueError(f"Unsupported render loop mode: {row['loop_mode']}")

    log_path = args.log_dir / f"{int(track['number']):03d}-render.log"
    code = run_logged(cmd, log_path)
    if code != 0:
        raise RuntimeError(f"Render failed for {track['number']:03d}; see {log_path}")
    return "rendered"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--visual", required=True, type=Path)
    parser.add_argument("--audio-dir", type=Path, default=DEFAULT_AUDIO_DIR)
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR)
    parser.add_argument("--target", default="14:29:24")
    parser.add_argument("--fade", default=5.0, type=float)
    parser.add_argument("--output-fps", default=30, type=int)
    parser.add_argument("--audio-sample-rate", default=48000, type=int)
    parser.add_argument("--video-codec", default="hevc_nvenc")
    parser.add_argument("--cq", default=24, type=int)
    parser.add_argument("--only", help="Comma-separated track numbers or ranges.")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--skip-existing", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()

    track_by_number = {track["number"]: track for track in read_missing_tracks(args.metadata)}
    rows = [row for row in read_plan(args.plan) if row["requires_rerender"] == "True"]
    wanted = parse_only(args.only)
    if wanted is not None:
        rows = [row for row in rows if int(row["track"]) in wanted]
    if args.limit is not None:
        rows = rows[: args.limit]

    print(f"Tracks queued: {len(rows)}", flush=True)
    for index, row in enumerate(rows, 1):
        number = int(row["track"])
        track = track_by_number[number]
        label = f"{number:03d} {row['title']} ({row['loop_mode']})"
        print(f"[{index}/{len(rows)}] {label}", flush=True)
        audio = find_audio(args.audio_dir, track["number"], track["video_id"])
        if not audio:
            audio = download_audio(track, args.audio_dir, args.log_dir)
        status = render_row(row, track, audio, args)
        print(f"  {status}: {row['output_file']}", flush=True)


if __name__ == "__main__":
    main()
