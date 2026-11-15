// Sinyal Laba — dashboard TCBA Kelompok 7. Membaca API Azure Function (read-only) dan menggambar halaman.
const API = (window.TCBA_API_BASE || "").replace(/\/$/, "") + "/api/";
const TICKS = ["TLKM", "ISAT", "EXCL"];
const CO = {
  TLKM: { short: "Telkom", name: "Telkom Indonesia", full: "PT Telkom Indonesia (Persero) Tbk", c: "#2a78d6",
          desc: "BUMN telekomunikasi terbesar; induk Telkomsel (seluler) dan IndiHome (internet rumah)." },
  ISAT: { short: "Indosat", name: "Indosat Ooredoo Hutchison", full: "PT Indosat Tbk", c: "#eb6834",
          desc: "Operator seluler merek IM3 dan Tri; hasil merger Indosat Ooredoo dan Hutchison 3 (2022)." },
  EXCL: { short: "XLSmart", name: "XLSMART Telecom Sejahtera", full: "PT XLSMART Telecom Sejahtera Tbk", c: "#1baf7a",
          desc: "Dahulu XL Axiata; bergabung dengan Smartfren pada 2025 (merek XL, AXIS, Smartfren)." },
  JKSE: { short: "IHSG", name: "IHSG", c: "#898781" },
};
const DIR = { naik: "Naik", stabil: "Stabil", turun: "Turun" };
const ARROW = { naik: "▲", stabil: "■", turun: "▼" };
const DIRC = { naik: "#0a7d2c", stabil: "#c99a06", turun: "#c0392b" };
const RATIO = { roe_ttm: "ROE", roa_ttm: "ROA", npm_ttm: "NPM" };
const FEAT = {
  base_gap: "Efek basis (ROE kuartal ini − kuartal yang keluar)", ni_base_gap: "Efek basis laba (% dari laba setahun)",
  roe_q: "ROE kuartal ini", roe_q_drop: "ROE kuartal yang keluar dari hitungan", roe_ttm_chg1: "Perubahan ROE kuartal lalu",
  roe_ttm_chg4: "Perubahan ROE setahun", npm_ttm_chg1: "Perubahan margin laba kuartal lalu", rev_growth_yoy: "Pertumbuhan pendapatan",
  roe_ttm: "ROE (TTM)", roa_ttm: "ROA (TTM)", npm_ttm: "Margin laba bersih (TTM)", ret_q: "Return saham kuartalan",
  vol_q: "Volatilitas saham", volume_chg: "Perubahan volume transaksi", excess_ret_q: "Return di atas IHSG", ret_jkse: "Return IHSG",
  usd_idr_avg: "Kurs USD/IDR", usd_idr_chg: "Perubahan kurs USD/IDR", bi_rate: "BI-Rate", bi_rate_chg: "Perubahan BI-Rate",
  inflation_yoy: "Inflasi", sent_mean: "Skor sentimen berita", sent_n: "Jumlah berita", sent_neg_share: "Porsi berita negatif",
  has_news: "Ada berita", evt_merger: "Penanda merger", evt_akuntansi: "Penanda perubahan akuntansi", q_of_year: "Kuartal ke-", ticker: "Emiten",
};
const GLOSS = {
  roe: ["ROE (Return on Equity)", "Laba bersih dibagi modal pemegang saham. ROE 12% berarti setiap Rp100 modal menghasilkan laba Rp12 setahun."],
  roa: ["ROA (Return on Assets)", "Laba bersih dibagi total aset. Menunjukkan seberapa efisien aset dipakai untuk menghasilkan laba."],
  npm: ["NPM (Net Profit Margin)", "Laba bersih dibagi pendapatan. NPM 10% berarti dari Rp100 pendapatan tersisa laba Rp10."],
  ttm: ["TTM (trailing twelve months)", "Dihitung dari 4 kuartal terakhir, supaya pola musiman tidak membuat angka naik-turun palsu."],
  yoy: ["YoY (year on year)", "Dibandingkan dengan periode yang sama tahun sebelumnya."],
  walkforward: ["Uji maju-bertahap (walk-forward)", "Model hanya boleh belajar dari data sebelum kuartal yang ditebak, persis seperti memakai model di dunia nyata. Tidak ada contekan dari masa depan."],
  macrof1: ["Macro-F1", "Skor 0–1 yang menilai ketepatan untuk ketiga arah secara seimbang. Tebakan acak sekitar 0,33."],
  importance: ["Permutation importance", "Seberapa turun ketepatan model kalau satu faktor diacak. Makin besar, makin diandalkan model."],
  dr2: ["ΔR² (tambahan daya jelas)", "Berapa besar tambahan bagian naik-turun rasio yang bisa dijelaskan setelah satu kelompok data dimasukkan. 0,10 = tambahan 10%."],
  pvalue: ["p-value", "Peluang hasil seperti ini muncul hanya karena kebetulan. Di bawah 0,05 umumnya dianggap signifikan."],
  spearman: ["Korelasi Spearman (ρ)", "Ukuran −1 sampai 1 apakah dua hal cenderung bergerak searah (positif) atau berlawanan (negatif)."],
  efekbasis: ["Efek basis", "Laba setahun (TTM) kuartal depan = laba setahun sekarang + laba kuartal baru − laba kuartal yang keluar dari hitungan. Kalau laba kuartal ini lebih besar dari kuartal yang akan keluar, rasio cenderung naik."],
};
const charts = {};
const cache = {};
const state = { h: "1", tab: "ringkasan", histRatio: "roe_ttm", pxDays: 365 };

