#!/usr/bin/env python3
import argparse
import json
import math
import os
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import numpy as np


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


TARGET_DEFAULT = "14:29:24"


def run(cmd, *, capture=False):
    print("+ " + " ".join(str(c) for c in cmd), flush=True)
    if capture:
        return subprocess.check_output(cmd, text=True)
    subprocess.check_call(cmd)
    return ""


def parse_hms_duration(value):
    parts = value.split(":")
    if len(parts) != 3:
        raise ValueError("Duration must be HH:MM:SS")
    hours, minutes, seconds = (int(part) for part in parts)
    return hours * 3600 + minutes * 60 + seconds


def parse_target_frames(value, fps, target_format):
    parts = value.split(":")
    if len(parts) != 3:
        raise ValueError("Target must have three colon-separated fields")

    if target_format == "hms":
        seconds = parse_hms_duration(value)
        return int(round(seconds * float(fps)))

    if target_format == "mmssff":
        minutes, seconds, frames = (int(part) for part in parts)
        fps_int = int(round(float(fps)))
        if abs(float(fps) - fps_int) > 1e-6:
            raise ValueError(f"MM:SS:frames targets require integer fps, got {fps}")
        if seconds >= 60:
            raise ValueError("Seconds field must be less than 60 for MM:SS:frames")
        if frames >= fps_int:
            raise ValueError(f"Frame field must be less than fps ({fps_int})")
        return (minutes * 60 + seconds) * fps_int + frames

    raise ValueError(f"Unsupported target format: {target_format}")


def ffprobe(path):
    raw = run(
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
        capture=True,
    )
    return json.loads(raw)


def video_info(path):
    info = ffprobe(path)
    stream = next(s for s in info["streams"] if s["codec_type"] == "video")
    rate = Fraction(stream.get("avg_frame_rate") or stream["r_frame_rate"])
    if rate <= 0:
        raise RuntimeError(f"Could not read frame rate for {path}")
    return {
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "fps": rate,
    }


def audio_sample_rate(path):
    info = ffprobe(path)
    stream = next(s for s in info["streams"] if s["codec_type"] == "audio")
    return int(stream.get("sample_rate", 48000))


def count_video_packets(path):
    raw = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-count_packets",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=nb_read_packets",
            "-of",
            "json",
            str(path),
        ],
        capture=True,
    )
    info = json.loads(raw)
    return int(info["streams"][0]["nb_read_packets"])


def decode_audio_mono(path, sample_rate=11025):
    raw = subprocess.check_output(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-f",
            "f32le",
            "-",
        ]
    )
    return np.frombuffer(raw, dtype=np.float32).copy(), sample_rate


def spectral_features(audio, sr):
    frame = int(sr * 0.75)
    hop = int(sr * 0.10)
    if len(audio) < frame:
        raise RuntimeError("Audio is too short to analyze")

    window = np.hanning(frame).astype(np.float32)
    starts = np.arange(0, len(audio) - frame, hop, dtype=np.int64)
    feature_rows = []

    # 80 roughly-logarithmic bins from about 60 Hz to 5 kHz are enough to
    # identify repeated musical sections without making the matrix huge.
    freqs = np.fft.rfftfreq(frame, 1.0 / sr)
    edges = np.geomspace(60, min(5000, sr / 2), 81)
    bin_masks = [(freqs >= edges[i]) & (freqs < edges[i + 1]) for i in range(80)]

    for start in starts:
        chunk = audio[start : start + frame] * window
        mag = np.abs(np.fft.rfft(chunk))
        row = np.array(
            [float(mag[mask].mean()) if np.any(mask) else 0.0 for mask in bin_masks],
            dtype=np.float32,
        )
        row = np.log1p(row)
        norm = np.linalg.norm(row)
        if norm > 1e-8:
            row /= norm
        feature_rows.append(row)

    return np.vstack(feature_rows), hop / sr


def moving_average(values, window):
    if window <= 1:
        return values
    kernel = np.ones(window, dtype=np.float32) / window
    return np.convolve(values, kernel, mode="same")


