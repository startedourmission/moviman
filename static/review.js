const shell = document.querySelector(".editor-shell");
const form = document.querySelector(".review-form");
const video = document.getElementById("editor-video");
const track = document.getElementById("timeline-track");
const ruler = document.getElementById("timeline-ruler");
const playhead = document.getElementById("timeline-playhead");
const timecode = document.getElementById("timecode");
const playButton = document.querySelector('[data-action="play"]');

let duration = Number(shell?.dataset.duration || 0);
let cuts = [];

try {
  cuts = JSON.parse(shell?.dataset.cuts || "[]").map((cut, index) => ({
    id: cut.id || `cut_${index + 1}`,
    start: Number(cut.start || 0),
    end: Number(cut.end || 0),
    enabled: cut.enabled !== false,
    reason: cut.reason || "silence",
  }));
} catch {
  cuts = [];
}

function formatTime(seconds) {
  const safe = Math.max(0, seconds || 0);
  const minutes = Math.floor(safe / 60);
  const rest = safe - minutes * 60;
  return `${String(minutes).padStart(2, "0")}:${rest.toFixed(2).padStart(5, "0")}`;
}

function clampTime(value) {
  return Math.max(0, Math.min(duration || 0, value));
}

function percent(value) {
  if (!duration) return 0;
  return Math.max(0, Math.min(100, (value / duration) * 100));
}

function syncRows() {
  document.querySelectorAll(".cut-row").forEach((row) => {
    const cut = cuts.find((item) => item.id === row.dataset.cutRow);
    const input = row.querySelector('input[name="cut"]');
    if (!cut || !input) return;
    input.checked = cut.enabled;
    row.classList.toggle("is-muted", !cut.enabled);
  });
}

function renderTimeline() {
  if (!track) return;
  track.innerHTML = "";
  cuts.forEach((cut) => {
    const block = document.createElement("button");
    block.type = "button";
    block.className = `timeline-cut${cut.enabled ? "" : " is-muted"}`;
    block.style.left = `${percent(cut.start)}%`;
    block.style.width = `${Math.max(0.6, percent(cut.end) - percent(cut.start))}%`;
    block.title = `${formatTime(cut.start)} - ${formatTime(cut.end)}`;
    block.dataset.cutId = cut.id;
    block.textContent = cut.reason === "manual" ? "manual" : "silence";
    block.addEventListener("click", (event) => {
      event.stopPropagation();
      cut.enabled = !cut.enabled;
      renderTimeline();
      syncRows();
    });
    track.appendChild(block);
  });
}

function setPlayhead() {
  const current = video?.currentTime || 0;
  if (playhead) playhead.style.left = `${percent(current)}%`;
  if (timecode) timecode.textContent = formatTime(current);
}

function addManualCut() {
  const center = clampTime(video?.currentTime || 0);
  const half = 0.35;
  const start = clampTime(center - half);
  const end = clampTime(center + half);
  cuts.push({
    id: `manual_${Date.now()}`,
    start,
    end,
    enabled: true,
    reason: "manual",
  });
  cuts.sort((a, b) => a.start - b.start);
  renderTimeline();
}

function setAll(enabled) {
  cuts.forEach((cut) => {
    cut.enabled = enabled;
  });
  renderTimeline();
  syncRows();
}

document.addEventListener("change", (event) => {
  if (!event.target.matches('input[name="cut"]')) return;
  const cut = cuts.find((item) => item.id === event.target.value);
  if (!cut) return;
  cut.enabled = event.target.checked;
  renderTimeline();
  syncRows();
});

document.addEventListener("click", (event) => {
  const action = event.target.closest("[data-action]")?.dataset.action;
  if (!action) return;
  if (action === "select-all") setAll(true);
  if (action === "select-none") setAll(false);
  if (action === "split") addManualCut();
  if (action === "back") video.currentTime = clampTime((video.currentTime || 0) - 5);
  if (action === "forward") video.currentTime = clampTime((video.currentTime || 0) + 5);
  if (action === "play") {
    if (video.paused) video.play();
    else video.pause();
  }
});

ruler?.addEventListener("click", (event) => {
  const rect = ruler.getBoundingClientRect();
  const ratio = (event.clientX - rect.left) / rect.width;
  video.currentTime = clampTime(ratio * duration);
});

video?.addEventListener("loadedmetadata", () => {
  duration = video.duration || duration;
  setPlayhead();
  renderTimeline();
});

video?.addEventListener("timeupdate", setPlayhead);
video?.addEventListener("play", () => {
  if (playButton) playButton.textContent = "정지";
});
video?.addEventListener("pause", () => {
  if (playButton) playButton.textContent = "재생";
});

form?.addEventListener("submit", () => {
  const hidden = document.createElement("input");
  hidden.type = "hidden";
  hidden.name = "cuts_json";
  hidden.value = JSON.stringify(cuts);
  form.appendChild(hidden);
});

renderTimeline();
syncRows();
setPlayhead();
