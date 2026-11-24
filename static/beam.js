const el = id => document.getElementById(id);
const settings = el("settings");
const fields = settings.elements;
const state = {panel: null, result: null, report: null, mode: "across", tool: "probe",
  boxStart: null, highlight: null, generation: 0};
const base = "/beam/panels";
const toolNotes = {
  probe:"Click the photo to read its RGB and brightness.", box:"Pick two corners of the inspection box.",
  row:"Click inside the box to move the horizontal profile.", column:"Click inside the box to move the vertical profile.",
  origin:"Click the center for radial sampling."
};

async function api(path, method = "GET", data) {
  const options = {method};
  if (data instanceof FormData) {
    options.body = data;
  } else if (data !== undefined) {
    options.headers = {"Content-Type":"application/json"};
    options.body = JSON.stringify(data);
  }
  const response = await fetch(path, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "The inspection could not be completed.");
  return result;
}

function notice(message, error = false) {
  el("status").textContent = message;
  el("status").dataset.error = error;
}

function run(action) {
  return async event => {
    event?.preventDefault();
    try {
      await action(event);
    } catch (error) {
      notice(error.message, true);
    }
  };
}

function path(suffix = "") {
  return base + "/" + state.panel.id + suffix;
}

function sourceURL(role, saved = null, download = false) {
  const params = new URLSearchParams();
  if (saved) params.set("report", saved);
  if (download) params.set("download", "1");
  return path("/source/" + role + ".png") + (params.size ? "?" + params : "");
}

function selectedPhoto() {
  return state.report?.source ?? fields.source.value;
}

function option(value, label) {
  return new Option(label, value);
}

function button(label, action, active) {
  const entry = document.createElement("button");
  entry.type = "button";
  entry.textContent = label;
  entry.classList.toggle("active", Boolean(active));
  entry.onclick = run(action);
  return entry;
}

function list(container, values) {
  container.replaceChildren(...values);
}

async function showLibrary() {
  const panels = await api(base);
  list(el("panels"), panels.map(item => button(item.title, () => open(item.id), item.id === state.panel?.id)));
  el("archives").hidden = !state.panel?.reports.length;
  list(el("reports"), (state.panel?.reports ?? []).map(item => button(
    item.heading + " · " + item.created.slice(0, 10), () => openReport(item.id), item.id === state.report?.id
  )));
}

function fill(current) {
  const {box, origin} = current;
  for (const key of ["source", "row", "column", "threshold", "clip_low", "clip_high", "radius_step"]) {
    fields[key].value = current[key];
  }
  [fields.left.value, fields.top.value, fields.right.value, fields.bottom.value] = box;
  [fields.originX.value, fields.originY.value] = origin;
}

function chosen() {
  const val = name => fields[name].valueAsNumber;
  return {
    box:["left", "top", "right", "bottom"].map(val), row:val("row"), column:val("column"),
    origin:["originX", "originY"].map(val), source:fields.source.value, threshold:val("threshold"),
    clip_low:val("clip_low"), clip_high:val("clip_high"), radius_step:val("radius_step"),
  };
}

function updateControls() {
  const visible = [...settings.querySelectorAll("[data-for]")];
  for (const label of visible) label.hidden = label.dataset.for !== state.mode;
  el("sampling-fields").hidden = visible.every(label => label.hidden);
  fields.mode.value = state.mode;
  for (const control of el("tools").querySelectorAll("button")) {
    control.hidden = Boolean(state.report) && control.dataset.tool !== "probe";
    control.setAttribute("aria-pressed", control.dataset.tool === state.tool);
  }
  const editing = !state.report;
  el("live-controls").hidden = !editing;
  el("saved-controls").hidden = editing;
  el("live").hidden = editing;
  el("save-report").hidden = !editing;
  el("tool-note").textContent = state.boxStart ? "Choose the opposite corner." : toolNotes[state.tool];
}

function updatePhoto() {
  const saved = state.report?.id ?? null;
  const role = selectedPhoto();
  const entry = (state.report || state.panel).sources[role];
  const photo = el("photo");
  const url = sourceURL(role, saved);
  if (photo.getAttribute("src") !== url) photo.src = url;
  el("source-link").href = sourceURL(role, saved, true);
  const {width, height} = state.panel;
  el("stage").style.aspectRatio = width + " / " + height;
  el("source-note").textContent = (state.panel.synthetic ? "Synthetic sample · " : "") + width + " × " + height + " px · " + entry.name;
  el("prepare").href = "/prepare?panel=" + state.panel.id;
}

async function open(id, existing = null) {
  const generation = ++state.generation;
  const panel = existing || await api(base + "/" + id);
  if (generation !== state.generation) return;
  state.panel = panel;
  state.result = state.report = state.boxStart = state.highlight = null;
  state.mode = "across";
  state.tool = "probe";
  localStorage.setItem("beambench-panel", panel.id);
  el("empty").hidden = true;
  el("desk").hidden = false;
  el("title").textContent = panel.title;
  el("probe-result").textContent = "";
  list(fields.source, Object.keys(panel.sources).map(role => option(role, role === "a" ? "Main photo" : "Reference photo")));
  fields.mode.querySelector('[value="compare"]').disabled = !panel.sources.b;
  fill(panel.settings);
  updateControls();
  updatePhoto();
  await Promise.all([showLibrary(), measure()]);
}

