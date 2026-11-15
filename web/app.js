// Dashboard TCBA Kelompok 7 — membaca API Azure Function (read-only) dan menggambar tabel + grafik.
const API = (window.TCBA_API_BASE || "").replace(/\/$/, "") + "/api/";
const COLORS = { TLKM: "#c0392b", ISAT: "#e0a100", EXCL: "#0b5cab" };
const ARROW = { naik: "▲ Naik", stabil: "■ Stabil", turun: "▼ Turun" };
const charts = {};
const H = () => document.getElementById("horizon-sel").value;          // "1" = kuartal depan, "4" = tahun depan
const HQ = (sep = "?") => (H() === "4" ? `${sep}horizon=4` : "");
const BLK = { pasar: "Pasar", makro: "Makro", sentimen: "Sentimen", kontrol: "Kontrol" };

async function get(path) {
  const r = await fetch(API + path);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || `HTTP ${r.status}`);
  return j;
}
const pct = v => (v == null ? "–" : (v * 100).toFixed(0) + "%");
const num = (v, d = 2) => (v == null ? "–" : Number(v).toFixed(d));
const pill = l => `<span class="pill ${l}">${ARROW[l] || l}</span>`;
function draw(id, cfg) {
  if (typeof Chart === "undefined") return;                     // CDN grafik gagal dimuat: tabel tetap tampil
  if (charts[id]) charts[id].destroy();
  charts[id] = new Chart(document.getElementById(id), cfg);
}
function fail(el, e) { document.querySelector(el).innerHTML = `<tr><td class="err" colspan="9">${e.message}</td></tr>`; }

async function loadPredictions() {
  try {
    const p = await get("predictions" + HQ());
    const ratio = (p.target_ratio || "roe_ttm").replace("_ttm", "").toUpperCase();
    document.getElementById("model-info").textContent =
      `Model: ${p.model} · target: arah ${ratio} TTM ${p.horizon === 4 ? "4 kuartal ke depan" : "kuartal depan"} · dilatih ${String(p.trained_at || "").slice(0, 16).replace("T", " ")} UTC · macro-F1 uji ${num(p.test_macro_f1)} (baseline ${num(p.baseline_persistence_f1)})`;
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
  } catch (e) { fail("#tbl-pred tbody", e); document.getElementById("cards").innerHTML = ""; }
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
    const m = await get("metrics" + HQ());
    const fi = (m.feature_importance || []).slice(0, 12).reverse();
    draw("ch-fi", { type: "bar", data: { labels: fi.map(x => x.feature), datasets: [
        { label: "Penurunan macro-F1 jika fitur diacak", data: fi.map(x => x.importance), backgroundColor: "#2a9d8f" }] },
      options: { indexAxis: "y", maintainAspectRatio: false, plugins: { legend: { display: false } } } });
  } catch (e) { console.warn(e); }
}

