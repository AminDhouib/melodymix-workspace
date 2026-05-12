#!/usr/bin/env python3
import argparse
import csv
import math
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUDIT = ROOT / "Zelda Spirit Tracks Metadata" / "loop_reconsideration_audit.md"
DEFAULT_AUDIO_DIR = ROOT / "Zelda Spirit Tracks Source Audio"
DEFAULT_OUT_DIR = ROOT / "Zelda Spirit Tracks Metadata" / "waveform-loop-audit"
DEFAULT_MD = ROOT / "Zelda Spirit Tracks Metadata" / "waveform_loop_boundary_audit.md"
DEFAULT_TSV = ROOT / "Zelda Spirit Tracks Metadata" / "waveform_loop_boundary_audit.tsv"


def safe_name(value):
    return "".join(c if c.isalnum() or c in "._- " else "_" for c in value).strip()


def parse_seconds(value):
    return float(value.rstrip("s"))


def parse_loop(value):
    match = re.match(r"([0-9.]+)-([0-9.]+)s$", value.strip())
    if not match:
        raise ValueError(f"Could not parse loop value: {value}")
    return float(match.group(1)), float(match.group(2))


def parse_audit(path):
    section = None
    candidates = []
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if line.startswith("## Uploaded Candidates"):
            section = "uploaded"
            continue
        if line.startswith("## Not Yet Uploaded Candidates"):
            section = "not_yet_uploaded"
            continue
        if line.startswith("## "):
            section = None
            continue
        if section is None or not line.startswith("|"):
            continue
        fields = [item.strip() for item in line.strip("|").split("|")]
        if not fields or fields[0] not in {"HIGH", "REVIEW"}:
            continue
        loop_start, loop_end = parse_loop(fields[5])
        candidates.append(
            {
                "risk": fields[0],
                "uploaded": section == "uploaded",
                "order": int(fields[1]),
                "track": int(fields[2]),
                "title": fields[3],
                "video_id": fields[4],
                "loop_start": loop_start,
                "loop_end": loop_end,
                "source_duration": parse_seconds(fields[6]),
                "tail_left": parse_seconds(fields[7]),
                "auto_score": float(fields[8]),
                "reason": fields[9],
            }
        )
    return candidates


def find_audio(audio_dir, track):
    matches = sorted(audio_dir.glob(f"{track:03d} -*"))
    if not matches:
        raise FileNotFoundError(f"No source audio found for track {track:03d}")
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


def segment(audio, start_sample, length):
    start_sample = int(start_sample)
    end_sample = start_sample + int(length)
    if start_sample < 0 or end_sample > len(audio):
        padded = np.zeros((length, audio.shape[1]), dtype=np.float32)
        src_start = max(0, start_sample)
        src_end = min(len(audio), end_sample)
        if src_end > src_start:
            dst_start = src_start - start_sample
            padded[dst_start : dst_start + (src_end - src_start)] = audio[src_start:src_end]
        return padded
    return audio[start_sample:end_sample]


def rms(values):
    if values.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(values), dtype=np.float64)))


def db_ratio(numerator, denominator):
    if numerator <= 1e-12 or denominator <= 1e-12:
        return -120.0
    return float(20.0 * math.log10(numerator / denominator))


def corr(a, b):
    if a.size == 0 or b.size == 0:
        return 0.0
    av = a.reshape(-1).astype(np.float64)
    bv = b.reshape(-1).astype(np.float64)
    av -= av.mean()
    bv -= bv.mean()
    denom = np.linalg.norm(av) * np.linalg.norm(bv)
    if denom <= 1e-12:
        return 0.0
    return float(np.dot(av, bv) / denom)


def nrmse(a, b):
    denom = (rms(a) + rms(b)) / 2.0
    if denom <= 1e-12:
        return 0.0
    return float(rms(a - b) / denom)


def best_center_match(audio, start_s, end_s, sample_rate, window_s=0.75, search_s=0.35):
    length = samples(window_s, sample_rate)
    half = length // 2
    start_center = samples(start_s, sample_rate)
    end_center = samples(end_s, sample_rate)
    reference = segment(audio, start_center - half, length)
    step = max(1, samples(0.005, sample_rate))
    radius = samples(search_s, sample_rate)
    best = {"corr": -1.0, "offset_s": 0.0, "nrmse": 99.0}
    for offset in range(-radius, radius + 1, step):
        candidate = segment(audio, end_center + offset - half, length)
        c = corr(reference, candidate)
        e = nrmse(reference, candidate)
        if c > best["corr"]:
            best = {"corr": c, "offset_s": offset / sample_rate, "nrmse": e}
    return best


