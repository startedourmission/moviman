#!/usr/bin/env python3
import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path


TIME_RE = re.compile(r"silence_(start|end):\s*([0-9.]+)")
EXTRA_TOOL_PATHS = (
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "/usr/bin",
    "/bin",
)


def extend_tool_path():
    existing = os.environ.get("PATH", "")
    parts = [path for path in existing.split(os.pathsep) if path]
    for path in EXTRA_TOOL_PATHS:
        if path not in parts:
            parts.append(path)
    os.environ["PATH"] = os.pathsep.join(parts)


def write_progress(percent, stage):
    progress_path = os.environ.get("MOVIMAN_PROGRESS_FILE")
    if not progress_path:
        return
    path = Path(progress_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(
            {
                "percent": max(0, min(100, int(percent))),
                "stage": stage,
                "updated_at": time.time(),
            }
        ),
        encoding="utf-8",
    )
    tmp_path.replace(path)


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


def build_filter(segments, audio_offset, external_audio):
    pieces = []
    concat_inputs = []
    audio_input = "1:a" if external_audio else "0:a"

    for index, (start, end) in enumerate(segments):
        audio_start = max(0.0, start - audio_offset)
        audio_end = max(audio_start, end - audio_offset)
        pieces.append(
            f"[0:v]trim=start={start:.6f}:end={end:.6f},"
            f"setpts=PTS-STARTPTS[v{index}]"
        )
        pieces.append(
            f"[{audio_input}]atrim=start={audio_start:.6f}:end={audio_end:.6f},"
            f"asetpts=PTS-STARTPTS[a{index}]"
        )
        concat_inputs.append(f"[v{index}][a{index}]")

    pieces.append(
        "".join(concat_inputs)
        + f"concat=n={len(segments)}:v=1:a=1[outv][outa]"
    )
    return ";".join(pieces)


def is_full_length_segment(segments, start_time, end_time):
    if len(segments) != 1:
        return False
    start, end = segments[0]
    return abs(start - start_time) < 0.01 and abs(end - end_time) < 0.01


def video_encode_args(mode):
    if mode == "quality":
        return ["-c:v", "libx264", "-preset", "medium", "-crf", "18"]
    if mode == "fastest":
        return ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "28"]
    if mode == "hardware":
        return ["-c:v", "h264_videotoolbox", "-b:v", "6000k", "-allow_sw", "1"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23"]


def copy_full_video(video_path, output_path):
    run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-i",
            str(video_path),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )


