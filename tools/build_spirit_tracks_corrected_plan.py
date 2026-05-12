#!/usr/bin/env python3
import argparse
import csv
import json
import sys
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "Zelda Spirit Tracks Metadata" / "upload_manifest.json"
DEFAULT_PML = ROOT / "Zelda Spirit Tracks Metadata" / "pymusiclooper_loop_candidates.tsv"
DEFAULT_WAVEFORM = ROOT / "Zelda Spirit Tracks Metadata" / "waveform_loop_boundary_audit.tsv"
DEFAULT_MANUAL_OVERRIDES = ROOT / "Zelda Spirit Tracks Metadata" / "manual_loop_overrides.tsv"
DEFAULT_CANDIDATE_SCORES = ROOT / "Zelda Spirit Tracks Metadata" / "pymusiclooper_candidate_seam_scores.tsv"
DEFAULT_PLAN = ROOT / "Zelda Spirit Tracks Metadata" / "corrected_loop_render_plan.tsv"
DEFAULT_OUT_MANIFEST = ROOT / "Zelda Spirit Tracks Metadata" / "upload_manifest_corrected.json"
DEFAULT_OUT_TSV = ROOT / "Zelda Spirit Tracks Metadata" / "upload_manifest_corrected.tsv"
DEFAULT_OUTPUT_DIR = ROOT / "Zelda Spirit Tracks Extended Corrected"


def safe_name(value):
    return "".join(c if c.isalnum() or c in "._- '()&!," else "_" for c in value).strip()


def load_json(path):
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    tmp.replace(path)


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


def best_pml_rows(path):
    rows = {}
    for row in read_tsv(path):
        if row.get("candidate_rank") not in {"1", ""}:
            continue
        rows[int(row["track"])] = row
    return rows


def waveform_rows(path):
    return {int(row["track"]): row for row in read_tsv(path)}


def manual_override_rows(path):
    path = Path(path)
    if not path.exists():
        return {}
    return {int(row["track"]): row for row in read_tsv(path)}


def candidate_score_rows(path):
    path = Path(path)
    if not path.exists():
        return {}
    selected = {}
    for row in read_tsv(path):
        if row.get("selected") == "True":
            selected[int(row["track"])] = row
    return selected


def classify_score(score):
    if score >= 0.99:
        return "strong_pml_candidate"
    if score >= 0.90:
        return "usable_pml_candidate_review"
    if score >= 0.75:
        return "weak_pml_candidate_review"
    return "poor_pml_candidate"


def choose_mode(item, pml, waveform, min_score, manual_overrides, candidate_scores):
    track = int(item["source_track_number"])
    wave = waveform.get(track)
    pml_row = pml.get(track)
    if not wave and not pml_row:
        return {
            "loop_mode": "reuse_existing",
            "loop_start": "",
            "loop_end": "",
            "reason": "not_in_loop_audit_existing_full_track_or_unflagged",
            "pml_score": "",
            "pml_classification": "",
            "waveform_classification": "",
            "requires_rerender": "False",
        }

    score = float(pml_row.get("pml_score") or 0.0) if pml_row else 0.0
    start = pml_row.get("candidate_start", "") if pml_row else ""
    end = pml_row.get("candidate_end", "") if pml_row else ""
    pml_classification = pml_row.get("pml_classification", "") if pml_row else ""
    waveform_classification = wave.get("classification", "") if wave else ""

    override = manual_overrides.get(track)
    if override:
        return {
            "loop_mode": override.get("loop_mode") or "manual_pymusiclooper",
            "loop_start": override.get("loop_start", ""),
            "loop_end": override.get("loop_end", ""),
            "reason": override.get("reason") or "manual_loop_override",
            "pml_score": override.get("pml_score") or (f"{score:.9f}" if pml_row else ""),
            "pml_classification": override.get("pml_classification") or pml_classification,
            "waveform_classification": override.get("waveform_classification") or waveform_classification,
            "requires_rerender": override.get("requires_rerender") or "True",
        }

    scored_row = candidate_scores.get(track)
    if scored_row:
        score = float(scored_row.get("pml_score") or 0.0)
        start = scored_row.get("candidate_start", "")
        end = scored_row.get("candidate_end", "")
        pml_classification = (
            scored_row.get("pml_classification")
            or (pml_row.get("pml_classification", "") if pml_row else "")
            or classify_score(score)
        )
        reason = f"pymusiclooper_rank{scored_row.get('candidate_rank')}_selected_by_seam_score"
    else:
        reason = "pymusiclooper_candidate_selected_waveform_listening_still_recommended"

    if (pml_row or scored_row) and score >= min_score and start and end:
        return {
            "loop_mode": "manual_pymusiclooper",
            "loop_start": start,
            "loop_end": end,
            "reason": reason,
            "pml_score": f"{score:.9f}",
            "pml_classification": pml_classification,
            "waveform_classification": waveform_classification,
            "requires_rerender": "True",
        }

    return {
        "loop_mode": "full_track",
        "loop_start": "",
        "loop_end": "",
        "reason": "weak_or_missing_pymusiclooper_candidate_use_full_track_repeat",
        "pml_score": f"{score:.9f}" if pml_row else "",
        "pml_classification": pml_classification,
        "waveform_classification": waveform_classification,
        "requires_rerender": "True",
    }


