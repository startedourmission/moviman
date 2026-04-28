const runId = window.movimanRunId;
const fill = document.getElementById("fill");
const percent = document.getElementById("percent");
const elapsed = document.getElementById("elapsed");
const stage = document.getElementById("stage");
const downloads = document.getElementById("downloads");
const log = document.getElementById("log");

function formatElapsed(seconds) {
  const value = Math.max(0, Math.floor(seconds || 0));
  const minutes = Math.floor(value / 60);
  const rest = value % 60;
  if (minutes > 0) return `${minutes}분 ${rest}초`;
  return `${rest}초`;
}

function renderDownloads(files) {
  downloads.innerHTML = files
    .map((file) => {
      const href = `/download/${runId}/${encodeURIComponent(file)}`;
      return `<a class="button secondary" href="${href}">${file}</a>`;
    })
    .join("");
}

function render(data) {
  const progress = Math.max(0, Math.min(100, data.percent || 0));
  fill.style.width = `${progress}%`;
  percent.textContent = `${progress}%`;
  elapsed.textContent = formatElapsed(data.elapsed);
  stage.textContent = data.stage || data.state || "처리 중";
  stage.className = data.state === "error" ? "error-text" : "";
  log.textContent = data.log || "";
  if (data.files && data.files.length) renderDownloads(data.files);
  if (data.state !== "done" && data.state !== "error") {
    setTimeout(poll, 700);
  }
}

async function poll() {
  const response = await fetch(`/status/${runId}`);
  render(await response.json());
}

poll();
