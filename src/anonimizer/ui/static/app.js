"use strict";
// Anonimizer local interface. No external resource is loaded; every value shown on the page
// is inserted as text (never as HTML), so file contents cannot inject markup.

const $ = (id) => document.getElementById(id);
const state = { meta: null, inspect: null, contract: null };

function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (k === "checked" || k === "disabled" || k === "selected" || k === "open") node[k] = Boolean(v);
    else if (k === "value") node.value = v;
    else node.setAttribute(k, v);
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return node;
}

function table(headers, rows, opts) {
  const o = opts || {};
  const thead = el("thead", {}, el("tr", {}, headers.map((h) => el("th", { text: h }))));
  const tbody = el("tbody", {}, rows.map((r) => el("tr", {}, r.map((c) =>
    (c && c.nodeType && c.tagName === "TD") ? c : el("td", { class: o.cellClass || null }, c === null || c === undefined ? "" : c)))));
  const t = el("table", {}, thead, tbody);
  return o.scroll ? el("div", { class: "scroll" }, t) : t;
}

function say(text, kind) {
  const box = $("msg");
  box.replaceChildren();
  if (text) box.append(el("div", { class: kind || "info", text }));
}

async function api(path, body, raw) {
  const init = raw ? { method: "POST", body: raw, credentials: "same-origin" }
    : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}), credentials: "same-origin" };
  let res;
  try {
    res = await fetch(path, init);
  } catch (e) {
    throw new Error("The local server did not answer. Is it still running in the terminal?");
  }
  let data = {};
  try { data = await res.json(); } catch (e) { /* empty body */ }
  if (!res.ok) throw new Error(data.error || ("Request failed (" + res.status + ")"));
  return data;
}

async function busy(button, label, fn) {
  const old = button.textContent;
  button.disabled = true;
  button.textContent = label;
  say(label, "info");
  try {
    await fn();
    say("");
  } catch (e) {
    say(e.message, "err");
  } finally {
    button.disabled = false;
    button.textContent = old;
  }
}

function show(id, on) { $(id).hidden = !on; }
function hideFrom(ids) { ids.forEach((id) => show(id, false)); }
const pill = (text, kind) => el("span", { class: "pill " + (kind || ""), text });
const statusKind = (s) => (s === "passed" ? "ok" : s === "failed" ? "bad" : "warn");

// ---- step 1 and 2: file and regions ------------------------------------------------------
function renderInspect(data) {
  state.inspect = data;
  const f = data.file;
  const facts = [];
  facts.push(data.file_name + " — " + f.format.toUpperCase());
  if (f.format === "csv") {
    facts.push("encoding " + f.encoding.encoding + " (confidence " + f.encoding.confidence + ")");
    facts.push("delimiter " + JSON.stringify(f.delimiter.delimiter) + " (confidence " + f.delimiter.confidence + ")");
    if (f.records !== null && f.records !== undefined) facts.push(f.records + " records");
  } else {
    facts.push(f.sheet_count + " sheet(s)" + (f.hidden_sheets ? ", " + f.hidden_sheets + " hidden" : ""));
  }
  $("file-facts").textContent = facts.join(" · ");
  const rows = data.recipe.tables.map((t, i) => {
    const num = (key) => el("input", { type: "number", min: "1", class: "num", value: t[key] === null ? "" : t[key], "data-i": i, "data-k": key });
    return [
      el("input", { type: "checkbox", checked: t.include, "data-i": i, "data-k": "include" }),
      el("input", { type: "text", value: t.name, "data-i": i, "data-k": "name" }),
      el("select", { "data-i": i, "data-k": "kind" }, ["table", "note"].map((k) => el("option", { value: k, selected: t.kind === k, text: k }))),
      t.sheet || "", num("header_row"), num("first_data_row"), num("last_data_row"), num("first_col"), num("last_col"),
      el("span", { class: t.confidence < 0.75 ? "low" : null, text: t.confidence }),
      (t.notes || []).join("; ") + (t.source === "user" ? " [set by you]" : ""),
    ];
  });
  $("regions").replaceChildren(table(["Use", "Name", "Kind", "Sheet", "Header row", "First data row", "Last data row", "First column", "Last column", "Confidence", "Notes"], rows));
  show("s-regions", true);
  show("s-policy", true);
  hideFrom(["s-report", "s-contract", "s-generate", "s-result"]);
  renderPolicies();
}