// ---------------------------------------------------------------- utilitas
async function get(path) {
  if (cache[path]) return cache[path];
  const p = fetch(API + path).then(async r => {
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || `HTTP ${r.status}`);
    return j;
  });
  cache[path] = p;
  p.catch(() => delete cache[path]);
  return p;
}
const HQ = (sep = "?") => (state.h === "4" ? `${sep}horizon=4` : "");
const pct = (v, d = 0) => (v == null ? "–" : (v * 100).toFixed(d).replace(".", ",") + "%");
const num = (v, d = 2) => (v == null || isNaN(v) ? "–" : Number(v).toFixed(d).replace(".", ","));
const pctv = (v, d = 1) => (v == null || isNaN(v) ? "–" : num(v, d) + "%");
const signed = (v, d = 1, u = "") => (v == null ? "–" : (v > 0 ? "+" : "") + num(v, d) + u);
const pill = l => `<span class="pill ${l}">${ARROW[l] || ""} ${DIR[l] || l}</span>`;
const tic = (t, label) => `<td class="tic" style="--c:${(CO[t] || {}).c || "#7c8a90"}">${label || t}</td>`;
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
function fail(sel, e, cols = 9) { const el = document.querySelector(sel); if (el) el.innerHTML = `<tr><td class="err" colspan="${cols}">Data belum bisa dimuat: ${esc(e.message)}</td></tr>`; }

function confidence(r) {
  const p = [r.proba_naik, r.proba_stabil, r.proba_turun].map(Number).sort((a, b) => b - a);
  const top = p[0], gap = p[0] - p[1];
  if (gap < 0.06) return { n: 1, label: "belum yakin", unclear: true };
  if (top >= 0.6) return { n: 3, label: "keyakinan tinggi" };
  if (top >= 0.45) return { n: 2, label: "keyakinan sedang" };
  return { n: 1, label: "keyakinan rendah" };
}
const barsHTML = c => `<span class="conf"><span class="bars" data-n="${c.n}" aria-hidden="true"><i></i><i></i><i></i></span>${c.label}</span>`;
function sentence(r, ratio) {
  const c = confidence(r), co = CO[r.ticker];
  if (c.unclear) return `Arah ${ratio} ${co.short} di ${r.predicted_quarter} belum jelas; peluang naik, stabil, dan turun hampir sama.`;
  const verb = { naik: "naik", stabil: "relatif stabil", turun: "turun" }[r.prediction];
  return `${ratio} ${co.short} diperkirakan <span class="dir ${r.prediction}">${verb}</span> di ${r.predicted_quarter}.`;
}

// ---------------------------------------------------------------- Chart.js dasar
if (window.Chart) {
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  Chart.defaults.font.size = 12;
  Chart.defaults.color = "#4a5a61";
  Chart.defaults.borderColor = "#e7ecea";
  Chart.defaults.plugins.legend.labels.boxWidth = 12;
  Chart.defaults.plugins.legend.labels.boxHeight = 12;
  Chart.defaults.plugins.tooltip.backgroundColor = "#16242b";
  Chart.defaults.plugins.tooltip.padding = 10;
  Chart.defaults.elements.line.borderWidth = 2;
  Chart.defaults.elements.point.radius = 0;
  Chart.defaults.elements.point.hoverRadius = 5;
  Chart.defaults.elements.bar.borderRadius = 4;
  Chart.defaults.interaction = { mode: "index", intersect: false };
  Chart.defaults.maintainAspectRatio = false;
}
function draw(id, cfg) {
  if (!window.Chart) return;
  const el = document.getElementById(id);
  if (!el) return;
  if (charts[id]) charts[id].destroy();
  charts[id] = new Chart(el, cfg);
}
const pctAxis = { ticks: { callback: v => v + "%" } };

// ---------------------------------------------------------------- status atas
async function loadStatus() {
  const api = document.getElementById("st-api");
  try { const h = await get("health"); api.textContent = h.model_ready ? "normal" : "model belum ada"; api.className = "ok"; }
  catch (e) { api.textContent = "API tidak terjangkau"; api.className = "bad"; }
  try {
    const r = await get("retrain_log");
    const last = r.items[r.items.length - 1] || {};
    document.getElementById("st-retrain").textContent = `${r.count}× (terakhir ${String(last.trained_at || "").slice(0, 10)})`;
    document.getElementById("st-data").textContent = last.data_max_quarter || "–";
  } catch (e) { /* biarkan */ }
  try { const m = await get("metrics"); document.getElementById("st-model").textContent = String(m.best_model || "–").replace("|", " · "); }
  catch (e) { /* biarkan */ }
}

