// Dashboard TCBA Kelompok 7 — membaca API Azure Function (read-only) dan menggambar tabel + grafik.
const API = (window.TCBA_API_BASE || "").replace(/\/$/, "") + "/api/";
const COLORS = { TLKM: "#c0392b", ISAT: "#e0a100", EXCL: "#0b5cab" };
const ARROW = { naik: "▲ Naik", stabil: "■ Stabil", turun: "▼ Turun" };
const charts = {};

async function get(path) {
  const r = await fetch(API + path);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || `HTTP ${r.status}`);
  return j;
}
const pct = v => (v == null ? "–" : (v * 100).toFixed(0) + "%");
const num = (v, d = 2) => (v == null ? "–" : Number(v).toFixed(d));
const pill = l => `<span class="pill ${l}">${ARROW[l] || l}</span>`;
function draw(id, cfg) { if (charts[id]) charts[id].destroy(); charts[id] = new Chart(document.getElementById(id), cfg); }
function fail(el, e) { document.querySelector(el).innerHTML = `<tr><td class="err" colspan="9">${e.message}</td></tr>`; }

async function loadPredictions() {
  try {
    const p = await get("predictions");
    const ratio = (p.target_ratio || "roe_ttm").replace("_ttm", "").toUpperCase();
    document.getElementById("model-info").textContent =
      `Model: ${p.model} · target: arah ${ratio} TTM · dilatih ${String(p.trained_at || "").slice(0, 16).replace("T", " ")} UTC · macro-F1 uji ${num(p.test_macro_f1)}`;
    document.querySelector("#tbl-pred tbody").innerHTML = p.items.map(r => `<tr>
      <td><b>${r.ticker}</b></td><td>${r.base_quarter}</td><td>${r.predicted_quarter}</td><td>${pill(r.prediction)}</td>
      <td>${pct(r.proba_naik)}</td><td>${pct(r.proba_stabil)}</td><td>${pct(r.proba_turun)}</td><td>${num(r.current_value)}%</td></tr>`).join("");
    document.getElementById("cards").innerHTML = p.items.map(r => `<div class="card">
      <div class="t">${r.ticker}</div><div class="n">${ratio} TTM ${r.base_quarter}: ${num(r.current_value)}%</div>
      <div class="big ${r.prediction}">${ARROW[r.prediction]}</div>
      <div class="meta">${r.predicted_quarter} · keyakinan ${pct(r.confidence)}</div></div>`).join("");
    draw("ch-proba", { type: "bar", data: { labels: p.items.map(r => r.ticker), datasets: [
        { label: "naik", data: p.items.map(r => r.proba_naik), backgroundColor: "#1e8e5a" },
        { label: "stabil", data: p.items.map(r => r.proba_stabil), backgroundColor: "#d4a800" },
        { label: "turun", data: p.items.map(r => r.proba_turun), backgroundColor: "#c0392b" }] },
      options: { maintainAspectRatio: false, scales: { x: { stacked: true }, y: { stacked: true, max: 1,
        ticks: { callback: v => v * 100 + "%" } } } } });
  } catch (e) { fail("#tbl-pred tbody", e); }
}

async function loadRatios() {
  try {
    const key = document.getElementById("ratio-sel").value;
    const d = (await get("ratios")).items;
    const qs = [...new Set(d.map(r => r.quarter))].sort();
    const ds = Object.keys(COLORS).map(t => ({ label: t, borderColor: COLORS[t], backgroundColor: COLORS[t],
      pointRadius: 0, tension: .2, data: qs.map(q => (d.find(r => r.ticker === t && r.quarter === q) || {})[key] ?? null) }));
    draw("ch-ratio", { type: "line", data: { labels: qs, datasets: ds },
      options: { maintainAspectRatio: false, spanGaps: true, scales: { y: { ticks: { callback: v => v + "%" } } } } });
  } catch (e) { console.warn(e); }
}

async function loadRetrain() {
  try {
    const r = await get("retrain_log");
    document.getElementById("retrain-count").textContent = `${r.count}× retrain`;
    const it = r.items;
    draw("ch-retrain", { type: "bar", data: { labels: it.map((x, i) => `#${i + 1}`), datasets: [
        { type: "bar", label: "Macro-F1 uji (model)", data: it.map(x => x.test_macro_f1), backgroundColor: "#0b5cab" },
        { type: "line", label: "Baseline persistence", data: it.map(x => x.baseline_persistence_f1), borderColor: "#c0392b", pointRadius: 3 }] },
      options: { maintainAspectRatio: false, scales: { y: { min: 0, max: 1 } } } });
    document.querySelector("#tbl-rt tbody").innerHTML = it.map((x, i) => `<tr><td>${i + 1}</td>
      <td>${String(x.trained_at).slice(0, 16).replace("T", " ")}</td><td>${x.trigger}</td><td>${x.best_model}</td>
      <td>${x.data_max_quarter}</td><td>${num(x.test_macro_f1)}</td><td>${num(x.test_accuracy)}</td></tr>`).reverse().join("");
  } catch (e) { fail("#tbl-rt tbody", e); }
}

async function loadMetrics() {
  try {
    const m = await get("metrics");
    const fi = (m.feature_importance || []).slice(0, 12).reverse();
    draw("ch-fi", { type: "bar", data: { labels: fi.map(x => x.feature), datasets: [
        { label: "Penurunan macro-F1 jika fitur diacak", data: fi.map(x => x.importance), backgroundColor: "#2a9d8f" }] },
      options: { indexAxis: "y", maintainAspectRatio: false, plugins: { legend: { display: false } } } });
  } catch (e) { console.warn(e); }
}

async function loadBacktest() {
  try {
    const b = (await get("backtest")).items;
    const acc = b.filter(x => x.correct).length / Math.max(1, b.length);
    document.getElementById("bt-acc").textContent = `akurasi ${pct(acc)} dari ${b.length} prediksi`;
    document.querySelector("#tbl-bt tbody").innerHTML = b.map(x => `<tr><td><b>${x.ticker}</b></td><td>${x.quarter}</td>
      <td>${x.predicted_quarter}</td><td>${pill(x.actual)}</td><td>${pill(x.predicted)}</td><td>${x.correct ? "✔" : "✘"}</td></tr>`).join("");
  } catch (e) { fail("#tbl-bt tbody", e); }
}

async function loadPrices() {
  try {
    const t = document.getElementById("px-sel").value;
    const d = (await get(`prices?ticker=${t}&days=730`)).items;
    draw("ch-price", { type: "line", data: { labels: d.map(x => String(x.date).slice(0, 10)), datasets: [
        { label: `${t} close (Rp)`, data: d.map(x => x.close), borderColor: COLORS[t], pointRadius: 0, borderWidth: 1.5 }] },
      options: { maintainAspectRatio: false, scales: { x: { ticks: { maxTicksLimit: 10 } } } } });
  } catch (e) { console.warn(e); }
}

async function init() {
  try {
    const h = await get("health");
    document.getElementById("status").textContent = `API: ${h.status} · lake: ${h.lake_mode} · model ${h.model_ready ? "siap" : "belum ada"}`;
  } catch (e) { document.getElementById("status").textContent = "API tidak dapat dihubungi: " + e.message; }
  document.getElementById("ratio-sel").onchange = loadRatios;
  document.getElementById("px-sel").onchange = loadPrices;
  await Promise.all([loadPredictions(), loadRatios(), loadRetrain(), loadMetrics(), loadBacktest(), loadPrices()]);
}
init();
