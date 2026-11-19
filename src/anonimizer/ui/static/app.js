"use strict";
// Anonimizer local interface. No external resource is loaded; every value shown on the page
// is inserted as text (never as HTML), so file contents cannot inject markup.

const $ = (id) => document.getElementById(id);
const API = 4;  // must equal API_REVISION of the server that delivered this page
const PAGE_ROWS = 50;   // rows of the source shown at a time
const PAGE_COLS = 30;
const SOURCE_ROWS = 5;  // original rows shown above the synthetic sample in step 4
const state = {
  meta: null, inspect: null, report: null, contract: null,
  region: null, cards: [],            // step 2: selected region and its card nodes
  minis: {}, techInputs: {},          // step 2: small preview box and first correction field per region
  smallOpen: undefined,               // step 2: whether "Small regions and notes" was opened or closed by the user
  table: null, column: null,          // step 4: selected table name and column id ("" = whole rows)
  fields: {}, panels: {},             // step 4: form controls and panels by "table\u0000column"
  sample: null, sampleStale: false,   // synthetic sample rows of the applied contract
  sampleWhy: "",                      // why no sample is available, in the server's words
  src: null,                          // source inspector: the rectangle of original cells on screen
  srcRows: {},                        // first original data rows per table, for the grid of step 4
  stats: null,                        // exact local counts, once asked for
  original: {},                       // step 4: each column's name in the file, kept from the analysis
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
  $("compare").replaceChildren();
  if (had && why) say(why + " The previous result and its download links were withdrawn.", "info");
}
function recipeEdited() {
  dirty.recipe = true;
  flag("recipe-state", "Unapplied changes: confirm and apply them, then analyse again.");
  dropResult("");
  hideFrom(["s-report", "s-contract", "s-generate"]);
  state.report = null;
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
  if (regions.length) lines.push(count(isMainTable) + " table(s) have " + MAIN_ROWS + " or more data rows and are listed first in step 2; "
    + count((t) => !isMainTable(t)) + " smaller region(s) and note(s) are grouped below them.");
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

// The list of regions is split in two for display only. Which regions are analysed and generated is
// decided by "Use this region" and the confirm button, never by the group a region is shown in.
const MAIN_ROWS = 5;   // a table region with at least this many data rows is listed under "Detected tables"
const MINI_ROWS = 5;   // data rows shown in the small preview of a region
const MINI_COLS = 30;  // columns fetched for the small preview; wider regions scroll and say so
const plural = (n, one, many) => n + " " + (n === 1 ? one : many);
// Sizes come from the region's own row and column numbers. The header row is not a data row.
function regionSize(t) {
  return {
    rows: t.kind === "table" ? t.last_data_row - t.first_data_row + 1 : t.last_data_row - t.first_row + 1,
    cols: t.last_col - t.first_col + 1,
  };
}
const isMainTable = (t) => t.kind === "table" && regionSize(t).rows >= MAIN_ROWS;
const cardClass = (t, sel) => "card" + (t.confidence < LOW ? " low" : "") + (t.include ? "" : " out") + (sel ? " sel" : "");

function regionCard(t, i, multiSheet) {
  const low = t.confidence < LOW;
  const size = regionSize(t);
  const where = (t.sheet && t.sheet !== "csv" ? "Sheet " + t.sheet + " · " : "")
    + "rows " + t.first_row + "–" + t.last_data_row + " · columns " + t.first_col + "–" + t.last_col + " · "
    + (t.kind !== "table" ? "not read as a table" : t.header_row ? "header in row " + t.header_row : "no header row")
    + " · detection confidence " + t.confidence;
  const meta = (multiSheet && t.sheet ? "Sheet " + t.sheet + " · " : "")
    + (t.kind === "table" ? plural(size.rows, "data row", "data rows") : plural(size.rows, "row", "rows")) + " · "
    + plural(size.cols, "column", "columns") + (t.kind === "table" && !t.header_row ? " · no header row" : "");
  const mini = el("div", { class: "mini" });
  state.minis[i] = mini;
  // One short line per region. Opening it shows a small preview of its cells, loaded only then.
  const card = el("details", { class: cardClass(t, false), ontoggle: () => { if (card.open) loadMini(i); } },
    el("summary", { class: "card-top" },
      el("span", { class: "rname", text: t.name }),
      el("span", { class: "kind", text: t.kind === "table" ? "table" : "note" }),
      el("span", { class: "meta", text: meta }),
      regionStatus(t)),
    el("div", { class: "card-body" },
      mini,
      el("div", { class: "card-fields" },
        el("label", {}, el("input", { type: "checkbox", checked: t.include, "data-i": i, "data-k": "include" }), " Use this region"),
        el("input", { type: "text", value: t.name, "data-i": i, "data-k": "name", "aria-label": "Name of region " + (i + 1) }),
        el("select", { "data-i": i, "data-k": "kind", "aria-label": "Kind of region " + (i + 1) },
          ["table", "note"].map((k) => el("option", { value: k, selected: t.kind === k, text: k === "table" ? "table" : "note (text outside a table)" }))),
        el("div", { class: "hint", text: where }),
        low && (t.notes || []).length ? el("div", { class: "low", text: t.notes.join("; ") }) : null,
        el("button", { class: "link", text: "Correct its rows, columns or header", onclick: () => openCorrections(i) }))));
  return card;
}

function renderInspect(data) {
  state.inspect = data;
  state.report = null;
  dirty.recipe = false;
  dirty.contract = false;
  flag("recipe-state", "");
  dropResult("");
  state.stats = null;  // counts belong to one applied set of table settings
  $("stats").replaceChildren();
  $("file-facts").textContent = fileFacts(data).join(" · ");
  const regions = data.recipe.tables;
  const multiSheet = new Set(regions.map((t) => t.sheet)).size > 1 || (data.sheets || []).length > 1;
  state.minis = {};  // previews belong to one applied set of table settings
  state.cards = regions.map((t, i) => regionCard(t, i, multiSheet));
  const main = [];
  const small = [];
  regions.forEach((t, i) => (isMainTable(t) ? main : small).push(state.cards[i]));  // source order within each group
  const smallBox = el("details", { class: "rgroup small",
    open: state.smallOpen === undefined ? main.length === 0 : state.smallOpen || main.length === 0,
    ontoggle: () => { if (main.length) state.smallOpen = smallBox.open; } },  // forced open when alone: not the user's choice
    el("summary", {}, "Small regions and notes ", el("span", { class: "count", text: "(" + small.length + ")" })),
    el("p", { class: "hint", text: "Tables with fewer than " + MAIN_ROWS + " data rows, and text read as notes. Some of them may still be "
      + "useful tables: open one to see its cells. Being listed here changes nothing: a region is used if \"Use this region\" is ticked." }),
    small.length ? small : el("p", { class: "hint", text: "There is no small region or note in this file." }));
  $("region-cards").replaceChildren(
    el("div", { class: "rgroup main" },
      el("h3", {}, "Detected tables ", el("span", { class: "count", text: "(" + main.length + ")" })),
      main.length ? main : el("p", { class: "hint", text: "No table with " + MAIN_ROWS + " or more data rows was found. "
        + (small.length ? "Your tables may be among the small regions below, which are opened for this reason." : "") })),
    smallBox);
  state.techInputs = {};
  const rows = regions.map((t, i) => {
    const num = (k) => el("input", { type: "number", min: "1", class: "num", value: t[k] === null ? "" : t[k], "data-i": i, "data-k": k });
    const first = num("header_row");
    state.techInputs[i] = first;
    return [t.name, t.sheet || "", first, num("first_data_row"), num("last_data_row"), num("first_col"), num("last_col"),
      el("span", { class: t.confidence < LOW ? "low" : null, text: t.confidence }),
      (t.notes || []).join("; ") + (t.source === "user" ? " [set by you]" : "")];
  });
  $("regions").replaceChildren(table(["Region", "Sheet", "Header row", "First data row", "Last data row", "First column", "Last column", "Confidence", "Notes"], rows, { scroll: true }));
  show("s-regions", true);
  show("s-policy", true);
  hideFrom(["s-report", "s-contract", "s-generate"]);
  renderPolicies();
  renderGlance();
  let first = regions.findIndex((t) => isMainTable(t) && t.include);
  if (first < 0) first = regions.findIndex((t) => t.kind === "table" && t.include);
  if (regions.length) selectRegion(first < 0 ? 0 : first);
}

function selectRegion(i) {
  state.region = i;
  const regions = state.inspect.recipe.tables;
  state.cards.forEach((card, j) => { card.className = cardClass(regions[j], j === i); });
  $("source-box").open = true;
  return loadSource({ region: i });
}

// The small preview inside a region's line: its header and first data rows, read on demand from the
// local source inspector. Looking at it selects, confirms and changes nothing.
async function loadMini(i) {
  const box = state.minis[i];
  if (!box || box.dataset.loaded) return;
  box.dataset.loaded = "1";
  const t = state.inspect.recipe.tables[i];
  const size = regionSize(t);
  const isTable = t.kind === "table";
  const start = isTable ? (t.header_row || t.first_data_row) : t.first_row;
  const dataFrom = isTable ? t.first_data_row : t.first_row;
  const open = el("button", { class: "small-btn", text: "Open detailed preview", onclick: () => openDetailed(i) });
  box.replaceChildren(el("p", { class: "hint", text: "Loading a preview…" }));
  let d;
  try {
    d = await api("/api/source", { region: i, row: start, col: t.first_col, rows: dataFrom - start + MINI_ROWS, cols: Math.min(size.cols, MINI_COLS) });
  } catch (e) {
    delete box.dataset.loaded;
    box.replaceChildren(el("p", { class: "low", text: "The preview could not be shown: " + e.message }), el("div", { class: "row" }, open));
    return;
  }
  const cols = Array.from({ length: d.columns }, (_, j) => d.first_col + j);
  const header = isTable && t.header_row ? d.rows.find((r) => r.row === t.header_row) : null;
  const data = d.rows.filter((r) => r.row >= dataFrom && r.row <= t.last_data_row).slice(0, MINI_ROWS);
  const cell = (v) => (v === null || v === undefined ? "" : v);
  const head = el("tr", {}, el("th", { class: "corner", text: "Row" }),
    cols.map((c, j) => el("th", { text: header ? cell(header.cells[j]) || "col " + c : "col " + c })));
  const body = data.map((r) => el("tr", {}, el("td", { class: "rowhead", text: String(r.row) }),
    r.cells.map((v) => el("td", { class: v === null ? "absent" : null, text: cell(v) }))));
  const notes = [];
  if (isTable) notes.push(header ? "Header in row " + t.header_row + "." : "No header row: the columns are shown by number.");
  notes.push("First " + plural(data.length, "row", "rows") + " of " + size.rows + (isTable ? " data row(s)." : " row(s)."));
  if (size.cols > d.columns) notes.push("Columns " + d.first_col + "–" + (d.first_col + d.columns - 1) + " of " + t.first_col + "–" + t.last_col + " are shown.");
  if (d.truncated_cells) notes.push(plural(d.truncated_cells, "long cell is", "long cells are") + " cut for display.");
  box.replaceChildren(
    el("div", { class: "scroll mini-grid" }, el("table", { class: "src mini-table" }, el("thead", {}, head), el("tbody", {}, body))),
    el("div", { class: "row" }, open, el("span", { class: "hint", text: notes.join(" ") })));
}

// Shows the region in the large source viewer, with what surrounds it, and brings the viewer into view.
async function openDetailed(i) {
  await selectRegion(i);
  $("source-box").scrollIntoView({ behavior: "smooth", block: "start" });
}

// The boundary and header numbers live in the technical details; this opens them at the region's row.
function openCorrections(i) {
  $("regions-tech").open = true;
  const inp = state.techInputs[i];
  if (inp) {
    inp.scrollIntoView({ behavior: "smooth", block: "center" });
    if (inp.focus) inp.focus({ preventScroll: true });
  }
}

// ---- source inspector: the original cells of the user's own file --------------------------------
// What is loaded here stays in this page. It is never sent back to the server and never becomes part
// of the contract, a report or an export.
async function loadSource(request) {
  try {
    state.src = await api("/api/source", Object.assign({ rows: PAGE_ROWS, cols: PAGE_COLS }, request));
    drawSource();
  } catch (e) {
    state.src = null;
    $("source-pos").textContent = "";
    $("source").replaceChildren(el("p", { class: "low", text: "The file could not be shown: " + e.message }));
  }
}

function moveSource(change) {
  const d = state.src;
  if (d) loadSource(Object.assign({ sheet: d.sheet, row: d.first_row, col: d.first_col }, change(d)));
}

const within = (r, row, col) => row >= r.first_row && row <= r.last_row && col >= r.first_col && col <= r.last_col;

function drawSource() {
  const d = state.src;
  const sel = d.regions.find((r) => r.index === state.region) || null;
  const cols = Array.from({ length: d.columns }, (_, j) => d.first_col + j);
  const head = el("tr", {}, el("th", { text: "Row" }), cols.map((c) => {
    const mine = sel && sel.kind === "table" && c >= sel.first_col && c <= sel.last_col;
    return el("th", { class: mine ? "in" : null }, mine
      ? el("button", { class: "link", title: "Open the settings of this column", text: "col " + c + " · settings", onclick: () => openColumn(sel, c) })
      : "col " + c);
  }));
  const body = d.rows.map((r) => {
    const role = !sel || r.row < sel.first_row || r.row > sel.last_row ? ""
      : sel.kind !== "table" ? "note" : r.row === sel.header_row ? "header" : r.row < sel.first_data_row ? "before the table" : "data";
    return el("tr", {}, el("td", { class: "rowhead", text: r.row + (role ? " · " + role : "") + (r.hidden ? " · hidden row" : "") }),
      r.cells.map((v, j) => {
        const c = cols[j];
        const cls = v === null ? "absent" : sel && within(sel, r.row, c) ? (r.row === sel.header_row ? "hdr" : "in")
          : d.regions.some((x) => within(x, r.row, c)) ? "oth" : null;
        return el("td", { class: cls, text: v === null ? "" : v });
      }));
  });
  const lastRow = d.rows.length ? d.rows[d.rows.length - 1].row : d.first_row;
  $("source-title").textContent = sel ? "Your file: " + sel.name + " and what surrounds it" : "Your file: sheet " + d.sheet_name;
  $("source-pos").textContent = "Sheet " + d.sheet_name + " · rows " + d.first_row + "–" + lastRow + (d.more_rows ? "" : " (end of the sheet)")
    + " · columns " + d.first_col + "–" + (d.first_col + Math.max(d.columns, 1) - 1) + " of " + d.columns_total
    + (sel ? " · selected region " + sel.name + ": rows " + sel.first_row + "–" + sel.last_row + ", columns " + sel.first_col + "–" + sel.last_col
      + (sel.header_row ? ", header in row " + sel.header_row : "") : "")
    + (d.truncated_cells ? " · " + d.truncated_cells + " long cell(s) are cut for display" : "");
  $("source").replaceChildren(
    el("p", { class: "legend" }, el("span", { class: "in", text: "selected region" }), el("span", { class: "oth", text: "another region" }),
      el("span", { class: "ctx", text: "outside every region" })),
    d.rows.length ? el("div", { class: "scroll" }, el("table", { class: "src" }, el("thead", {}, head), el("tbody", {}, body)))
      : el("p", { class: "hint", text: "There is no row " + d.first_row + ": the sheet ends before it." }));
  $("src-sheet").replaceChildren(...d.sheets.map((x) => el("option", { value: String(x.index), selected: x.index === d.sheet,
    text: x.name + (x.state && x.state !== "visible" ? " (" + x.state + ")" : "") })));
  $("src-prev").disabled = d.first_row <= 1;
  $("src-next").disabled = !d.more_rows;
  $("src-left").disabled = d.first_col <= 1;
  $("src-right").disabled = d.first_col + d.columns - 1 >= d.columns_total;
  $("src-region").disabled = state.region === null;
}

// A column heading of the selected table leads to that column's settings, once they exist.
function openColumn(region, col) {
  const t = state.contract && !$("s-contract").hidden ? state.contract.tables.find((x) => x.name === region.name) : null;
  const id = "c" + (col - region.first_col + 1);
  if (t && state.panels[key(t.name, id)]) {
    selectColumn(t.name, id);
    $("s-contract").scrollIntoView({ behavior: "smooth" });
    say("");
  } else {
    say("The settings of this column open after the analysis: choose a privacy policy in step 3 and analyse the file.", "info");
  }
}

function drawStats() {
  const box = $("stats");
  box.replaceChildren();
  if (!state.stats) return;
  const kv = (o) => Object.entries(o).map(([k, v]) => k + " ×" + v).join(", ");
  state.stats.tables.forEach((t) => {
    box.append(el("h3", { text: "Exact counts of " + t.name + ": " + t.rows + " data rows, " + t.columns_total + " columns"
      + (t.duplicate_extra_rows ? ", " + t.duplicate_extra_rows + " repeated row(s)" : "") + (t.hidden_rows ? ", " + t.hidden_rows + " hidden row(s)" : "") }));
    box.append(table(["Column", "Type found", "Cells", "With a value", "Missing", "Kinds of missing", "Missing markers", "Kinds of value", "Distinct values", "Most frequent values"],
      t.columns.map((c) => [c.name, c.type, c.cells, c.values, c.missing, kv(c.missing_kinds), kv(c.markers), kv(c.kinds), c.distinct,
        c.frequent_values.map(([v, n]) => v + " ×" + n).join(", ")]), { scroll: true }));
  });
  if (!state.stats.tables.length) box.append(el("p", { class: "hint", text: "No region is in use as a table, so there is nothing to count." }));
  box.append(el("p", { class: "hint", text: "Most frequent values are listed only for columns with few distinct values. These counts stay on this machine; what reports and exports contain is decided by the privacy policy of step 3." }));
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
  // Applied names that differ from the file mean the names were changed: the naming choice says so.
  const renamed = contract.tables.some((t) => t.columns.some((c) => state.original[key(t.name, c.id)] !== undefined && c.name !== state.original[key(t.name, c.id)]));
  if (renamed) { $("names-change").checked = true; $("names-keep").checked = false; }
  if (keepTable) selectColumn(keepTable.name, keepCol);
}

function selectColumn(tableName, columnId) {
  state.table = tableName;
  state.column = columnId;
  Object.entries(state.panels).forEach(([k, panel]) => { panel.hidden = k !== key(tableName, columnId === null ? "\u0001" : columnId); });
  drawSheet();
  drawBulkColumns();
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
  const original = state.srcRows[t.name] || [];
  const body = original.map((r) => el("tr", { class: "srcrow" }, el("td", { class: "rowhead", text: "your file, row " + r.row }),
    t.columns.map((c) => {
      const v = r.cells[Number(c.id.slice(1)) - 1];
      return el("td", { class: "cell", text: v === null || v === undefined ? "" : v });
    })));
  (sample ? sample.rows : []).forEach((row, i) => body.push(el("tr", { class: "synrow" }, el("td", { class: "rowhead", text: "synthetic " + (i + 1) }),
    t.columns.map((c) => {
      const j = sample.columns.indexOf(c.id);
      return el("td", { class: "cell", text: j < 0 ? "" : row[j] });
    }))));
  const notes = [];
  if (original.length) notes.push("Rows marked \"your file\" are original rows, shown for comparison on this machine only.");
  if (state.sampleStale) notes.push("The column settings changed. Press \"Apply decisions\" to see synthetic rows for the new settings.");
  else if (sample) notes.push("Rows marked \"synthetic\" are examples of ordinary values produced from the applied settings; exceptions are listed per column.");
  else notes.push("No synthetic sample rows are available for this table" + (state.sampleWhy ? ": " + state.sampleWhy : "."));
  const rowPanel = state.panels[key(t.name, "")];
  const parts = [
    el("div", { class: "scroll" }, el("table", { class: "sheet" }, el("thead", {}, head), el("tbody", {}, body))),
    el("p", { class: "hint", text: notes.join(" ") })];
  if (rowPanel) parts.push(el("button", { class: "tab" + (state.column === "" ? " sel" : ""), text: "Scenarios that concern whole rows", onclick: () => selectColumn(t.name, "") }));
  $("sheet").replaceChildren(...parts);
  drawGenSummary();
}

// ---- step 5: what will be generated -----------------------------------------------------------
// A short summary per table, with a few original rows (local only, like the grid of step 4) above
// a few synthetic rows of the applied settings.
const SUMMARY_ROWS = 3;
function drawGenSummary() {
  const box = $("gen-summary");
  box.replaceChildren();
  if (!state.contract) return;
  box.append(el("h3", { text: "What will be generated" }));
  if (dirty.contract) box.append(el("p", { class: "pill warn", text: "The column settings have unapplied changes: press \"Apply decisions\" in step 4 first." }));
  state.contract.tables.forEach((t) => {
    const kept = t.columns.filter((c) => state.fields[key(t.name, c.id)].keep.checked);
    const left = t.columns.filter((c) => !state.fields[key(t.name, c.id)].keep.checked);
    const name = (c) => state.fields[key(t.name, c.id)].name.value || c.id;
    const card = el("div", { class: "sumcard" },
      el("p", {}, el("strong", { text: "Table " + t.name + ": " }),
        kept.length ? "synthetic values for " + kept.length + " column(s): " + kept.map(name).join(", ") + "."
          : "no column is kept, so nothing is generated for it.",
        left.length ? " Left out: " + left.map(name).join(", ") + "." : ""));
    const original = (state.srcRows[t.name] || []).slice(0, SUMMARY_ROWS);
    const sample = !state.sampleStale && state.sample ? state.sample[t.name] : null;
    const synth = sample ? sample.rows.slice(0, SUMMARY_ROWS) : [];
    if (kept.length && (original.length || synth.length)) {
      const rows = original.map((r) => [el("td", { class: "rowhead", text: "your file, row " + r.row })].concat(kept.map((c) => {
        const v = r.cells[Number(c.id.slice(1)) - 1];
        return el("td", { class: "cell src", text: v === null || v === undefined ? "" : v });
      })));
      synth.forEach((row, i) => rows.push([el("td", { class: "rowhead", text: "synthetic " + (i + 1) })].concat(kept.map((c) => {
        const j = sample.columns.indexOf(c.id);
        return el("td", { class: "cell syn", text: j < 0 ? "" : row[j] });
      }))));
      card.append(table([""].concat(kept.map(name)), rows, { scroll: true }));
    }
    box.append(card);
  });
  box.append(el("p", { class: "hint", text: "Rows from your file are shown here on this machine only, for comparison. The synthetic rows show ordinary values; the generated file also contains the planned exception scenarios." }));
}

async function loadSample() {
  state.sampleWhy = "";
  try {
    state.sample = (await api("/api/sample", {})).tables;
  } catch (e) {
    state.sample = null;
    state.sampleWhy = e.message;
  }
  state.srcRows = {};
  const regions = state.inspect.recipe.tables;
  for (const t of state.contract.tables) {
    const i = regions.findIndex((r) => r.name === t.name && r.kind === "table");
    if (i < 0) continue;
    try {
      const d = await api("/api/source", { region: i, row: regions[i].first_data_row, col: regions[i].first_col, rows: SOURCE_ROWS, cols: 60 });
      state.srcRows[t.name] = d.rows.filter((r) => r.row <= regions[i].last_data_row);
    } catch (e) { /* the grid then shows synthetic rows only */ }
  }
  state.sampleStale = false;
  drawSheet();
}

// Column naming: the server's naming layer (the same as the command line's) computes the
// names; the page only previews them or fills them into the fields, to be applied as usual.
// The word lists below are fixed vocabularies of this page; none comes from the user's file.
const THEMES = {
  letters: "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split(""),
  cities: ["Tokyo", "Paris", "London", "Cairo", "Lima", "Oslo", "Rome", "Seoul", "Lagos", "Delhi", "Madrid", "Berlin", "Sydney",
    "Dakar", "Quito", "Hanoi", "Nairobi", "Vienna", "Lisbon", "Havana", "Toronto", "Mumbai", "Istanbul", "Bogota", "Prague",
    "Dublin", "Athens", "Manila", "Santiago", "Helsinki"],
  nato: ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf", "Hotel", "India", "Juliett", "Kilo", "Lima", "Mike",
    "November", "Oscar", "Papa", "Quebec", "Romeo", "Sierra", "Tango", "Uniform", "Victor", "Whiskey", "Xray", "Yankee", "Zulu"],
  rivers: ["Nile", "Amazon", "Yangtze", "Mississippi", "Danube", "Volga", "Mekong", "Congo", "Niger", "Ganges", "Rhine", "Seine",
    "Thames", "Indus", "Tigris", "Euphrates", "Zambezi", "Orinoco", "Yukon", "Loire", "Elbe", "Murray", "Jordan", "Tagus",
    "Ebro", "Dnieper", "Lena", "Amur", "Rhone", "Vistula"],
  lakes: ["Baikal", "Victoria", "Titicaca", "Superior", "Geneva", "Como", "Tahoe", "Ontario", "Erie", "Huron", "Michigan", "Malawi",
    "Tanganyika", "Ladoga", "Balaton", "Garda", "Constance", "Chad", "Toba", "Inle", "Bled", "Ohrid", "Lucerne", "Annecy",
    "Taupo", "Nicaragua", "Winnipeg", "Vostok", "Kivu", "Van"],
  stars: ["Mercury", "Venus", "Earth", "Mars", "Jupiter", "Saturn", "Uranus", "Neptune", "Pluto", "Sirius", "Vega", "Rigel",
    "Altair", "Deneb", "Polaris", "Antares", "Betelgeuse", "Arcturus", "Capella", "Aldebaran", "Spica", "Procyon", "Canopus",
    "Castor", "Pollux", "Regulus", "Mira", "Bellatrix", "Achernar", "Sol"],
  scientists: ["Curie", "Newton", "Einstein", "Darwin", "Galileo", "Tesla", "Pasteur", "Lovelace", "Turing", "Bohr", "Kepler",
    "Faraday", "Mendel", "Hypatia", "Noether", "Planck", "Fermi", "Feynman", "Hubble", "Copernicus", "Archimedes", "Euler",
    "Gauss", "Avicenna", "Khwarizmi", "Lavoisier", "Maxwell", "Hawking", "Franklin", "Meitner"],
};
const UNITS = ["Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve",
  "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"];
const TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"];
function numberWord(n) {
  if (n < 20) return UNITS[n];
  if (n < 100) return TENS[Math.floor(n / 10)] + (n % 10 ? "-" + UNITS[n % 10] : "");
  return String(n);
}
// n names from a theme; a list that runs out starts again with a number (Tokyo, …, Tokyo2).
function themeNames(theme, n) {
  if (theme === "digits") return Array.from({ length: n }, (_, i) => String(i + 1));
  if (theme === "words") return Array.from({ length: n }, (_, i) => numberWord(i + 1));
  const words = THEMES[theme] || [];
  return Array.from({ length: n }, (_, i) => words[i % words.length] + (i < words.length ? "" : String(Math.floor(i / words.length) + 1)));
}

function bulkColumns(t) {
  const target = $("bulk-target").value;
  const kept = t.columns.filter((c) => state.fields[key(t.name, c.id)].keep.checked);
  const ticked = new Set(Array.from(document.querySelectorAll("#bulk-cols [data-col]")).filter((x) => x.checked).map((x) => x.dataset.col));
  return { kept, selected: target === "selected" ? kept.filter((c) => ticked.has(c.id)).map((c) => c.id) : null };
}

function drawBulkColumns() {
  const t = currentTable();
  const box = $("bulk-cols");
  const selecting = $("bulk-target").value === "selected";
  box.hidden = !selecting || !t;
  drawNamingTools();
  if (!t) return;
  const ticked = new Set(Array.from(document.querySelectorAll("#bulk-cols [data-col]")).filter((x) => x.checked).map((x) => x.dataset.col));
  if (box.dataset.table !== t.name) ticked.clear();  // a new table starts with nothing ticked
  box.dataset.table = t.name;
  box.replaceChildren(...t.columns.filter((c) => state.fields[key(t.name, c.id)].keep.checked).map((c) =>
    el("label", {}, el("input", { type: "checkbox", "data-col": c.id, checked: ticked.has(c.id) }),
      " " + (state.fields[key(t.name, c.id)].name.value || c.id))));
}

