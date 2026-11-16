"use strict";
// Anonimizer local interface. No external resource is loaded; every value shown on the page
// is inserted as text (never as HTML), so file contents cannot inject markup.

const $ = (id) => document.getElementById(id);
const state = {
  meta: null, inspect: null, report: null, contract: null,
  region: null, cards: [],            // step 2: selected region and its card nodes
  table: null, column: null,          // step 4: selected table name and column id ("" = whole rows)
  fields: {}, panels: {},             // step 4: form controls and panels by "table\u0000column"
  sample: null, sampleStale: false,   // synthetic sample rows of the applied contract
};

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

function show(id, on) {
  $(id).hidden = !on;
  const nav = $("nav-" + id);  // the step list shows which missions are open
  if (nav) nav.className = (nav.className || "").replace(/\s*\boff\b/g, "") + (on ? "" : " off");
}
function hideFrom(ids) { ids.forEach((id) => show(id, false)); }
const pill = (text, kind) => el("span", { class: "pill " + (kind || ""), text });
const statusKind = (s) => (s === "passed" ? "ok" : s === "failed" ? "bad" : "warn");
const LOW = 0.75;  // below this detection confidence a region is flagged for checking
const key = (t, c) => t + "\u0000" + c;

// ---- unapplied changes -----------------------------------------------------------------------
// The server only knows what was applied. An edited form that was not applied must never be
// taken for the configuration in force: the affected later steps are withdrawn until Apply.
const dirty = { recipe: false, contract: false };
function flag(id, text) {
  const n = $(id);
  n.textContent = text || "";
  n.className = text ? "pill warn" : "hint";
}
function dropResult(why) {
  const had = !$("s-result").hidden;
  show("s-result", false);
  $("result").replaceChildren();
  if (had && why) say(why + " The previous result and its download links were withdrawn.", "info");
}
function recipeEdited() {
  dirty.recipe = true;
  flag("recipe-state", "Unapplied changes: confirm and apply them, then analyse again.");
  dropResult("");
  hideFrom(["s-report", "s-contract", "s-generate"]);
  state.report = null;
  $("layout").replaceChildren(el("p", { class: "hint", text: "The table settings changed. Apply them to see the layout again." }));
  renderGlance();
}
function policyEdited() {
  if ($("s-report").hidden && $("s-contract").hidden) return;
  dropResult("");
  hideFrom(["s-report", "s-contract", "s-generate"]);
  state.report = null;
  renderGlance();
  say("The privacy policy changed: analyse the file again.", "info");
}
function contractEdited() {
  dirty.contract = true;
  state.sampleStale = true;
  flag("contract-state", "Unapplied changes: click 'Apply decisions' before generating.");
  dropResult("The column settings changed.");
  drawSheet();
}
function settingsEdited() { dropResult("The generation settings changed: generate again."); }
function onEdit(id, fn) { ["input", "change"].forEach((ev) => $(id).addEventListener(ev, fn)); }

// ---- your file at a glance -------------------------------------------------------------------
// Every sentence is a count or a fact taken from the server's answers. Nothing is interpreted.
function fileFacts(data) {
  const f = data.file;
  const facts = [data.file_name + " — " + f.format.toUpperCase()];
  if (f.format === "csv") {
    facts.push("encoding " + f.encoding.encoding + " (confidence " + f.encoding.confidence + ")");
    facts.push("delimiter " + JSON.stringify(f.delimiter.delimiter) + " (confidence " + f.delimiter.confidence + ")");
    if (f.records !== null && f.records !== undefined) facts.push(f.records + " records");
  } else {
    facts.push(f.sheet_count + " sheet(s)" + (f.hidden_sheets ? ", " + f.hidden_sheets + " hidden" : ""));
  }
  return facts;
}

