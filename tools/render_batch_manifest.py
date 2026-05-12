#!/usr/bin/env python3
import argparse
import csv
import subprocess
import sys
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "manifests" / "render_manifest.tsv"
DEFAULT_WORK_DIR = ROOT / ".render-work" / "batch"
DEFAULT_LOG_DIR = ROOT / "render-logs" / "batch"


def read_tsv(path):
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def truthy(value):
    return str(value or "").strip().lower() not in {"", "0", "false", "no", "n", "skip"}


def resolve_path(value):
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    return path


def parse_only(value):
    if not value:
        return None
    return {part.strip() for part in value.split(",") if part.strip()}


def row_id(row, index):
    return str(row.get("id") or row.get("order") or index).strip()


def row_value(row, key, default):
    value = str(row.get(key) or "").strip()
    return value if value else default


def build_command(row, args):
    audio = resolve_path(row["audio"])
    visual = resolve_path(row["visual"])
    output = resolve_path(row["output"])
    output.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        str(ROOT / "tools" / "extend_with_visual_template.py"),
        "--audio-input",
        str(audio),
        "--video-input",
        str(visual),
        "--output",
        str(output),
        "--target",
        row_value(row, "target", args.target),
        "--target-format",
        row_value(row, "target_format", args.target_format),
        "--fade",
        row_value(row, "fade", str(args.fade)),
        "--output-fps",
        row_value(row, "output_fps", str(args.output_fps)),
        "--audio-sample-rate",
        row_value(row, "audio_sample_rate", str(args.audio_sample_rate)),
        "--video-codec",
        row_value(row, "video_codec", args.video_codec),
        "--cq",
        row_value(row, "cq", str(args.cq)),
        "--work-dir",
        str(args.work_dir),
    ]

    loop_mode = row_value(row, "loop_mode", "auto").lower()
    if loop_mode == "manual":
        loop_start = row_value(row, "loop_start", "")
        loop_end = row_value(row, "loop_end", "")
        if not loop_start or not loop_end:
            raise ValueError(f"Manual loop row needs loop_start and loop_end: {row}")
        cmd.extend(["--loop-start", loop_start, "--loop-end", loop_end])
    elif loop_mode in {"auto", "full"}:
        cmd.extend(["--audio-loop", loop_mode])
    else:
        raise ValueError(f"Unsupported loop_mode {loop_mode!r}; use auto, full, or manual")
    return cmd, output


def run_logged(cmd, log_path):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        log.write("+ " + " ".join(str(part) for part in cmd) + "\n")
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR)
    parser.add_argument("--target", default="14:29:24")
    parser.add_argument("--target-format", default="mmssff")
    parser.add_argument("--fade", type=float, default=5.0)
    parser.add_argument("--output-fps", type=int, default=30)
    parser.add_argument("--audio-sample-rate", type=int, default=48000)
    parser.add_argument("--video-codec", default="hevc_nvenc")
    parser.add_argument("--cq", type=int, default=24)
    parser.add_argument("--only", help="Comma-separated manifest ids to render.")
    parser.add_argument("--skip-existing", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()

    wanted = parse_only(args.only)
    rows = []
    for index, row in enumerate(read_tsv(args.manifest), 1):
        current_id = row_id(row, index)
        if not truthy(row.get("enabled", "yes")):
            continue
        if wanted and current_id not in wanted:
            continue
        rows.append((index, current_id, row))

    print(f"Rows queued: {len(rows)}", flush=True)
    for position, (index, current_id, row) in enumerate(rows, 1):
        cmd, output = build_command(row, args)
        label = row.get("title") or row.get("output") or current_id
        print(f"[{position}/{len(rows)}] {current_id} {label}", flush=True)
        if output.exists() and args.skip_existing:
            print(f"  skipped existing: {output}", flush=True)
            continue
        log_path = args.log_dir / f"{current_id}.log"
        code = run_logged(cmd, log_path)
        if code != 0:
            raise RuntimeError(f"Render failed for {current_id}; see {log_path}")
        print(f"  rendered: {output}", flush=True)


if __name__ == "__main__":
    main()