// Shows only the controls of the chosen way of naming.
function drawNamingTools() {
  const change = $("names-change").checked;
  const how = $("bulk-how").value;
  const theme = $("bulk-theme").value;
  $("bulk-tools").hidden = !change;
  $("nm-prefix").hidden = how !== "prefix";
  $("nm-suffix").hidden = how !== "suffix";
  $("nm-theme").hidden = how !== "theme";
  $("nm-list").hidden = !(how === "theme" && theme === "mine");
  $("nm-actions").hidden = how === "custom";
  $("names-custom").hidden = !change || how !== "custom";
  if (change && how === "custom") drawCustomNames();
}

// "I will choose each name myself": one field per kept column, written straight into the column's own name field.
function drawCustomNames() {
  const t = currentTable();
  const box = $("names-custom");
  if (!t) { box.replaceChildren(); return; }
  const rows = t.columns.filter((c) => state.fields[key(t.name, c.id)].keep.checked).map((c) => {
    const f = state.fields[key(t.name, c.id)];
    const inp = el("input", { type: "text", value: f.name.value, "aria-label": "New name of column " + c.id,
      oninput: () => { f.name.value = inp.value; contractEdited(); } });
    return [state.original[key(t.name, c.id)] || c.name, inp];
  });
  box.replaceChildren(el("p", { class: "hint", text: "Type the new name of each column. Press \"Apply decisions\" below to use them." }),
    table(["Name in your file", "New name"], rows, { scroll: true }));
}