// ---------------------------------------------------------------- RINGKASAN
async function renderRingkasan() {
  const ratioName = "ROE";
  let p, ratios;
  try { [p, ratios] = await Promise.all([get("predictions" + HQ()), get("ratios")]); }
  catch (e) { document.getElementById("hero-title").textContent = "Prediksi belum tersedia"; document.getElementById("companies").innerHTML = `<p class="err">${esc(e.message)}</p>`; return; }
  const items = TICKS.map(t => p.items.find(r => r.ticker === t)).filter(Boolean);
  const hz = state.h === "4" ? "Tahun depan" : "Kuartal depan";
  const cnt = { naik: 0, stabil: 0, turun: 0, unclear: 0 };
  items.forEach(r => (confidence(r).unclear ? cnt.unclear++ : cnt[r.prediction]++));
  const parts = [["naik", "naik"], ["stabil", "stabil"], ["turun", "turun"]].filter(([k]) => cnt[k]).map(([k, w]) => `${cnt[k]} ${w}`);
  if (cnt.unclear) parts.push(`${cnt.unclear} belum jelas`);
  document.getElementById("hero-title").textContent = `${hz}: ROE operator telko diperkirakan ${parts.join(", ")}`;

  const byT = t => ratios.items.filter(r => r.ticker === t);
  document.getElementById("companies").innerHTML = items.map(r => {
    const co = CO[r.ticker], hist = byT(r.ticker), last = hist[hist.length - 1] || {};
    const c = confidence(r);
    return `<article class="co" style="--c:${co.c}">
      <div class="co-head"><span class="mono" aria-hidden="true">${r.ticker}</span>
        <div><div class="co-name">${co.name}</div><div class="co-desc">${co.full}</div></div></div>
      <div class="co-now"><span class="co-roe">${pctv(r.current_value)}</span>
        <span class="co-roe-l">ROE ${r.base_quarter}<br>${hist.length > 4 ? `${signed(last.roe_ttm - hist[hist.length - 5].roe_ttm, 1, " poin")} dibanding setahun lalu` : ""}</span></div>
      <div class="spark"><canvas id="sp-${r.ticker}" aria-label="Riwayat ROE ${co.name}"></canvas></div>
      <div class="co-pred">${barsHTML(c)}<p>${sentence(r, ratioName)}</p></div>
    </article>`;
  }).join("");
  items.forEach(r => {
    const hist = byT(r.ticker);
    draw(`sp-${r.ticker}`, { type: "line", data: { labels: hist.map(x => x.quarter), datasets: [{ data: hist.map(x => x.roe_ttm),
      borderColor: CO[r.ticker].c, pointRadius: hist.map((_, i) => (i === hist.length - 1 ? 3 : 0)), pointBackgroundColor: CO[r.ticker].c, tension: .25 }] },
      options: { plugins: { legend: { display: false }, tooltip: { callbacks: { label: x => `ROE ${num(x.raw, 1)}%` } } },
        scales: { x: { display: false }, y: { display: false } } } });
  });

  renderHist(ratios);
  const latestQ = {};
  document.querySelector("#tbl-kpi tbody").innerHTML = TICKS.map(t => {
    const h = byT(t), l = h[h.length - 1] || {}; latestQ[t] = l.quarter;
    return `<tr>${tic(t)}<td class="num">${pctv(l.roe_ttm)}</td><td class="num">${pctv(l.roa_ttm)}</td><td class="num">${pctv(l.npm_ttm)}</td><td class="num">${signed(l.rev_growth_yoy, 1, "%")}</td></tr>`;
  }).join("");
  document.getElementById("kpi-q").textContent = "per " + [...new Set(Object.values(latestQ))].join(" / ");

  try {
    const m = await get("metrics" + HQ());
    const t = m.test || {}, b = (m.baselines || {}).persistence || {};
    document.getElementById("callout-akurasi").innerHTML = `<b>Seberapa bisa dipercaya?</b> Pada kuartal uji yang tidak dipakai
      untuk belajar, model ini tepat ${pct(t.accuracy)} dari ${t.n || "beberapa"} tebakan. Sebagai pembanding, tebakan acak tepat
      sekitar 33% dan cara naif (menganggap arahnya sama dengan kuartal lalu) ${pct(b.accuracy)}. Anggap perkiraan ini sebagai
      gambaran arah, bukan kepastian. Rinciannya ada di tab Akurasi model.`;
  } catch (e) { /* opsional */ }
}

function renderHist(ratios) {
  const key = state.histRatio, qs = [...new Set(ratios.items.map(r => r.quarter))].sort();
  draw("ch-hist", { type: "line", data: { labels: qs, datasets: TICKS.map(t => ({ label: CO[t].name, borderColor: CO[t].c, backgroundColor: CO[t].c, tension: .2,
      data: qs.map(q => (ratios.items.find(r => r.ticker === t && r.quarter === q) || {})[key] ?? null) })) },
    options: { spanGaps: true, plugins: { tooltip: { callbacks: { label: x => `${x.dataset.label}: ${num(x.raw, 1)}%` } } },
      scales: { x: { grid: { display: false }, ticks: { maxTicksLimit: 8 } }, y: pctAxis } } });
  document.querySelector("#tab-ringkasan .grid2 h2").innerHTML = `Perjalanan <abbr data-term="${RATIO[key].toLowerCase()}" tabindex="0">${RATIO[key]}</abbr> sejak ${qs[0] || ""}`;
  document.getElementById("hist-note").innerHTML = `${RATIO[key]} dihitung dari laba 4 kuartal terakhir (<abbr data-term="ttm" tabindex="0">TTM</abbr>).`;
}

