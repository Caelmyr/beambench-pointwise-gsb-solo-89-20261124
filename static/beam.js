const el = id => document.getElementById(id);
const settings = el("settings");
const fields = settings.elements;
const state = {panel: null, result: null, report: null, mode: "across", tool: "probe",
  boxStart: null, highlight: null, generation: 0, segment: null};
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
  for (const key of ["source", "row", "column", "threshold", "clip_low", "clip_high", "radius_step",
      "place_min", "place_width", "place_tol"]) {
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
    place_min:val("place_min"), place_width:val("place_width"), place_tol:val("place_tol"),
    place_segment:state.segment,
  };
}

function updateControls() {
  const visible = [...settings.querySelectorAll("[data-for]")];
  for (const label of visible) {
    label.hidden = !label.dataset.for.split(/\s+/).includes(state.mode);
  }
  el("sampling-fields").hidden = visible
    .filter(label => label.closest("#sampling-fields"))
    .every(label => label.hidden);
  el("placement-fields").hidden = !["across", "down"].includes(state.mode) || Boolean(state.report);
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
  state.segment = null;
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

function trace(canvas, mark) {
  const ctx = canvas.getContext("2d");
  ctx.beginPath();
  if (mark.kind === "rect") {
    const [l, t, r, b] = mark.box;
    ctx.fillStyle = "rgba(255,165,65," + (0.08 + mark.level / 940) + ")";
    ctx.fillRect(l, t, r - l + 1, b - t + 1);
    ctx.strokeStyle = "rgba(225,232,244,.57)";
    ctx.rect(l, t, r - l + 1, b - t + 1);
    ctx.stroke();
  } else if (mark.kind === "segment") {
    const [start, end] = mark.points;
    const width = state.panel.width;
    ctx.strokeStyle = "#7ff2a4";
    ctx.lineWidth = Math.max(2, width / 240);
    ctx.beginPath();
    ctx.moveTo(...start);
    ctx.lineTo(...end);
    ctx.stroke();
    const tick = Math.max(5, width / 110);
    for (const [x, y] of [start, end]) {
      ctx.beginPath();
      ctx.moveTo(x, y - tick);
      ctx.lineTo(x, y + tick);
      ctx.stroke();
    }
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
    ctx.stroke();
  }
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

function drawChart(values, shade = null) {
  const canvas = el("chart");
  canvas.hidden = !values.length;
  if (!values.length) return;
  const ctx = canvas.getContext("2d");
  const {width, height} = canvas;
  ctx.clearRect(0, 0, width, height);
  const pointX = index => 33 + (width - 43) * index / Math.max(1, values.length - 1);
  if (shade) {
    ctx.fillStyle = "rgba(127,242,164,.14)";
    ctx.fillRect(pointX(shade.start), 6, pointX(shade.end) - pointX(shade.start), height - 12);
    ctx.strokeStyle = "rgba(127,242,164,.55)";
    ctx.setLineDash([4, 3]);
    for (const index of [shade.start, shade.end]) {
      ctx.beginPath();
      ctx.moveTo(pointX(index), 6);
      ctx.lineTo(pointX(index), height - 6);
      ctx.stroke();
    }
    ctx.setLineDash([]);
  }
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
    const x = pointX(index);
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
      const link = button("Probe " + row.x + ", " + row.y, () => probe([row.x, row.y]));
      tr.insertCell().append(link);
    }
  }
  list(el("rows"), [element]);
}

function metric(label, value) {
  const item = document.createElement("div");
  item.className = "place-metric";
  const caption = document.createElement("span");
  caption.textContent = label;
  const amount = document.createElement("strong");
  amount.textContent = value;
  item.append(caption, amount);
  return item;
}

