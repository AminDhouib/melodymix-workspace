#!/usr/bin/env python3
import argparse
import subprocess
import sys
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_METADATA = ROOT / "Zelda Spirit Tracks Metadata" / "missing_tracks.tsv"
DEFAULT_AUDIO_DIR = ROOT / "Zelda Spirit Tracks Source Audio"
DEFAULT_OUTPUT_DIR = ROOT / "Zelda Spirit Tracks Extended"
DEFAULT_WORK_DIR = ROOT / ".render-work"
DEFAULT_LOG_DIR = ROOT / "render-logs" / "zelda-spirit-tracks"


def safe_name(value):
    return "".join(c if c.isalnum() or c in "._- '()&!," else "_" for c in value).strip()


def read_missing_tracks(path):
    tracks = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        number, video_id, duration, name, url = line.split("\t")[:5]
        tracks.append(
            {
                "number": int(number),
                "video_id": video_id,
                "duration": duration,
                "name": name,
                "url": url,
            }
        )
    return tracks


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


def find_audio(audio_dir, number, video_id):
    matches = sorted(audio_dir.glob(f"{number:03d} -*[{video_id}].*"))
    if matches:
        return matches[0]
    matches = sorted(audio_dir.glob(f"{number:03d} -* {video_id}.*"))
    if matches:
        return matches[0]
    matches = sorted(audio_dir.glob(f"{number:03d} -*"))
    return matches[0] if matches else None


def download_audio(track, audio_dir, log_dir):
    existing = find_audio(audio_dir, track["number"], track["video_id"])
    if existing:
        return existing

    audio_dir.mkdir(parents=True, exist_ok=True)
    out_template = str(
        audio_dir
        / f'{track["number"]:03d} - %(title).180B [%(id)s].%(ext)s'
    )
    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--no-playlist",
        "--ignore-errors",
        "--no-warnings",
        "-f",
        "bestaudio[ext=webm]/bestaudio",
        "-o",
        out_template,
        track["url"],
    ]
    log_path = log_dir / f'{track["number"]:03d}-download.log'
    code = run_logged(cmd, log_path)
    if code != 0:
        raise RuntimeError(f'Audio download failed for {track["number"]:03d}; see {log_path}')

    audio = find_audio(audio_dir, track["number"], track["video_id"])
    if not audio:
        raise RuntimeError(f'Audio download did not produce a file for {track["number"]:03d}')
    return audio


def render_track(track, audio_path, visual_path, output_dir, work_dir, log_dir, args):
    output_dir.mkdir(parents=True, exist_ok=True)
    title_name = safe_name(track["name"])
    output = output_dir / (
        f'{track["number"]:03d} - {title_name} - Spirit Tracks OST '
        f"[14-29-24 timecode].mp4"
    )
    if output.exists() and args.skip_existing:
        return output, "skipped"

    cmd = [
        sys.executable,
        str(ROOT / "tools" / "extend_with_visual_template.py"),
        "--audio-input",
        str(audio_path),
        "--video-input",
        str(visual_path),
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
        "--audio-loop",
        args.audio_loop,
        "--audio-sample-rate",
        str(args.audio_sample_rate),
        "--video-codec",
        args.video_codec,
        "--cq",
        str(args.cq),
        "--work-dir",
        str(work_dir),
    ]
    log_path = log_dir / f'{track["number"]:03d}-render.log'
    code = run_logged(cmd, log_path)
    if code != 0:
        raise RuntimeError(f'Render failed for {track["number"]:03d}; see {log_path}')
    return output, "rendered"


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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", default=DEFAULT_METADATA, type=Path)
    parser.add_argument("--visual", required=True, type=Path)
    parser.add_argument("--audio-dir", default=DEFAULT_AUDIO_DIR, type=Path)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, type=Path)
    parser.add_argument("--work-dir", default=DEFAULT_WORK_DIR, type=Path)
    parser.add_argument("--log-dir", default=DEFAULT_LOG_DIR, type=Path)
    parser.add_argument("--target", default="14:29:24")
    parser.add_argument("--fade", default=5.0, type=float)
    parser.add_argument("--output-fps", default=30, type=int)
    parser.add_argument("--audio-loop", choices=["auto", "full"], default="auto")
    parser.add_argument("--audio-sample-rate", default=48000, type=int)
    parser.add_argument("--video-codec", default="hevc_nvenc")
    parser.add_argument("--cq", default=24, type=int)
    parser.add_argument("--only", help="Comma-separated track numbers or ranges, e.g. 23,24,28-32.")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--skip-existing", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()

    tracks = read_missing_tracks(args.metadata)
    wanted = parse_only(args.only)
    if wanted is not None:
        tracks = [track for track in tracks if track["number"] in wanted]
    if args.limit is not None:
        tracks = tracks[: args.limit]

    print(f"Tracks queued: {len(tracks)}", flush=True)
    for index, track in enumerate(tracks, 1):
        label = f'{track["number"]:03d} {track["name"]}'
        print(f"[{index}/{len(tracks)}] {label}", flush=True)
        audio = download_audio(track, args.audio_dir, args.log_dir)
        output, status = render_track(
            track,
            audio,
            args.visual,
            args.output_dir,
            args.work_dir,
            args.log_dir,
            args,
        )
        print(f"  {status}: {output}", flush=True)


if __name__ == "__main__":
    main()
