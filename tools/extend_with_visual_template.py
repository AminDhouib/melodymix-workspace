#!/usr/bin/env python3
import argparse
import math
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

from extend_starfox_video import (
    TARGET_DEFAULT,
    audio_sample_rate,
    concat_video,
    count_video_packets,
    detect_loop_points,
    encode_base_video,
    encode_final_video,
    encode_looped_audio,
    ffmpeg_video_args,
    ffprobe,
    mux,
    parse_target_frames,
    run,
    video_info,
    write_concat_list,
)


def safe_name(value):
    return "".join(c if c.isalnum() or c in "._- " else "_" for c in value).strip()


def visual_cache_paths(work_dir, video_input, target):
    prefix = work_dir / safe_name(f"{video_input.stem}.{target}.visual")
    return {
        "base": prefix.with_suffix(".base.mp4"),
        "final": prefix.with_suffix(".final-video.mp4"),
        "concat": prefix.with_suffix(".concat.txt"),
        "looped": prefix.with_suffix(".video-looped.mp4"),
    }


def audio_cache_path(work_dir, audio_input, target):
    prefix = work_dir / safe_name(f"{audio_input.stem}.{target}.audio")
    return prefix.with_suffix(".m4a")


def render_visual(video_input, work_dir, target, target_format, fade, codec, cq, output_fps):
    info = video_info(video_input)
    fps = Fraction(output_fps) if output_fps else info["fps"]
    target_frames = parse_target_frames(target, fps, target_format)
    fade_frames = int(math.ceil(fade * float(fps)))
    paths = visual_cache_paths(work_dir, video_input, target)

    if paths["looped"].exists():
        return paths["looped"], target_frames, target_frames / float(fps), fps

    if not paths["base"].exists():
        encode_base_video(video_input, paths["base"], fps, codec, cq)

    base_frames = count_video_packets(paths["base"])
    loops = target_frames // base_frames
    remainder = target_frames % base_frames
    if remainder < fade_frames:
        loops -= 1
        remainder += base_frames
    if loops < 0:
        raise RuntimeError("Visual template is longer than the target duration")

    print(
        f"Visual repeat plan: base_frames={base_frames} loops={loops} "
        f"final_frames={remainder} target_frames={target_frames}",
        flush=True,
    )

    encode_final_video(video_input, paths["final"], remainder, fps, fade, codec, cq)
    write_concat_list(paths["concat"], paths["base"], loops, paths["final"])
    concat_video(paths["concat"], paths["looped"])
    return paths["looped"], target_frames, target_frames / float(fps), fps


def main():
    parser = argparse.ArgumentParser(
        description="Render an exact-length extended OST video using separate audio and visual inputs."
    )
    parser.add_argument("--audio-input", required=True, type=Path)
    parser.add_argument("--video-input", required=True, type=Path)
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
    parser.add_argument(
        "--output-fps",
        default=None,
        help="Force the rendered video frame rate, for example 30 for exact MM:SS:frames targets.",
    )
    parser.add_argument("--cq", default=24, type=int)
    parser.add_argument("--audio-loop", choices=["auto", "full"], default="auto")
    parser.add_argument("--audio-sample-rate", default=48000, type=int)
    parser.add_argument("--loop-start", type=float)
    parser.add_argument("--loop-end", type=float)
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.work_dir.mkdir(parents=True, exist_ok=True)

    visual_video, target_frames, target_seconds, fps = render_visual(
        args.video_input,
        args.work_dir,
        args.target,
        args.target_format,
        args.fade,
        args.video_codec,
        args.cq,
        args.output_fps,
    )

    if args.loop_start is not None and args.loop_end is not None:
        loop_start, loop_end, score = args.loop_start, args.loop_end, 1.0
    elif args.audio_loop == "auto":
        print("Detecting audio loop points...", flush=True)
        loop_start, loop_end, score = detect_loop_points(args.audio_input)
    else:
        duration = float(ffprobe(args.audio_input)["format"]["duration"])
        loop_start, loop_end, score = 0.0, duration, 0.0

    print(
        f"Audio loop: start={loop_start:.3f}s end={loop_end:.3f}s "
        f"length={loop_end - loop_start:.3f}s score={score:.4f}",
        flush=True,
    )

    looped_audio = audio_cache_path(args.work_dir, args.audio_input, args.target)
    encode_looped_audio(
        args.audio_input,
        looped_audio,
        target_seconds,
        args.fade,
        loop_start,
        loop_end,
        args.audio_sample_rate,
    )
    mux(visual_video, looped_audio, args.output, target_seconds)
    print(
        f"Wrote {args.output} ({target_frames} frames at {float(fps):.3f} fps)",
        flush=True,
    )


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)