def tail_best_similarity(audio, loop_start_s, loop_end_s, duration_s, sample_rate):
    tail_len_s = max(0.0, min(4.0, duration_s - loop_end_s))
    if tail_len_s < 0.5:
        return 1.0
    length = samples(tail_len_s, sample_rate)
    tail = segment(audio, samples(loop_end_s, sample_rate), length)
    body_start = samples(loop_start_s, sample_rate)
    body_end = samples(loop_end_s, sample_rate)
    if body_end - body_start < length:
        return corr(tail, segment(audio, body_start, length))
    step = max(1, samples(0.10, sample_rate))
    best = -1.0
    for pos in range(body_start, body_end - length + 1, step):
        best = max(best, corr(tail, segment(audio, pos, length)))
    return float(best)


def classify(metrics):
    pre_corr = metrics["pre_corr"]
    center_corr = metrics["best_center_corr"]
    seam_jump = metrics["best_seam_jump_norm"]
    tail_db = metrics["tail_db_vs_body"]
    tail_similarity = metrics["tail_similarity"]
    post_corr = metrics["post_corr"]

    if center_corr >= 0.88 and seam_jump <= 0.65 and pre_corr >= 0.70:
        return "keep_after_listening_check"
    if center_corr >= 0.78:
        return "manual_loop_point_review"
    if center_corr >= 0.62:
        return "ambiguous_boundary_review"
    if tail_db > -22.0 and tail_similarity < 0.45 and post_corr < 0.45:
        return "full_track_review_unique_tail"
    return "full_track_review_no_clean_waveform_match"


def draw_wave_panel(draw, box, title, waves, colors):
    x0, y0, x1, y1 = box
    draw.rectangle(box, outline=(190, 190, 190), fill=(252, 252, 252))
    draw.text((x0 + 8, y0 + 6), title, fill=(20, 20, 20))
    mid = (y0 + y1) // 2
    draw.line((x0 + 8, mid, x1 - 8, mid), fill=(220, 220, 220))
    width = x1 - x0 - 16
    height = y1 - y0 - 34
    top = y0 + 28
    for wave, color in zip(waves, colors):
        mono = wave.mean(axis=1)
        if mono.size == 0:
            continue
        idx = np.linspace(0, mono.size - 1, width).astype(np.int64)
        vals = mono[idx]
        peak = max(0.02, float(np.percentile(np.abs(vals), 99)))
        points = []
        for i, val in enumerate(vals):
            y = top + height / 2 - float(np.clip(val / peak, -1.0, 1.0)) * (height / 2 - 3)
            points.append((x0 + 8 + i, int(round(y))))
        if len(points) > 1:
            draw.line(points, fill=color, width=1)


def draw_tail_panel(draw, box, audio, loop_end_s, duration_s, sample_rate):
    x0, y0, x1, y1 = box
    draw.rectangle(box, outline=(190, 190, 190), fill=(252, 252, 252))
    draw.text((x0 + 8, y0 + 6), "Tail waveform after detected loop end", fill=(20, 20, 20))
    tail_len = max(0, samples(duration_s - loop_end_s, sample_rate))
    if tail_len <= 0:
        return
    tail = segment(audio, samples(loop_end_s, sample_rate), tail_len).mean(axis=1)
    width = x1 - x0 - 16
    height = y1 - y0 - 34
    top = y0 + 28
    idx = np.linspace(0, tail.size - 1, width).astype(np.int64)
    vals = tail[idx]
    peak = max(0.02, float(np.percentile(np.abs(vals), 99)))
    points = []
    for i, val in enumerate(vals):
        y = top + height / 2 - float(np.clip(val / peak, -1.0, 1.0)) * (height / 2 - 3)
        points.append((x0 + 8 + i, int(round(y))))
    if len(points) > 1:
        draw.line(points, fill=(70, 70, 70), width=1)


