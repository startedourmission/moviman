#!/usr/bin/env python3
import html
import json
import os
import re
import subprocess
import sys
import threading
import time
from email.parser import BytesParser
from email.policy import default
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


BASE_DIR = Path(__file__).resolve().parent
RUNS_DIR = BASE_DIR / "runs"
SCRIPT_PATH = BASE_DIR / "yt_auto_edit.py"
HOST = "127.0.0.1"
PORT = 5177
MAX_UPLOAD_SIZE = 20 * 1024 * 1024 * 1024
EXTRA_TOOL_PATHS = (
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "/usr/bin",
    "/bin",
)


def tool_env():
    env = os.environ.copy()
    existing = env.get("PATH", "")
    parts = [path for path in existing.split(os.pathsep) if path]
    for path in EXTRA_TOOL_PATHS:
        if path not in parts:
            parts.append(path)
    env["PATH"] = os.pathsep.join(parts)
    return env


def safe_filename(value, fallback="upload"):
    name = Path(value or fallback).name
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return name or fallback


def escape(value):
    return html.escape(str(value), quote=True)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(data), encoding="utf-8")
    tmp_path.replace(path)


def read_json(path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def shell():
    return """<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>moviman</title>
  <link rel="stylesheet" href="/static/style.css?v=6">
</head>
<body>
  <header class="appbar">
    <div class="wrap appbar-inner">
      <div class="brand-lockup">
        <span class="brand-mark">M</span>
        <div>
          <h1>moviman</h1>
          <p class="subtitle">Cut review studio</p>
        </div>
      </div>
      <div class="server-badge">local · 127.0.0.1:5177</div>
    </div>
  </header>
"""


def page(*, error=None, log=None):
    error_html = ""
    if error:
        log_html = f"<pre>{escape(log)}</pre>" if log else ""
        error_html = f"""
        <section class="notice error">
          <strong>처리 실패</strong>
          <span>{escape(error)}</span>
          {log_html}
        </section>
        """

    return shell() + f"""
  <main class="editor-shell home-editor-shell">
    {error_html}
    <form action="/process" method="post" enctype="multipart/form-data" class="home-editor" id="home-editor" aria-label="new edit">
      <section class="editor-topbar">
        <div>
          <h2>moviman editor</h2>
          <p>영상을 올리면 무음 컷을 분석하고 바로 타임라인 에디터로 넘어갑니다.</p>
        </div>
        <div class="timeline-actions">
          <button type="submit" class="button primary">컷 분석 시작</button>
        </div>
      </section>

      <section class="editor-stage">
        <label class="viewer-panel empty-viewer">
          <input class="hidden-file" type="file" name="video" accept=".mov,.mp4,.m4v,video/*" required>
          <div>
            <span class="drop-kicker">Drop video here</span>
            <h2>영상 파일을 여기에 올리기</h2>
            <p>MOV/MP4를 선택하면 분석 후 타임라인 에디터로 바로 이동합니다.</p>
            <span class="button secondary">영상 선택</span>
          </div>
        </label>
        <aside class="inspector-panel home-inspector">
          <div>
            <span class="eyebrow">Inspector</span>
            <h2>분석 설정</h2>
            <p>대부분은 기본값으로 시작하면 됩니다.</p>
          </div>
          <label class="field">
            <span>외부 오디오</span>
            <input type="file" name="audio" accept=".wav,.m4a,.mp3,.aac,audio/*">
          </label>
          <label class="field">
            <span>무음 기준</span>
            <input name="silence_threshold" value="-45dB">
          </label>
          <div class="field-pair">
            <label class="field">
              <span>최소 무음</span>
              <input name="min_silence" type="number" step="0.05" value="0.6">
            </label>
            <label class="field">
              <span>앞뒤 여유</span>
              <input name="padding" type="number" step="0.01" value="0.16">
            </label>
          </div>
          <label class="field">
            <span>오디오 오프셋</span>
            <input name="audio_offset" type="number" step="0.01" value="0">
          </label>
          <div class="field-pair">
            <label class="field">
              <span>캡션</span>
              <select name="captions">
                <option value="none">없음</option>
                <option value="faster-whisper">whisper</option>
              </select>
            </label>
            <label class="field">
              <span>언어</span>
              <select name="language">
                <option value="ko">한국어</option>
                <option value="en">English</option>
                <option value="ja">日本語</option>
              </select>
            </label>
          </div>
          <label class="field">
            <span>렌더 속도</span>
            <select name="encode_mode">
              <option value="fast">빠름</option>
              <option value="fastest">가장 빠름</option>
              <option value="hardware">하드웨어</option>
              <option value="quality">품질 우선</option>
            </select>
          </label>
        </aside>
      </section>

      <section class="timeline-panel">
        <div class="timeline-toolbar">
          <div class="transport">
            <button type="button" class="icon-button" disabled>-5s</button>
            <button type="button" class="button secondary" disabled>재생</button>
            <button type="button" class="icon-button" disabled>+5s</button>
            <span class="timecode">00:00.00</span>
          </div>
          <div class="timeline-actions">
            <button type="button" class="button secondary" disabled>현재 위치 컷 추가</button>
            <button type="submit" class="button primary">컷 분석 시작</button>
          </div>
        </div>
        <div class="timeline-ruler timeline-empty">
          <div class="timeline-track"></div>
          <div class="timeline-playhead"></div>
        </div>
      </section>
    </form>

    <form action="/extract" method="post" enctype="multipart/form-data" class="audio-extract-dock">
      <span>오디오만 필요할 때</span>
      <input type="file" name="video" accept=".mov,.mp4,.m4v,video/*" required>
      <select name="format">
        <option value="wav">WAV</option>
        <option value="m4a">M4A</option>
      </select>
      <button type="submit" class="button secondary">오디오 추출</button>
    </form>
  </main>
</body>
</html>"""


def job_page(run_id, title):
    escaped_run_id = escape(run_id)
    escaped_title = escape(title)
    return shell() + f"""
  <main class="wrap job-shell">
    <section class="panel job-panel">
      <div class="job-head">
        <div>
          <h2>{escaped_title}</h2>
          <p id="stage">대기 중</p>
        </div>
        <a class="button secondary" href="/">새 작업</a>
      </div>

      <div class="progress-meta">
        <strong id="percent">0%</strong>
        <span id="elapsed">0초</span>
      </div>
      <div class="progress-track" aria-label="progress">
        <div class="progress-fill" id="fill"></div>
      </div>

      <div class="downloads" id="downloads"></div>
      <div class="review-link" id="review-link"></div>
      <pre id="log"></pre>
    </section>
  </main>
  <script>window.movimanRunId = "{escaped_run_id}";</script>
  <script src="/static/app.js?v=6"></script>
</body>
</html>"""


def review_page(run_id, analysis):
    cuts = analysis.get("cuts", [])
    duration = float(analysis.get("duration", 0.0))
    video_name = Path(analysis["video"]).name
    cuts_json = escape(json.dumps(cuts))
    rows = []
    for cut in cuts:
        checked = "checked" if cut.get("enabled", True) else ""
        start = float(cut["start"])
        end = float(cut["end"])
        rows.append(
            f"""
            <label class="cut-row" data-cut-row="{escape(cut['id'])}">
              <input type="checkbox" name="cut" value="{escape(cut['id'])}" {checked}>
              <span class="cut-time">{format_time(start)} - {format_time(end)}</span>
              <span class="cut-duration">{end - start:.1f}s</span>
            </label>
            """
        )
    rows_html = "\n".join(rows) if rows else '<p class="empty-state">자동 컷 후보가 없습니다.</p>'
    return shell() + f"""
  <main class="editor-shell" data-duration="{duration:.6f}" data-cuts="{cuts_json}">
    <section class="editor-topbar">
      <div>
        <h2>moviman editor</h2>
        <p>컷 구간을 타임라인에서 확인하고 바로 수정합니다.</p>
      </div>
      <a class="button secondary" href="/">새 작업</a>
    </section>

    <section class="editor-stage">
      <div class="viewer-panel">
        <video id="editor-video" class="editor-video" controls src="/media/{escape(run_id)}/input/{escape(video_name)}"></video>
      </div>
      <aside class="inspector-panel">
        <div>
          <span class="eyebrow">Inspector</span>
          <h2>삭제 컷</h2>
          <p>켜진 컷만 최종 렌더에서 빠집니다.</p>
        </div>
        <div class="cut-list">{rows_html}</div>
      </aside>
    </section>

    <form action="/render/{escape(run_id)}" method="post" class="review-form editor-timeline-form">
      <section class="timeline-panel">
        <div class="timeline-toolbar">
          <div class="transport">
            <button type="button" class="icon-button" data-action="back" title="뒤로">-5s</button>
            <button type="button" class="button secondary" data-action="play">재생</button>
            <button type="button" class="icon-button" data-action="forward" title="앞으로">+5s</button>
            <span class="timecode" id="timecode">00:00.00</span>
          </div>
          <div class="timeline-actions">
            <button type="button" class="button secondary" data-action="split">현재 위치 컷 추가</button>
            <button type="button" class="button secondary" data-action="select-all">전체 선택</button>
            <button type="button" class="button secondary" data-action="select-none">전체 해제</button>
            <button type="submit" class="button primary">선택대로 렌더</button>
          </div>
        </div>
        <div class="timeline-ruler" id="timeline-ruler">
          <div class="timeline-track" id="timeline-track"></div>
          <div class="timeline-playhead" id="timeline-playhead"></div>
        </div>
        <div class="action-row">
          <span class="run-note">주황색 블록은 삭제될 컷입니다. 타임라인을 클릭하면 영상 위치가 이동합니다.</span>
        </div>
      </section>
    </form>
  </main>
  <script src="/static/review.js?v=6"></script>
</body>
</html>"""


def format_time(seconds):
    seconds = max(0.0, seconds)
    minutes = int(seconds // 60)
    rest = seconds - minutes * 60
    return f"{minutes:02d}:{rest:05.2f}"


def make_run_dir(prefix):
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    run_id = f"{prefix}-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}-{time.time_ns() % 1000000}"
    run_dir = RUNS_DIR / run_id
    (run_dir / "input").mkdir(parents=True)
    (run_dir / "output").mkdir()
    return run_id, run_dir


def parse_multipart(headers, body):
    content_type = headers.get("Content-Type", "")
    raw = (
        f"Content-Type: {content_type}\r\n"
        f"MIME-Version: 1.0\r\n\r\n"
    ).encode("utf-8") + body
    message = BytesParser(policy=default).parsebytes(raw)
    fields = {}
    files = {}
    if not message.is_multipart():
        return fields, files
    for part in message.iter_parts():
        disposition = part.get("Content-Disposition", "")
        if "form-data" not in disposition:
            continue
        name = part.get_param("name", header="content-disposition")
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""
        if filename and payload:
            files[name] = {
                "filename": safe_filename(filename),
                "content": payload,
            }
        elif name:
            charset = part.get_content_charset() or "utf-8"
            fields[name] = payload.decode(charset, errors="replace")
    return fields, files


def save_upload(file_info, target_dir):
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / file_info["filename"]
    path.write_bytes(file_info["content"])
    return path


def log_tail(path, max_chars=12000):
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def start_job(run_id, run_dir, cmd):
    status_path = run_dir / "status.json"
    progress_path = run_dir / "progress.json"
    log_path = run_dir / "job.log"
    write_json(
        status_path,
        {
            "state": "queued",
            "stage": "Queued",
            "started_at": time.time(),
            "ended_at": None,
            "returncode": None,
        },
    )

    def worker():
        started_at = time.time()
        write_json(
            status_path,
            {
                "state": "running",
                "stage": "Starting",
                "started_at": started_at,
                "ended_at": None,
                "returncode": None,
            },
        )
        env = tool_env()
        env["MOVIMAN_PROGRESS_FILE"] = str(progress_path)
        with log_path.open("w", encoding="utf-8") as log_file:
            process = subprocess.Popen(
                cmd,
                cwd=BASE_DIR,
                env=env,
                text=True,
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
            returncode = process.wait()
        ended_at = time.time()
        progress = read_json(progress_path, {})
        state = "done" if returncode == 0 else "error"
        stage = "Done" if returncode == 0 else "Failed"
        if returncode == 0:
            write_json(progress_path, {"percent": 100, "stage": stage, "updated_at": ended_at})
        write_json(
            status_path,
            {
                "state": state,
                "stage": progress.get("stage", stage),
                "started_at": started_at,
                "ended_at": ended_at,
                "returncode": returncode,
            },
        )

    thread = threading.Thread(target=worker, name=f"job-{run_id}", daemon=True)
    thread.start()


def output_files(run_dir):
    return sorted(path.name for path in (run_dir / "output").iterdir() if path.is_file())


def input_files(run_dir):
    input_dir = run_dir / "input"
    return sorted(path.name for path in input_dir.iterdir() if path.is_file())


class Handler(BaseHTTPRequestHandler):
    server_version = "moviman/0.2"

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_html(page())
            return
        if parsed.path == "/static/style.css":
            self.send_file(BASE_DIR / "static" / "style.css", "text/css; charset=utf-8")
            return
        if parsed.path == "/static/app.js":
            self.send_file(BASE_DIR / "static" / "app.js", "text/javascript; charset=utf-8")
            return
        if parsed.path == "/static/review.js":
            self.send_file(BASE_DIR / "static" / "review.js", "text/javascript; charset=utf-8")
            return
        if parsed.path.startswith("/status/"):
            self.handle_status(parsed.path)
            return
        if parsed.path.startswith("/review/"):
            self.handle_review(parsed.path)
            return
        if parsed.path.startswith("/media/"):
            self.handle_media(parsed.path)
            return
        if parsed.path.startswith("/download/"):
            self.handle_download(parsed.path)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            fields, files = self.read_form()
            if parsed.path == "/process":
                self.handle_process(fields, files)
                return
            if parsed.path == "/extract":
                self.handle_extract(fields, files)
                return
            if parsed.path.startswith("/render/"):
                self.handle_render(parsed.path, fields)
                return
        except ValueError as exc:
            self.send_html(page(error=str(exc)), status=HTTPStatus.BAD_REQUEST)
            return
        except RuntimeError as exc:
            self.send_html(
                page(error="처리 중 오류가 발생했습니다.", log=str(exc)),
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def read_form(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            raise ValueError("업로드된 데이터가 없습니다.")
        if length > MAX_UPLOAD_SIZE:
            raise ValueError("업로드 파일이 너무 큽니다.")
        body = self.rfile.read(length)
        content_type = self.headers.get("Content-Type", "")
        if content_type.startswith("application/x-www-form-urlencoded"):
            parsed = parse_qs(body.decode("utf-8"), keep_blank_values=True)
            return {key: values[-1] if values else "" for key, values in parsed.items()}, {}
        return parse_multipart(self.headers, body)

    def handle_process(self, fields, files):
        if "video" not in files:
            raise ValueError("영상 파일이 필요합니다.")

        run_id, run_dir = make_run_dir("edit")
        video_path = save_upload(files["video"], run_dir / "input")
        out_dir = run_dir / "output"

        cmd = [
            sys.executable,
            str(SCRIPT_PATH),
            "analyze",
            "--video",
            str(video_path),
            "--out",
            str(out_dir),
            "--silence-threshold",
            fields.get("silence_threshold", "-45dB"),
            "--min-silence",
            fields.get("min_silence", "0.6"),
            "--padding",
            fields.get("padding", "0.16"),
            "--audio-offset",
            fields.get("audio_offset", "0"),
            "--captions",
            fields.get("captions", "none"),
            "--language",
            fields.get("language", "ko"),
            "--encode-mode",
            fields.get("encode_mode", "fast"),
        ]
        if "audio" in files:
            audio_path = save_upload(files["audio"], run_dir / "input")
            cmd.extend(["--audio", str(audio_path)])
        start_job(run_id, run_dir, cmd)
        self.send_html(job_page(run_id, "컷 후보 분석 중"))

    def handle_extract(self, fields, files):
        if "video" not in files:
            raise ValueError("영상 파일이 필요합니다.")

        run_id, run_dir = make_run_dir("audio")
        video_path = save_upload(files["video"], run_dir / "input")
        audio_format = fields.get("format", "wav")
        if audio_format not in {"wav", "m4a"}:
            raise ValueError("지원하지 않는 오디오 형식입니다.")
        output_name = f"extracted_audio.{audio_format}"
        out_path = run_dir / "output" / output_name
        cmd = [
            sys.executable,
            str(SCRIPT_PATH),
            "extract-audio",
            "--video",
            str(video_path),
            "--out",
            str(out_path),
            "--format",
            audio_format,
        ]
        start_job(run_id, run_dir, cmd)
        self.send_html(job_page(run_id, "오디오 추출 중"))

    def handle_status(self, path):
        parts = [unquote(part) for part in path.split("/") if part]
        if len(parts) != 2:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        _, run_id = parts
        run_dir = RUNS_DIR / safe_filename(run_id)
        status = read_json(run_dir / "status.json")
        if not status:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        progress = read_json(run_dir / "progress.json", {})
        now = time.time()
        ended_at = status.get("ended_at")
        started_at = status.get("started_at") or now
        elapsed = (ended_at or now) - started_at
        percent = progress.get("percent")
        if percent is None:
            percent = 100 if status.get("state") == "done" else 2
        if status.get("state") == "error" and percent >= 100:
            percent = 99
        payload = {
            "state": status.get("state", "running"),
            "stage": progress.get("stage") or status.get("stage", "처리 중"),
            "percent": int(percent),
            "elapsed": elapsed,
            "files": output_files(run_dir) if status.get("state") == "done" else [],
            "inputs": input_files(run_dir) if status.get("state") == "done" else [],
            "review_url": f"/review/{safe_filename(run_id)}"
            if status.get("state") == "done" and (run_dir / "output" / "analysis.json").exists()
            else None,
            "log": log_tail(run_dir / "job.log"),
        }
        self.send_json(payload)

    def handle_review(self, path):
        parts = [unquote(part) for part in path.split("/") if part]
        if len(parts) != 2:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        _, run_id = parts
        safe_run_id = safe_filename(run_id)
        analysis_path = RUNS_DIR / safe_run_id / "output" / "analysis.json"
        analysis = read_json(analysis_path)
        if not analysis:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.send_html(review_page(safe_run_id, analysis))

    def handle_media(self, path):
        parts = [unquote(part) for part in path.split("/") if part]
        if len(parts) != 4 or parts[2] != "input":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        _, run_id, _, filename = parts
        target = RUNS_DIR / safe_filename(run_id) / "input" / safe_filename(filename)
        self.send_file(target, "video/mp4")

    def handle_render(self, path, fields):
        parts = [unquote(part) for part in path.split("/") if part]
        if len(parts) != 2:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        _, run_id = parts
        source_run_dir = RUNS_DIR / safe_filename(run_id)
        analysis_path = source_run_dir / "output" / "analysis.json"
        analysis = read_json(analysis_path)
        if not analysis:
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        if fields.get("cuts_json"):
            try:
                posted_cuts = json.loads(fields["cuts_json"])
            except json.JSONDecodeError as exc:
                raise ValueError("컷 데이터가 올바르지 않습니다.") from exc
            cleaned_cuts = []
            for index, cut in enumerate(posted_cuts):
                start = max(0.0, float(cut.get("start", 0.0)))
                end = min(float(analysis.get("duration", 0.0)), float(cut.get("end", start)))
                if end <= start:
                    continue
                cleaned_cuts.append(
                    {
                        "id": safe_filename(cut.get("id") or f"cut_{index + 1:04d}", f"cut_{index + 1:04d}"),
                        "start": start,
                        "end": end,
                        "enabled": bool(cut.get("enabled", True)),
                        "reason": str(cut.get("reason") or "manual"),
                    }
                )
            analysis["cuts"] = sorted(cleaned_cuts, key=lambda item: item["start"])
        else:
            enabled_ids = set(fields.get("enabled_cuts", "").split(",")) if fields.get("enabled_cuts") else set()
            for cut in analysis.get("cuts", []):
                cut["enabled"] = cut["id"] in enabled_ids
        analysis_path.write_text(json.dumps(analysis, indent=2), encoding="utf-8")

        render_id, render_dir = make_run_dir("render")
        render_analysis_path = render_dir / "input" / "analysis.json"
        render_analysis_path.write_text(json.dumps(analysis, indent=2), encoding="utf-8")
        cmd = [
            sys.executable,
            str(SCRIPT_PATH),
            "render-plan",
            "--analysis",
            str(render_analysis_path),
            "--out",
            str(render_dir / "output"),
        ]
        start_job(render_id, render_dir, cmd)
        self.send_html(job_page(render_id, "선택한 컷 렌더링 중"))

    def handle_download(self, path):
        parts = [unquote(part) for part in path.split("/") if part]
        if len(parts) != 3:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        _, run_id, filename = parts
        target = RUNS_DIR / safe_filename(run_id) / "output" / safe_filename(filename)
        if not target.exists() or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.send_file(target, "application/octet-stream", attachment_name=safe_filename(filename))

    def send_file(self, path, content_type, attachment_name=None):
        if not path.exists() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if attachment_name:
            self.send_header("Content-Disposition", f'attachment; filename="{attachment_name}"')
        self.end_headers()
        try:
            self.wfile.write(data)
        except BrokenPipeError:
            return

    def send_html(self, content, status=HTTPStatus.OK):
        data = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except BrokenPipeError:
            return

    def send_json(self, payload, status=HTTPStatus.OK):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except BrokenPipeError:
            return


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"moviman running at http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