function collectRecipe() {
  const tables = state.inspect.recipe.tables.map((t) => Object.assign({}, t));
  document.querySelectorAll("#regions [data-i]").forEach((inp) => {
    const t = tables[Number(inp.dataset.i)];
    const k = inp.dataset.k;
    if (k === "include") t.include = inp.checked;
    else if (k === "name" || k === "kind") t[k] = inp.value;
    else t[k] = inp.value === "" ? null : Number(inp.value);
  });
  const delim = $("ov-delim").value;
  const markers = $("ov-markers").value.split(",").map((s) => s.trim()).filter(Boolean);
  return {
    recipe_version: 1,
    file: { encoding: $("ov-enc").value.trim() || null, delimiter: delim === "" ? null : (delim === "tab" || delim === "\\t" ? "\t" : delim), quotechar: '"' },
    extra_markers: markers, tables,
  };
}

function renderPolicies() {
  const box = $("policies");
  if (box.childElementCount) return;
  state.meta.policies.forEach((p) => {
    box.append(el("label", { class: "policy" },
      el("input", { type: "radio", name: "policy", value: p.id }),
      el("strong", { text: p.id }), " — " + p.description,
      el("div", { class: "hint", text: p.rationale + " Maximum tier: " + p.max_tier + ". " + p.limits })));
  });
}

// ---- step 4: report ----------------------------------------------------------------------
function renderReport(report) {
  const box = $("report");
  box.replaceChildren();
  box.append(el("h3", { text: "Tables" }));
  box.append(table(["Table", "Sheet", "Rows", "Columns", "Header", "Intro rows", "Detection confidence", "Duplicate rows", "Notes"],
    report.tables.map((t) => [t.name, t.sheet, t.rows, t.columns, t.header_present ? "yes" : "no", t.introductory_rows,
      el("span", { class: t.detection_confidence < 0.75 ? "low" : null, text: t.detection_confidence }),
      t.duplicate_rows.extra_rows, (t.detection_notes || []).join("; ")])));
  report.tables.forEach((t) => {
    box.append(el("h4", { text: "Columns of " + t.name }));
    box.append(table(["Column", "Type", "Type share", "Missing", "Missing kinds", "Markers", "Distinct", "Key role", "Sensitivity hint"],
      t.column_summaries.map((c) => [c.name, c.logical_type, c.type_share, c.missing,
        Object.entries(c.missing_kinds).map(([k, v]) => k + " ×" + v).join(", "),
        Object.entries(c.markers).map(([k, v]) => k + " ×" + v).join(", "), c.distinct,
        c.key_role + (c.references ? " → " + c.references.table + "." + c.references.column_name : ""), c.sensitivity_hint]), { scroll: true }));
  });
  box.append(el("h3", { text: "Exception Catalogue (" + report.exception_catalogue.length + ")" }));
  if (report.exception_catalogue.length) {
    box.append(table(["Priority", "Table", "Column", "Exception", "Count", "Can be generated"],
      report.exception_catalogue.map((e) => ["P" + e.priority, e.table || "(file)", e.column || "(row / file)", e.description, e.count, e.reproducible ? "yes" : "no"]), { scroll: true }));
  } else {
    box.append(el("p", { text: "Nothing exceptional was found." }));
  }
  if (report.relationships.length) {
    box.append(el("h3", { text: "Relationships" }));
    box.append(table(["From", "To", "Share of values found", "Rows without a match"],
      report.relationships.map((r) => [r.from_table + "." + r.from_column_name, r.to_table + "." + r.to_column_name, r.containment, r.dangling_rows])));
  }
  if (report.unresolved_ambiguities.length) {
    box.append(el("h3", { text: "Unresolved ambiguities" }));
    box.append(el("ul", {}, report.unresolved_ambiguities.map((a) => el("li", { text: a.scope + ": " + a.message + " (confidence " + a.confidence + ")" }))));
  }
  show("s-report", true);
}

