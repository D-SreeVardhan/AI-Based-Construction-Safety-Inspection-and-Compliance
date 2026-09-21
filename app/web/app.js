const drop = document.getElementById("drop");
const fileInput = document.getElementById("file");
const logEl = document.getElementById("log");
const result = document.getElementById("result");
const preview = document.getElementById("preview");
const coverageEl = document.getElementById("coverage");
const incidentsEl = document.getElementById("incidents");
const runIdEl = document.getElementById("run-id");
const reportLink = document.getElementById("report-link");
const ticketN = document.getElementById("ticket-n");

ticketN.textContent = Math.random().toString(16).slice(2, 6).toUpperCase();

function log(line) {
  const item = document.createElement("li");
  item.textContent = line;
  logEl.appendChild(item);
  logEl.scrollTop = logEl.scrollHeight;
}

function setBusy(busy) {
  drop.classList.toggle("busy", busy);
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
  if (file) sendFile(file);
});

fileInput.addEventListener("change", () => {
  const file = fileInput.files?.[0];
  if (file) sendFile(file);
});

async function sendFile(file) {
  setBusy(true);
  result.hidden = true;
  log(`Intake: ${file.name}`);
  log("Pass 1 placeholder — writing synthetic tracks.");
  const body = new FormData();
  body.append("video", file, file.name);
  try {
    const response = await fetch("/api/process", { method: "POST", body });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || `HTTP ${response.status}`);
    }
    log(`Published ${payload.run_id}`);
    showResult(payload);
  } catch (error) {
    log(`Failed: ${error.message}`);
  } finally {
    setBusy(false);
    fileInput.value = "";
  }
}

function showResult(payload) {
  result.hidden = false;
  runIdEl.textContent = payload.run_id;
  reportLink.href = payload.report_url;
  preview.src = payload.video_url;
  coverageEl.replaceChildren(
    ...payload.rule_coverage.map((entry) => {
      const li = document.createElement("li");
      li.innerHTML = `<span class="rid">${entry.rule_id}</span><span>${entry.reason_code}</span><span class="state">${entry.status}</span>`;
      return li;
    }),
  );
  incidentsEl.replaceChildren(
    ...payload.incidents.map((item) => {
      const li = document.createElement("li");
      li.innerHTML = `<span class="rid">${item.rule_id}</span><span>${item.observation_text}</span><span class="state">${item.status}</span>`;
      return li;
    }),
  );
}