async function loadBacktest() {
  try {
    const b = (await get("backtest" + HQ())).items;
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

// ---- Prediksi real-time (GET /api/predict_live): fitur dihitung saat dipanggil dari data 90 hari terakhir
let liveTimer = null, lastLive = {};
const signed = (v, d = 1, unit = "") => (v == null ? "–" : (v > 0 ? "+" : "") + Number(v).toFixed(d) + unit);

async function loadLive() {
  const btn = document.getElementById("live-run");
  btn.disabled = true;
  try {
    const qs = new URLSearchParams();
    const tic = document.getElementById("live-tic").value;
    if (tic) qs.set("ticker", tic);
    if (H() === "4") qs.set("horizon", "4");
    document.querySelectorAll("#sim-box input[data-f]").forEach(i => { if (i.value !== "") qs.set(i.dataset.f, i.value); });
    const t0 = performance.now();
    const d = await get("predict_live" + (qs.toString() ? "?" + qs : ""));
    const rtt = Math.round(performance.now() - t0);
    const sim = d.mode === "simulasi";
    const badge = document.getElementById("live-badge");
    badge.textContent = sim ? "SIMULASI" : "LIVE";
    badge.className = "badge live-badge pulse" + (sim ? " sim" : "");
    setTimeout(() => badge.classList.remove("pulse"), 1000);
    const at = new Date(d.generated_at).toLocaleTimeString("id-ID");
    document.getElementById("live-info").textContent =
      `Dihitung ${at} · model ${d.model} · server ${d.latency_ms} ms · total ${rtt} ms`;
    document.querySelector("#tbl-live tbody").innerHTML = d.items.map(r => {
      const prev = lastLive[r.ticker], ch = prev && prev !== r.prediction && sim ? " changed" : "";
      return `<tr><td><b>${r.ticker}</b></td><td>${r.fundamental_quarter}</td><td>${r.predicted_quarter}</td>
        <td class="${ch.trim()}">${pill(r.prediction)}</td><td>${pct(r.proba_naik)}</td><td>${pct(r.proba_stabil)}</td><td>${pct(r.proba_turun)}</td>
        <td>${signed(r.live_features.ret_q, 1, "%")}</td><td>${signed(r.live_features.sent_mean, 2)}</td><td>${r.data_as_of.prices || "–"}</td></tr>`;
    }).join("");
    if (!sim) { d.items.forEach(r => (lastLive[r.ticker] = r.prediction)); fillSimPlaceholders(d.items); }
    const stale = d.items.filter(r => r.fundamentals_stale).map(r => r.ticker);
    const w = document.getElementById("live-warn");
    w.hidden = !stale.length;
    w.textContent = stale.length ? `Laporan keuangan terakhir ${stale.join(", ")} masih ${d.items[0].fundamental_quarter}, ` +
      `jadi prediksi masih untuk ${d.items[0].predicted_quarter} (kuartal sekarang ${d.current_quarter}). ` +
      `Tambahkan laporan kuartal terbaru agar prediksi maju.` : "";
  } catch (e) { fail("#tbl-live tbody", e); }
  btn.disabled = false;
}

function fillSimPlaceholders(items) {
  const r = items.find(x => x.ticker === (document.getElementById("live-tic").value || "TLKM")) || items[0];
  if (!r) return;
  document.querySelectorAll("#sim-box input[data-f]").forEach(i => {
    const v = r.live_features[i.dataset.f];
    i.placeholder = v == null ? "" : `aktual ${r.ticker}: ${Number(v).toFixed(2)}`;
  });
}

function setupLive() {
  document.getElementById("live-run").onclick = loadLive;
  document.getElementById("live-tic").onchange = loadLive;
  document.getElementById("sim-reset").onclick = () => {
    document.querySelectorAll("#sim-box input[data-f]").forEach(i => (i.value = ""));
    loadLive();
  };
  document.querySelectorAll("#sim-box input[data-f]").forEach(i => (i.onchange = loadLive));
  document.getElementById("live-auto").onchange = e => {
    clearInterval(liveTimer);
    if (e.target.checked) liveTimer = setInterval(loadLive, 60000);
  };
}

// ---- Uji akurasi: prediksi yang pernah dibuat vs aktual (GET /api/evaluation)
async function loadEvaluation() {
  try {
    const d = await get("evaluation" + HQ());
    document.getElementById("eval-badge").textContent = d.evaluated
      ? `${d.correct}/${d.evaluated} benar (${pct(d.accuracy)})` : "belum ada yang bisa dinilai";
    const st = { benar: "✔ benar", salah: "✘ salah", "menunggu laporan": "⏳ menunggu laporan" };
    document.querySelector("#tbl-eval tbody").innerHTML = d.items.map(r => `<tr>
      <td><b>${r.ticker}</b></td><td>${r.base_quarter}</td><td>${r.predicted_quarter}</td><td>${pill(r.prediction)}</td>
      <td>${r.actual ? pill(r.actual) : "–"}</td><td>${num(r.base_value)}% → ${r.actual_value == null ? "?" : num(r.actual_value) + "%"}</td>
      <td class="st-${String(r.status).split(" ")[0]}">${st[r.status] || r.status}</td>
      <td>${String(r.generated_at || "").slice(0, 10)}</td></tr>`).join("") ||
      `<tr><td colspan="8" class="hint">Belum ada riwayat prediksi.</td></tr>`;
  } catch (e) { fail("#tbl-eval tbody", e); }
}

// ---- Analisis pengaruh (GET /api/analysis)
const rhoColor = v => {
  if (v == null) return "";
  const a = Math.min(1, Math.abs(v)), c = v > 0 ? "30,142,90" : "192,57,43";
  return `background:rgba(${c},${(a * 0.55).toFixed(2)})`;
};
const pfmt = p => (p == null ? "–" : p < 0.001 ? "<0,001" : p.toFixed(3));

async function loadAnalysis() {
  try {
    const qs = new URLSearchParams({ ratio: document.getElementById("an-ratio").value, lag: document.getElementById("an-lag").value });
    const tic = document.getElementById("an-tic").value;
    if (tic) qs.set("ticker", tic);
    const a = await get("analysis?" + qs);
    const rg = a.regresi || {};
    document.getElementById("an-info").textContent =
      `Y = ${a.y_label} · ${a.periode.join("–")} · n regresi = ${rg.n ?? "–"}`;
    document.getElementById("an-concl").innerHTML = a.kesimpulan.map(x => `<li>${x}</li>`).join("");
    document.querySelector("#tbl-corr tbody").innerHTML = a.korelasi.map(c => `<tr class="${c.sig ? "sig" : ""}">
      <td><span class="blk ${c.blok}">${BLK[c.blok]}</span></td><td>${c.label}</td><td class="num">${c.n}</td>
      <td class="num">${num(c.pearson_r)}</td><td class="rho" style="${rhoColor(c.spearman_rho)}">${num(c.spearman_rho)} ${c.sig || ""}</td>
      <td class="num">${pfmt(c.spearman_p)}</td></tr>`).join("");
    const bl = rg.blok || [], ml = a.ml_importance_blok || [];
    document.querySelector("#tbl-blocks tbody").innerHTML = bl.map(b => `<tr class="${b.sig ? "sig" : ""}">
      <td><span class="blk ${b.blok}">${BLK[b.blok]}</span> ${b.nama}</td><td class="num">${num(b.delta_r2_unik, 3)}</td>
      <td class="num">${num(b.delta_r2_sendiri, 3)}</td><td class="num">${num(b.f, 2)}</td><td class="num">${pfmt(b.p)} ${b.sig}</td></tr>`).join("") +
      (rg.ok ? `<tr><td><b>Ketiga blok sekaligus</b></td><td class="num"><b>${num(rg.delta_r2_integrasi, 3)}</b></td><td class="num">R² ${num(rg.r2_kontrol)} → ${num(rg.r2_lengkap)}</td>
        <td class="num">${num(rg.f_integrasi, 2)}</td><td class="num">${pfmt(rg.p_integrasi)} ${rg.sig_integrasi}</td></tr>` : "");
    draw("ch-blocks", { type: "bar", data: { labels: bl.map(b => BLK[b.blok]), datasets: [
        { label: "ΔR² unik (regresi)", data: bl.map(b => b.delta_r2_unik), backgroundColor: "#0b5cab" },
        { label: "Permutation importance (model ML)", data: bl.map(b => (ml.find(m => m.blok === b.blok) || {}).importance), backgroundColor: "#2a9d8f" }] },
      options: { maintainAspectRatio: false, indexAxis: "y" } });
    document.querySelector("#tbl-coef tbody").innerHTML = (rg.koefisien || []).map(c => `<tr class="${c.sig ? "sig" : ""}">
      <td>${c.label}</td><td><span class="blk ${c.blok}">${BLK[c.blok]}</span></td><td class="num">${num(c.beta, 3)} ${c.sig}</td>
      <td class="num">${num(c.se, 3)}</td><td class="num">${num(c.t, 2)}</td><td class="num">${pfmt(c.p)}</td></tr>`).join("") ||
      `<tr><td colspan="6" class="hint">Sampel terlalu kecil untuk regresi.</td></tr>`;
    const ex = (rg.dikecualikan || []).map(x => `${x.label} (${x.alasan})`).join("; ");
    document.getElementById("an-note").textContent = a.catatan + (ex ? ` Dikeluarkan dari regresi: ${ex}.` : "") +
      (rg.fixed_effect_emiten ? " Model memakai efek tetap emiten (perbedaan rata-rata antar-emiten dikendalikan)." : "");
  } catch (e) { document.getElementById("an-concl").innerHTML = `<li class="err">${e.message}</li>`; }
}

function onHorizon() {
  document.getElementById("horizon-hint").textContent = H() === "4"
    ? "Arah rasio TTM 4 kuartal setelah laporan terakhir (setara perubahan tahunan)."
    : "Arah rasio 1 kuartal setelah laporan terakhir.";
  lastLive = {};
  return Promise.all([loadPredictions(), loadBacktest(), loadMetrics(), loadLive(), loadEvaluation()]);
}

async function init() {
  try {
    const h = await get("health");
    document.getElementById("status").textContent = `API: ${h.status} · lake: ${h.lake_mode} · model ${h.model_ready ? "siap" : "belum ada"}`;
  } catch (e) { document.getElementById("status").textContent = "API tidak dapat dihubungi: " + e.message; }
  document.getElementById("ratio-sel").onchange = loadRatios;
  document.getElementById("px-sel").onchange = loadPrices;
  setupLive();
  document.getElementById("horizon-sel").onchange = onHorizon;
  ["an-ratio", "an-lag", "an-tic"].forEach(id => (document.getElementById(id).onchange = loadAnalysis));
  await Promise.all([loadPredictions(), loadRatios(), loadRetrain(), loadMetrics(), loadBacktest(), loadPrices(), loadLive(),
    loadEvaluation(), loadAnalysis()]);
}
init();