def write_waveform_png(path, candidate, audio, duration_s, sample_rate, metrics):
    width, height = 1400, 1130
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)

    title = (
        f"{candidate['track']:03d} {candidate['title']} | order {candidate['order']:03d} | "
        f"{metrics['classification']}"
    )
    draw.text((24, 20), title, fill=(0, 0, 0))
    metric_line = (
        f"loop {candidate['loop_start']:.3f}-{candidate['loop_end']:.3f}s | "
        f"pre_corr={metrics['pre_corr']:.3f} post_corr={metrics['post_corr']:.3f} "
        f"best_center={metrics['best_center_corr']:.3f} "
        f"offset={metrics['best_center_offset_ms']:.0f}ms "
        f"seam_jump={metrics['seam_jump_norm']:.2f} "
        f"best_seam={metrics['best_seam_jump_norm']:.2f} "
        f"tail_db={metrics['tail_db_vs_body']:.1f} tail_sim={metrics['tail_similarity']:.3f}"
    )
    draw.text((24, 42), metric_line, fill=(45, 45, 45))

    start = samples(candidate["loop_start"], sample_rate)
    end = samples(candidate["loop_end"], sample_rate)
    best_end = samples(metrics["suggested_loop_end"], sample_rate)
    pre_len = samples(0.50, sample_rate)
    post_len = samples(0.50, sample_rate)

    start_pre = segment(audio, start - pre_len, pre_len)
    end_pre = segment(audio, end - pre_len, pre_len)
    best_end_pre = segment(audio, best_end - pre_len, pre_len)
    start_post = segment(audio, start, post_len)
    end_post = segment(audio, end, post_len)
    seam = np.vstack([end_pre, start_post])
    best_seam = np.vstack([best_end_pre, start_post])

    draw_wave_panel(
        draw,
        (24, 80, 1376, 280),
        "Overlay: 0.5s before loop start (blue) vs 0.5s before loop end (orange)",
        [start_pre, end_pre],
        [(0, 85, 180), (210, 95, 0)],
    )
    draw_wave_panel(
        draw,
        (24, 300, 1376, 500),
        "Overlay: 0.5s after loop start (blue) vs source after loop end/tail (orange)",
        [start_post, end_post],
        [(0, 85, 180), (210, 95, 0)],
    )
    draw_wave_panel(
        draw,
        (24, 520, 1376, 720),
        "Original detected seam: 0.5s before loop end joined to 0.5s after loop start",
        [seam],
        [(0, 110, 70)],
    )
    seam_mid = 24 + 8 + (1376 - 24 - 16) // 2
    draw.line((seam_mid, 548, seam_mid, 716), fill=(180, 30, 30), width=2)
    draw_wave_panel(
        draw,
        (24, 740, 1376, 940),
        "Refined waveform seam: 0.5s before suggested end joined to loop start",
        [best_seam],
        [(100, 60, 160)],
    )
    draw.line((seam_mid, 768, seam_mid, 936), fill=(180, 30, 30), width=2)
    draw_tail_panel(draw, (24, 960, 1376, 1100), audio, candidate["loop_end"], duration_s, sample_rate)
    image.save(path)


def analyze_candidate(candidate, audio_dir, out_dir, sample_rate):
    audio_path = find_audio(audio_dir, candidate["track"])
    audio = decode_audio_stereo(audio_path, sample_rate)
    duration_s = len(audio) / sample_rate

    start_sample = samples(candidate["loop_start"], sample_rate)
    end_sample = samples(candidate["loop_end"], sample_rate)
    pre_len = samples(0.50, sample_rate)
    post_len = samples(0.50, sample_rate)
    body = segment(
        audio,
        start_sample,
        max(samples(0.25, sample_rate), end_sample - start_sample),
    )
    tail = segment(
        audio,
        end_sample,
        max(1, len(audio) - end_sample),
    )
    start_pre = segment(audio, start_sample - pre_len, pre_len)
    end_pre = segment(audio, end_sample - pre_len, pre_len)
    start_post = segment(audio, start_sample, post_len)
    end_post = segment(audio, end_sample, post_len)

    end_last = segment(audio, end_sample - samples(0.004, sample_rate), samples(0.004, sample_rate))
    start_first = segment(audio, start_sample, samples(0.004, sample_rate))
    seam_delta = float(np.abs(audio[min(end_sample, len(audio) - 1)] - audio[start_sample]).mean())
    seam_norm = seam_delta / max(1e-6, (rms(end_last) + rms(start_first)) / 2.0)
    best = best_center_match(audio, candidate["loop_start"], candidate["loop_end"], sample_rate)
    best_end_sample = end_sample + samples(best["offset_s"], sample_rate)
    best_end_sample = max(samples(0.01, sample_rate), min(len(audio) - 1, best_end_sample))
    best_end_last = segment(
        audio,
        best_end_sample - samples(0.004, sample_rate),
        samples(0.004, sample_rate),
    )
    best_seam_delta = float(np.abs(audio[best_end_sample] - audio[start_sample]).mean())
    best_seam_norm = best_seam_delta / max(1e-6, (rms(best_end_last) + rms(start_first)) / 2.0)

    metrics = {
        "source_file": str(audio_path),
        "decoded_duration": duration_s,
        "pre_corr": corr(start_pre, end_pre),
        "post_corr": corr(start_post, end_post),
        "pre_nrmse": nrmse(start_pre, end_pre),
        "post_nrmse": nrmse(start_post, end_post),
        "best_center_corr": best["corr"],
        "best_center_offset_ms": best["offset_s"] * 1000.0,
        "suggested_loop_end": candidate["loop_end"] + best["offset_s"],
        "best_center_nrmse": best["nrmse"],
        "seam_jump_norm": seam_norm,
        "best_seam_jump_norm": best_seam_norm,
        "tail_db_vs_body": db_ratio(rms(tail), rms(body)),
        "tail_similarity": tail_best_similarity(
            audio,
            candidate["loop_start"],
            candidate["loop_end"],
            duration_s,
            sample_rate,
        ),
    }
    metrics["classification"] = classify(metrics)

    png_name = f"{candidate['track']:03d}-{safe_name(candidate['title'])}.png"
    png_path = out_dir / png_name
    write_waveform_png(png_path, candidate, audio, duration_s, sample_rate, metrics)
    metrics["waveform_png"] = str(png_path)
    return metrics