def detect_loop_points(path):
    audio, sr = decode_audio_mono(path)
    features, step = spectral_features(audio, sr)
    n_frames = features.shape[0]
    duration = len(audio) / sr

    min_loop = max(20.0, min(45.0, duration * 0.20))
    max_loop = duration * 0.90
    min_shift = int(min_loop / step)
    max_shift = min(int(max_loop / step), n_frames - 30)
    context = max(8, int(2.0 / step))

    best = None
    best_score = -1.0

    for shift in range(min_shift, max_shift):
        sims = np.einsum("ij,ij->i", features[:-shift], features[shift:])
        if sims.shape[0] < context:
            continue
        smooth = moving_average(sims, context)
        idx = int(np.argmax(smooth))
        score = float(smooth[idx])

        # Prefer musically substantial loop bodies and avoid choosing the first
        # matching texture if a longer phrase scores almost as well.
        phrase_bonus = min(0.04, (shift * step) / 4000.0)
        if idx * step < 0.25:
            phrase_bonus += 0.01
        score_with_bonus = score + phrase_bonus

        if score_with_bonus > best_score:
            best_score = score_with_bonus
            best = (idx * step, (idx + shift) * step, score)

    if best is None:
        return 0.0, duration, 0.0

    start, end, raw_score = best
    if end <= start + 5:
        return 0.0, duration, raw_score

    # Keep the loop points on millisecond boundaries for ffmpeg filters.
    return round(start, 3), round(end, 3), raw_score


def ffmpeg_video_args(codec, cq):
    if codec == "hevc_nvenc":
        return [
            "-c:v",
            "hevc_nvenc",
            "-preset",
            "p5",
            "-tune",
            "hq",
            "-cq:v",
            str(cq),
            "-b:v",
            "0",
            "-tag:v",
            "hvc1",
        ]
    if codec == "h264_nvenc":
        return [
            "-c:v",
            "h264_nvenc",
            "-preset",
            "p5",
            "-tune",
            "hq",
            "-cq:v",
            str(cq),
            "-b:v",
            "0",
        ]
    if codec == "libx264":
        return ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(cq)]
    raise ValueError(f"Unsupported codec: {codec}")


def encode_base_video(input_path, output_path, fps, codec, cq):
    filter_graph = f"fps={float(fps):.8f},format=yuv420p"
    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-y",
            "-i",
            str(input_path),
            "-an",
            "-vf",
            filter_graph,
            *ffmpeg_video_args(codec, cq),
            str(output_path),
        ]
    )


def encode_final_video(input_path, output_path, frames, fps, fade_seconds, codec, cq):
    duration = frames / float(fps)
    fade_start = max(0.0, duration - fade_seconds)
    filter_graph = (
        f"fps={float(fps):.8f},trim=0:{duration:.9f},"
        f"setpts=PTS-STARTPTS,fade=t=out:st={fade_start:.9f}:d={fade_seconds:.9f},"
        "format=yuv420p"
    )
    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-y",
            "-stream_loop",
            "-1",
            "-i",
            str(input_path),
            "-an",
            "-vf",
            filter_graph,
            "-frames:v",
            str(frames),
            *ffmpeg_video_args(codec, cq),
            str(output_path),
        ]
    )


def write_concat_list(path, base_path, loops, final_path):
    lines = []
    base_abs = base_path.resolve().as_posix()
    final_abs = final_path.resolve().as_posix()
    for _ in range(loops):
        lines.append(f"file '{base_abs}'")
    lines.append(f"file '{final_abs}'")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def concat_video(list_path, output_path):
    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_path),
            "-c",
            "copy",
            str(output_path),
        ]
    )