function renderGlance() {
  const data = state.inspect;
  const box = $("glance");
  box.replaceChildren();
  if (!data) { show("s-glance", false); return; }
  const regions = data.recipe.tables;
  const count = (fn) => regions.filter(fn).length;
  const confirmed = count((t) => t.source === "user");
  const low = count((t) => t.include && t.confidence < LOW);
  const out = count((t) => !t.include);
  const lines = [fileFacts(data).join(" · ")];
  lines.push(regions.length + " region(s) found: " + count((t) => t.kind === "table") + " read as table(s), "
    + count((t) => t.kind !== "table") + " read as note(s), meaning text outside a table.");
  lines.push(confirmed === 0 ? "You have not confirmed any region yet: all of them are automatic detections."
    : confirmed + " of " + regions.length + " region(s) were confirmed or set by you; the others are automatic detections.");
  if (low) lines.push(low + " region(s) in use were detected with low confidence. Check them in step 2.");
  if (out) lines.push(out + " region(s) are left out and will not be analysed or generated.");
  if (dirty.recipe) lines.push("Table settings were changed but not applied; this summary describes the applied state.");
  const rep = state.report;
  if (!rep) {
    lines.push("Columns and exceptions have not been analysed yet (step 3).");
  } else {
    rep.tables.forEach((t) => lines.push("Table " + t.name + ": " + t.rows + " rows, " + t.columns + " columns"
      + (t.header_present ? "" : ", no header row") + "."));
    const cat = rep.exception_catalogue;
    lines.push(cat.length + " kind(s) of exception were found in the data; " + count2(cat, (e) => e.reproducible)
      + " of them can be generated. They are listed per column in step 4.");
    if (rep.relationships.length) lines.push(rep.relationships.length + " key reference(s) between tables: the values of one column were found in a key column of another table.");
    if (rep.unresolved_ambiguities.length) lines.push(rep.unresolved_ambiguities.length + " point(s) the tool could not decide; they are listed in the technical details of step 4.");
    lines.push("Rules that link several columns of one row are not detected and not preserved.");
  }
  lines.forEach((text) => box.append(el("li", { text })));
  show("s-glance", true);
}
const count2 = (list, fn) => list.filter(fn).length;

// ---- step 2: regions ---------------------------------------------------------------------------
function regionStatus(t) {
  if (!t.include) return pill("left out", "bad");
  if (t.source === "user") return pill("confirmed by you", "ok");
  if (t.confidence < LOW) return pill("detected — please check", "warn");
  return pill("detected automatically", "");
}

function renderInspect(data) {
  state.inspect = data;
  state.report = null;
  dirty.recipe = false;
  dirty.contract = false;
  flag("recipe-state", "");
  dropResult("");
  $("file-facts").textContent = fileFacts(data).join(" · ");
  const regions = data.recipe.tables;
  state.cards = regions.map((t, i) => {
    const low = t.confidence < LOW;
    const where = (t.sheet && t.sheet !== "csv" ? "Sheet " + t.sheet + " · " : "")
      + "rows " + t.first_row + "–" + t.last_data_row + " · columns " + t.first_col + "–" + t.last_col + " · "
      + (t.kind !== "table" ? "not read as a table" : t.header_row ? "header in row " + t.header_row : "no header row");
    return el("div", { class: "card" + (low ? " low" : "") + (t.include ? "" : " out") },
      el("div", { class: "card-top" },
        el("label", {}, el("input", { type: "checkbox", checked: t.include, "data-i": i, "data-k": "include" }), " Use"),
        regionStatus(t)),
      el("input", { type: "text", value: t.name, "data-i": i, "data-k": "name", "aria-label": "Name of region " + (i + 1) }),
      el("select", { "data-i": i, "data-k": "kind", "aria-label": "Kind of region " + (i + 1) },
        ["table", "note"].map((k) => el("option", { value: k, selected: t.kind === k, text: k === "table" ? "table" : "note (text outside a table)" }))),
      el("div", { class: "hint", text: where }),
      low && (t.notes || []).length ? el("div", { class: "low", text: t.notes.join("; ") }) : null,
      el("button", { class: "link", text: "Show the layout of this region", onclick: () => selectRegion(i) }));
  });
  $("region-cards").replaceChildren(...state.cards);
  const rows = regions.map((t, i) => {
    const num = (k) => el("input", { type: "number", min: "1", class: "num", value: t[k] === null ? "" : t[k], "data-i": i, "data-k": k });
    return [t.name, t.sheet || "", num("header_row"), num("first_data_row"), num("last_data_row"), num("first_col"), num("last_col"),
      el("span", { class: t.confidence < LOW ? "low" : null, text: t.confidence }),
      (t.notes || []).join("; ") + (t.source === "user" ? " [set by you]" : "")];
  });
  $("regions").replaceChildren(table(["Region", "Sheet", "Header row", "First data row", "Last data row", "First column", "Last column", "Confidence", "Notes"], rows, { scroll: true }));
  show("s-regions", true);
  show("s-policy", true);
  hideFrom(["s-report", "s-contract", "s-generate"]);
  renderPolicies();
  renderGlance();
  const first = regions.findIndex((t) => t.kind === "table" && t.include);
  if (regions.length) selectRegion(first < 0 ? 0 : first);
}