// Keep the names: every kept column of every table gets its name from the file back.
function keepOriginalNames() {
  let changed = 0;
  (state.contract ? state.contract.tables : []).forEach((t) => t.columns.forEach((c) => {
    const f = state.fields[key(t.name, c.id)];
    const original = state.original[key(t.name, c.id)];
    if (original !== undefined && f.name.value !== original) { f.name.value = original; changed += 1; }
  }));
  if (changed) {
    contractEdited();
    say(changed + " column name(s) were set back to the names in your file. Press \"Apply decisions\" to use them.", "info");
  }
}

async function bulkPlan() {
  const t = currentTable();
  if (!t) return null;
  const { kept, selected } = bulkColumns(t);
  const how = $("bulk-how").value;
  const theme = $("bulk-theme").value;
  let mode = "edit";
  let names = null;
  if (how === "theme" && theme === "greek") mode = "sequence";
  else if (how === "theme" && theme === "mine") {
    mode = "list";
    names = $("bulk-names").value.split(/\r?\n/).filter((x, i, a) => i < a.length - 1 || x !== "");
  } else if (how === "theme") {
    mode = "list";
    names = themeNames(theme, selected ? selected.length : kept.length);
  }
  const body = {
    table: t.name, mode, selected, names,
    columns: kept.map((c) => ({ id: c.id, name: state.fields[key(t.name, c.id)].name.value })),
    style: $("bulk-style").value, find: $("bulk-find").value, replace: $("bulk-replace").value,
    prefix: how === "prefix" ? $("bulk-prefix").value : "", suffix: how === "suffix" ? $("bulk-suffix").value : "",
  };
  try {
    const data = await api("/api/names", body);
    say("", "info");
    return { t, plan: data.plan };
  } catch (e) {
    $("bulk-preview").replaceChildren();
    say(e.message, "err");
    return null;
  }
}