def encode_looped_audio(
    input_path,
    output_path,
    target_seconds,
    fade_seconds,
    loop_start,
    loop_end,
    output_sample_rate=None,
):
    sample_rate = output_sample_rate or audio_sample_rate(input_path)
    loop_start = max(0.0, loop_start)
    loop_end = max(loop_start + 0.25, loop_end)
    loop_samples = max(1, int(round((loop_end - loop_start) * sample_rate)))
    fade_start = target_seconds - fade_seconds

    if loop_start < 0.02:
        filter_graph = (
            f"[0:a]aresample={sample_rate},atrim={loop_start:.9f}:{loop_end:.9f},"
            f"asetpts=PTS-STARTPTS,aloop=loop=-1:size={loop_samples}:start=0,"
            f"atrim=0:{target_seconds:.9f},"
            f"afade=t=out:st={fade_start:.9f}:d={fade_seconds:.9f}[a]"
        )
    else:
        filter_graph = (
            f"[0:a]aresample={sample_rate},asplit=2[a0][a1];"
            f"[a0]atrim=0:{loop_start:.9f},asetpts=PTS-STARTPTS[intro];"
            f"[a1]atrim={loop_start:.9f}:{loop_end:.9f},asetpts=PTS-STARTPTS,"
            f"aloop=loop=-1:size={loop_samples}:start=0[loop];"
            f"[intro][loop]concat=n=2:v=0:a=1,atrim=0:{target_seconds:.9f},"
            f"afade=t=out:st={fade_start:.9f}:d={fade_seconds:.9f}[a]"
        )

    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-y",
            "-i",
            str(input_path),
            "-filter_complex",
            filter_graph,
            "-map",
            "[a]",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            str(output_path),
        ]
    )


def mux(video_path, audio_path, output_path, target_seconds):
    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-y",
            "-i",
            str(video_path),
            "-i",
            str(audio_path),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c",
            "copy",
            "-t",
            f"{target_seconds:.9f}",
            str(output_path),
        ]
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--target", default=TARGET_DEFAULT)
    parser.add_argument(
        "--target-format",
        choices=["hms", "mmssff"],
        default="hms",
        help="Interpret --target as HH:MM:SS or MM:SS:frames.",
    )
    parser.add_argument("--fade", default=5.0, type=float)
    parser.add_argument("--work-dir", default=Path(".render-work"), type=Path)
    parser.add_argument("--video-codec", default="hevc_nvenc")
    parser.add_argument("--cq", default=24, type=int)
    parser.add_argument("--audio-loop", choices=["auto", "full"], default="auto")
    parser.add_argument("--loop-start", type=float)
    parser.add_argument("--loop-end", type=float)
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.work_dir.mkdir(parents=True, exist_ok=True)

    stem = args.input.stem
    work_prefix = args.work_dir / stem
    base_video = work_prefix.with_suffix(".base.mp4")
    final_video = work_prefix.with_suffix(".final-video.mp4")
    concat_list = work_prefix.with_suffix(".concat.txt")
    looped_video = work_prefix.with_suffix(".video-looped.mp4")
    looped_audio = work_prefix.with_suffix(".audio.m4a")

    info = video_info(args.input)
    fps = info["fps"]
    target_frames = parse_target_frames(args.target, fps, args.target_format)
    target_seconds = target_frames / float(fps)
    fade_frames = int(math.ceil(args.fade * float(fps)))

    if args.loop_start is not None and args.loop_end is not None:
        loop_start, loop_end, score = args.loop_start, args.loop_end, 1.0
    elif args.audio_loop == "auto":
        print("Detecting audio loop points...", flush=True)
        loop_start, loop_end, score = detect_loop_points(args.input)
    else:
        duration = float(ffprobe(args.input)["format"]["duration"])
        loop_start, loop_end, score = 0.0, duration, 0.0

    print(
        f"Audio loop: start={loop_start:.3f}s end={loop_end:.3f}s "
        f"length={loop_end - loop_start:.3f}s score={score:.4f}",
        flush=True,
    )

    if not base_video.exists():
        encode_base_video(args.input, base_video, fps, args.video_codec, args.cq)

    base_frames = count_video_packets(base_video)
    loops = target_frames // base_frames
    remainder = target_frames % base_frames
    if remainder < fade_frames:
        loops -= 1
        remainder += base_frames
    if loops < 0:
        raise RuntimeError("Source video is longer than the target duration")

    print(
        f"Video repeat plan: base_frames={base_frames} loops={loops} "
        f"final_frames={remainder} target_frames={target_frames}",
        flush=True,
    )

    encode_final_video(args.input, final_video, remainder, fps, args.fade, args.video_codec, args.cq)
    write_concat_list(concat_list, base_video, loops, final_video)
    concat_video(concat_list, looped_video)
    encode_looped_audio(
        args.input, looped_audio, target_seconds, args.fade, loop_start, loop_end
    )
    mux(looped_video, looped_audio, args.output, target_seconds)

    print(f"Wrote {args.output}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)