// ---- step 5: contract ----------------------------------------------------------------------
function renderContract(contract) {
  state.contract = contract;
  const box = $("contract");
  box.replaceChildren();
  contract.tables.forEach((t) => {
    box.append(el("h3", { text: t.name + " — about " + t.source_rows + " source rows" }));
    const rows = t.columns.map((c) => [
      el("input", { type: "checkbox", checked: c.keep, "data-t": t.name, "data-c": c.id, "data-k": "keep" }),
      el("input", { type: "text", value: c.name, "data-t": t.name, "data-c": c.id, "data-k": "name" }),
      c.logical_type,
      el("select", { "data-t": t.name, "data-c": c.id, "data-k": "sensitivity" },
        state.meta.sensitivity_classes.map((s) => el("option", { value: s, selected: c.sensitivity.class === s, text: s }))),
      c.sensitivity.basis + (c.sensitivity.confirmed ? " (confirmed)" : " (proposal)"),
      c.key.role + (c.key.references ? " → " + c.key.references.table : ""),
      c.can_keep_literals
        ? el("label", {}, el("input", { type: "checkbox", checked: c.value_policy.mode !== "synthetic", "data-t": t.name, "data-c": c.id, "data-k": "literal_categories" }),
          " copy frequent values" + (c.value_policy.mode !== "synthetic" ? " (" + c.value_policy.approved_literals.length + " approved)" : ""))
        : "synthetic",
    ]);
    box.append(table(["Keep", "Output name", "Type", "Sensitivity", "Basis", "Key role", "Values"], rows, { scroll: true }));
    const sc = t.scenarios.map((s) => [
      el("input", { type: "checkbox", checked: s.enabled && s.reproducible, disabled: !s.reproducible, "data-s": s.id, "data-k": "enabled" }),
      el("input", { type: "checkbox", checked: s.pinned, disabled: !s.reproducible, "data-s": s.id, "data-k": "pinned" }),
      "P" + s.priority, (t.columns.find((c) => c.id === s.column) || { name: "(row)" }).name, s.description, s.source_count,
      s.reproducible ? "" : s.not_reproduced_reason,
    ]);
    box.append(el("details", {}, el("summary", { text: "Scenarios to generate (" + t.scenarios.length + ")" }),
      table(["Generate", "Pin", "Priority", "Column", "Scenario", "Count in source", "Note"], sc, { scroll: true })));
  });
  const r = contract.review;
  $("contract-state").textContent = r.confirmed ? "Confirmed by " + r.confirmed_by + " on " + r.confirmed_at + "." : "Not confirmed yet: output will be LOCAL_ONLY.";
  const rf = $("rows-for");
  rf.replaceChildren();
  if (contract.tables.length > 1) {
    rf.append(el("span", { class: "hint", text: "Optional row count per table (smaller tables keep their source size by default):" }));
    contract.tables.forEach((t) => rf.append(el("label", { text: t.name }), el("input", { type: "number", min: "1", class: "short", "data-table": t.name, placeholder: "auto" })));
  }
  show("s-contract", true);
  show("s-generate", true);
}

function collectDecisions() {
  const cols = {};
  document.querySelectorAll("#contract [data-c]").forEach((inp) => {
    const key = inp.dataset.t + "\u0000" + inp.dataset.c;
    const c = cols[key] || (cols[key] = { table: inp.dataset.t, id: inp.dataset.c });
    c[inp.dataset.k] = inp.type === "checkbox" ? inp.checked : inp.value;
  });
  const scen = {};
  document.querySelectorAll("#contract [data-s]").forEach((inp) => {
    const s = scen[inp.dataset.s] || (scen[inp.dataset.s] = { id: inp.dataset.s });
    s[inp.dataset.k] = inp.checked;
  });
  return { columns: Object.values(cols), scenarios: Object.values(scen), approved_by: $("approved-by").value.trim() || null, confirm_by: $("confirm-by").value.trim() || null };
}