async function bulkPreview() {
  const res = await bulkPlan();
  if (!res) return;
  const changed = res.plan.filter((p) => p.changed).length;
  $("bulk-preview").replaceChildren(
    el("p", { class: "hint", text: changed + " of " + res.plan.length + " selected column(s) would change. Nothing is changed until you press \"Use these names\" and then \"Apply decisions\"." }),
    table(["Column", "Current name", "New name"], res.plan.map((p) => [p.id, p.current, p.new]), { scroll: true }));
}

async function bulkRename(restore) {
  const t = currentTable();
  if (!t) return;
  let changed = 0;
  if (restore) {
    t.columns.forEach((c) => {
      const f = state.fields[key(t.name, c.id)];
      if (f.keep.checked && f.name.value !== c.name) { f.name.value = c.name; changed += 1; }
    });
  } else {
    const res = await bulkPlan();
    if (!res) return;
    res.plan.forEach((p) => {
      const f = state.fields[key(t.name, p.id)];
      if (p.new && p.new !== f.name.value) { f.name.value = p.new; changed += 1; }
    });
  }
  $("bulk-preview").replaceChildren();
  if (changed) contractEdited(); else drawSheet();
  drawBulkColumns();
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

// The same area of the source, under the generated preview. Kept apart from the result, which holds
// only what was generated.
async function loadCompare(r) {
  const box = $("compare");
  box.replaceChildren();
  const sheets = state.inspect.sheets || [];
  for (const p of r.preview) {
    let i = sheets.findIndex((x) => x.name === p.sheet);
    if (i < 0 && r.preview.length === 1) i = 0;
    if (i < 0) continue;
    try {
      const d = await api("/api/source", { sheet: i, row: 1, col: 1, rows: 40, cols: 30 });
      const head = Array.from({ length: Math.max(d.columns, 1) }, (_, j) => String(d.first_col + j));
      box.append(el("h4", { text: "Your file" + (r.preview.length > 1 ? ", sheet " + d.sheet_name : "") + ": first " + d.rows.length + " rows" }));
      box.append(table(["#"].concat(head), d.rows.map((row) => [String(row.row)].concat(row.cells.map((v) => (v === null ? "" : v)))), { scroll: true, cellClass: "cell" }));
    } catch (e) {
      box.append(el("p", { class: "hint", text: "The source could not be shown here: " + e.message }));
    }
  }
}

// ---- wiring ----------------------------------------------------------------------------------
async function init() {
  const res = await fetch("/api/meta", { credentials: "same-origin" });
  state.meta = await res.json();
  if (state.meta.api !== API) throw new Error("This page and the running application come from different versions. Close the application window and start it again.");
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
    // A fresh analysis carries the names as they are in the file: they are what "keep the names" restores.
    state.original = {};
    data.contract.tables.forEach((t) => t.columns.forEach((c) => { state.original[key(t.name, c.id)] = c.name; }));
    $("names-keep").checked = true;
    $("names-change").checked = false;
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
  $("btn-bulk-preview").addEventListener("click", () => bulkPreview());
  $("bulk-target").addEventListener("change", () => drawBulkColumns());
  $("bulk-how").addEventListener("change", () => { $("bulk-preview").replaceChildren(); drawNamingTools(); });
  $("bulk-theme").addEventListener("change", () => { $("bulk-preview").replaceChildren(); drawNamingTools(); });
  $("names-keep").addEventListener("change", () => { $("bulk-preview").replaceChildren(); drawNamingTools(); keepOriginalNames(); });
  $("names-change").addEventListener("change", () => drawNamingTools());
  $("btn-generate").addEventListener("click", () => busy($("btn-generate"), "Generating and assessing…", async () => {
    if (dirty.recipe) throw new Error("The table settings were changed but not applied. Apply them and analyse again before generating.");
    if (dirty.contract) throw new Error("The column settings have unapplied changes. Click 'Apply decisions' first; nothing was generated.");
    dropResult("");
    const rowsFor = {};
    document.querySelectorAll("#rows-for [data-table]").forEach((i) => { if (i.value !== "") rowsFor[i.dataset.table] = Number(i.value); });
    const result = await api("/api/generate", { rows: Number($("rows").value), rows_for: rowsFor, seed: $("seed").value, packing: $("packing").value });
    renderResult(result);
    await loadCompare(result);
  }));
  $("btn-stats").addEventListener("click", () => busy($("btn-stats"), "Counting every cell…", async () => {
    state.stats = await api("/api/source/stats", {});
    drawStats();
  }));
  $("src-region").addEventListener("click", () => { if (state.region !== null) selectRegion(state.region); });
  $("src-top").addEventListener("click", () => moveSource(() => ({ row: 1, col: 1 })));
  $("src-prev").addEventListener("click", () => moveSource((d) => ({ row: Math.max(1, d.first_row - PAGE_ROWS) })));
  $("src-next").addEventListener("click", () => moveSource((d) => ({ row: d.first_row + PAGE_ROWS })));
  $("src-left").addEventListener("click", () => moveSource((d) => ({ col: Math.max(1, d.first_col - PAGE_COLS) })));
  $("src-right").addEventListener("click", () => moveSource((d) => ({ col: d.first_col + PAGE_COLS })));
  $("src-go").addEventListener("click", () => {
    const row = Math.floor(Number($("src-goto").value));
    if (!(row >= 1)) { say("Type a row number of 1 or more.", "err"); return; }
    moveSource(() => ({ row }));
  });
  $("src-sheet").addEventListener("change", () => loadSource({ sheet: Number($("src-sheet").value), row: 1, col: 1 }));
  onEdit("region-cards", recipeEdited);
  onEdit("regions-tech", recipeEdited);
  onEdit("policies", policyEdited);
  onEdit("contract", contractEdited);
  onEdit("approved-by", contractEdited);
  onEdit("confirm-by", contractEdited);
  onEdit("gen-settings", settingsEdited);
}

init().catch((e) => say(e.message, "err"));