def write_reports(rows, md_path, tsv_path):
    fields = [
        "uploaded",
        "risk",
        "order",
        "track",
        "title",
        "video_id",
        "loop_start",
        "loop_end",
        "auto_score",
        "classification",
        "pre_corr",
        "post_corr",
        "best_center_corr",
        "best_center_offset_ms",
        "suggested_loop_end",
        "seam_jump_norm",
        "best_seam_jump_norm",
        "tail_db_vs_body",
        "tail_similarity",
        "waveform_png",
    ]
    with tsv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    lines = [
        "# Spirit Tracks Waveform Loop Boundary Audit",
        "",
        "Generated from actual decoded source-audio waveforms. This is not a deletion manifest.",
        "Use these results to choose listening targets, manual loop points, or full-track rerenders.",
        "",
        "Metric notes:",
        "",
        "- `pre_corr`: waveform match for the half-second before loop start vs before loop end.",
        "- `post_corr`: waveform after loop start vs source tail after loop end; low values often mean a unique ending/coda follows the detected loop.",
        "- `best_center_corr`: best nearby start/end waveform match after searching +/-350 ms around the detected loop end.",
        "- `offset ms` and `suggested end`: refined loop-end candidate from the waveform search.",
        "- `seam` and `best seam`: normalized sample jump at the detected join and at the refined join.",
        "- `tail_db`: loudness of skipped tail relative to detected loop body.",
        "- Final delete/replace decisions still require a listening check.",
        "",
        "| Uploaded | Risk | Order | Track | Title | Video ID | Classification | Pre | Post | Best | Offset ms | Suggested End | Seam | Best Seam | Tail dB | Tail Sim | Waveform |",
        "|---|---|---:|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        png_rel = Path(row["waveform_png"]).relative_to(ROOT).as_posix()
        lines.append(
            "| {uploaded} | {risk} | {order} | {track} | {title} | {video_id} | "
            "{classification} | {pre_corr:.3f} | {post_corr:.3f} | "
            "{best_center_corr:.3f} | {best_center_offset_ms:.0f} | "
            "{suggested_loop_end:.3f} | {seam_jump_norm:.2f} | "
            "{best_seam_jump_norm:.2f} | {tail_db_vs_body:.1f} | {tail_similarity:.3f} | "
            "[PNG]({png_rel}) |".format(**row, png_rel=png_rel)
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--audio-dir", type=Path, default=DEFAULT_AUDIO_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MD)
    parser.add_argument("--tsv", type=Path, default=DEFAULT_TSV)
    parser.add_argument("--sample-rate", type=int, default=48000)
    parser.add_argument("--tracks", help="Comma-separated track numbers or ranges.")
    parser.add_argument("--uploaded-only", action="store_true")
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    wanted = parse_track_filter(args.tracks)
    candidates = parse_audit(args.audit)
    if args.uploaded_only:
        candidates = [candidate for candidate in candidates if candidate["uploaded"]]
    if wanted is not None:
        candidates = [candidate for candidate in candidates if candidate["track"] in wanted]

    rows = []
    for index, candidate in enumerate(candidates, 1):
        label = f"{candidate['track']:03d} {candidate['title']}"
        print(f"[{index}/{len(candidates)}] {label}", flush=True)
        metrics = analyze_candidate(candidate, args.audio_dir, args.out_dir, args.sample_rate)
        row = {**candidate, **metrics}
        rows.append(row)
        print(
            f"  {metrics['classification']} "
            f"pre={metrics['pre_corr']:.3f} "
            f"post={metrics['post_corr']:.3f} "
            f"best={metrics['best_center_corr']:.3f} "
            f"tail_db={metrics['tail_db_vs_body']:.1f}",
            flush=True,
        )

    write_reports(rows, args.markdown, args.tsv)
    print(f"Wrote {args.markdown}", flush=True)
    print(f"Wrote {args.tsv}", flush=True)


if __name__ == "__main__":
    main()