def corrected_output_path(output_dir, item):
    track = int(item["source_track_number"])
    title_name = safe_name(item["source_title"])
    return output_dir / f"{track:03d} - {title_name} - Spirit Tracks OST [14-29-24 timecode].mp4"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--pymusiclooper", type=Path, default=DEFAULT_PML)
    parser.add_argument("--waveform", type=Path, default=DEFAULT_WAVEFORM)
    parser.add_argument("--manual-overrides", type=Path, default=DEFAULT_MANUAL_OVERRIDES)
    parser.add_argument("--candidate-scores", type=Path, default=DEFAULT_CANDIDATE_SCORES)
    parser.add_argument(
        "--use-candidate-scores",
        action="store_true",
        help="Use selected rows from the candidate seam score TSV. Manual overrides are always used.",
    )
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--out-manifest", type=Path, default=DEFAULT_OUT_MANIFEST)
    parser.add_argument("--out-tsv", type=Path, default=DEFAULT_OUT_TSV)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--min-score", type=float, default=0.90)
    args = parser.parse_args()

    manifest = load_json(args.manifest)
    pml = best_pml_rows(args.pymusiclooper)
    waveform = waveform_rows(args.waveform)
    manual_overrides = manual_override_rows(args.manual_overrides)
    candidate_scores = candidate_score_rows(args.candidate_scores) if args.use_candidate_scores else {}

    corrected = dict(manifest)
    corrected["items"] = []
    corrected["render_plan"] = {
        "source": "pymusiclooper_candidate_pass",
        "min_pymusiclooper_score": args.min_score,
        "corrected_output_dir": str(args.output_dir),
        "manual_overrides": str(args.manual_overrides),
        "candidate_seam_scores": str(args.candidate_scores) if args.use_candidate_scores else "",
        "use_candidate_seam_scores": args.use_candidate_scores,
        "rule": "manual overrides first; then optionally seam-scored PyMusicLooper candidates at or above min score; then rank-1 PyMusicLooper candidates; full-track repeat for weak or missing candidates; existing unflagged renders reused",
    }

    plan_rows = []
    upload_rows = []
    for item in manifest["items"]:
        item = dict(item)
        track = int(item["source_track_number"])
        decision = choose_mode(item, pml, waveform, args.min_score, manual_overrides, candidate_scores)
        if decision["requires_rerender"] == "True":
            output = corrected_output_path(args.output_dir, item)
            item["file"] = str(output)
        else:
            output = Path(item["file"])
        item["loop_render_mode"] = decision["loop_mode"]
        item["loop_render_reason"] = decision["reason"]
        if decision["loop_start"]:
            item["loop_start"] = float(decision["loop_start"])
            item["loop_end"] = float(decision["loop_end"])
        corrected["items"].append(item)
        plan_rows.append(
            {
                "order": item["upload_order"],
                "track": track,
                "title": item["source_title"],
                "loop_mode": decision["loop_mode"],
                "loop_start": decision["loop_start"],
                "loop_end": decision["loop_end"],
                "pml_score": decision["pml_score"],
                "pml_classification": decision["pml_classification"],
                "waveform_classification": decision["waveform_classification"],
                "requires_rerender": decision["requires_rerender"],
                "source_file": manifest["items"][int(item["upload_order"]) - 1]["file"],
                "output_file": str(output),
                "reason": decision["reason"],
            }
        )
        upload_rows.append(
            {
                "order": item["upload_order"],
                "offset_hours": item["schedule_offset_hours"],
                "track": track,
                "file": item["file"],
                "title": item["title"],
                "loop_mode": decision["loop_mode"],
            }
        )

    write_tsv(
        args.plan,
        plan_rows,
        [
            "order",
            "track",
            "title",
            "loop_mode",
            "loop_start",
            "loop_end",
            "pml_score",
            "pml_classification",
            "waveform_classification",
            "requires_rerender",
            "source_file",
            "output_file",
            "reason",
        ],
    )
    write_tsv(args.out_tsv, upload_rows, ["order", "offset_hours", "track", "file", "title", "loop_mode"])
    save_json(args.out_manifest, corrected)

    counts = {}
    for row in plan_rows:
        counts[row["loop_mode"]] = counts.get(row["loop_mode"], 0) + 1
    print(f"Wrote {args.plan}")
    print(f"Wrote {args.out_manifest}")
    print(f"Wrote {args.out_tsv}")
    for key in sorted(counts):
        print(f"{key}: {counts[key]}")


if __name__ == "__main__":
    main()
