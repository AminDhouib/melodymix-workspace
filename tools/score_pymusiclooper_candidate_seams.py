#!/usr/bin/env python3
import argparse
import csv
import math
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PML = ROOT / "Zelda Spirit Tracks Metadata" / "pymusiclooper_loop_candidates.tsv"
DEFAULT_AUDIO_DIR = ROOT / "Zelda Spirit Tracks Source Audio"
DEFAULT_OUT = ROOT / "Zelda Spirit Tracks Metadata" / "pymusiclooper_candidate_seam_scores.tsv"
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


def find_audio(audio_dir, track):
    matches = sorted(Path(audio_dir).glob(f"{int(track):03d} -*"))
    if not matches:
        raise FileNotFoundError(f"No source audio found for track {int(track):03d}")
    return matches[0]


def decode_audio_stereo(path, sample_rate):
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


def samples(seconds, sample_rate):
    return int(round(seconds * sample_rate))


def segment(audio, start, length):
    start = int(start)
    end = start + int(length)
    if start < 0 or end > len(audio):
        padded = np.zeros((length, audio.shape[1]), dtype=np.float32)
        src_start = max(0, start)
        src_end = min(len(audio), end)
        if src_end > src_start:
            dst_start = src_start - start
            padded[dst_start : dst_start + (src_end - src_start)] = audio[src_start:src_end]
        return padded
    return audio[start:end]


def rms(values):
    if values.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(values), dtype=np.float64)))


def corr(a, b):
    if a.size == 0 or b.size == 0:
        return 0.0
    n = min(len(a), len(b))
    av = a[:n].reshape(-1).astype(np.float64)
    bv = b[:n].reshape(-1).astype(np.float64)
    av -= av.mean()
    bv -= bv.mean()
    denom = np.linalg.norm(av) * np.linalg.norm(bv)
    if denom <= 1e-12:
        return 0.0
    return float(np.dot(av, bv) / denom)


def db_ratio(numerator, denominator):
    if numerator <= 1e-12 or denominator <= 1e-12:
        return -120.0
    return float(20.0 * math.log10(numerator / denominator))


def score_candidate(audio, start_s, end_s, sample_rate):
    start = samples(start_s, sample_rate)
    end = samples(end_s, sample_rate)
    if start < 0 or end <= start or start >= len(audio):
        raise ValueError(f"Invalid loop candidate {start_s}-{end_s}")

    local_window = samples(1.0, sample_rate)
    compare_window = samples(0.5, sample_rate)
    seam_window = samples(0.030, sample_rate)
    edge_window = samples(0.015, sample_rate)

    before_end = segment(audio, end - local_window, local_window)
    after_start = segment(audio, start, local_window)
    local_rms = max(1e-9, (rms(before_end) + rms(after_start)) / 2.0)

    last_sample = segment(audio, end - 1, 1)[0]
    first_sample = segment(audio, start, 1)[0]
    seam_jump = float(np.abs(last_sample - first_sample).mean())

    seam_audio = np.vstack(
        [
            segment(audio, end - seam_window, seam_window),
            segment(audio, start, seam_window),
        ]
    )
    edge_audio = np.vstack(
        [
            segment(audio, end - edge_window, edge_window),
            segment(audio, start, edge_window),
        ]
    )
    seam_derivative = float(np.abs(np.diff(seam_audio, axis=0)).mean(axis=1).max())
    edge_derivative = float(np.abs(np.diff(edge_audio, axis=0)).mean(axis=1).max())

    pre_corr = corr(
        segment(audio, start - compare_window, compare_window),
        segment(audio, end - compare_window, compare_window),
    )
    post_corr = corr(
        segment(audio, start, compare_window),
        segment(audio, end, compare_window),
    )
    rms_delta_db = db_ratio(rms(after_start), rms(before_end))

    return {
        "seam_jump": seam_jump,
        "seam_jump_norm": seam_jump / local_rms,
        "seam_peak_derivative": seam_derivative,
        "seam_peak_derivative_norm": seam_derivative / local_rms,
        "edge_peak_derivative": edge_derivative,
        "edge_peak_derivative_norm": edge_derivative / local_rms,
        "pre_corr": pre_corr,
        "post_corr": post_corr,
        "rms_delta_db": rms_delta_db,
        "local_rms": local_rms,
    }