async function selectRegion(i) {
  state.region = i;
  const regions = state.inspect.recipe.tables;
  state.cards.forEach((card, j) => {
    card.className = "card" + (regions[j].confidence < LOW ? " low" : "") + (regions[j].include ? "" : " out") + (j === i ? " sel" : "");
  });
  const box = $("layout");
  if (dirty.recipe) {
    box.replaceChildren(el("p", { class: "hint", text: "The table settings changed. Apply them to see the layout again." }));
    return;
  }
  try {
    const lay = await api("/api/layout", { index: i });
    if (state.region === i && !dirty.recipe) drawLayout(lay, regions[i]);
  } catch (e) {
    box.replaceChildren(el("p", { class: "hint", text: "The layout of this region could not be shown: " + e.message }));
  }
}

const ROLE = { header: "header", intro: "text before the table", data: "data" };
function drawLayout(lay, region) {
  const head = el("tr", {}, el("th", { text: "Row" }), Array.from({ length: lay.columns }, (_, j) => el("th", { text: "col " + (lay.first_col + j) })));
  const body = lay.rows.map((r) => el("tr", {},
    el("td", { class: "rowhead", text: r.row + " · " + (region.kind === "table" ? ROLE[r.role] : "note") }),
    r.kinds.map((k) => el("td", { class: "k k-" + k, text: k }))));
  $("layout").replaceChildren(
    el("h3", { text: "Layout of " + region.name + ": first " + lay.rows.length + " of " + lay.rows_total + " rows"
      + (lay.columns < lay.columns_total ? ", first " + lay.columns + " of " + lay.columns_total + " columns" : "") }),
    el("p", { class: "hint", text: "Only the kind of each cell is shown (text, number, date, missing). The values of your file are not sent to this page. "
      + "If the header or the first data row is in the wrong place, correct it in the technical details below." }),
    el("div", { class: "scroll" }, el("table", {}, el("thead", {}, head), el("tbody", {}, body))));
}

