const MAX_BROWSER_UPLOAD = 400 * 1024 * 1024;

const STATUS_LABELS = {
  evaluated_alert: "alert",
  evaluated_clear: "clear",
  unsupported_for_feed: "no signal",
  inconclusive: "inconclusive",
  not_applicable: "n/a",
};

const el = (id) => document.getElementById(id);

const drop = el("drop");
const fileInput = el("file");
const pathForm = el("path-form");
const pathInput = el("path");
const runButton = el("run");
const statusEl = el("status");
const statusLed = el("status-led");
const elapsedEl = el("elapsed");
const clipsEl = el("clips");
const clipCountEl = el("clip-count");
const idleEl = el("idle");
const resultEl = el("result");
const runIdEl = el("run-id");
const reportLink = el("report-link");
const preview = el("preview");
const coverageEl = el("coverage");
const incidentsEl = el("incidents");
const briefingsEl = el("briefings");
const alertCountEl = el("alert-count");
const askForm = el("ask-form");
const questionInput = el("question");
const askButton = el("ask");
const answersEl = el("answers");

let timerId = null;
let currentRunId = null;

function setStatus(text, state) {
  statusEl.textContent = text;
  statusEl.classList.toggle("bad", state === "bad");
  statusLed.className = `led ${{ busy: "led-busy", bad: "led-bad", done: "led-on" }[state] || ""}`;
}

function startTimer() {
  const began = performance.now();
  stopTimer();
  const tick = () => {
    elapsedEl.textContent = `${((performance.now() - began) / 1000).toFixed(1)}s`;
  };
  tick();
  timerId = setInterval(tick, 100);
}

function stopTimer() {
  if (timerId !== null) {
    clearInterval(timerId);
    timerId = null;
  }
}

function setBusy(busy) {
  drop.classList.toggle("busy", busy);
  runButton.disabled = busy;
  runButton.textContent = busy ? "Running" : "Run";
  pathInput.disabled = busy;
  askButton.disabled = busy || !currentRunId;
  for (const button of clipsEl.querySelectorAll("button")) {
    button.disabled = busy;
  }
}

function formatBytes(bytes) {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  if (bytes >= 1024 ** 2) return `${Math.round(bytes / 1024 ** 2)} MB`;
  return `${Math.round(bytes / 1024)} KB`;
}

drop.addEventListener("click", () => fileInput.click());
drop.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    fileInput.click();
  }
});

for (const name of ["dragenter", "dragover"]) {
  drop.addEventListener(name, (event) => {
    event.preventDefault();
    drop.classList.add("hot");
  });
}

for (const name of ["dragleave", "dragend", "drop"]) {
  drop.addEventListener(name, () => drop.classList.remove("hot"));
}

drop.addEventListener("drop", (event) => {
  event.preventDefault();
  const file = event.dataTransfer?.files?.[0];
  if (file) {
    handleBrowserFile(file);
  }
});

fileInput.addEventListener("change", () => {
  const file = fileInput.files?.[0];
  if (file) {
    handleBrowserFile(file);
  }
});

pathForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const path = pathInput.value.trim();
  if (!path) {
    setStatus("Enter a file path, or pick a source clip.", "bad");
    pathInput.focus();
    return;
  }
  runJob(path, () => postProcess(JSON.stringify({ path }), "application/json"));
});

askForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const question = questionInput.value.trim();
  if (!currentRunId || !question) {
    return;
  }
  askRun(question);
});

function handleBrowserFile(file) {
  if (file.size > MAX_BROWSER_UPLOAD) {
    setStatus(
      `${file.name} is ${formatBytes(file.size)}. Paste its full path and press Run instead.`,
      "bad",
    );
    pathInput.focus();
    return;
  }
  const body = new FormData();
  body.append("video", file, file.name);
  runJob(file.name, () => postProcess(body));
}

async function runJob(label, send) {
  setBusy(true);
  startTimer();
  setStatus(`Running pipeline on ${label}`, "busy");
  try {
    showResult(await send());
  } catch (error) {
    resultEl.hidden = true;
    idleEl.hidden = false;
    setStatus(error.message, "bad");
  } finally {
    stopTimer();
    setBusy(false);
    fileInput.value = "";
  }
}

async function postProcess(body, contentType) {
  const options = { method: "POST", body };
  if (contentType) {
    options.headers = { "Content-Type": contentType };
  }
  const response = await fetch("/api/process", options);
  const text = await response.text();
  let payload;
  try {
    payload = JSON.parse(text);
  } catch {
    throw new Error(
      response.ok ? "The server sent a broken reply." : `Request failed (${response.status}).`,
    );
  }
  if (!response.ok) {
    throw new Error(payload.error || `Request failed (${response.status}).`);
  }
  return payload;
}