// ---------------------------------------------------------------- PREDIKSI
let liveTimer = null, lastLive = {};
async function renderPrediksi() {
  try {
    const p = await get("predictions" + HQ());
    const items = TICKS.map(t => p.items.find(r => r.ticker === t)).filter(Boolean);
    document.getElementById("model-info").innerHTML = `model ${esc((p.model || "").replace("|", " · "))}${p.n_fitur ? `, ${p.n_fitur} faktor` : ""},
      dilatih ${String(p.trained_at || "").slice(0, 10)}`;
    draw("ch-proba", { type: "bar", data: { labels: items.map(r => CO[r.ticker].name), datasets: ["naik", "stabil", "turun"].map(k => ({
        label: DIR[k], data: items.map(r => r["proba_" + k]), backgroundColor: DIRC[k], borderColor: "#fff", borderWidth: { left: 2, right: 0 }, borderSkipped: false })) },
      options: { indexAxis: "y", interaction: { mode: "nearest", axis: "y", intersect: true },
        plugins: { tooltip: { callbacks: { label: x => `${x.dataset.label}: ${pct(x.raw)}` } } },
        scales: { x: { stacked: true, max: 1, ticks: { callback: v => v * 100 + "%" } }, y: { stacked: true, grid: { display: false } } } } });
    document.querySelector("#tbl-pred tbody").innerHTML = items.map(r => `<tr>${tic(r.ticker)}<td>${r.base_quarter}</td><td>${r.predicted_quarter}</td>
      <td>${pill(r.prediction)}</td><td>${barsHTML(confidence(r))}</td><td class="num">${pct(r.proba_naik)}</td><td class="num">${pct(r.proba_stabil)}</td>
      <td class="num">${pct(r.proba_turun)}</td><td class="num">${pctv(r.current_value)}</td></tr>`).join("");
  } catch (e) { fail("#tbl-pred tbody", e); }
  loadLive();
}

async function loadLive() {
  const btn = document.getElementById("live-run");
  btn.disabled = true;
  try {
    const qs = new URLSearchParams();
    const t = document.getElementById("live-tic").value;
    if (t) qs.set("ticker", t);
    if (state.h === "4") qs.set("horizon", "4");
    document.querySelectorAll("#sim-box input[data-f]").forEach(i => { if (i.value !== "") qs.set(i.dataset.f, i.value); });
    const t0 = performance.now();
    const r = await fetch(API + "predict_live" + (qs.toString() ? "?" + qs : ""));
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || `HTTP ${r.status}`);
    const sim = d.mode === "simulasi";
    const badge = document.getElementById("live-badge");
    badge.textContent = sim ? "skenario" : "langsung";
    badge.className = "badge live-badge" + (sim ? " sim" : "");
    document.getElementById("live-info").textContent = `dihitung ${new Date(d.generated_at).toLocaleTimeString("id-ID")} dalam ${Math.round(performance.now() - t0)} ms`;
    document.querySelector("#tbl-live tbody").innerHTML = d.items.map(x => {
      const ch = sim && lastLive[x.ticker] && lastLive[x.ticker] !== x.prediction ? "changed" : "";
      return `<tr>${tic(x.ticker)}<td>${x.fundamental_quarter}</td><td>${x.predicted_quarter}</td><td class="${ch}">${pill(x.prediction)}</td>
        <td class="num">${pct(x.proba_naik)}</td><td class="num">${pct(x.proba_stabil)}</td><td class="num">${pct(x.proba_turun)}</td>
        <td class="num">${signed(x.live_features.ret_q, 1, "%")}</td><td class="num">${signed(x.live_features.sent_mean, 2)}</td><td>${x.data_as_of.prices || "–"}</td></tr>`;
    }).join("");
    if (!sim) { d.items.forEach(x => (lastLive[x.ticker] = x.prediction)); fillPlaceholders(d.items); }
    const msgs = [];
    const stale = d.items.filter(x => x.fundamentals_stale).map(x => x.ticker);
    if (stale.length) msgs.push(`Laporan keuangan terbaru ${stale.join(", ")} belum terbit, jadi perkiraannya masih untuk kuartal setelah laporan terakhir.`);
    if (!(d.fitur_live_dipakai || []).length) msgs.push(`Model yang terpilih saat ini hanya memakai rasio keuangan dan efek basis, karena itu yang paling tepat di uji.
      Data pasar dan berita di tabel ini tampil sebagai konteks, sehingga skenario tidak mengubah perkiraan untuk horizon ini.`);
    const w = document.getElementById("live-warn"); w.hidden = !msgs.length; w.textContent = msgs.join(" ");
  } catch (e) { fail("#tbl-live tbody", e, 10); }
  btn.disabled = false;
}
function fillPlaceholders(items) {
  const r = items.find(x => x.ticker === (document.getElementById("live-tic").value || "TLKM")) || items[0];
  if (!r) return;
  document.querySelectorAll("#sim-box input[data-f]").forEach(i => {
    const v = r.live_features[i.dataset.f]; i.placeholder = v == null ? "" : `aktual ${r.ticker}: ${num(v, 2)}`;
  });
}

