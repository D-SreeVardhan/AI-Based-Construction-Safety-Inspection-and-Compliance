const MAX_BROWSER_UPLOAD = 400 * 1024 * 1024;

const drop = document.getElementById("drop");
const fileInput = document.getElementById("file");
const pathForm = document.getElementById("path-form");
const pathInput = document.getElementById("path");
const statusEl = document.getElementById("status");
const clipsEl = document.getElementById("clips");
const result = document.getElementById("result");
const preview = document.getElementById("preview");
const coverageEl = document.getElementById("coverage");
const incidentsEl = document.getElementById("incidents");
const runIdEl = document.getElementById("run-id");
const reportLink = document.getElementById("report-link");

function setStatus(text) {
  statusEl.textContent = text;
}

function setBusy(busy) {
  drop.classList.toggle("busy", busy);
  pathForm.querySelector("button").disabled = busy;
}

drop.addEventListener("click", () => fileInput.click());
drop.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    fileInput.click();
  }
});

["dragenter", "dragover"].forEach((name) => {
  drop.addEventListener(name, (event) => {
    event.preventDefault();
    drop.classList.add("hot");
  });
});
["dragleave", "drop"].forEach((name) => {
  drop.addEventListener(name, (event) => {
    event.preventDefault();
    drop.classList.remove("hot");
  });
});

drop.addEventListener("drop", (event) => {
  const file = event.dataTransfer?.files?.[0];
  if (file) handleBrowserFile(file);
});
fileInput.addEventListener("change", () => {
  const file = fileInput.files?.[0];
  if (file) handleBrowserFile(file);
});

pathForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const path = pathInput.value.trim();
  if (path) processPath(path);
});

function handleBrowserFile(file) {
  if (file.size > MAX_BROWSER_UPLOAD) {
    setStatus(
      `${file.name} is ${formatBytes(file.size)}. Paste the full file path below and click Run. The browser cannot send files this large.`,
    );
    pathInput.focus();
    return;
  }
  sendUpload(file);
}

async function sendUpload(file) {
  setBusy(true);
  result.hidden = true;
  setStatus(`Working on ${file.name}…`);
  const body = new FormData();
  body.append("video", file, file.name);
  try {
    const payload = await postProcess(body);
    showResult(payload);
  } catch (error) {
    setStatus(error.message);
  } finally {
    setBusy(false);
    fileInput.value = "";
  }
}

async function processPath(path) {
  setBusy(true);
  result.hidden = true;
  setStatus(`Working on ${path}…`);
  try {
    const payload = await postProcess(JSON.stringify({ path }), "application/json");
    showResult(payload);
  } catch (error) {
    setStatus(error.message);
  } finally {
    setBusy(false);
  }
}

async function postProcess(body, contentType) {
  const options = { method: "POST", body };
  if (contentType) options.headers = { "Content-Type": contentType };
  const response = await fetch("/api/process", options);
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || `Request failed (${response.status})`);
  }
  return payload;
}

function showResult(payload) {
  setStatus(`Done. Run ${payload.run_id}.`);
  result.hidden = false;
  runIdEl.textContent = payload.run_id;
  reportLink.href = payload.report_url;
  preview.src = payload.video_url;
  coverageEl.replaceChildren(
    ...payload.rule_coverage.map((entry) => {
      const li = document.createElement("li");
      li.innerHTML = `<span class="rid">${entry.rule_id}</span>${plainStatus(entry.status)} — ${entry.reason_code}`;
      return li;
    }),
  );
  incidentsEl.replaceChildren(
    ...payload.incidents.map((item) => {
      const li = document.createElement("li");
      li.innerHTML = `<span class="rid">${item.rule_id}</span>${item.observation_text}`;
      return li;
    }),
  );
}

function plainStatus(status) {
  return {
    evaluated_alert: "alert",
    evaluated_clear: "clear",
    unsupported_for_feed: "not available on this clip",
    inconclusive: "not sure yet",
    not_applicable: "does not apply",
  }[status] || status;
}

function formatBytes(bytes) {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  if (bytes >= 1024 ** 2) return `${Math.round(bytes / 1024 ** 2)} MB`;
  return `${Math.round(bytes / 1024)} KB`;
}

async function loadClips() {
  try {
    const response = await fetch("/api/clips");
    const payload = await response.json();
    if (!payload.clips?.length) {
      clipsEl.innerHTML = "<li class=\"empty\">No videos found in data/. Add a file, or paste a path.</li>";
      return;
    }
    clipsEl.replaceChildren(
      ...payload.clips.map((clip) => {
        const li = document.createElement("li");
        const button = document.createElement("button");
        button.type = "button";
        button.className = "clip";
        button.innerHTML = `<span>${clip.name}</span><span class="meta">${clip.size} · ${clip.path}</span>`;
        button.addEventListener("click", () => {
          pathInput.value = clip.path;
          processPath(clip.path);
        });
        li.appendChild(button);
        return li;
      }),
    );
  } catch {
    clipsEl.innerHTML = "<li class=\"empty\">Could not list local videos.</li>";
  }
}

loadClips();