function showPlacement(display) {
  const card = el("placement");
  const finder = display.placement;
  const profileMode = ["across", "down"].includes(display.mode);
  card.hidden = !profileMode || !finder;
  if (!profileMode || !finder) return;
  card.replaceChildren();
  const head = document.createElement("div");
  head.className = "place-head";
  const title = document.createElement("h3");
  title.textContent = "Placement finder";
  head.append(title);
  card.append(head);

  if (display.placement_adopted) {
    card.classList.add("adopted");
    const [start, end] = state.segment ?? [];
    const banner = document.createElement("div");
    banner.className = "place-banner";
    banner.textContent = "Adopted segment — profile, table and CSV measure this range only on original coordinates.";
    const metrics = document.createElement("div");
    metrics.className = "place-metrics";
    metrics.append(
      metric("Profile positions", (start ?? "?") + " – " + (end ?? "?")),
      metric("Width px", (end ?? 0) - (start ?? 0) + 1),
      metric("Brightness min", display.summary ? Math.min(...display.chart).toFixed(2) : "–"),
      metric("Brightness max", display.summary ? Math.max(...display.chart).toFixed(2) : "–"),
      metric("Swing", display.summary.Spread)
    );
    const clearBtn = document.createElement("button");
    clearBtn.type = "button";
    clearBtn.textContent = "Clear segment · measure full line";
    clearBtn.onclick = run(clearSegment);
    if (state.report) clearBtn.disabled = true;
    card.append(banner, metrics, clearBtn);
    return;
  }
  card.classList.remove("adopted");
  const selected = finder.selected;
  if (!selected) {
    const empty = document.createElement("p");
    empty.className = "place-empty";
    empty.textContent = finder.message || "No continuous segment meets all three requirements.";
    card.append(empty);
    if (finder.runs?.length) {
      const runs = document.createElement("p");
      runs.className = "place-runs";
      runs.textContent = finder.runs.length + " lit run(s) separated below " + finder.minimum +
        "; none reaches the " + finder.min_width + " px shortest width within the tolerance.";
      card.append(runs);
    }
    return;
  }
  const best = finder.candidates[0];
  const metrics = document.createElement("div");
  metrics.className = "place-metrics";
  metrics.append(
    metric("Positions", selected.start + " – " + selected.end),
    metric("Width px", best.width),
    metric("Min / max", best.min + " / " + best.max),
    metric("Swing", best.spread),
    metric("Tolerance reserve", best.margin),
    metric("Match score", best.score)
  );
  const why = document.createElement("p");
  why.className = "place-reason";
  why.textContent = "Why here: " + best.reason + " Score equally balances width vs. reserve within this line's options (" +
    Math.round(best.width_score * 100) + "% width position, " +
    Math.round(best.margin_score * 100) + "% reserve position).";
  const adoptBtn = document.createElement("button");
  adoptBtn.type = "button";
  adoptBtn.className = "primary";
  adoptBtn.textContent = "Adopt this segment";
  adoptBtn.onclick = run(() => adoptSegment(selected.start, selected.end));
  card.append(metrics, why, adoptBtn);

  if (finder.candidates.length > 1) {
    const alternatives = document.createElement("div");
    alternatives.className = "place-alts";
    const caption = document.createElement("small");
    caption.textContent = "Alternative continuous runs (wider vs. flatter trade-off):";
    alternatives.append(caption);
    for (const candidate of finder.candidates.slice(1)) {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "place-alt";
      row.innerHTML = "<span>" + candidate.start + " – " + candidate.end + " · " + candidate.width +
        " px</span><span>swing " + candidate.spread + " · reserve " + candidate.margin +
        " · score " + candidate.score + "</span>";
      row.onclick = run(() => adoptSegment(candidate.start, candidate.end));
      alternatives.append(row);
    }
    card.append(alternatives);
  }
  if (finder.runs.length > 1) {
    const note = document.createElement("p");
    note.className = "place-runs";
    note.textContent = finder.runs.length + " lit runs on this line; dark trenches below " +
      finder.minimum + " are kept separate.";
    card.append(note);
  }
}

async function adoptSegment(start, end) {
  if (state.report) return;
  state.segment = [start, end];
  await measure();
  notice("Segment adopted — the profile and CSV now measure this range only.");
}

async function clearSegment() {
  if (state.report) return;
  state.segment = null;
  await measure();
  notice("Full-line measurement restored.");
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
  let shade = null;
  if (["across", "down"].includes(display.mode) && display.placement) {
    if (display.placement_adopted && state.segment) {
      shade = {start: 0, end: display.chart.length - 1};
    } else if (display.placement.selected) {
      shade = display.placement.selected;
    }
  }
  drawChart(display.chart, shade);
  table(display);
  showPlacement(display);
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
  state.segment = null;
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
  state.segment = saved.placement_adopted && saved.placement?.selected
    ? [saved.placement.selected.start, saved.placement.selected.end] : null;
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
settings.onsubmit = run(async () => {
  state.segment = null;
  await measure();
});
fields.mode.onchange = run(async () => {
  state.mode = fields.mode.value;
  state.segment = null;
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
  state.segment = null;
  const panel = await api(path("/settings"), "PUT", {revision:state.panel.revision, settings:chosen()});
  if (generation !== state.generation) return;
  state.panel = panel;
  fill(panel.settings);
  updateControls();
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
