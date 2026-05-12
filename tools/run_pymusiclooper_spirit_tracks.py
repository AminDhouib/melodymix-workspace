#!/usr/bin/env python3
import argparse
import csv
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WAVEFORM_TSV = ROOT / "Zelda Spirit Tracks Metadata" / "waveform_loop_boundary_audit.tsv"
DEFAULT_AUDIO_DIR = ROOT / "Zelda Spirit Tracks Source Audio"
DEFAULT_CACHE_DIR = ROOT / ".render-work" / "pymusiclooper-cache"
DEFAULT_OUT_TSV = ROOT / "Zelda Spirit Tracks Metadata" / "pymusiclooper_loop_candidates.tsv"
DEFAULT_OUT_MD = ROOT / "Zelda Spirit Tracks Metadata" / "pymusiclooper_loop_candidates.md"


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


def read_waveform_rows(path):
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def find_audio(audio_dir, track):
    matches = sorted(audio_dir.glob(f"{int(track):03d} -*"))
    if not matches:
        raise FileNotFoundError(f"No source audio found for track {int(track):03d}")
    return matches[0]


def ensure_wav_cache(source_audio, cache_dir, track, sample_rate):
    cache_dir.mkdir(parents=True, exist_ok=True)
    wav_path = cache_dir / f"{int(track):03d}.wav"
    if wav_path.exists() and wav_path.stat().st_mtime >= source_audio.stat().st_mtime:
        return wav_path
    command = [
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-i",
        str(source_audio),
        "-vn",
        "-ac",
        "2",
        "-ar",
        str(sample_rate),
        "-c:a",
        "pcm_s16le",
        str(wav_path),
    ]
    subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return wav_path


def run_pymusiclooper(row, audio_dir, cache_dir, top, timeout, brute_force, approx, python_version, min_loop_duration, sample_rate):
    track = int(row["track"])
    audio = find_audio(audio_dir, track)
    wav_audio = ensure_wav_cache(audio, cache_dir, track, sample_rate)
    command = [
        "uvx",
        "--python",
        python_version,
        "--from",
        "pymusiclooper",
        "pymusiclooper",
        "export-points",
        "--path",
        str(wav_audio),
        "--fmt",
        "seconds",
        "--alt-export-top",
        str(top),
    ]
    if min_loop_duration is not None:
        command.extend(["--min-loop-duration", str(min_loop_duration)])
    if brute_force:
        command.append("--brute-force")
    if approx:
        command.extend(["--approx-loop-position", row["loop_start"], row["loop_end"]])

    proc = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    candidates = []
    for line in proc.stdout.splitlines():
        parts = line.strip().split()
        if len(parts) != 5:
            continue
        try:
            start, end, note_diff, loudness_diff, score = (float(item) for item in parts)
        except ValueError:
            continue
        candidates.append(
            {
                "candidate_start": start,
                "candidate_end": end,
                "candidate_length": end - start,
                "pml_note_difference": note_diff,
                "pml_loudness_difference": loudness_diff,
                "pml_score": score,
            }
        )
    return {
        "row": row,
        "audio": audio,
        "wav_audio": wav_audio,
        "returncode": proc.returncode,
        "stderr_tail": "\n".join(proc.stderr.splitlines()[-6:]),
        "candidates": candidates,
    }


def classify_pml_candidate(candidate_count, best_score):
    if candidate_count <= 0:
        return "no_pml_candidates"
    if best_score >= 0.99:
        return "strong_pml_candidate"
    if best_score >= 0.90:
        return "usable_pml_candidate_review"
    if best_score >= 0.75:
        return "weak_pml_candidate_review"
    return "poor_pml_candidate"