// ---------------------------------------------------------------- AKURASI
async function renderAkurasi() {
  try {
    const m = await get("metrics" + HQ());
    const t = m.test || {}, b = m.baselines || {}, wf = m.walk_forward || {};
    const bars = [["Model terpilih", t.accuracy, t.macro_f1], ["Model awal", (b.model_lama || {}).accuracy, (b.model_lama || {}).macro_f1],
      ["Cara naif", (b.persistence || {}).accuracy, (b.persistence || {}).macro_f1], ["Tebakan acak", 1 / 3, 1 / 3]].filter(x => x[1] != null);
    document.getElementById("acc-note").textContent = `${t.n || "?"} tebakan uji, ${(m.test_quarters || []).slice(0, 1)}–${(m.test_quarters || []).slice(-1)}`;
    draw("ch-compare", { type: "bar", data: { labels: bars.map(x => x[0]), datasets: [{ label: "Akurasi", data: bars.map(x => x[1]),
        backgroundColor: bars.map((_, i) => (i === 0 ? "#0e6f7a" : "#b9c6c8")), maxBarThickness: 46 }] },
      options: { plugins: { legend: { display: false }, tooltip: { callbacks: { label: x => `Akurasi ${pct(x.raw)} · macro-F1 ${num(bars[x.dataIndex][2])}` } } },
        scales: { y: { min: 0, max: 1, ticks: { callback: v => v * 100 + "%" } }, x: { grid: { display: false } } } } });
    if (wf.n_prediksi) document.querySelector("#tab-akurasi .grid2 .note").innerHTML += ` Di seluruh ${wf.n_prediksi} tebakan uji maju-bertahap (${wf.kuartal.join("–")}), model tepat ${pct(wf.accuracy)}.`;
    const cm = (t.confusion_matrix || {}), L = cm.labels || [], M = cm.matrix || [];
    const mx = Math.max(1, ...M.flat());
    document.getElementById("confusion").innerHTML = L.length ? `<table><thead><tr><th></th>${L.map(l => `<th>ditebak ${DIR[l].toLowerCase()}</th>`).join("")}</tr></thead><tbody>${
      M.map((row, i) => `<tr><th class="rowh">sebenarnya ${DIR[L[i]].toLowerCase()}</th>${row.map((v, j) =>
        `<td class="${i === j ? "diag" : ""}" style="background:rgba(42,120,214,${(0.06 + 0.5 * v / mx).toFixed(2)})">${v}</td>`).join("")}</tr>`).join("")}</tbody></table>` : `<p class="muted">Belum tersedia.</p>`;
    const fi = (m.feature_importance || []).filter(x => x.feature !== "ticker" && x.importance > 0).slice(0, 10).reverse();
    const fiBox = document.getElementById("ch-fi").parentElement;
    fiBox.nextElementSibling?.classList.contains("fi-empty") && fiBox.nextElementSibling.remove();
    if (!fi.length) fiBox.insertAdjacentHTML("afterend", `<p class="note fi-empty">Tidak ada satu faktor pun yang, kalau diacak, membuat
      model lebih buruk di kuartal uji. Artinya model ini belum bergantung kuat pada faktor tertentu.</p>`);
    draw("ch-fi", { type: "bar", data: { labels: fi.map(x => FEAT[x.feature] || x.feature), datasets: [{ data: fi.map(x => Math.max(0, x.importance)),
        backgroundColor: "#0e6f7a", maxBarThickness: 18 }] },
      options: { indexAxis: "y", interaction: { mode: "nearest", axis: "y", intersect: false }, plugins: { legend: { display: false },
        tooltip: { callbacks: { label: x => `penurunan skor bila diacak: ${num(x.raw, 3)}` } } }, scales: { y: { grid: { display: false } } } } });
  } catch (e) { document.getElementById("confusion").innerHTML = `<p class="err">${esc(e.message)}</p>`; }

  try {
    const d = await get("evaluation" + HQ());
    document.getElementById("eval-badge").textContent = d.evaluated ? `${d.correct} dari ${d.evaluated} tepat` : "menunggu laporan terbit";
    const st = { benar: "✔ tepat", salah: "✘ meleset", "menunggu laporan": "⏳ menunggu laporan" };
    document.querySelector("#tbl-eval tbody").innerHTML = d.items.map(r => `<tr>${tic(r.ticker)}<td>${r.base_quarter}</td><td>${r.predicted_quarter}</td>
      <td>${pill(r.prediction)}</td><td>${r.actual ? pill(r.actual) : "–"}</td><td>${pctv(r.base_value)} → ${r.actual_value == null ? "?" : pctv(r.actual_value)}</td>
      <td class="res-${String(r.status).split(" ")[0]}">${st[r.status] || r.status}</td><td>${String(r.generated_at || "").slice(0, 10)}</td></tr>`).join("") ||
      `<tr><td colspan="8" class="muted">Belum ada riwayat prediksi.</td></tr>`;
  } catch (e) { fail("#tbl-eval tbody", e, 8); }

  try {
    const b = (await get("backtest" + HQ())).items;
    document.querySelector("#tbl-bt tbody").innerHTML = b.map(x => `<tr>${tic(x.ticker)}<td>${x.quarter}</td><td>${x.predicted_quarter}</td>
      <td>${pill(x.actual)}</td><td>${pill(x.predicted)}</td><td class="${x.correct ? "res-benar" : "res-salah"}">${x.correct ? "✔" : "✘"}</td></tr>`).join("");
  } catch (e) { fail("#tbl-bt tbody", e, 6); }

  try {
    const r = await get("retrain_log"), it = r.items;
    document.getElementById("retrain-count").textContent = `${r.count}× dilatih ulang`;
    draw("ch-retrain", { type: "bar", data: { labels: it.map((_, i) => `#${i + 1}`), datasets: [
        { type: "bar", label: "Macro-F1 model", data: it.map(x => x.test_macro_f1), backgroundColor: "#0e6f7a", maxBarThickness: 34 },
        { type: "line", label: "Cara naif", data: it.map(x => x.baseline_persistence_f1), borderColor: "#c0392b", pointRadius: 3, pointBackgroundColor: "#c0392b" }] },
      options: { plugins: { tooltip: { callbacks: { title: x => `#${x[0].dataIndex + 1} · ${String(it[x[0].dataIndex].trained_at).slice(0, 16).replace("T", " ")}` } } },
        scales: { y: { min: 0, max: 1 }, x: { grid: { display: false } } } } });
    document.querySelector("#tbl-rt tbody").innerHTML = it.map((x, i) => `<tr><td class="num">${i + 1}</td><td>${String(x.trained_at).slice(0, 16).replace("T", " ")}</td>
      <td>${esc(x.trigger)}</td><td>${esc(String(x.best_model).replace("|", " · "))}</td><td>${x.data_max_quarter}</td>
      <td class="num">${num(x.test_macro_f1)}</td><td class="num">${pct(x.test_accuracy)}</td></tr>`).reverse().join("");
  } catch (e) { fail("#tbl-rt tbody", e, 7); }
}