def render_video(video_path, audio_path, output_path, segments, audio_offset, encode_mode):
    external_audio = audio_path is not None
    filter_complex = build_filter(segments, audio_offset, external_audio)
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-i",
        str(video_path),
    ]
    if external_audio:
        cmd.extend(["-i", str(audio_path)])
    cmd.extend(
        [
            "-filter_complex",
            filter_complex,
            "-map",
            "[outv]",
            "-map",
            "[outa]",
            *video_encode_args(encode_mode),
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )
    run(cmd)


def cut_segments_from_keep(keep_segments, start_time, end_time):
    cuts = []
    cursor = start_time
    for start, end in keep_segments:
        if start > cursor:
            cuts.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < end_time:
        cuts.append((cursor, end_time))
    return cuts


def keep_segments_from_cuts(cuts, start_time, end_time, padding, min_keep):
    normalized = []
    for cut in cuts:
        if not cut.get("enabled", True):
            continue
        start = max(start_time, float(cut["start"]) - padding)
        end = min(end_time, float(cut["end"]) + padding)
        if end > start:
            normalized.append((start, end))
    normalized = merge_segments(sorted(normalized))

    keep = []
    cursor = start_time
    for start, end in normalized:
        if start - cursor >= min_keep:
            keep.append((cursor, start))
        cursor = max(cursor, end)
    if end_time - cursor >= min_keep:
        keep.append((cursor, end_time))
    return keep


def analyze_media(args):
    write_progress(3, "Preparing analysis")
    require_tool("ffmpeg")
    require_tool("ffprobe")

    video_path = Path(args.video).expanduser().resolve()
    audio_path = Path(args.audio).expanduser().resolve() if args.audio else None
    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if not video_path.exists():
        raise SystemExit(f"Video not found: {video_path}")
    if audio_path is not None and not audio_path.exists():
        raise SystemExit(f"Audio not found: {audio_path}")

    write_progress(10, "Reading media duration")
    video_duration = ffprobe_duration(video_path)
    if audio_path is None:
        source_audio_path = video_path
        audio_offset = 0.0
        start_time = 0.0
        end_time = video_duration
    else:
        source_audio_path = audio_path
        audio_offset = args.audio_offset
        audio_duration = ffprobe_duration(audio_path)
        start_time = max(0.0, audio_offset)
        end_time = min(video_duration, audio_duration + audio_offset)
    if not math.isfinite(end_time) or end_time <= start_time:
        raise SystemExit("Could not determine a valid media duration.")

    write_progress(30, "Detecting silence")
    silences = detect_silences(source_audio_path, args.silence_threshold, args.min_silence)
    timeline_silences = [
        (start + audio_offset, end + audio_offset)
        for start, end in silences
    ]
    keep_segments = invert_silences(
        timeline_silences,
        start_time,
        end_time,
        args.padding,
        args.min_keep,
    )
    fallback_reason = None
    if not keep_segments:
        fallback_reason = (
            "Silence detection marked the whole source as silent; "
            "no cut candidates were enabled."
        )
        keep_segments = [(start_time, end_time)]
        cut_segments = []
    else:
        cut_segments = cut_segments_from_keep(keep_segments, start_time, end_time)

    analysis = {
        "version": 1,
        "video": str(video_path),
        "audio": str(audio_path) if audio_path is not None else None,
        "audio_source": "external" if audio_path is not None else "video",
        "duration": video_duration,
        "start_time": start_time,
        "end_time": end_time,
        "silences": silences,
        "timeline_silences": timeline_silences,
        "keep_segments": keep_segments,
        "fallback_reason": fallback_reason,
        "settings": {
            "silence_threshold": args.silence_threshold,
            "min_silence": args.min_silence,
            "padding": args.padding,
            "min_keep": args.min_keep,
            "audio_offset": audio_offset,
            "encode_mode": args.encode_mode,
            "captions": args.captions,
            "language": args.language,
            "whisper_model": args.whisper_model,
        },
        "cuts": [
            {
                "id": f"cut_{index:04d}",
                "start": start,
                "end": end,
                "enabled": True,
                "reason": "silence",
            }
            for index, (start, end) in enumerate(cut_segments, start=1)
        ],
    }
    analysis_path = out_dir / "analysis.json"
    analysis_path.write_text(json.dumps(analysis, indent=2), encoding="utf-8")
    write_progress(100, "Analysis ready")
    print(f"Analysis: {analysis_path}")


def render_from_analysis(args):
    write_progress(3, "Preparing render")
    analysis_path = Path(args.analysis).expanduser().resolve()
    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))

    video_path = Path(analysis["video"]).resolve()
    audio_path = Path(analysis["audio"]).resolve() if analysis.get("audio") else None
    settings = analysis.get("settings", {})
    start_time = float(analysis.get("start_time", 0.0))
    end_time = float(analysis.get("end_time", analysis["duration"]))
    min_keep = float(settings.get("min_keep", 0.2))
    audio_offset = float(settings.get("audio_offset", 0.0))
    encode_mode = args.encode_mode or settings.get("encode_mode", "fast")
    captions = args.captions or settings.get("captions", "none")
    language = args.language or settings.get("language", "ko")
    whisper_model = args.whisper_model or settings.get("whisper_model", "small")

    segments = keep_segments_from_cuts(
        analysis.get("cuts", []),
        start_time,
        end_time,
        0.0,
        min_keep,
    )
    if not segments:
        segments = [(start_time, end_time)]

    segments_json = out_dir / "segments.json"
    segments_json.write_text(
        json.dumps(
            {
                **analysis,
                "kept_segments": segments,
                "settings": {
                    **settings,
                    "encode_mode": encode_mode,
                    "captions": captions,
                    "language": language,
                    "whisper_model": whisper_model,
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    edited_path = out_dir / args.output_name
    can_copy = (
        audio_path is None
        and audio_offset == 0
        and is_full_length_segment(segments, start_time, end_time)
    )
    if can_copy:
        write_progress(70, "Copying media without re-encoding")
        copy_full_video(video_path, edited_path)
    else:
        write_progress(38, f"Rendering edited video ({encode_mode})")
        render_video(video_path, audio_path, edited_path, segments, audio_offset, encode_mode)

    if captions == "faster-whisper":
        write_progress(88, "Generating captions")
        generate_captions_faster_whisper(
            edited_path,
            out_dir / "edited.srt",
            language,
            whisper_model,
        )
    elif captions == "whisper-cli":
        write_progress(88, "Generating captions")
        generate_captions_whisper_cli(edited_path, out_dir / "edited.srt", language)

    write_progress(100, "Done")
    print(f"Done: {edited_path}")
    print(f"Edit decision list: {segments_json}")


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
            "faster-whisper is not installed. Run: uv sync --extra captions"
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


def extract_audio_file(video_path, output_path, audio_format):
    require_tool("ffmpeg")

    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-i",
        str(video_path),
        "-vn",
    ]
    if audio_format == "wav":
        cmd.extend(["-acodec", "pcm_s16le", "-ar", "48000", "-ac", "2"])
    elif audio_format == "m4a":
        cmd.extend(["-c:a", "aac", "-b:a", "192k"])
    else:
        raise SystemExit(f"Unsupported audio format: {audio_format}")
    cmd.append(str(output_path))
    run(cmd)


def extract_audio(args):
    write_progress(5, "Preparing audio extraction")
    video_path = Path(args.video).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not video_path.exists():
        raise SystemExit(f"Video not found: {video_path}")

    audio_format = args.format
    if audio_format == "auto":
        audio_format = out_path.suffix.lstrip(".").lower()
    write_progress(25, "Extracting audio")
    extract_audio_file(video_path, out_path, audio_format)
    write_progress(100, "Done")
    print(f"Done: {out_path}")


def process(args):
    write_progress(3, "Preparing files")
    require_tool("ffmpeg")
    require_tool("ffprobe")

    video_path = Path(args.video).expanduser().resolve()
    audio_path = Path(args.audio).expanduser().resolve() if args.audio else None
    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if not video_path.exists():
        raise SystemExit(f"Video not found: {video_path}")
    if audio_path is not None and not audio_path.exists():
        raise SystemExit(f"Audio not found: {audio_path}")

    write_progress(8, "Reading media duration")
    video_duration = ffprobe_duration(video_path)
    if audio_path is None:
        source_audio_path = video_path
        audio_offset = 0.0
        start_time = 0.0
        end_time = video_duration
    else:
        source_audio_path = audio_path
        audio_offset = args.audio_offset
        audio_duration = ffprobe_duration(audio_path)
        start_time = max(0.0, audio_offset)
        end_time = min(video_duration, audio_duration + audio_offset)
    if not math.isfinite(end_time) or end_time <= start_time:
        raise SystemExit("Could not determine a valid media duration.")

    write_progress(18, "Detecting silence")
    silences = detect_silences(source_audio_path, args.silence_threshold, args.min_silence)
    timeline_silences = [
        (start + audio_offset, end + audio_offset)
        for start, end in silences
    ]
    segments = invert_silences(
        timeline_silences,
        start_time,
        end_time,
        args.padding,
        args.min_keep,
    )
    fallback_reason = None
    if not segments:
        fallback_reason = (
            "Silence detection marked the whole source as silent; "
            "kept the full media instead."
        )
        segments = [(start_time, end_time)]

    write_progress(30, "Writing edit decision list")
    segments_json = out_dir / "segments.json"
    segments_json.write_text(
        json.dumps(
            {
                "video": str(video_path),
                "audio": str(audio_path) if audio_path is not None else None,
                "audio_source": "external" if audio_path is not None else "video",
                "silences": silences,
                "timeline_silences": timeline_silences,
                "kept_segments": segments,
                "fallback_reason": fallback_reason,
                "settings": {
                    "silence_threshold": args.silence_threshold,
                    "min_silence": args.min_silence,
                    "padding": args.padding,
                    "min_keep": args.min_keep,
                    "audio_offset": audio_offset,
                    "encode_mode": args.encode_mode,
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    edited_path = out_dir / args.output_name
    can_copy = (
        audio_path is None
        and audio_offset == 0
        and is_full_length_segment(segments, start_time, end_time)
    )
    if can_copy:
        if fallback_reason:
            print(fallback_reason)
        write_progress(70, "Copying media without re-encoding")
        copy_full_video(video_path, edited_path)
    elif fallback_reason:
        print(fallback_reason)
        write_progress(38, f"Rendering full media ({args.encode_mode})")
        render_video(video_path, audio_path, edited_path, segments, audio_offset, args.encode_mode)
    else:
        write_progress(38, f"Rendering edited video ({args.encode_mode})")
        render_video(video_path, audio_path, edited_path, segments, audio_offset, args.encode_mode)

    if args.captions == "faster-whisper":
        write_progress(88, "Generating captions")
        generate_captions_faster_whisper(
            edited_path,
            out_dir / "edited.srt",
            args.language,
            args.whisper_model,
        )
    elif args.captions == "whisper-cli":
        write_progress(88, "Generating captions")
        generate_captions_whisper_cli(edited_path, out_dir / "edited.srt", args.language)

    write_progress(100, "Done")
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
    process_parser.add_argument("--audio")
    process_parser.add_argument("--out", default="./output")
    process_parser.add_argument("--output-name", default="edited.mp4")
    process_parser.add_argument("--silence-threshold", default="-36dB")
    process_parser.add_argument("--min-silence", type=float, default=0.5)
    process_parser.add_argument("--padding", type=float, default=0.14)
    process_parser.add_argument("--min-keep", type=float, default=0.2)
    process_parser.add_argument("--audio-offset", type=float, default=0.0)
    process_parser.add_argument(
        "--encode-mode",
        choices=["fast", "fastest", "quality", "hardware"],
        default="fast",
    )
    process_parser.add_argument(
        "--captions",
        choices=["none", "faster-whisper", "whisper-cli"],
        default="none",
    )
    process_parser.add_argument("--language", default="ko")
    process_parser.add_argument("--whisper-model", default="small")
    process_parser.set_defaults(func=process)

    analyze_parser = subparsers.add_parser("analyze")
    analyze_parser.add_argument("--video", required=True)
    analyze_parser.add_argument("--audio")
    analyze_parser.add_argument("--out", default="./output")
    analyze_parser.add_argument("--silence-threshold", default="-45dB")
    analyze_parser.add_argument("--min-silence", type=float, default=0.6)
    analyze_parser.add_argument("--padding", type=float, default=0.16)
    analyze_parser.add_argument("--min-keep", type=float, default=0.2)
    analyze_parser.add_argument("--audio-offset", type=float, default=0.0)
    analyze_parser.add_argument(
        "--encode-mode",
        choices=["fast", "fastest", "quality", "hardware"],
        default="fast",
    )
    analyze_parser.add_argument(
        "--captions",
        choices=["none", "faster-whisper", "whisper-cli"],
        default="none",
    )
    analyze_parser.add_argument("--language", default="ko")
    analyze_parser.add_argument("--whisper-model", default="small")
    analyze_parser.set_defaults(func=analyze_media)

    render_parser = subparsers.add_parser("render-plan")
    render_parser.add_argument("--analysis", required=True)
    render_parser.add_argument("--out", default="./output")
    render_parser.add_argument("--output-name", default="edited.mp4")
    render_parser.add_argument(
        "--encode-mode",
        choices=["fast", "fastest", "quality", "hardware"],
    )
    render_parser.add_argument(
        "--captions",
        choices=["none", "faster-whisper", "whisper-cli"],
    )
    render_parser.add_argument("--language")
    render_parser.add_argument("--whisper-model")
    render_parser.set_defaults(func=render_from_analysis)

    extract_parser = subparsers.add_parser("extract-audio")
    extract_parser.add_argument("--video", required=True)
    extract_parser.add_argument("--out", required=True)
    extract_parser.add_argument(
        "--format",
        choices=["auto", "wav", "m4a"],
        default="auto",
    )
    extract_parser.set_defaults(func=extract_audio)

    return parser.parse_args(argv)


def main():
    extend_tool_path()
    args = parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
