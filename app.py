#!/usr/bin/env python3
import html
import os
import re
import subprocess
import sys
import time
from email.parser import BytesParser
from email.policy import default
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


BASE_DIR = Path(__file__).resolve().parent
RUNS_DIR = BASE_DIR / "runs"
SCRIPT_PATH = BASE_DIR / "yt_auto_edit.py"
HOST = "127.0.0.1"
PORT = 5177
MAX_UPLOAD_SIZE = 20 * 1024 * 1024 * 1024


def safe_filename(value, fallback="upload"):
    name = Path(value or fallback).name
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return name or fallback


def escape(value):
    return html.escape(str(value), quote=True)


def page(*, error=None, result=None, log=None):
    error_html = ""
    if error:
        log_html = f"<pre>{escape(log)}</pre>" if log else ""
        error_html = f"""
        <section class="error">
          <h2>실패</h2>
          <p>{escape(error)}</p>
          {log_html}
        </section>
        """

    result_html = ""
    if result:
        links = "\n".join(
            f'<a class="button secondary" href="/download/{escape(result["run_id"])}/{escape(file)}">{escape(file)}</a>'
            for file in result["files"]
        )
        log_html = f"<pre>{escape(result['log'])}</pre>" if result.get("log") else ""
        result_html = f"""
        <section class="result">
          <h2>완료</h2>
          <p class="muted">{escape(result["message"])}</p>
          <div class="downloads">{links}</div>
          {log_html}
        </section>
        """

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>moviman</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --ink: #1f2933;
      --muted: #64707d;
      --line: #d8dde3;
      --accent: #1c7c70;
      --accent-strong: #135e55;
      --danger: #b42318;
      --soft: #edf5f3;
      --focus: #f3b34c;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.5;
    }}
    header {{
      border-bottom: 1px solid var(--line);
      background: #ffffff;
    }}
    .wrap {{
      width: min(1120px, calc(100vw - 32px));
      margin: 0 auto;
    }}
    .top {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 18px 0;
    }}
    h1 {{
      margin: 0;
      font-size: 22px;
      letter-spacing: 0;
    }}
    .status {{
      color: var(--muted);
      font-size: 14px;
      white-space: nowrap;
    }}
    main {{ padding: 28px 0 48px; }}
    .grid {{
      display: grid;
      grid-template-columns: minmax(0, 1.4fr) minmax(280px, 0.6fr);
      gap: 20px;
      align-items: start;
    }}
    section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 20px;
    }}
    h2 {{
      margin: 0 0 16px;
      font-size: 17px;
      letter-spacing: 0;
    }}
    form {{ display: grid; gap: 16px; }}
    .row {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
    }}
    label {{
      display: grid;
      gap: 7px;
      font-size: 13px;
      font-weight: 650;
    }}
    input, select {{
      width: 100%;
      min-height: 42px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 9px 10px;
      color: var(--ink);
      background: #ffffff;
      font: inherit;
    }}
    input[type="file"] {{ padding: 8px; }}
    input:focus, select:focus, button:focus {{
      outline: 3px solid color-mix(in srgb, var(--focus) 45%, transparent);
      outline-offset: 1px;
    }}
    .actions {{
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
      padding-top: 4px;
    }}
    button, .button {{
      min-height: 42px;
      border: 1px solid var(--accent);
      border-radius: 6px;
      padding: 9px 14px;
      background: var(--accent);
      color: #ffffff;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
    }}
    button:hover, .button:hover {{
      background: var(--accent-strong);
      border-color: var(--accent-strong);
    }}
    .button.secondary {{
      background: #ffffff;
      color: var(--accent-strong);
    }}
    .muted {{
      margin: 0;
      color: var(--muted);
      font-size: 13px;
    }}
    .stack {{ display: grid; gap: 20px; }}
    .result {{
      background: var(--soft);
      border-color: #b9d7d0;
      margin-bottom: 20px;
    }}
    .error {{
      background: #fff1f0;
      border-color: #ffccc7;
      color: var(--danger);
      margin-bottom: 20px;
    }}
    .downloads {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 14px;
    }}
    pre {{
      max-height: 360px;
      overflow: auto;
      margin: 14px 0 0;
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #111827;
      color: #e5e7eb;
      font-size: 12px;
      white-space: pre-wrap;
    }}
    @media (max-width: 820px) {{
      .grid, .row {{ grid-template-columns: 1fr; }}
      .top {{
        align-items: flex-start;
        flex-direction: column;
      }}
      .status {{ white-space: normal; }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="wrap top">
      <h1>moviman</h1>
      <div class="status">로컬 유튜브 편집 자동화</div>
    </div>
  </header>
  <main class="wrap">
    {error_html}
    {result_html}
    <div class="grid">
      <section>
        <h2>무음 컷 + 오디오 교체 + 캡션</h2>
        <form action="/process" method="post" enctype="multipart/form-data">
          <label>
            영상 파일
            <input type="file" name="video" accept=".mov,.mp4,.m4v,video/*" required>
          </label>
          <label>
            외부 오디오 파일
            <input type="file" name="audio" accept=".wav,.m4a,.mp3,.aac,audio/*" required>
          </label>
          <div class="row">
            <label>
              무음 기준
              <input name="silence_threshold" value="-38dB">
            </label>
            <label>
              최소 무음 길이
              <input name="min_silence" type="number" step="0.05" value="0.6">
            </label>
          </div>
          <div class="row">
            <label>
              앞뒤 여유
              <input name="padding" type="number" step="0.01" value="0.16">
            </label>
            <label>
              오디오 싱크 오프셋
              <input name="audio_offset" type="number" step="0.01" value="0">
            </label>
          </div>
          <div class="row">
            <label>
              캡션
              <select name="captions">
                <option value="none">생성 안 함</option>
                <option value="faster-whisper">faster-whisper</option>
              </select>
            </label>
            <label>
              언어
              <select name="language">
                <option value="ko">한국어</option>
                <option value="en">English</option>
                <option value="ja">日本語</option>
              </select>
            </label>
          </div>
          <div class="actions">
            <button type="submit">처리 시작</button>
            <p class="muted">처리가 끝날 때까지 이 창을 유지하세요.</p>
          </div>
        </form>
      </section>
      <div class="stack">
        <section>
          <h2>MOV 오디오 추출</h2>
          <form action="/extract" method="post" enctype="multipart/form-data">
            <label>
              영상 파일
              <input type="file" name="video" accept=".mov,.mp4,.m4v,video/*" required>
            </label>
            <label>
              저장 형식
              <select name="format">
                <option value="wav">WAV</option>
                <option value="m4a">M4A</option>
              </select>
            </label>
            <div class="actions">
              <button type="submit">오디오 추출</button>
            </div>
          </form>
        </section>
        <section>
          <h2>추천값</h2>
          <p class="muted">말 사이를 자연스럽게 자르려면 -38dB, 0.6, 0.16부터 시작하세요. 너무 많이 잘리면 무음 기준을 -42dB로 낮추고 앞뒤 여유를 늘리면 됩니다.</p>
        </section>
      </div>
    </div>
  </main>
</body>
</html>"""


def make_run_dir(prefix):
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    run_id = f"{prefix}-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
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
        if filename:
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


def run_command(cmd):
    result = subprocess.run(
        cmd,
        cwd=BASE_DIR,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stdout)
    return result.stdout


def output_files(run_dir):
    return sorted(path.name for path in (run_dir / "output").iterdir() if path.is_file())


class Handler(BaseHTTPRequestHandler):
    server_version = "moviman/0.1"

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_html(page())
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
        return parse_multipart(self.headers, body)

    def handle_process(self, fields, files):
        if "video" not in files or "audio" not in files:
            raise ValueError("영상 파일과 오디오 파일이 필요합니다.")

        run_id, run_dir = make_run_dir("edit")
        video_path = save_upload(files["video"], run_dir / "input")
        audio_path = save_upload(files["audio"], run_dir / "input")
        out_dir = run_dir / "output"

        cmd = [
            sys.executable,
            str(SCRIPT_PATH),
            "process",
            "--video",
            str(video_path),
            "--audio",
            str(audio_path),
            "--out",
            str(out_dir),
            "--silence-threshold",
            fields.get("silence_threshold", "-38dB"),
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
        ]
        log = run_command(cmd)
        self.send_html(
            page(
                result={
                    "run_id": run_id,
                    "message": "편집 결과가 준비됐습니다.",
                    "files": output_files(run_dir),
                    "log": log,
                }
            )
        )

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
        log = run_command(cmd)
        self.send_html(
            page(
                result={
                    "run_id": run_id,
                    "message": "오디오 파일이 준비됐습니다.",
                    "files": [output_name],
                    "log": log,
                }
            )
        )

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

        data = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header(
            "Content-Disposition",
            f'attachment; filename="{safe_filename(filename)}"',
        )
        self.end_headers()
        self.wfile.write(data)

    def send_html(self, content, status=HTTPStatus.OK):
        data = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


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