// ---------------------------------------------------------------- ANALISIS
async function renderAnalisis() {
  const qs = new URLSearchParams({ ratio: document.getElementById("an-ratio").value, lag: document.getElementById("an-lag").value });
  const t = document.getElementById("an-tic").value; if (t) qs.set("ticker", t);
  let a;
  try { a = await get("analysis?" + qs); } catch (e) { document.getElementById("an-concl").innerHTML = `<li class="err">${esc(e.message)}</li>`; return; }
  const rg = a.regresi || {}, R = qs.get("ratio").toUpperCase();
  document.getElementById("r2-hero").innerHTML = rg.ok ? `
    <div class="r2-step"><b>${num(rg.r2_kontrol)}</b><span>bagian naik-turun ${R} yang terjelaskan tanpa data eksternal (R²)</span></div>
    <div class="r2-arrow" aria-hidden="true">→</div>
    <div class="r2-step after"><b>${num(rg.r2_lengkap)}</b><span>setelah data pasar, makro, dan berita dimasukkan</span></div>
    <div class="r2-step"><b>${rg.p_integrasi < 0.05 ? "signifikan" : rg.p_integrasi < 0.1 ? "lemah" : "tidak signifikan"}</b>
      <span>uji F, <abbr data-term="pvalue" tabindex="0">p</abbr> = ${num(rg.p_integrasi, 3)}; ${rg.n} observasi</span></div>` : `<p class="muted">Sampel terlalu kecil untuk regresi.</p>`;
  document.getElementById("an-concl").innerHTML = a.kesimpulan.map(x => `<li>${esc(x)}</li>`).join("");

  const bl = rg.blok || [];
  draw("ch-blocks", { type: "bar", data: { labels: bl.map(b => b.nama), datasets: [{ label: "ΔR² unik", data: bl.map(b => b.delta_r2_unik),
      backgroundColor: bl.map(b => (b.p < 0.1 ? "#0e6f7a" : "#b9c6c8")), maxBarThickness: 26 }] },
    options: { indexAxis: "y", interaction: { mode: "nearest", axis: "y", intersect: false }, plugins: { legend: { display: false },
      tooltip: { callbacks: { label: x => `ΔR² unik ${num(x.raw, 3)} · p = ${num(bl[x.dataIndex].p, 3)}` } } }, scales: { y: { grid: { display: false } } } } });
  document.querySelector("#tbl-blocks tbody").innerHTML = bl.map(b => `<tr><td>${b.nama}</td><td class="num">${num(b.delta_r2_unik, 3)}</td>
    <td class="num">${num(b.delta_r2_sendiri, 3)}</td><td class="num">${num(b.f)}</td><td class="num">${num(b.p, 3)} ${b.sig}</td></tr>`).join("") +
    (rg.ok ? `<tr><td><b>Ketiganya sekaligus</b></td><td class="num"><b>${num(rg.delta_r2_integrasi, 3)}</b></td><td class="num">–</td>
      <td class="num">${num(rg.f_integrasi)}</td><td class="num">${num(rg.p_integrasi, 3)} ${rg.sig_integrasi}</td></tr>` : "");

  const corr = a.korelasi.filter(c => c.spearman_rho != null).sort((x, y) => y.spearman_rho - x.spearman_rho);
  draw("ch-corr", { type: "bar", data: { labels: corr.map(c => c.label), datasets: [{ data: corr.map(c => c.spearman_rho),
      backgroundColor: corr.map(c => (c.spearman_rho >= 0 ? "#2a78d6" : "#c0392b") + (c.spearman_p < 0.1 ? "" : "55")), maxBarThickness: 16 }] },
    options: { indexAxis: "y", interaction: { mode: "nearest", axis: "y", intersect: false }, plugins: { legend: { display: false },
      tooltip: { callbacks: { label: x => `ρ = ${num(x.raw)} · p = ${num(corr[x.dataIndex].spearman_p, 3)} · n = ${corr[x.dataIndex].n}` } } },
      scales: { x: { min: -0.6, max: 0.6 }, y: { grid: { display: false } } } } });
  document.querySelector("#tbl-corr tbody").innerHTML = a.korelasi.map(c => `<tr><td><span class="grp">${c.blok_nama}</span></td><td>${c.label}</td>
    <td class="num">${c.n}</td><td class="num">${num(c.pearson_r)}</td><td class="num">${num(c.spearman_rho)} ${c.sig || ""}</td><td class="num">${num(c.spearman_p, 3)}</td></tr>`).join("");

  const cf = (rg.koefisien || []);
  draw("ch-coef", { data: { labels: cf.map(c => c.label), datasets: [
      { type: "bar", label: "Rentang 95%", data: cf.map(c => [c.beta - 1.96 * c.se, c.beta + 1.96 * c.se]), backgroundColor: cf.map(c => (c.p < 0.1 ? "#0e6f7a55" : "#d5dddd")), barThickness: 6, borderRadius: 3 },
      { type: "line", label: "β", data: cf.map(c => c.beta), showLine: false, pointRadius: 5, pointHoverRadius: 7,
        pointBackgroundColor: cf.map(c => (c.p < 0.1 ? "#0e6f7a" : "#7c8a90")), pointBorderColor: "#fff", pointBorderWidth: 1.5 }] },
    options: { indexAxis: "y", interaction: { mode: "nearest", axis: "y", intersect: false },
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: x => { const c = cf[x.dataIndex]; return `β = ${num(c.beta, 3)} · p = ${num(c.p, 3)} ${c.sig}`; } }, filter: x => x.datasetIndex === 1 } },
      scales: { y: { grid: { display: false } }, x: { title: { display: true, text: "← menurunkan        β (terstandar)        menaikkan →" } } } } });
  document.querySelector("#tbl-coef tbody").innerHTML = cf.map(c => `<tr><td>${c.label}</td><td><span class="grp">${c.blok}</span></td>
    <td class="num">${num(c.beta, 3)} ${c.sig}</td><td class="num">${num(c.se, 3)}</td><td class="num">${num(c.t)}</td><td class="num">${num(c.p, 3)}</td></tr>`).join("");
  const ex = (rg.dikecualikan || []).map(x => `${x.label} (${x.alasan})`).join("; ");
  document.getElementById("an-note").textContent = a.catatan + (rg.fixed_effect_emiten ? " Perbedaan rata-rata antaremiten sudah dikendalikan (efek tetap)." : "") + (ex ? ` Tidak dipakai: ${ex}.` : "");
}

