"use strict";
const $ = (s) => document.querySelector(s);
const el = (t, c, h) => { const n = document.createElement(t); if (c) n.className = c; if (h != null) n.innerHTML = h; return n; };
const esc = (s) => (s == null ? "" : String(s)).replace(/[&<>"]/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[m]));
let selected = [];

/* ---------- theme ---------- */
(function theme() {
  const saved = localStorage.getItem("gre-theme");
  if (saved) document.documentElement.setAttribute("data-theme", saved);
  $("#theme").addEventListener("click", () => {
    const cur = document.documentElement.getAttribute("data-theme");
    const dark = cur ? cur === "dark" : matchMedia("(prefers-color-scheme:dark)").matches;
    const next = dark ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem("gre-theme", next);
  });
})();

/* ---------- toast ---------- */
function toast(msg, kind = "") {
  const t = el("div", "toast " + kind, esc(msg));
  $("#toasts").appendChild(t);
  setTimeout(() => { t.style.opacity = "0"; t.style.transition = ".4s"; }, 3600);
  setTimeout(() => t.remove(), 4200);
}

/* ---------- classification pill ---------- */
function clsPill(c) {
  if (!c) return '<span class="pill vus">—</span>';
  const low = c.toLowerCase();
  const k = low.includes("likely") ? "likely" : low.includes("pathogenic") ? "path" : "vus";
  return `<span class="pill ${k}">${esc(c)}</span>`;
}
const fmtSize = (b) => (b == null ? "" : b < 1024 ? b + " B" : b < 1048576 ? (b / 1024).toFixed(0) + " KB" : (b / 1048576).toFixed(1) + " MB");

/* ---------- file selection ---------- */
const drop = $("#drop"), fileInput = $("#file");
$("#browse").addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", () => addFiles(fileInput.files));
["dragenter", "dragover"].forEach((e) => drop.addEventListener(e, (ev) => { ev.preventDefault(); drop.classList.add("drag"); }));
["dragleave", "drop"].forEach((e) => drop.addEventListener(e, (ev) => { ev.preventDefault(); if (e === "drop" || ev.target === drop) drop.classList.remove("drag"); }));
drop.addEventListener("drop", (ev) => addFiles(ev.dataTransfer.files));

function addFiles(list) {
  for (const f of list) if (f.name.toLowerCase().endsWith(".pdf") && !selected.find((x) => x.file.name === f.name && x.file.size === f.size))
    selected.push({ file: f, state: "" });
  renderFiles();
}
function renderFiles() {
  const box = $("#filelist"); box.innerHTML = "";
  selected.forEach((s, i) => {
    const row = el("div", "filerow");
    row.innerHTML = `<span class="dot ${s.state}"></span><span class="nm">${esc(s.file.name)}</span><span class="sz">${fmtSize(s.file.size)}</span>`;
    if (!s.state) { const x = el("button", "btn ghost", "✕"); x.style.padding = "2px 7px"; x.onclick = () => { selected.splice(i, 1); renderFiles(); }; row.appendChild(x); }
    box.appendChild(row);
  });
  $("#upload").disabled = selected.filter((s) => s.state !== "ok").length === 0;
}

/* ---------- upload ----------
   Files are sent in size-bounded batches (the server caps request bodies at
   ~4.5 MB), a few batches in parallel, so hundreds of PDFs upload reliably. */
const MAX_BATCH_BYTES = 4_000_000;
const UPLOAD_CONCURRENCY = 3;

function buildBatches(items) {
  const batches = [];
  let cur = [], size = 0;
  for (const s of items) {
    if (cur.length && size + s.file.size > MAX_BATCH_BYTES) { batches.push(cur); cur = []; size = 0; }
    cur.push(s); size += s.file.size;
  }
  if (cur.length) batches.push(cur);
  return batches;
}

async function postBatch(batch) {
  const fd = new FormData();
  batch.forEach((s) => fd.append("files", s.file, s.file.name));
  const res = await fetch("/api/upload", { method: "POST", body: fd });
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    if (res.status === 413) msg = "batch too large for the server";
    else {
      const txt = await res.text();
      try { msg = JSON.parse(txt).detail || msg; } catch { msg = (txt || msg).slice(0, 140); }
    }
    throw new Error(msg);
  }
  return (await res.json()).results;
}

$("#upload").addEventListener("click", async () => {
  const pending = selected.filter((s) => s.state !== "ok");
  if (!pending.length) return;
  pending.forEach((s) => (s.state = "run"));
  renderFiles();
  $("#upload").disabled = true;
  const btn = $("#upload"), label = btn.textContent;

  const batches = buildBatches(pending);
  let done = 0, patients = 0, errs = 0;
  const byName = (n) => selected.find((x) => x.file.name === n);

  const runBatch = async (batch) => {
    try {
      const results = await postBatch(batch);
      results.forEach((r) => {
        const s = byName(r.filename);
        if (s) s.state = r.status === "success" ? "ok" : "err";
        if (r.status === "success") patients += r.patients.length; else errs++;
      });
    } catch (e) {
      batch.forEach((s) => (s.state = "err"));
      errs += batch.length;
      toast(`A batch failed: ${e.message}`, "err");
    } finally {
      done += batch.length;
      btn.textContent = `Uploading ${done}/${pending.length}…`;
      renderFiles();
    }
  };

  // Simple concurrency pool over the batches.
  let idx = 0;
  const workers = Array.from({ length: Math.min(UPLOAD_CONCURRENCY, batches.length) }, async () => {
    while (idx < batches.length) { const b = batches[idx++]; await runBatch(b); if (idx % UPLOAD_CONCURRENCY === 0) await refresh(); }
  });
  await Promise.all(workers);

  btn.textContent = label;
  if (patients) toast(`Extracted ${patients} patient record(s) from ${pending.length - errs} file(s).`, "ok");
  if (errs) toast(`${errs} file(s) could not be processed.`, "err");
  await refresh();
});

/* ---------- tables ---------- */
async function refresh() {
  const [recs, txs, st] = await Promise.all([
    fetch("/api/records").then((r) => r.json()),
    fetch("/api/transactions").then((r) => r.json()),
    fetch("/api/stats").then((r) => r.json()),
  ]);
  $("#k-records").textContent = st.records;
  $("#k-uploads").textContent = st.uploads;
  $("#k-path").textContent = st.pathogenic_records;
  $("#k-patients").textContent = st.unique_patients;
  renderRecords(recs.records);
  renderTx(txs.transactions);
}

function renderRecords(rows) {
  $("#b-records").textContent = rows.length;
  const body = $("#records-body"); body.innerHTML = "";
  $("#records-empty").style.display = rows.length ? "none" : "";
  rows.forEach((r) => {
    const tr = el("tr");
    tr.innerHTML =
      `<td><strong>${esc(r.patient_name || "—")}</strong><div class="sub mono">no. ${esc(r.patient_no || "?")}</div></td>` +
      `<td>${esc(r.sex || "—")}</td>` +
      `<td class="mono">${esc(r.your_ref || "—")}</td>` +
      `<td class="mono">${esc(r.gene || "—")}<div class="sub">${esc(r.variant ? r.variant.replace((r.gene||"")+" ", "") : "")}</div></td>` +
      `<td>${clsPill(r.classification)}</td>` +
      `<td>${esc(r.doctor || "—")}<div class="sub">${esc(r.hospital || "")}</div></td>` +
      `<td>${esc(r.overall_result || "—")}</td>` +
      `<td class="mono"><span class="pill tmpl">${esc(r.template || "")}</span></td>`;
    tr.onclick = () => openRecord(r.id);
    body.appendChild(tr);
  });
}

function renderTx(rows) {
  $("#b-tx").textContent = rows.length;
  const body = $("#tx-body"); body.innerHTML = "";
  $("#tx-empty").style.display = rows.length ? "none" : "";
  rows.forEach((t) => {
    const tr = el("tr");
    const badge = t.status === "success" ? '<span class="pill ok">success</span>' : '<span class="pill err">error</span>';
    tr.innerHTML =
      `<td class="mono">${esc(t.filename)}</td>` +
      `<td class="sub">${esc((t.uploaded_at || "").replace("T", " "))}</td>` +
      `<td>${badge}</td>` +
      `<td class="mono">${t.num_patients}</td>` +
      `<td class="sub">${fmtSize(t.size_bytes)}</td>` +
      `<td class="sub">${esc(t.error || "")}</td>`;
    body.appendChild(tr);
  });
}

/* ---------- tabs ---------- */
document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => {
  document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
  tab.classList.add("active");
  const t = tab.dataset.tab;
  $("#pane-records").style.display = t === "records" ? "" : "none";
  $("#pane-tx").style.display = t === "tx" ? "" : "none";
}));