const clipColors = {single:"#ffd065", multi:"#ff4848"};

function trace(canvas, mark) {
  const ctx = canvas.getContext("2d");
  ctx.beginPath();
  if (mark.kind === "rect") {
    const [l, t, r, b] = mark.box;
    ctx.fillStyle = "rgba(255,165,65," + (0.08 + mark.level / 940) + ")";
    ctx.fillRect(l, t, r - l + 1, b - t + 1);
    ctx.strokeStyle = "rgba(225,232,244,.57)";
    ctx.rect(l, t, r - l + 1, b - t + 1);
  } else if (mark.kind === "clip_pixels") {
    ctx.fillStyle = clipColors[mark.class];
    for (const [y, x0, x1] of mark.runs) ctx.fillRect(x0, y, x1 - x0 + 1, 1);
    return;
  } else {
    ctx.strokeStyle = "#ffd065";
    if (mark.kind === "circle") {
      ctx.arc(...mark.center, mark.radius, 0, Math.PI * 2);
    } else {
      const [first, ...remaining] = mark.points;
      ctx.moveTo(...first);
      for (const point of remaining) ctx.lineTo(...point);
      if (mark.kind === "outline") ctx.closePath();
    }
  }
  ctx.stroke();
}

function drawMarks() {
  const canvas = el("marks");
  const {width, height} = state.panel;
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  const current = state.result;
  if (current) {
    ctx.lineWidth = Math.max(1, width / 465);
    for (const mark of current.marks) trace(canvas, mark);
    const [l, t, r, b] = current.settings.box;
    ctx.strokeStyle = "#4fe1df";
    ctx.strokeRect(l + .5, t + .5, r - l, b - t);
  }
  if (state.highlight || state.boxStart) {
    const [x, y] = state.highlight || state.boxStart;
    ctx.strokeStyle = "#cefdfc";
    ctx.lineWidth = Math.max(1, width / 420);
    ctx.beginPath();
    ctx.arc(x, y, Math.max(5, width / 120), 0, Math.PI * 2);
    ctx.stroke();
  }
}

function drawChart(values) {
  const canvas = el("chart");
  canvas.hidden = !values.length;
  if (!values.length) return;
  const ctx = canvas.getContext("2d");
  const {width, height} = canvas;
  ctx.clearRect(0, 0, width, height);
  for (const level of [0, 64, 128, 192, 255]) {
    const y = 11 + (255 - level) * .39;
    ctx.strokeStyle = "#303a4b";
    ctx.beginPath();
    ctx.moveTo(33, y);
    ctx.lineTo(width - 10, y);
    ctx.stroke();
    ctx.font = "10px sans-serif";
    ctx.fillStyle = "#a1adc1";
    ctx.fillText(level, 8, y + 3);
  }
  ctx.strokeStyle = "#ffd065";
  ctx.lineWidth = 2.3;
  ctx.beginPath();
  values.forEach((value, index) => {
    const x = 33 + (width - 43) * index / Math.max(1, values.length - 1);
    const y = 11 + (255 - value) * .39;
    if (index) ctx.lineTo(x, y);
    else ctx.moveTo(x, y);
    if (values.length === 1) ctx.arc(x, y, 2, 0, Math.PI * 2);
  });
  ctx.stroke();
}

function table(display) {
  if (!display.rows.length) {
    const empty = document.createElement("p");
    empty.textContent = "No samples meet this inspection’s settings.";
    list(el("rows"), [empty]);
    return;
  }
  const element = document.createElement("table");
  const columns = display.columns;
  const hasLocation = columns.includes("x") && columns.includes("y");
  const labels = element.createTHead().insertRow();
  for (const label of [...columns, ...(hasLocation ? ["Source position"] : [])]) {
    const cell = document.createElement("th");
    cell.textContent = label.replaceAll("_", " ");
    cell.scope = "col";
    labels.append(cell);
  }
  const body = element.createTBody();
  for (const row of display.rows) {
    const tr = body.insertRow();
    for (const column of columns) tr.insertCell().textContent = row[column];
    if (hasLocation) {
      const px = Number.isFinite(row.pick_x) ? row.pick_x : row.x;
      const py = Number.isFinite(row.pick_y) ? row.pick_y : row.y;
      const link = button("Probe " + px + ", " + py, () => probe([px, py]));
      tr.insertCell().append(link);
    }
  }
  list(el("rows"), [element]);
}

function show(display) {
  state.result = display;
  el("result-title").textContent = display.heading;
  el("result-source").textContent = display.source === "a" ? "Main photo" : "Reference photo";
  const measures = Object.entries(display.summary).map(([name, value]) => {
    const card = document.createElement("div");
    card.className = "measure";
    const caption = document.createElement("span");
    caption.textContent = name;
    const amount = document.createElement("strong");
    amount.textContent = value;
    card.append(caption, amount);
    return card;
  });
  list(el("measures"), measures);
  el("clip-legend").hidden = display.mode !== "clipping";
  drawChart(display.chart);
  table(display);
  drawMarks();
}