// ---------------------------------------------------------------- PASAR
async function renderPasar() {
  try {
    const all = await Promise.all(["TLKM", "ISAT", "EXCL", "JKSE"].map(t => get(`prices?ticker=${t}&days=1095`).then(d => [t, d.items])));
    const end = new Date(Math.max(...all.flatMap(([, it]) => it.map(x => +new Date(x.date)))));
    const start = new Date(end - state.pxDays * 864e5);
    const series = all.map(([t, it]) => [t, it.filter(x => new Date(x.date) >= start)]);
    const dates = [...new Set(series.flatMap(([, it]) => it.map(x => String(x.date).slice(0, 10))))].sort();
    draw("ch-price", { type: "line", data: { labels: dates, datasets: series.map(([t, it]) => {
        const base = it.length ? it[0].close : 1, m = Object.fromEntries(it.map(x => [String(x.date).slice(0, 10), x.close / base * 100]));
        return { label: CO[t].name, data: dates.map(d => m[d] ?? null), borderColor: CO[t].c, backgroundColor: CO[t].c, borderWidth: t === "JKSE" ? 1.5 : 2, spanGaps: true };
      }) }, options: { plugins: { tooltip: { callbacks: { label: x => `${x.dataset.label}: ${num(x.raw, 1)}` } } },
        scales: { x: { ticks: { maxTicksLimit: 8 }, grid: { display: false } } } } });
    document.querySelector("#tbl-px tbody").innerHTML = series.map(([t, it]) => {
      const f = it[0] || {}, l = it[it.length - 1] || {};
      return `<tr>${tic(t, t === "JKSE" ? "IHSG" : t)}<td class="num">${Number(l.close || 0).toLocaleString("id-ID")}</td>
        <td class="num">${signed((l.close / f.close - 1) * 100, 1, "%")}</td><td>${String(l.date || "").slice(0, 10)}</td></tr>`;
    }).join("");
  } catch (e) { fail("#tbl-px tbody", e, 4); }

  try {
    const r = (await get("ratios")).items, qs = [...new Set(r.map(x => x.quarter))].sort();
    draw("ch-sent", { type: "line", data: { labels: qs, datasets: TICKS.map(t => ({ label: CO[t].name, borderColor: CO[t].c, backgroundColor: CO[t].c, spanGaps: true,
        data: qs.map(q => { const x = r.find(y => y.ticker === t && y.quarter === q); return x && x.sent_n > 0 ? x.sent_mean : null; }) })) },
      options: { plugins: { tooltip: { callbacks: { label: x => `${x.dataset.label}: ${num(x.raw)}` } } }, scales: { y: { min: -1, max: 1 }, x: { grid: { display: false } } } } });
    const q1 = qs.map(q => r.find(y => y.quarter === q && y.bi_rate != null) || r.find(y => y.quarter === q) || {});
    draw("ch-macro", { type: "line", data: { labels: qs, datasets: [
        { label: "BI-Rate", data: q1.map(x => x.bi_rate ?? null), borderColor: "#0e6f7a", backgroundColor: "#0e6f7a", stepped: true, spanGaps: true },
        { label: "Inflasi tahunan", data: q1.map(x => x.inflation_yoy ?? null), borderColor: "#6250d6", backgroundColor: "#6250d6", spanGaps: true }] },
      options: { plugins: { tooltip: { callbacks: { label: x => `${x.dataset.label}: ${num(x.raw)}%` } } }, scales: { y: pctAxis, x: { grid: { display: false } } } } });
    draw("ch-fx", { type: "line", data: { labels: qs, datasets: [{ label: "USD/IDR", data: q1.map(x => x.usd_idr_avg ?? null), borderColor: "#16242b", spanGaps: true }] },
      options: { plugins: { legend: { display: false }, tooltip: { callbacks: { label: x => `Rp${Math.round(x.raw).toLocaleString("id-ID")}` } } },
        scales: { y: { ticks: { callback: v => v.toLocaleString("id-ID") } }, x: { grid: { display: false } } } } });
  } catch (e) { console.warn(e); }
}

