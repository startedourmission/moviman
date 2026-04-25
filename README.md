# moviman

Small YouTube editing automation for a workflow where video is recorded on a phone and clean audio is recorded separately, for example on iPad GarageBand.

## What It Does

- Replaces the phone audio with the separate GarageBand audio.
- Detects silent parts in the external audio.
- Cuts those silent parts from both video and audio.
- Optionally generates Korean/English captions as `.srt`.

## Requirements

Install `ffmpeg` first:

```bash
brew install ffmpeg
```

For local caption generation, install Python dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`faster-whisper` downloads a speech model the first time it runs.

## Quick Start

Run the local web app:

```bash
source .venv/bin/activate
python3 app.py
```

Then open:

```text
http://127.0.0.1:5177
```

The web UI can:

- Upload a phone video and separate audio file.
- Cut silent sections and render `edited.mp4`.
- Generate `edited.srt` when captions are enabled.
- Extract WAV or M4A audio from a MOV/MP4 file.

## CLI

Put your files somewhere convenient, then run:

```bash
python3 yt_auto_edit.py process \
  --video ./input/phone_video.mov \
  --audio ./input/garageband_audio.m4a \
  --out ./output \
  --language ko \
  --captions faster-whisper
```

The output folder will contain:

- `edited.mp4`: video with silent parts removed and clean audio attached.
- `edited.srt`: captions, if captions are enabled.
- `segments.json`: the edit decision list used for the cut.

Extract audio from a MOV file:

```bash
python3 yt_auto_edit.py extract-audio \
  --video ./input/phone_video.mov \
  --out ./output/extracted_audio.wav \
  --format wav
```

## Useful Options

Tune silence cutting:

```bash
python3 yt_auto_edit.py process \
  --video phone.mov \
  --audio garageband.m4a \
  --silence-threshold=-38dB \
  --min-silence 0.6 \
  --padding 0.16
```

If the cut feels too aggressive, lower the threshold or increase padding:

- More aggressive cut: `--silence-threshold=-32dB --min-silence 0.35`
- More natural cut: `--silence-threshold=-42dB --min-silence 0.8 --padding 0.25`

If the video and audio do not start at exactly the same time, pass an offset:

```bash
python3 yt_auto_edit.py process \
  --video phone.mov \
  --audio garageband.m4a \
  --audio-offset 1.25
```

`--audio-offset 1.25` means the external audio starts 1.25 seconds after the video timeline. Use a negative value if the external audio started before the video.

## Recommended Recording Workflow

1. Start GarageBand recording.
2. Start phone video recording.
3. Make one sharp clap visible on camera and audible in GarageBand.
4. Edit with this tool.
5. If sync is off, adjust `--audio-offset`.
