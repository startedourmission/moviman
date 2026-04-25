#!/usr/bin/env python3
import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


TIME_RE = re.compile(r"silence_(start|end):\s*([0-9.]+)")


def run(cmd, *, capture=False):
    kwargs = {
        "text": True,
        "check": False,
    }
    if capture:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
    print("+ " + " ".join(str(part) for part in cmd))
    result = subprocess.run(cmd, **kwargs)
    if result.returncode != 0:
        if capture and result.stderr:
            print(result.stderr, file=sys.stderr)
        raise SystemExit(result.returncode)
    return result


def require_tool(name):
    if shutil.which(name) is None:
        raise SystemExit(f"Missing required tool: {name}. Install it first.")


def ffprobe_duration(path):
    result = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture=True,
    )
    return float(result.stdout.strip())


def detect_silences(audio_path, threshold, min_silence):
    result = run(
        [
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(audio_path),
            "-af",
            f"silencedetect=n={threshold}:d={min_silence}",
            "-f",
            "null",
            "-",
        ],
        capture=True,
    )

    silences = []
    current_start = None
    for line in result.stderr.splitlines():
        match = TIME_RE.search(line)
        if not match:
            continue
        kind, value = match.group(1), float(match.group(2))
        if kind == "start":
            current_start = value
        elif kind == "end" and current_start is not None:
            silences.append((current_start, value))
            current_start = None
    return silences


def invert_silences(silences, start_time, end_time, padding, min_keep):
    keep = []
    cursor = start_time
    for start, end in silences:
        if end <= start_time or start >= end_time:
            continue
        start = max(start, start_time)
        end = min(end, end_time)
        keep_start = cursor
        keep_end = max(cursor, start + padding)
        if keep_end - keep_start >= min_keep:
            keep.append((keep_start, keep_end))
        cursor = max(cursor, end - padding)

    if end_time - cursor >= min_keep:
        keep.append((cursor, end_time))

    return merge_segments(keep)


def merge_segments(segments):
    if not segments:
        return []
    merged = [segments[0]]
    for start, end in segments[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def build_filter(segments, audio_offset):
    pieces = []
    concat_inputs = []

    for index, (start, end) in enumerate(segments):
        audio_start = max(0.0, start - audio_offset)
        audio_end = max(audio_start, end - audio_offset)
        pieces.append(
            f"[0:v]trim=start={start:.6f}:end={end:.6f},"
            f"setpts=PTS-STARTPTS[v{index}]"
        )
        pieces.append(
            f"[1:a]atrim=start={audio_start:.6f}:end={audio_end:.6f},"
            f"asetpts=PTS-STARTPTS[a{index}]"
        )
        concat_inputs.append(f"[v{index}][a{index}]")

    pieces.append(
        "".join(concat_inputs)
        + f"concat=n={len(segments)}:v=1:a=1[outv][outa]"
    )
    return ";".join(pieces)


def render_video(video_path, audio_path, output_path, segments, audio_offset):
    if not segments:
        raise SystemExit("No kept segments were detected. Try a less aggressive silence threshold.")

    filter_complex = build_filter(segments, audio_offset)
    run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-i",
            str(video_path),
            "-i",
            str(audio_path),
            "-filter_complex",
            filter_complex,
            "-map",
            "[outv]",
            "-map",
            "[outa]",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )


def srt_timestamp(seconds):
    seconds = max(0.0, seconds)
    millis = int(round(seconds * 1000))
    hours, rem = divmod(millis, 3600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{ms:03}"


def write_srt(segments, path):
    lines = []
    for index, segment in enumerate(segments, start=1):
        start = srt_timestamp(segment["start"])
        end = srt_timestamp(segment["end"])
        text = segment["text"].strip()
        if not text:
            continue
        lines.extend([str(index), f"{start} --> {end}", text, ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def generate_captions_faster_whisper(video_path, srt_path, language, model_size):
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise SystemExit(
            "faster-whisper is not installed. Run: pip install -r requirements.txt"
        ) from exc

    model = WhisperModel(model_size, device="auto", compute_type="auto")
    segments, _ = model.transcribe(str(video_path), language=language, vad_filter=True)
    write_srt(
        [
            {"start": item.start, "end": item.end, "text": item.text}
            for item in segments
        ],
        srt_path,
    )


def generate_captions_whisper_cli(video_path, srt_path, language):
    require_tool("whisper")
    out_dir = srt_path.parent
    run(
        [
            "whisper",
            str(video_path),
            "--language",
            language,
            "--output_format",
            "srt",
            "--output_dir",
            str(out_dir),
        ]
    )
    generated = out_dir / f"{video_path.stem}.srt"
    if generated != srt_path:
        generated.replace(srt_path)


def process(args):
    require_tool("ffmpeg")
    require_tool("ffprobe")

    video_path = Path(args.video).expanduser().resolve()
    audio_path = Path(args.audio).expanduser().resolve()
    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if not video_path.exists():
        raise SystemExit(f"Video not found: {video_path}")
    if not audio_path.exists():
        raise SystemExit(f"Audio not found: {audio_path}")

    video_duration = ffprobe_duration(video_path)
    audio_duration = ffprobe_duration(audio_path)
    start_time = max(0.0, args.audio_offset)
    end_time = min(video_duration, audio_duration + args.audio_offset)
    if not math.isfinite(end_time) or end_time <= start_time:
        raise SystemExit("Could not determine a valid media duration.")

    silences = detect_silences(audio_path, args.silence_threshold, args.min_silence)
    timeline_silences = [
        (start + args.audio_offset, end + args.audio_offset)
        for start, end in silences
    ]
    segments = invert_silences(
        timeline_silences,
        start_time,
        end_time,
        args.padding,
        args.min_keep,
    )

    segments_json = out_dir / "segments.json"
    segments_json.write_text(
        json.dumps(
            {
                "video": str(video_path),
                "audio": str(audio_path),
                "silences": silences,
                "timeline_silences": timeline_silences,
                "kept_segments": segments,
                "settings": {
                    "silence_threshold": args.silence_threshold,
                    "min_silence": args.min_silence,
                    "padding": args.padding,
                    "min_keep": args.min_keep,
                    "audio_offset": args.audio_offset,
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    edited_path = out_dir / args.output_name
    render_video(video_path, audio_path, edited_path, segments, args.audio_offset)

    if args.captions == "faster-whisper":
        generate_captions_faster_whisper(
            edited_path,
            out_dir / "edited.srt",
            args.language,
            args.whisper_model,
        )
    elif args.captions == "whisper-cli":
        generate_captions_whisper_cli(edited_path, out_dir / "edited.srt", args.language)

    print(f"Done: {edited_path}")
    print(f"Edit decision list: {segments_json}")


def normalize_argv(argv):
    normalized = []
    index = 0
    value_options = {"--silence-threshold"}
    while index < len(argv):
        item = argv[index]
        if item in value_options and index + 1 < len(argv):
            normalized.append(f"{item}={argv[index + 1]}")
            index += 2
            continue
        normalized.append(item)
        index += 1
    return normalized


def parse_args(argv=None):
    argv = normalize_argv(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        description="Cut silent sections from a phone video using separate recorded audio."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    process_parser = subparsers.add_parser("process")
    process_parser.add_argument("--video", required=True)
    process_parser.add_argument("--audio", required=True)
    process_parser.add_argument("--out", default="./output")
    process_parser.add_argument("--output-name", default="edited.mp4")
    process_parser.add_argument("--silence-threshold", default="-36dB")
    process_parser.add_argument("--min-silence", type=float, default=0.5)
    process_parser.add_argument("--padding", type=float, default=0.14)
    process_parser.add_argument("--min-keep", type=float, default=0.2)
    process_parser.add_argument("--audio-offset", type=float, default=0.0)
    process_parser.add_argument(
        "--captions",
        choices=["none", "faster-whisper", "whisper-cli"],
        default="none",
    )
    process_parser.add_argument("--language", default="ko")
    process_parser.add_argument("--whisper-model", default="small")
    process_parser.set_defaults(func=process)

    return parser.parse_args(argv)


def main():
    args = parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