// ---------------------------------------------------------------- TENTANG
function renderTentang() {
  document.getElementById("profiles").innerHTML = TICKS.map(t => `<div class="profile"><span class="mono" style="background:${CO[t].c}" aria-hidden="true">${t}</span>
    <div><b>${CO[t].full}</b><p>${CO[t].desc}</p></div></div>`).join("");
  document.getElementById("glossary").innerHTML = Object.values(GLOSS).map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join("");
}

// ---------------------------------------------------------------- navigasi & interaksi
const RENDER = { ringkasan: renderRingkasan, prediksi: renderPrediksi, akurasi: renderAkurasi, analisis: renderAnalisis, pasar: renderPasar, tentang: renderTentang };
function showTab(name, push = true) {
  state.tab = name;
  document.querySelectorAll(".tabs [role=tab]").forEach(b => {
    const on = b.id === "t-" + name; b.setAttribute("aria-selected", on); b.tabIndex = on ? 0 : -1;
    document.getElementById(b.getAttribute("aria-controls")).hidden = !on;
  });
  if (push) history.replaceState(null, "", "#" + name);
  RENDER[name]();
}
function segment(id, attr, onChange) {
  const g = document.getElementById(id) || document.querySelector(id);
  g.querySelectorAll("button").forEach(b => b.addEventListener("click", () => {
    g.querySelectorAll("button").forEach(x => x.setAttribute("aria-checked", x === b));
    onChange(b.dataset[attr]);
  }));
}
function setupTips() {
  const tip = document.getElementById("tip");
  document.querySelectorAll("abbr[data-term]").forEach(a => a.setAttribute("tabindex", "0"));
  const show = e => {
    const a = e.target.closest("abbr[data-term]"); if (!a) return;
    const g = GLOSS[a.dataset.term]; if (!g) return;
    tip.innerHTML = `<b>${g[0]}</b>${g[1]}`; tip.hidden = false;
    const r = a.getBoundingClientRect(), w = Math.min(320, innerWidth - 20);
    tip.style.left = Math.max(10, Math.min(r.left, innerWidth - w - 10)) + "px";
    tip.style.top = (r.bottom + 8 + 120 > innerHeight ? r.top - tip.offsetHeight - 8 : r.bottom + 8) + "px";
  };
  const hide = e => { if (e.target.closest && e.target.closest("abbr[data-term]")) tip.hidden = true; };
  document.addEventListener("mouseover", show); document.addEventListener("focusin", show);
  document.addEventListener("mouseout", hide); document.addEventListener("focusout", hide);
}

function init() {
  document.querySelectorAll(".tabs [role=tab]").forEach(b => b.addEventListener("click", () => showTab(b.id.slice(2))));
  document.querySelector(".tabs").addEventListener("keydown", e => {
    if (!["ArrowRight", "ArrowLeft"].includes(e.key)) return;
    const tabs = [...document.querySelectorAll(".tabs [role=tab]")], i = tabs.findIndex(b => b.getAttribute("aria-selected") === "true");
    const n = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length]; n.focus(); n.click();
  });
  segment(".horizon .seg", "h", h => { state.h = h; lastLive = {}; RENDER[state.tab](); });
  segment("hist-ratio", "r", r => { state.histRatio = r; get("ratios").then(renderHist); });
  segment("px-range", "d", d => { state.pxDays = +d; renderPasar(); });
  ["an-ratio", "an-lag", "an-tic"].forEach(id => (document.getElementById(id).onchange = renderAnalisis));
  document.getElementById("live-run").onclick = loadLive;
  document.getElementById("live-tic").onchange = loadLive;
  document.querySelectorAll("#sim-box input[data-f]").forEach(i => (i.onchange = loadLive));
  document.getElementById("sim-reset").onclick = () => { document.querySelectorAll("#sim-box input[data-f]").forEach(i => (i.value = "")); loadLive(); };
  document.getElementById("live-auto").onchange = e => { clearInterval(liveTimer); if (e.target.checked) liveTimer = setInterval(loadLive, 60000); };
  setupTips();
  loadStatus();
  const start = (location.hash || "").slice(1);
  showTab(RENDER[start] ? start : "ringkasan", false);
}
init();