// ---- step 7: result ------------------------------------------------------------------------
function locText(e) {
  return e.locations.map((l) => l.cell || (l.line ? "line " + l.line + (l.field ? ", field " + l.field : "") : "row " + l.row)).join("; ");
}

function renderResult(r) {
  const box = $("result");
  box.replaceChildren();
  const a = r.assessment;
  const restricted = a.release_tier === "RESTRICTED";
  box.append(el("div", { class: "banner " + (restricted ? "restricted" : "local") },
    el("strong", { text: "Release tier: " + a.release_tier }),
    el("div", { text: restricted ? "May be shared only inside the organisation that controls the source data, under its own rules. Not assessed as anonymous."
      : "Keep on this machine. Not assessed for sharing." }),
    el("div", { text: "Transformation: " + a.transformation_class + " · assessment: " + a.assessment_status + " · policy: " + a.policy.id + " v" + a.policy.version + " · review by " + a.review_by }),
    a.tier_reasons.length ? el("ul", {}, a.tier_reasons.map((x) => el("li", { text: x }))) : null));

  box.append(el("h3", { text: "Privacy assessment" }));
  box.append(table(["Criterion", "Status", "How it was measured"], Object.entries(a.criteria || {}).map(([k, v]) => [k.replace(/_/g, " "), pill(v.status.replace(/_/g, " "), statusKind(v.status)), v.method])));
  if ((a.residual_risk_statements || []).length) box.append(el("ul", {}, a.residual_risk_statements.map((s) => el("li", { text: s }))));

  box.append(el("h3", { text: "Scenario coverage" }));
  box.append(table(["Table", "Requested rows", "Generated rows", "Blank rows", "Scenarios", "Covered", "Max per row", "Rows needed (one per row)", "Rows needed (packed)"],
    r.coverage.tables.map((c) => [c.table, c.requested_rows, c.generated_data_rows, c.blank_rows, c.scenarios_total, c.scenarios_covered,
      c.max_scenarios_per_row || "unlimited", c.n_min_isolated, c.n_min_packed])));
  const unc = r.coverage.tables.flatMap((c) => c.uncovered.map((u) => [c.table, u.description, u.reason]));
  box.append(el("h4", { text: "Exception classes not represented (" + unc.length + ")" }));
  box.append(unc.length ? table(["Table", "Scenario", "Reason"], unc, { scroll: true }) : el("p", { text: "Every catalogued scenario is represented." }));

  box.append(el("h3", { text: "Scenario Manifest (" + r.manifest.length + ")" }));
  box.append(table(["Table", "Column", "Scenario", "Data rows", "Location in the file", "Note"],
    r.manifest.map((e) => [e.table, e.column_name || "(row)", e.description, e.data_rows.join(" "), locText(e), e.note || ""]), { scroll: true }));

  box.append(el("h3", { text: "Before / after" }));
  r.comparison.tables.forEach((t) => {
    box.append(el("h4", { text: t.name + ": " + t.source_rows + " source rows → " + t.generated_rows + " generated rows" }));
    box.append(table(["Column", "Source type", "Generated type", "Classes preserved", "Not represented", "New in output"],
      t.columns.map((c) => [c.name, c.source_type, c.generated_type, c.classes_preserved.join(", "), c.classes_not_represented.join(", "), c.classes_new_in_output.join(", ")]), { scroll: true }));
  });
  const sv = r.comparison.scenario_verification;
  box.append(el("p", { text: "Self-check: the generated file was profiled again; " + sv.covered_scenarios_found_again + " covered scenario(s) were found again, " + sv.covered_scenarios_not_found_again.length + " were not." }));
  if (r.comparison.structural_differences.length) box.append(el("ul", {}, r.comparison.structural_differences.map((d) => el("li", { text: d }))));

  box.append(el("h3", { text: "Preview of " + r.dataset_file }));
  r.preview.forEach((p) => {
    if (r.preview.length > 1) box.append(el("h4", { text: p.sheet }));
    const width = Math.max(1, ...p.rows.map((x) => x.length));
    const head = Array.from({ length: width }, (_, i) => String(i + 1));
    box.append(table(["#"].concat(head), p.rows.map((row, i) => [String(i + 1)].concat(Array.from({ length: width }, (_, j) => (row[j] === undefined ? "" : row[j])))), { scroll: true, cellClass: "cell" }));
  });

  box.append(el("h3", { text: "Export" }));
  box.append(el("p", { class: "hint", text: "Every file carries the classification above. The bundle contains the dataset, the Scenario Manifest, the coverage report, both quality reports, the comparison, the contract, the recipe and the assessment record." }));
  box.append(el("p", {}, r.files.map((f) => [el("a", { href: "/api/download/" + encodeURIComponent(f), text: f }), "  "])));
  const dir = el("input", { type: "text", id: "save-dir", placeholder: "/path/to/new-folder" });
  const btn = el("button", { text: "Save the bundle to this folder" });
  btn.addEventListener("click", () => busy(btn, "Saving…", async () => {
    const out = await api("/api/save", { directory: dir.value });
    box.append(el("p", { text: "Saved " + out.files.length + " files to " + out.directory + " (" + out.release_tier + ")." }));
  }));
  box.append(el("div", { class: "row" }, dir, btn));
  show("s-result", true);
  $("s-result").scrollIntoView({ behavior: "smooth" });
}

