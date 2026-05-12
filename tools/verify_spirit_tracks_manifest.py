#!/usr/bin/env python3
import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "Zelda Spirit Tracks Metadata" / "upload_manifest_corrected.json"
DEFAULT_OUT = ROOT / "Zelda Spirit Tracks Metadata" / "corrected_render_verification.tsv"


def load_json(path):
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def ffprobe_json(path):
    raw = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-print_format",
            "json",
            str(path),
        ],
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return json.loads(raw)


def inspect_item(item, expected_duration, expected_frames):
    path = Path(item["file"])
    row = {
        "order": item["upload_order"],
        "track": item["source_track_number"],
        "title": item["source_title"],
        "loop_mode": item.get("loop_render_mode", ""),
        "file": str(path),
        "exists": path.exists(),
        "duration": "",
        "vcodec": "",
        "width": "",
        "height": "",
        "fps": "",
        "nb_frames": "",
        "acodec": "",
        "sample_rate": "",
        "channels": "",
        "audio_duration": "",
        "ok": "False",
        "error": "",
    }
    if not path.exists():
        row["error"] = "missing_file"
        return row
    try:
        info = ffprobe_json(path)
        video = next(stream for stream in info["streams"] if stream["codec_type"] == "video")
        audio = next(stream for stream in info["streams"] if stream["codec_type"] == "audio")
        row.update(
            {
                "duration": info["format"].get("duration", ""),
                "vcodec": video.get("codec_name", ""),
                "width": video.get("width", ""),
                "height": video.get("height", ""),
                "fps": video.get("avg_frame_rate", ""),
                "nb_frames": video.get("nb_frames", ""),
                "acodec": audio.get("codec_name", ""),
                "sample_rate": audio.get("sample_rate", ""),
                "channels": audio.get("channels", ""),
                "audio_duration": audio.get("duration", ""),
            }
        )
        duration_ok = abs(float(row["duration"]) - expected_duration) < 0.01
        audio_duration_ok = abs(float(row["audio_duration"]) - expected_duration) < 0.02
        frames_ok = int(row["nb_frames"]) == expected_frames
        codec_ok = row["vcodec"] == "hevc" and row["acodec"] == "aac"
        audio_ok = row["sample_rate"] == "48000" and int(row["channels"]) == 2
        video_ok = int(row["width"]) == 1920 and int(row["height"]) == 1080 and row["fps"] == "30/1"
        row["ok"] = str(duration_ok and audio_duration_ok and frames_ok and codec_ok and audio_ok and video_ok)
    except Exception as exc:
        row["error"] = repr(exc)
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    manifest = load_json(args.manifest)
    expected_duration = float(manifest["duration_seconds"])
    expected_frames = int(manifest["frames"])
    rows = [inspect_item(item, expected_duration, expected_frames) for item in manifest["items"]]
    fieldnames = [
        "order",
        "track",
        "title",
        "loop_mode",
        "file",
        "exists",
        "duration",
        "vcodec",
        "width",
        "height",
        "fps",
        "nb_frames",
        "acodec",
        "sample_rate",
        "channels",
        "audio_duration",
        "ok",
        "error",
    ]
    with args.out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    failures = [row for row in rows if row["ok"] != "True"]
    print(f"Checked {len(rows)} manifest items")
    print(f"Failures: {len(failures)}")
    print(f"Wrote {args.out}")
    if failures:
        for row in failures[:20]:
            print(f"FAIL {row['track']} {row['title']}: {row['error'] or row}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