function collectRecipe() {
  const tables = state.inspect.recipe.tables.map((t) => Object.assign({}, t));
  ["#region-cards [data-i]", "#regions [data-i]"].forEach((sel) => document.querySelectorAll(sel).forEach((inp) => {
    const t = tables[Number(inp.dataset.i)];
    const k = inp.dataset.k;
    if (k === "include") t.include = inp.checked;
    else if (k === "name" || k === "kind") t[k] = inp.value;
    else t[k] = inp.value === "" ? null : Number(inp.value);
  }));
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

// ---- technical details of step 4: full report --------------------------------------------------
function renderReport(report) {
  const box = $("report");
  box.replaceChildren();
  box.append(el("h3", { text: "Tables" }));
  box.append(table(["Table", "Sheet", "Rows", "Columns", "Header", "Intro rows", "Detection confidence", "Duplicate rows", "Notes"],
    report.tables.map((t) => [t.name, t.sheet, t.rows, t.columns, t.header_present ? "yes" : "no", t.introductory_rows,
      el("span", { class: t.detection_confidence < LOW ? "low" : null, text: t.detection_confidence }),
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
    box.append(el("h3", { text: "Key references between tables" }));
    box.append(table(["From", "To", "Share of values found", "Rows without a match"],
      report.relationships.map((r) => [r.from_table + "." + r.from_column_name, r.to_table + "." + r.to_column_name, r.containment, r.dangling_rows])));
  }
  if (report.unresolved_ambiguities.length) {
    box.append(el("h3", { text: "Unresolved ambiguities" }));
    box.append(el("ul", {}, report.unresolved_ambiguities.map((a) => el("li", { text: a.scope + ": " + a.message + " (confidence " + a.confidence + ")" }))));
  }
  show("s-report", true);
}

// ---- step 4: column workspace -------------------------------------------------------------------
function scenarioTable(list) {
  return table(["Generate", "Pin", "Priority", "Scenario", "Count in source", "Note"], list.map((s) => [
    el("input", { type: "checkbox", checked: s.enabled && s.reproducible, disabled: !s.reproducible, "data-s": s.id, "data-k": "enabled" }),
    el("input", { type: "checkbox", checked: s.pinned, disabled: !s.reproducible, "data-s": s.id, "data-k": "pinned" }),
    "P" + s.priority, s.description, s.source_count, s.reproducible ? "" : s.not_reproduced_reason,
  ]), { scroll: true });
}

function renderContract(contract) {
  state.contract = contract;
  dirty.contract = false;
  dropResult("");
  flag("contract-state", "");
  const box = $("contract");
  box.replaceChildren();
  state.fields = {};
  state.panels = {};
  state.sample = null;  // sample rows belong to one applied contract; they are fetched again after this
  state.sampleStale = false;
  let unreviewed = 0;
  contract.tables.forEach((t) => {
    t.columns.forEach((c) => {
      const scen = t.scenarios.filter((s) => s.column === c.id);
      const at = { "data-t": t.name, "data-c": c.id };
      const f = {
        col: c, scenarios: scen.length,
        name: el("input", Object.assign({ type: "text", value: c.name, "data-k": "name" }, at)),
        keep: el("input", Object.assign({ type: "checkbox", checked: c.keep, "data-k": "keep" }, at)),
        sens: el("select", Object.assign({ "data-k": "sensitivity" }, at),
          state.meta.sensitivity_classes.map((s) => el("option", { value: s, selected: c.sensitivity.class === s, text: s }))),
      };
      if (c.keep && c.sensitivity.class === "unreviewed") unreviewed += 1;
      const copied = c.value_policy.mode !== "synthetic";
      const panel = el("div", { class: "panel" },
        el("h3", { text: "Column " + c.name + " of " + t.name }),
        el("p", { class: "hint", text: "Type found: " + c.logical_type + " · key role: " + c.key.role
          + (c.key.references ? " → " + c.key.references.table : "") + " · values: " + (copied ? "frequent values copied" : "synthetic") }),
        el("div", { class: "row" }, el("label", { text: "Output name" }), f.name,
          el("label", {}, f.keep, " Include this column in the output")),
        c.can_keep_literals ? el("div", { class: "row" }, el("label", {},
          el("input", Object.assign({ type: "checkbox", checked: copied, "data-k": "literal_categories" }, at)),
          " Copy the frequent values of this column instead of inventing them"
          + (copied ? " (" + c.value_policy.approved_literals.length + " approved)" : " (needs an approver name below)"))) : null,
        el("details", { open: c.sensitivity.class === "unreviewed" }, el("summary", { text: "Classification: " + c.sensitivity.class }),
          el("div", { class: "row" }, el("label", { text: "Sensitivity" }), f.sens,
            el("span", { class: "hint", text: c.sensitivity.basis + (c.sensitivity.confirmed ? " (confirmed)" : " (proposal)") }))),
        el("h4", { text: "Scenarios to generate for this column (" + scen.length + ")" }),
        scen.length ? scenarioTable(scen) : el("p", { class: "hint", text: "No exception was catalogued for this column." }));
      panel.hidden = true;
      state.fields[key(t.name, c.id)] = f;
      state.panels[key(t.name, c.id)] = panel;
      box.append(panel);
    });
    const rowScen = t.scenarios.filter((s) => !t.columns.some((c) => c.id === s.column));
    if (rowScen.length) {
      const panel = el("div", { class: "panel" },
        el("h3", { text: "Scenarios that concern whole rows of " + t.name + " (" + rowScen.length + ")" }), scenarioTable(rowScen));
      panel.hidden = true;
      state.panels[key(t.name, "")] = panel;
      box.append(panel);
    }
  });
  const r = contract.review;
  $("contract-state").textContent = r.confirmed ? "Confirmed by " + r.confirmed_by + " on " + r.confirmed_at + "." : "Not confirmed yet: output will be LOCAL_ONLY.";
  $("review-note").textContent = unreviewed ? unreviewed + " kept column(s) have no sensitivity class yet (\"unreviewed\"). They are marked in the grid; open \"Classification\" in each of them to set it." : "";
  const rf = $("rows-for");
  rf.replaceChildren();
  if (contract.tables.length > 1) {
    rf.append(el("span", { class: "hint", text: "Optional row count per table (smaller tables keep their source size by default):" }));
    contract.tables.forEach((t) => rf.append(el("label", { text: t.name }), el("input", { type: "number", min: "1", class: "short", "data-table": t.name, placeholder: "auto" })));
  }
  const keepTable = contract.tables.find((t) => t.name === state.table) || contract.tables[0];
  const keepCol = keepTable && state.panels[key(keepTable.name, state.column === null ? "\u0001" : state.column)] ? state.column
    : (keepTable && keepTable.columns.length ? keepTable.columns[0].id : null);
  show("s-contract", true);
  show("s-generate", true);
  if (keepTable) selectColumn(keepTable.name, keepCol);
}

function selectColumn(tableName, columnId) {
  state.table = tableName;
  state.column = columnId;
  Object.entries(state.panels).forEach(([k, panel]) => { panel.hidden = k !== key(tableName, columnId === null ? "\u0001" : columnId); });
  drawSheet();
}

function currentTable() {
  return state.contract ? state.contract.tables.find((t) => t.name === state.table) || null : null;
}

function drawSheet() {
  const t = currentTable();
  if (!t) return;
  $("table-tabs").replaceChildren(...state.contract.tables.map((x) =>
    el("button", { class: "tab" + (x.name === t.name ? " sel" : ""), text: x.name + " · " + x.columns.length + " columns · about " + x.source_rows + " source rows",
      onclick: () => selectColumn(x.name, x.columns.length ? x.columns[0].id : null) })));
  const head = el("tr", {}, el("th", { class: "corner", text: "#" }), t.columns.map((c) => {
    const f = state.fields[key(t.name, c.id)];
    const kept = f.keep.checked;
    const notes = [c.logical_type, f.scenarios + " exception(s)"];
    if (!kept) notes.push("left out");
    else if (f.sens.value === "unreviewed") notes.push("unreviewed");
    return el("th", {}, el("button", { class: "colbtn" + (c.id === state.column ? " sel" : "") + (kept ? "" : " dropped"),
      title: "Edit this column", onclick: () => selectColumn(t.name, c.id) },
      el("span", { class: "nm", text: f.name.value || "(no name)" }), el("small", { text: notes.join(" · ") })));
  }));
  const sample = !state.sampleStale && state.sample ? state.sample[t.name] : null;
  const body = (sample ? sample.rows : []).map((row, i) => el("tr", {}, el("td", { class: "rowhead", text: String(i + 1) }),
    t.columns.map((c) => {
      const j = sample.columns.indexOf(c.id);
      return el("td", { class: "cell", text: j < 0 ? "" : row[j] });
    })));
  const note = state.sampleStale ? "The column settings changed. Press \"Apply decisions\" to see sample rows for the new settings."
    : sample ? "The rows above are synthetic examples of ordinary values, produced from the applied settings. They are not rows of your file; exceptions are listed per column."
      : "No sample rows are available for this table.";
  const rowPanel = state.panels[key(t.name, "")];
  $("sheet").replaceChildren(
    el("div", { class: "scroll" }, el("table", { class: "sheet" }, el("thead", {}, head), el("tbody", {}, body))),
    el("p", { class: "hint", text: note }),
    rowPanel ? el("button", { class: "tab" + (state.column === "" ? " sel" : ""), text: "Scenarios that concern whole rows", onclick: () => selectColumn(t.name, "") }) : null);
}

async function loadSample() {
  try {
    state.sample = (await api("/api/sample", {})).tables;
  } catch (e) {
    state.sample = null;
  }
  state.sampleStale = false;
  drawSheet();
}

function bulkRename(restore) {
  const t = currentTable();
  if (!t) return;
  const style = $("bulk-style").value;
  const find = $("bulk-find").value;
  let changed = 0;
  t.columns.forEach((c) => {
    const f = state.fields[key(t.name, c.id)];
    if (!f.keep.checked) return;
    let v = restore ? c.name : f.name.value;
    if (!restore) {
      if (find) v = v.split(find).join($("bulk-replace").value);
      if (style === "snake") v = v.trim().toLowerCase().replace(/[\s!-\/:-@\[-`{-~]+/g, "_").replace(/^_+|_+$/g, "");
      else if (style === "lower") v = v.toLowerCase();
      else if (style === "upper") v = v.toUpperCase();
      v = $("bulk-prefix").value + v + $("bulk-suffix").value;
    }
    if (v && v !== f.name.value) { f.name.value = v; changed += 1; }
  });
  if (changed) contractEdited(); else drawSheet();
  say(changed + " output name(s) of " + t.name + (restore ? " were set back to the applied names." : " were filled in.")
    + (changed ? " Press \"Apply decisions\" to use them." : ""), "info");
}

function collectDecisions() {
  const cols = {};
  document.querySelectorAll("#contract [data-c]").forEach((inp) => {
    const k = key(inp.dataset.t, inp.dataset.c);
    const c = cols[k] || (cols[k] = { table: inp.dataset.t, id: inp.dataset.c });
    c[inp.dataset.k] = inp.type === "checkbox" ? inp.checked : inp.value;
  });
  const scen = {};
  document.querySelectorAll("#contract [data-s]").forEach((inp) => {
    const s = scen[inp.dataset.s] || (scen[inp.dataset.s] = { id: inp.dataset.s });
    s[inp.dataset.k] = inp.checked;
  });
  return { columns: Object.values(cols), scenarios: Object.values(scen), approved_by: $("approved-by").value.trim() || null, confirm_by: $("confirm-by").value.trim() || null };
}

// ---- step 5: result ------------------------------------------------------------------------
function locText(e) {
  return e.locations.map((l) => l.cell || (l.line ? "line " + l.line + (l.field ? ", field " + l.field : "") : "row " + l.row)).join("; ");
}

function renderResult(r) {
  const box = $("result");
  box.replaceChildren();
  const a = r.assessment;
  const restricted = a.release_tier === "RESTRICTED";
  const rowsMade = r.coverage.tables.reduce((n, c) => n + c.generated_data_rows, 0);
  box.append(el("div", { class: "banner done" },
    el("strong", { text: "Done: " + r.dataset_file + " was generated (" + rowsMade + " data rows, release tier " + a.release_tier + ")." }),
    el("div", {}, el("a", { class: "btn download", href: "/api/download/" + encodeURIComponent(r.dataset_file), text: "Download " + r.dataset_file }),
      "The other bundle files and 'save to a folder' are under Export at the end of this section.")));
  box.append(el("div", { class: "banner " + (restricted ? "restricted" : "local") },
    el("strong", { text: "Release tier: " + a.release_tier }),
    el("div", { text: restricted ? "May be shared only inside the organisation that controls the source data, under its own rules. Not assessed as anonymous."
      : "Keep on this machine. Not assessed for sharing." }),
    el("div", { text: "Transformation: " + a.transformation_class + " · assessment: " + a.assessment_status + " · policy: " + a.policy.id + " v" + a.policy.version + " · review by " + a.review_by }),
    a.tier_reasons.length ? el("ul", {}, a.tier_reasons.map((x) => el("li", { text: x }))) : null));

  box.append(el("h3", { text: "Preview of " + r.dataset_file }));
  r.preview.forEach((p) => {
    if (r.preview.length > 1) box.append(el("h4", { text: p.sheet }));
    const width = Math.max(1, ...p.rows.map((x) => x.length));
    const head = Array.from({ length: width }, (_, i) => String(i + 1));
    box.append(table(["#"].concat(head), p.rows.map((row, i) => [String(i + 1)].concat(Array.from({ length: width }, (_, j) => (row[j] === undefined ? "" : row[j])))), { scroll: true, cellClass: "cell" }));
  });

  const criteria = Object.entries(a.criteria || {});
  const allPassed = a.assessment_status === "passed" && criteria.every(([, v]) => v.status === "passed");
  box.append(el("details", { open: !allPassed },
    el("summary", { text: "Privacy assessment: " + a.assessment_status + " (" + criteria.length + " criteria)" }),
    table(["Criterion", "Status", "How it was measured"], criteria.map(([k, v]) => [k.replace(/_/g, " "), pill(v.status.replace(/_/g, " "), statusKind(v.status)), v.method])),
    (a.residual_risk_statements || []).length ? el("ul", {}, a.residual_risk_statements.map((s) => el("li", { text: s }))) : null));

  const unc = r.coverage.tables.flatMap((c) => c.uncovered.map((u) => [c.table, u.description, u.reason]));
  const covered = r.coverage.tables.reduce((n, c) => n + c.scenarios_covered, 0);
  const total = r.coverage.tables.reduce((n, c) => n + c.scenarios_total, 0);
  box.append(el("details", { open: unc.length > 0 },
    el("summary", { text: "Scenario coverage: " + covered + " of " + total + " scenario(s) represented, " + unc.length + " not represented" }),
    table(["Table", "Requested rows", "Generated rows", "Blank rows", "Scenarios", "Covered", "Max per row", "Rows needed (one per row)", "Rows needed (packed)"],
      r.coverage.tables.map((c) => [c.table, c.requested_rows, c.generated_data_rows, c.blank_rows, c.scenarios_total, c.scenarios_covered,
        c.max_scenarios_per_row || "unlimited", c.n_min_isolated, c.n_min_packed])),
    el("h4", { text: "Exception classes not represented (" + unc.length + ")" }),
    unc.length ? table(["Table", "Scenario", "Reason"], unc, { scroll: true }) : el("p", { text: "Every catalogued scenario is represented." })));

  box.append(el("details", {},
    el("summary", { text: "Scenario Manifest: where each scenario is in the file (" + r.manifest.length + ")" }),
    table(["Table", "Column", "Scenario", "Data rows", "Location in the file", "Note"],
      r.manifest.map((e) => [e.table, e.column_name || "(row)", e.description, e.data_rows.join(" "), locText(e), e.note || ""]), { scroll: true })));

  const sv = r.comparison.scenario_verification;
  box.append(el("details", {},
    el("summary", { text: "Before / after comparison of the source and the generated file" }),
    r.comparison.tables.map((t) => [
      el("h4", { text: t.name + ": " + t.source_rows + " source rows → " + t.generated_rows + " generated rows" }),
      table(["Column", "Source type", "Generated type", "Classes preserved", "Not represented", "New in output"],
        t.columns.map((c) => [c.name, c.source_type, c.generated_type, c.classes_preserved.join(", "), c.classes_not_represented.join(", "), c.classes_new_in_output.join(", ")]), { scroll: true })]),
    el("p", { text: "Self-check: the generated file was profiled again; " + sv.covered_scenarios_found_again + " covered scenario(s) were found again, " + sv.covered_scenarios_not_found_again.length + " were not." }),
    r.comparison.structural_differences.length ? el("ul", {}, r.comparison.structural_differences.map((d) => el("li", { text: d }))) : null));

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
  $("s-generate").scrollIntoView({ behavior: "smooth" });
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
  $("btn-profile").addEventListener("click", () => busy($("btn-profile"), "Analysing every cell…", async () => {
    if (dirty.recipe) throw new Error("The table settings were changed but not applied. Click 'Confirm and apply these table settings' (or 'Back to automatic detection') first.");
    const chosen = document.querySelector("input[name=policy]:checked");
    if (!chosen) throw new Error("Choose a privacy policy first.");
    const data = await api("/api/profile", { policy: chosen.value });
    state.report = data.report;
    renderReport(data.report);
    renderContract(data.contract);
    renderGlance();
    await loadSample();
  }));
  $("btn-contract").addEventListener("click", () => busy($("btn-contract"), "Applying…", async () => {
    renderContract((await api("/api/contract", collectDecisions())).contract);
    await loadSample();
  }));
  $("btn-bulk").addEventListener("click", () => bulkRename(false));
  $("btn-bulk-undo").addEventListener("click", () => bulkRename(true));
  $("btn-generate").addEventListener("click", () => busy($("btn-generate"), "Generating and assessing…", async () => {
    if (dirty.recipe) throw new Error("The table settings were changed but not applied. Apply them and analyse again before generating.");
    if (dirty.contract) throw new Error("The column settings have unapplied changes. Click 'Apply decisions' first; nothing was generated.");
    dropResult("");
    const rowsFor = {};
    document.querySelectorAll("#rows-for [data-table]").forEach((i) => { if (i.value !== "") rowsFor[i.dataset.table] = Number(i.value); });
    renderResult(await api("/api/generate", { rows: Number($("rows").value), rows_for: rowsFor, seed: $("seed").value, packing: $("packing").value }));
  }));
  onEdit("s-regions", recipeEdited);
  onEdit("policies", policyEdited);
  onEdit("contract", contractEdited);
  onEdit("approved-by", contractEdited);
  onEdit("confirm-by", contractEdited);
  onEdit("gen-settings", settingsEdited);
}

init().catch((e) => say(e.message, "err"));