// ---- wiring ----------------------------------------------------------------------------------
async function init() {
  const res = await fetch("/api/meta", { credentials: "same-origin" });
  state.meta = await res.json();
  $("statement").textContent = state.meta.statement;
  $("version").textContent = "Anonimizer " + state.meta.version;

  $("btn-open").addEventListener("click", () => busy($("btn-open"), "Reading the file…", async () => {
    renderInspect(await api("/api/open", { path: $("path").value }));
  }));
  $("file").addEventListener("change", async () => {
    const f = $("file").files[0];
    if (!f) return;
    await busy($("btn-open"), "Copying the file into the session folder…", async () => {
      renderInspect(await api("/api/upload?name=" + encodeURIComponent(f.name), null, f));
    });
  });
  $("btn-recipe").addEventListener("click", () => busy($("btn-recipe"), "Applying…", async () => {
    renderInspect(await api("/api/recipe", { recipe: collectRecipe() }));
  }));
  $("btn-recipe-reset").addEventListener("click", () => busy($("btn-recipe-reset"), "Detecting…", async () => {
    $("ov-delim").value = ""; $("ov-enc").value = ""; $("ov-markers").value = "";
    renderInspect(await api("/api/recipe", { reset: true }));
  }));
  $("btn-profile").addEventListener("click", () => busy($("btn-profile"), "Profiling every cell…", async () => {
    const chosen = document.querySelector("input[name=policy]:checked");
    if (!chosen) throw new Error("Choose a privacy policy first.");
    const data = await api("/api/profile", { policy: chosen.value });
    renderReport(data.report);
    renderContract(data.contract);
    show("s-result", false);
  }));
  $("btn-contract").addEventListener("click", () => busy($("btn-contract"), "Applying…", async () => {
    renderContract((await api("/api/contract", collectDecisions())).contract);
  }));
  $("btn-generate").addEventListener("click", () => busy($("btn-generate"), "Generating and assessing…", async () => {
    const rowsFor = {};
    document.querySelectorAll("#rows-for [data-table]").forEach((i) => { if (i.value !== "") rowsFor[i.dataset.table] = Number(i.value); });
    renderResult(await api("/api/generate", { rows: Number($("rows").value), rows_for: rowsFor, seed: $("seed").value, packing: $("packing").value }));
  }));
}

init().catch((e) => say(e.message, "err"));
