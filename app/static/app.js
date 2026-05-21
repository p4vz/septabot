const REFRESH_MS = 60_000;

const fmt = {
  pct: (v) => (v == null ? "" : ` · ${v}% precip`),
  late: (m) => `${m}m late`,
};

async function fetchJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url} -> ${r.status}`);
  return r.json();
}

function el(tag, className, text) {
  const e = document.createElement(tag);
  if (className) e.className = className;
  if (text != null) e.textContent = text;
  return e;
}

function renderWeather(node, w) {
  node.innerHTML = "";
  if (!w || !w.current) {
    node.append(el("div", "text-slate-500", "No data"));
    return;
  }
  const c = w.current;
  const head = el("div", "text-lg font-semibold text-slate-100");
  head.textContent = `${c.temperature}°${c.temperature_unit} · ${c.short_forecast}`;
  node.append(head);
  node.append(el("div", "text-xs text-slate-400", `${c.name} · wind ${c.wind}${fmt.pct(c.precipitation_probability)}`));
  (w.upcoming || []).slice(0, 3).forEach((p) => {
    const row = el("div", "mt-2 flex justify-between text-xs");
    row.append(el("span", "text-slate-300", `${p.name}`));
    row.append(el("span", "text-slate-400", `${p.temperature}° ${p.short_forecast}${fmt.pct(p.precipitation_probability)}`));
    node.append(row);
  });
}

function renderList(node, items, render, emptyText) {
  node.innerHTML = "";
  if (!items || items.length === 0) {
    node.append(el("div", "text-slate-500", emptyText));
    return;
  }
  items.forEach((it) => node.append(render(it)));
}

function renderAlert(a) {
  const row = el("div", "py-2 border-b border-slate-800 last:border-b-0");
  row.append(el("div", "text-xs font-semibold text-amber-200", `${a.route_id} · ${a.mode}`));
  row.append(el("div", "text-xs text-slate-300", a.current_message || a.advisory_message || ""));
  return row;
}

function renderTrain(t) {
  const row = el("div", "py-1.5 border-b border-slate-800 last:border-b-0 flex justify-between");
  row.append(el("span", "text-slate-200", `#${t.train_number} · ${t.line} → ${t.destination}`));
  row.append(el("span", "text-emerald-300 text-xs", fmt.late(t.late_minutes)));
  return row;
}

function renderDetour(d) {
  const row = el("div", "py-2 border-b border-slate-800 last:border-b-0");
  row.append(el("div", "text-xs font-semibold text-fuchsia-200", `Route ${d.route_id}`));
  row.append(el("div", "text-xs text-slate-300", d.reason || d.current_message || ""));
  if (d.start_location || d.end_location) {
    row.append(el("div", "text-xs text-slate-500", `${d.start_location} → ${d.end_location}`));
  }
  return row;
}

function renderTraffic(e) {
  const row = el("div", "py-2 border-b border-slate-800 last:border-b-0");
  row.append(el("div", "text-xs font-semibold text-rose-200", `${e.roadway || "?"} ${e.direction || ""}`));
  row.append(el("div", "text-xs text-slate-300", e.headline || e.description || ""));
  return row;
}

async function refresh() {
  const updated = document.getElementById("updated");
  try {
    const snap = await fetchJSON("/commute?min_late=5");
    renderWeather(document.getElementById("weather"), snap.weather);
    renderList(document.getElementById("alerts"), snap.septa_alerts, renderAlert, "No active alerts");
    renderList(document.getElementById("trains"), snap.train_delays, renderTrain, "All trains on time");
    renderList(document.getElementById("detours"), snap.bus_detours, renderDetour, "No detours");
    renderList(document.getElementById("traffic"), snap.traffic_events, renderTraffic, "No traffic events (or 511PA key not configured)");
    updated.textContent = new Date().toLocaleTimeString();
  } catch (err) {
    updated.textContent = `error: ${err.message}`;
  }
}

document.getElementById("refresh").addEventListener("click", refresh);
refresh();
setInterval(refresh, REFRESH_MS);