def group_candidates(rows, track_filter):
    grouped = defaultdict(list)
    for row in rows:
        if not row.get("candidate_rank"):
            continue
        track = int(row["track"])
        if track_filter and track not in track_filter:
            continue
        grouped[track].append(row)
    for items in grouped.values():
        items.sort(key=lambda item: int(item["candidate_rank"]))
    return grouped


def select_rows(rows, max_score_drop, family_start_tolerance, family_end_tolerance):
    if not rows:
        return
    best = max(float(row["pml_score"]) for row in rows)
    rank1 = min(rows, key=lambda item: int(item["candidate_rank"]))
    rank1_start = float(rank1["candidate_start"])
    rank1_end = float(rank1["candidate_end"])
    eligible = []
    family = []
    for row in rows:
        score = float(row["pml_score"])
        row["score_drop_from_best"] = best - score
        same_family = (
            abs(float(row["candidate_start"]) - rank1_start) <= family_start_tolerance
            and abs(float(row["candidate_end"]) - rank1_end) <= family_end_tolerance
        )
        row["same_boundary_family_as_rank1"] = "True" if same_family else "False"
        if best - score <= max_score_drop:
            eligible.append(row)
            if same_family:
                family.append(row)
    pool = family or eligible or rows

    # Keep the cost intentionally simple and source-derived. The rendered seam
    # audit is the final authority after encoding.
    for row in rows:
        score_drop = float(row["score_drop_from_best"])
        row["selection_cost"] = (
            float(row["seam_jump_norm"])
            + 0.15 * float(row["edge_peak_derivative_norm"])
            + 20.0 * score_drop
        )
        row["selected"] = "False"
    selected = min(pool, key=lambda item: float(item["selection_cost"]))
    selected["selected"] = "True"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pymusiclooper", type=Path, default=DEFAULT_PML)
    parser.add_argument("--audio-dir", type=Path, default=DEFAULT_AUDIO_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--sample-rate", type=int, default=DEFAULT_SAMPLE_RATE)
    parser.add_argument("--tracks", help="Comma/range filter such as 112 or 24,57,100-114")
    parser.add_argument("--max-score-drop", type=float, default=0.002)
    parser.add_argument("--family-start-tolerance", type=float, default=1.0)
    parser.add_argument("--family-end-tolerance", type=float, default=1.0)
    args = parser.parse_args()

    track_filter = parse_track_filter(args.tracks)
    grouped = group_candidates(read_tsv(args.pymusiclooper), track_filter)
    output_rows = []
    for track in sorted(grouped):
        audio_path = find_audio(args.audio_dir, track)
        audio = decode_audio_stereo(audio_path, args.sample_rate)
        scored = []
        for source in grouped[track]:
            row = dict(source)
            metrics = score_candidate(
                audio,
                float(row["candidate_start"]),
                float(row["candidate_end"]),
                args.sample_rate,
            )
            row.update({key: f"{value:.9f}" for key, value in metrics.items()})
            row["source_audio"] = str(audio_path)
            scored.append(row)
        select_rows(scored, args.max_score_drop, args.family_start_tolerance, args.family_end_tolerance)
        output_rows.extend(scored)

    fieldnames = [
        "uploaded",
        "order",
        "track",
        "title",
        "video_id",
        "classification",
        "loop_start",
        "loop_end",
        "candidate_rank",
        "candidate_start",
        "candidate_end",
        "candidate_length",
        "pml_note_difference",
        "pml_loudness_difference",
        "pml_score",
        "pml_classification",
        "score_drop_from_best",
        "same_boundary_family_as_rank1",
        "seam_jump_norm",
        "edge_peak_derivative_norm",
        "seam_peak_derivative_norm",
        "pre_corr",
        "post_corr",
        "rms_delta_db",
        "selection_cost",
        "selected",
        "source_audio",
    ]
    write_tsv(args.out, output_rows, fieldnames)
    selected = [row for row in output_rows if row.get("selected") == "True"]
    print(f"Wrote {args.out}")
    print(f"Tracks scored: {len(grouped)}")
    print(f"Selected candidates: {len(selected)}")
    for row in selected:
        print(
            f"{int(row['track']):03d}: rank {row['candidate_rank']} "
            f"{float(row['candidate_start']):.6f}-{float(row['candidate_end']):.6f} "
            f"score={float(row['pml_score']):.9f} "
            f"jump={float(row['seam_jump_norm']):.3f} "
            f"cost={float(row['selection_cost']):.3f}"
        )


if __name__ == "__main__":
    main()
