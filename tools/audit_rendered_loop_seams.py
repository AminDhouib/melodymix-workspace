#!/usr/bin/env python3
import argparse
import csv
import subprocess
import sys
from pathlib import Path

import numpy as np


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = ROOT / "Zelda Spirit Tracks Metadata" / "corrected_loop_render_plan.tsv"
DEFAULT_OUT = ROOT / "Zelda Spirit Tracks Metadata" / "corrected_audio_seam_audit.tsv"
DEFAULT_SAMPLE_RATE = 48000


def parse_track_filter(value):
    if not value:
        return None
    tracks = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = (int(item) for item in part.split("-", 1))
            tracks.update(range(start, end + 1))
        else:
            tracks.add(int(part))
    return tracks


def read_tsv(path):
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path, rows, fieldnames):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def decode_audio(path, sample_rate):
    raw = subprocess.check_output(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-vn",
            "-ac",
            "2",
            "-ar",
            str(sample_rate),
            "-f",
            "f32le",
            "-",
        ]
    )
    audio = np.frombuffer(raw, dtype=np.float32).copy()
    if audio.size % 2:
        audio = audio[:-1]
    return audio.reshape((-1, 2))


def seam_times(loop_start, loop_end, duration, fade, max_seams):
    length = loop_end - loop_start
    if length <= 0:
        return []
    times = []
    seam = loop_end
    stop = max(0.0, duration - fade)
    while seam < stop:
        times.append(seam)
        if max_seams and len(times) >= max_seams:
            break
        seam += length
    return times


def seam_metric(audio, seam_s, sample_rate, window_ms):
    seam = int(round(seam_s * sample_rate))
    window = int(round(window_ms * sample_rate / 1000.0))
    start = max(1, seam - window)
    end = min(len(audio) - 1, seam + window)
    local = audio[max(0, seam - sample_rate) : min(len(audio), seam + sample_rate)]
    local_rms = float(np.sqrt(np.mean(np.square(local), dtype=np.float64))) if local.size else 0.0
    diff = np.abs(np.diff(audio[start:end], axis=0)).mean(axis=1)
    peak_index = int(np.argmax(diff)) if diff.size else 0
    peak_sample = start + peak_index
    peak = float(diff[peak_index]) if diff.size else 0.0
    jump = float(np.abs(audio[seam] - audio[seam - 1]).mean()) if 0 < seam < len(audio) else 0.0
    divisor = max(local_rms, 1e-9)
    return {
        "seam_time": seam_s,
        "sample_jump_norm": jump / divisor,
        "peak_derivative_norm": peak / divisor,
        "peak_offset_ms": ((peak_sample / sample_rate) - seam_s) * 1000.0,
        "local_rms": local_rms,
    }


def summarize(metrics, peak_threshold, jump_threshold):
    if not metrics:
        return {
            "seam_count": 0,
            "mean_peak_derivative_norm": "",
            "max_peak_derivative_norm": "",
            "mean_sample_jump_norm": "",
            "max_sample_jump_norm": "",
            "audio_seam_ok": "True",
            "audio_seam_reason": "no_manual_loop_seams",
        }
    peaks = [float(item["peak_derivative_norm"]) for item in metrics]
    jumps = [float(item["sample_jump_norm"]) for item in metrics]
    max_peak = max(peaks)
    max_jump = max(jumps)
    ok = max_peak <= peak_threshold and max_jump <= jump_threshold
    reason = "ok"
    if max_peak > peak_threshold:
        reason = "peak_derivative_above_threshold"
    elif max_jump > jump_threshold:
        reason = "sample_jump_above_threshold"
    return {
        "seam_count": len(metrics),
        "mean_peak_derivative_norm": f"{float(np.mean(peaks)):.9f}",
        "max_peak_derivative_norm": f"{max_peak:.9f}",
        "mean_sample_jump_norm": f"{float(np.mean(jumps)):.9f}",
        "max_sample_jump_norm": f"{max_jump:.9f}",
        "audio_seam_ok": "True" if ok else "False",
        "audio_seam_reason": reason,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--sample-rate", type=int, default=DEFAULT_SAMPLE_RATE)
    parser.add_argument("--tracks", help="Comma/range filter such as 112 or 24,57,100-114")
    parser.add_argument("--fade", type=float, default=5.0)
    parser.add_argument("--window-ms", type=float, default=30.0)
    parser.add_argument("--peak-threshold", type=float, default=1.5)
    parser.add_argument("--jump-threshold", type=float, default=0.8)
    parser.add_argument("--max-seams", type=int, default=12)
    args = parser.parse_args()

    track_filter = parse_track_filter(args.tracks)
    rows = []
    for plan_row in read_tsv(args.plan):
        if plan_row.get("loop_mode") != "manual_pymusiclooper":
            continue
        track = int(plan_row["track"])
        if track_filter and track not in track_filter:
            continue
        output_file = Path(plan_row["output_file"])
        audio = decode_audio(output_file, args.sample_rate)
        duration = len(audio) / float(args.sample_rate)
        seams = seam_times(
            float(plan_row["loop_start"]),
            float(plan_row["loop_end"]),
            duration,
            args.fade,
            args.max_seams,
        )
        metrics = [
            seam_metric(audio, seam, args.sample_rate, args.window_ms)
            for seam in seams
        ]
        summary = summarize(metrics, args.peak_threshold, args.jump_threshold)
        rows.append(
            {
                "order": plan_row["order"],
                "track": plan_row["track"],
                "title": plan_row["title"],
                "loop_start": plan_row["loop_start"],
                "loop_end": plan_row["loop_end"],
                "file": str(output_file),
                **summary,
            }
        )

    fieldnames = [
        "order",
        "track",
        "title",
        "loop_start",
        "loop_end",
        "file",
        "seam_count",
        "mean_peak_derivative_norm",
        "max_peak_derivative_norm",
        "mean_sample_jump_norm",
        "max_sample_jump_norm",
        "audio_seam_ok",
        "audio_seam_reason",
    ]
    write_tsv(args.out, rows, fieldnames)
    failures = [row for row in rows if row["audio_seam_ok"] != "True"]
    print(f"Wrote {args.out}")
    print(f"Checked {len(rows)} manual-loop renders")
    print(f"Failures: {len(failures)}")
    for row in failures[:20]:
        print(
            f"{int(row['track']):03d}: {row['audio_seam_reason']} "
            f"peak={row['max_peak_derivative_norm']} jump={row['max_sample_jump_norm']} "
            f"{row['title']}"
        )


if __name__ == "__main__":
    main()