async function askRun(question) {
  askButton.disabled = true;
  try {
    const response = await fetch(`/api/runs/${encodeURIComponent(currentRunId)}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || `Ask failed (${response.status}).`);
    }
    answersEl.prepend(answerRow(payload));
    questionInput.value = "";
  } catch (error) {
    setStatus(error.message, "bad");
  } finally {
    askButton.disabled = false;
  }
}

function coverageRow(entry) {
  const li = document.createElement("li");
  const id = document.createElement("span");
  id.className = "rule-id";
  id.textContent = entry.rule_id;
  const pill = document.createElement("span");
  const label = STATUS_LABELS[entry.status] || entry.status;
  const tone = { alert: " pill-alert", clear: " pill-clear" }[label] || "";
  pill.className = `pill${tone}`;
  pill.textContent = label;
  const reason = document.createElement("span");
  reason.className = "reason";
  reason.textContent = entry.reason_code;
  li.append(id, pill, reason);
  return li;
}

function incidentRow(item) {
  const li = document.createElement("li");
  const id = document.createElement("span");
  id.className = "rule-id";
  id.textContent = item.rule_id;
  const text = document.createElement("span");
  text.className = "observation";
  text.textContent = item.observation_text;
  li.append(id, text);
  return li;
}

function briefingRow(item) {
  const li = document.createElement("li");
  const head = document.createElement("div");
  head.className = "briefing-head";
  const id = document.createElement("span");
  id.className = "rule-id";
  id.textContent = item.rule_id;
  const mode = document.createElement("span");
  mode.className = "pill";
  mode.textContent = item.refused ? "refused" : item.mode;
  head.append(id, mode);

  const body = document.createElement("p");
  body.className = "briefing-body";
  body.textContent = (item.sentences || []).map((sentence) => sentence.text).join(" ");

  const cites = document.createElement("p");
  cites.className = "briefing-cites";
  const clauseRefs = (item.retrieved_chunks || []).map((hit) => hit.chunk.clause_ref);
  cites.textContent = clauseRefs.length ? `Cites: ${clauseRefs.join(" | ")}` : "No clause retrieved.";

  li.append(head, body, cites);
  return li;
}

function answerRow(item) {
  const li = document.createElement("li");
  const question = document.createElement("p");
  question.className = "answer-question";
  question.textContent = `Q: ${item.question}`;
  const answer = document.createElement("p");
  answer.className = "answer-body";
  answer.textContent = item.answer;
  const trace = document.createElement("p");
  trace.className = "answer-trace";
  trace.textContent = `Trace: ${(item.tool_trace || []).join(" -> ")}`;
  li.append(question, answer, trace);
  return li;
}

function showResult(payload) {
  const coverage = payload.rule_coverage || [];
  const incidents = payload.incidents || [];
  const briefings = payload.briefings || [];

  idleEl.hidden = true;
  resultEl.hidden = false;
  currentRunId = payload.run_id;
  runIdEl.textContent = payload.run_id;
  reportLink.href = payload.report_url;
  preview.src = payload.video_url;

  coverageEl.replaceChildren(...coverage.map(coverageRow));

  if (incidents.length) {
    incidentsEl.replaceChildren(...incidents.map(incidentRow));
  } else {
    const empty = document.createElement("li");
    empty.className = "incidents-empty";
    empty.textContent = "No alerts raised on this clip.";
    incidentsEl.replaceChildren(empty);
  }
  if (briefings.length) {
    briefingsEl.replaceChildren(...briefings.map(briefingRow));
  } else {
    const empty = document.createElement("li");
    empty.className = "incidents-empty";
    empty.textContent = "No grounded briefing available.";
    briefingsEl.replaceChildren(empty);
  }
  alertCountEl.textContent = `${incidents.length} raised`;
  answersEl.replaceChildren();
  askButton.disabled = false;

  setStatus(`Run ${payload.run_id} ${payload.status}.`, "done");
}

function clipRow(clip) {
  const li = document.createElement("li");
  const button = document.createElement("button");
  button.type = "button";
  button.className = "clip";
  const name = document.createElement("span");
  name.className = "clip-name";
  name.textContent = clip.name;
  const meta = document.createElement("span");
  meta.className = "clip-meta";
  meta.textContent = `${clip.size} · ${clip.path}`;
  meta.title = clip.path;
  button.append(name, meta);
  button.addEventListener("click", () => {
    pathInput.value = clip.path;
    runJob(clip.name, () => postProcess(JSON.stringify({ path: clip.path }), "application/json"));
  });
  li.appendChild(button);
  return li;
}

function setClipsMessage(text) {
  const li = document.createElement("li");
  li.className = "clips-empty";
  li.textContent = text;
  clipsEl.replaceChildren(li);
}

async function loadClips() {
  try {
    const response = await fetch("/api/clips");
    const clips = (await response.json()).clips || [];
    if (!clips.length) {
      setClipsMessage("No videos under data/. Drop a file or paste a path.");
      clipCountEl.textContent = "0";
      return;
    }
    clipsEl.replaceChildren(...clips.map(clipRow));
    clipCountEl.textContent = `${clips.length} found`;
  } catch {
    setClipsMessage("Could not reach the local server.");
    clipCountEl.textContent = "";
  }
}

loadClips();