def write_reports(results, out_tsv, out_md, args):
    flat_rows = []
    summary_rows = []
    for result in results:
        source = result["row"]
        candidates = result["candidates"]
        best = candidates[0] if candidates else None
        best_score = best["pml_score"] if best else 0.0
        pml_classification = classify_pml_candidate(len(candidates), best_score)
        summary_rows.append(
            {
                "uploaded": source["uploaded"],
                "order": source["order"],
                "track": source["track"],
                "title": source["title"],
                "waveform_classification": source["classification"],
                "pml_classification": pml_classification,
                "candidate_count": len(candidates),
                "best_start": "" if best is None else best["candidate_start"],
                "best_end": "" if best is None else best["candidate_end"],
                "best_length": "" if best is None else best["candidate_length"],
                "best_score": "" if best is None else best["pml_score"],
                "audio": str(result["audio"]),
                "wav_audio": str(result["wav_audio"]),
                "returncode": result["returncode"],
                "stderr_tail": result["stderr_tail"],
            }
        )
        if not candidates:
            flat_rows.append(
                {
                    **source,
                    "candidate_rank": "",
                    "candidate_start": "",
                    "candidate_end": "",
                    "candidate_length": "",
                    "pml_note_difference": "",
                    "pml_loudness_difference": "",
                    "pml_score": "",
                    "pml_classification": pml_classification,
                    "pml_returncode": result["returncode"],
                    "pml_stderr_tail": result["stderr_tail"],
                }
            )
            continue
        for rank, candidate in enumerate(candidates, 1):
            flat_rows.append(
                {
                    **source,
                    **candidate,
                    "candidate_rank": rank,
                    "pml_classification": pml_classification if rank == 1 else "",
                    "pml_returncode": result["returncode"],
                    "pml_stderr_tail": result["stderr_tail"] if rank == 1 else "",
                }
            )

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
        "pml_returncode",
        "pml_stderr_tail",
    ]
    with out_tsv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(flat_rows)

    counts = {}
    uploaded_counts = {}
    for item in summary_rows:
        counts[item["pml_classification"]] = counts.get(item["pml_classification"], 0) + 1
        if item["uploaded"] == "True":
            uploaded_counts[item["pml_classification"]] = uploaded_counts.get(item["pml_classification"], 0) + 1

    lines = [
        "# Spirit Tracks PyMusicLooper Candidate Pass",
        "",
        "Generated from MP3/YouTube-derived local source audio using PyMusicLooper as a candidate generator.",
        "This report does not authorize deletion or replacement by itself; waveform review and listening remain required.",
        "",
        f"Run settings: `uvx --python {args.python_version} --from pymusiclooper`, WAV cache `{args.cache_dir}`, top `{args.top}`, minimum loop duration `{args.min_loop_duration}` seconds.",
        "",
        "Classification guide:",
        "",
        "- `strong_pml_candidate`: best PyMusicLooper score >= 0.99.",
        "- `usable_pml_candidate_review`: score >= 0.90.",
        "- `weak_pml_candidate_review`: score >= 0.75.",
        "- `poor_pml_candidate`: score below 0.75.",
        "- `no_pml_candidates`: PyMusicLooper did not return loop points.",
        "",
        "## Counts",
        "",
        "| Scope | Classification | Count |",
        "|---|---|---:|",
    ]
    for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| All | {name} | {count} |")
    for name, count in sorted(uploaded_counts.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| Uploaded | {name} | {count} |")

    lines.extend(
        [
            "",
            "## Best Candidate Per Track",
            "",
            "| Uploaded | Order | Track | Title | Waveform Class | PML Class | Best Start | Best End | Best Len | Score |",
            "|---|---:|---:|---|---|---|---:|---:|---:|---:|",
        ]
    )
    for item in summary_rows:
        score = item["best_score"]
        lines.append(
            "| {uploaded} | {order} | {track} | {title} | {waveform_classification} | "
            "{pml_classification} | {best_start} | {best_end} | {best_length} | {score} |".format(
                **item,
                score="" if score == "" else f"{float(score):.6f}",
            )
        )
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--waveform-tsv", type=Path, default=DEFAULT_WAVEFORM_TSV)
    parser.add_argument("--audio-dir", type=Path, default=DEFAULT_AUDIO_DIR)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--out-tsv", type=Path, default=DEFAULT_OUT_TSV)
    parser.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--python-version", default="3.11")
    parser.add_argument("--min-loop-duration", type=float, default=10.0)
    parser.add_argument("--sample-rate", type=int, default=48000)
    parser.add_argument("--tracks")
    parser.add_argument("--uploaded-only", action="store_true")
    parser.add_argument("--brute-force", action="store_true")
    parser.add_argument("--approx-existing-loop", action="store_true")
    args = parser.parse_args()

    rows = read_waveform_rows(args.waveform_tsv)
    wanted = parse_track_filter(args.tracks)
    if wanted is not None:
        rows = [row for row in rows if int(row["track"]) in wanted]
    if args.uploaded_only:
        rows = [row for row in rows if row["uploaded"] == "True"]

    print(f"Tracks queued: {len(rows)}", flush=True)
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                run_pymusiclooper,
                row,
                args.audio_dir,
                args.cache_dir,
                args.top,
                args.timeout,
                args.brute_force,
                args.approx_existing_loop,
                args.python_version,
                args.min_loop_duration,
                args.sample_rate,
            ): row
            for row in rows
        }
        for index, future in enumerate(as_completed(futures), 1):
            row = futures[future]
            label = f"{int(row['track']):03d} {row['title']}"
            try:
                result = future.result()
            except Exception as exc:
                result = {
                    "row": row,
                    "audio": "",
                    "wav_audio": "",
                    "returncode": -1,
                    "stderr_tail": repr(exc),
                    "candidates": [],
                }
            candidates = result["candidates"]
            best = candidates[0]["pml_score"] if candidates else 0.0
            print(
                f"[{index}/{len(rows)}] {label}: "
                f"{len(candidates)} candidates best={best:.6f}",
                flush=True,
            )
            results.append(result)

    results.sort(key=lambda item: (int(item["row"]["order"]), int(item["row"]["track"])))
    write_reports(results, args.out_tsv, args.out_md, args)
    print(f"Wrote {args.out_tsv}", flush=True)
    print(f"Wrote {args.out_md}", flush=True)


if __name__ == "__main__":
    main()