async function measure() {
  const generation = ++state.generation;
  const result = await api(path("/preview"), "POST", {mode:state.mode, settings:chosen()});
  if (generation === state.generation && !state.report) {
    updatePhoto();
    show(result);
  }
}

async function probe(point) {
  const generation = state.generation;
  const data = state.report ? {point, report:state.report.id} : {point, settings:chosen()};
  const sample = await api(path("/point"), "POST", data);
  if (generation !== state.generation) return;
  state.highlight = [sample.x, sample.y];
  el("probe-result").textContent = "(" + sample.x + ", " + sample.y + ") · RGB " +
    sample.rgb.join(" / ") + " · brightness " + sample.luma;
  drawMarks();
}

async function place(point) {
  const [x, y] = point;
  if (!point.every(Number.isInteger) || x < 0 || y < 0 || x >= state.panel.width || y >= state.panel.height) {
    throw new Error("Pick a pixel inside the source photo.");
  }
  if (state.tool === "probe" || state.report) return probe(point);
  const current = chosen();
  if (state.tool === "box") {
    if (!state.boxStart) {
      state.boxStart = point;
      updateControls();
      drawMarks();
      return;
    }
    const [ax, ay] = state.boxStart;
    current.box = [Math.min(ax,x), Math.min(ay,y), Math.max(ax,x), Math.max(ay,y)];
    const [l,t,r,b] = current.box;
    current.row = Math.min(b, Math.max(t, current.row));
    current.column = Math.min(r, Math.max(l, current.column));
    state.boxStart = null;
  } else if (state.tool === "origin") {
    current.origin = point;
    state.mode = "falloff";
  } else {
    const [l,t,r,b] = current.box;
    if (x < l || x > r || y < t || y > b) throw new Error("Pick inside the inspection box.");
    if (state.tool === "row") {
      current.row = y;
      state.mode = "across";
    } else {
      current.column = x;
      state.mode = "down";
    }
  }
  state.highlight = null;
  fill(current);
  updateControls();
  await measure();
}

async function openReport(id, existing = null) {
  const generation = ++state.generation;
  const saved = existing || await api(path("/reports/" + id));
  if (generation !== state.generation) return;
  state.report = saved;
  state.tool = "probe";
  state.boxStart = state.highlight = null;
  el("probe-result").textContent = "";
  el("saved-date").textContent = saved.created.slice(0, 10);
  const download = path("/reports/" + saved.id);
  el("csv").href = download + "/report.csv";
  el("overlay").href = download + "/overlay.png";
  updateControls();
  updatePhoto();
  show(saved);
  await showLibrary();
}

async function demo() {
  const panel = await api("/beam/demo", "POST");
  await open(panel.id, panel);
  notice("Synthetic lighting test opened.");
}

for (const id of ["demo", "empty-demo"]) el(id).onclick = run(demo);
el("intake").onsubmit = run(async event => {
  const panel = await api(base, "POST", new FormData(event.currentTarget));
  el("intake").reset();
  await open(panel.id, panel);
  notice("Photos imported.");
});
el("live").onclick = run(() => open(state.panel.id));
settings.onsubmit = run(measure);
fields.mode.onchange = run(async () => {
  state.mode = fields.mode.value;
  updateControls();
  await measure();
});
fields.source.onchange = run(async () => {
  state.highlight = null;
  el("probe-result").textContent = "";
  await measure();
});
el("tools").onclick = run(async event => {
  const tool = event.target.closest("[data-tool]");
  if (!tool) return;
  state.tool = tool.dataset.tool;
  state.boxStart = null;
  updateControls();
  drawMarks();
});
el("stage").onclick = run(event => {
  const rect = el("stage").getBoundingClientRect();
  const x = Math.floor((event.clientX - rect.left) * state.panel.width / rect.width);
  const y = Math.floor((event.clientY - rect.top) * state.panel.height / rect.height);
  return place([x, y]);
});
el("coordinates").onsubmit = run(event => {
  const inputs = event.currentTarget.elements;
  return place([inputs.x.valueAsNumber, inputs.y.valueAsNumber]);
});
el("save-setup").onclick = run(async () => {
  const generation = ++state.generation;
  const panel = await api(path("/settings"), "PUT", {revision:state.panel.revision, settings:chosen()});
  if (generation !== state.generation) return;
  state.panel = panel;
  fill(panel.settings);
  await measure();
  notice("Setup saved.");
});
el("save-report").onclick = run(async () => {
  const generation = ++state.generation;
  const result = await api(path("/reports"), "POST", {
    revision:state.panel.revision, mode:state.mode, settings:chosen()
  });
  if (generation !== state.generation) return;
  state.panel = result.panel;
  await openReport(result.report.id, result.report);
  notice("Inspection saved.");
});

run(async () => {
  const items = await api(base);
  const last = localStorage.getItem("beambench-panel");
  const panel = items.find(item => item.id === last) || items[0];
  if (panel) await open(panel.id, panel);
  else await showLibrary();
})();