/* ---------- record modal ---------- */
async function openRecord(id) {
  const rec = await fetch("/api/record/" + id).then((r) => r.json());
  const d = rec.data || {};
  const p = d.patient || {}, op = d.ordering_provider || {}, ci = d.clinical_information || {}, cov = d.coverage || {};
  const v = (d.variants || [])[0] || {};
  const dis = v.disorder || {};
  $("#m-title").innerHTML = `${esc(p.full_name || "Record")} <span class="pill tmpl">${esc(d.template_generation || "")}</span>`;
  const kv = (o) => `<dl class="kv">${o.filter(([, val]) => val).map(([k, val]) => `<dt>${esc(k)}</dt><dd>${esc(val)}</dd>`).join("")}</dl>`;
  const long = (label, val) => val ? `<div class="sect"><h4>${esc(label)}</h4><div class="longtext">${esc(val)}</div></div>` : "";
  $("#m-body").innerHTML =
    `<div class="sect"><h4>Patient</h4>${kv([["Patient no.", p.patient_no], ["Full name", p.full_name], ["Sex", p.sex], ["Date of birth", p.date_of_birth], ["Your ref.", p.your_ref], ["Order no.", p.order_no]])}</div>` +
    `<div class="sect"><h4>Doctor &amp; Hospital</h4>${kv([["Doctor", op.physician], ["Hospital", op.institution], ["Department", op.department], ["Address", op.address], ["Country", op.country]])}</div>` +
    `<div class="sect"><h4>Result</h4>${kv([["Overall result", d.overall_result], ["Summary", d.result_summary]])}</div>` +
    `<div class="sect"><h4>Variant</h4>${kv([["Gene", v.gene], ["Transcript", v.transcript], ["cDNA", v.cdna_change], ["Protein", v.protein_change], ["Genomic", v.genomic_coordinate], ["Exon", v.exon], ["Zygosity", v.zygosity], ["Type", v.variant_type], ["Classification", (v.classification || "") + (v.classification_class ? " (" + v.classification_class + ")" : "")], ["dbSNP", v.snp_identifier], ["PMID", v.pmid], ["Disorder", dis.name], ["OMIM", dis.omim], ["Inheritance", dis.inheritance]])}</div>` +
    `<div class="sect"><h4>Clinical information</h4>${kv([["HPO terms", (ci.hpo_terms || []).join("; ")], ["Diagnosed", ci.diagnosed_conditions], ["Age of onset", ci.age_of_manifestation], ["Family history", ci.family_history], ["Consanguinity", ci.consanguinity]])}</div>` +
    (Object.keys(cov).length ? `<div class="sect"><h4>Coverage</h4>${kv([["Average (X)", cov.average_coverage], ["≥ 20X", cov.pct_ge_20x], ["≥ 10X", cov.pct_ge_10x], ["≥ 50X", cov.pct_ge_50x]])}</div>` : "") +
    long("Interpretation", d.interpretation) +
    long("Recommendations", d.recommendations) +
    long("Secondary findings", d.secondary_findings);
  $("#modal").classList.add("open");
}
$("#m-close").addEventListener("click", () => $("#modal").classList.remove("open"));
$("#modal").addEventListener("click", (e) => { if (e.target === $("#modal")) $("#modal").classList.remove("open"); });

/* ---------- export & refresh ---------- */
$("#export").addEventListener("click", async () => {
  const st = await fetch("/api/stats").then((r) => r.json());
  if (!st.records) { toast("No records to export yet.", "err"); return; }
  window.location.href = "/api/export/xlsx";
  toast("Preparing Excel workbook…", "ok");
});
$("#refresh").addEventListener("click", refresh);

refresh();
