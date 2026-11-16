// Minimal DOM used to execute the interface script outside a browser (tests only).
"use strict";
class StubNode {
  constructor(tag) {
    this.tagName = (tag || "").toUpperCase(); this.nodeType = tag === "#text" ? 3 : 1; this.children = []; this.attrs = {};
    this.dataset = {}; this.className = ""; this.listeners = {}; this.value = ""; this.checked = false; this.disabled = false;
    this.hidden = false; this.selected = false; this._text = ""; this.files = []; this.id = ""; this.type = "";
  }
  setAttribute(k, v) {
    this.attrs[k] = String(v);
    if (k.startsWith("data-")) this.dataset[k.slice(5)] = String(v);
    if (k === "id") this.id = String(v);
    if (k === "type") this.type = String(v);
    if (k === "name") this.name = String(v);
  }
  getAttribute(k) { return this.attrs[k]; }
  addEventListener(name, fn) { (this.listeners[name] = this.listeners[name] || []).push(fn); }
  append(...nodes) {
    for (const n of nodes) {
      const node = (n && n.nodeType) ? n : document.createTextNode(String(n));
      if (this.tagName === "SELECT" && node.tagName === "OPTION" && node.selected) this.value = node.value;
      this.children.push(node);
    }
  }
  replaceChildren(...nodes) { this.children = []; this.append(...nodes); }
  get childElementCount() { return this.children.filter((c) => c.nodeType === 1).length; }
  get textContent() { return this.nodeType === 3 ? this._text : this.children.map((c) => c.textContent).join(" "); }
  set textContent(v) { if (this.nodeType === 3) { this._text = String(v); } else { this.children = [document.createTextNode(String(v))]; } }
  scrollIntoView() {}
  walk(out) { for (const c of this.children) { if (c.nodeType === 1) { out.push(c); c.walk(out); } } return out; }
  querySelectorAll(sel) { return document._query(this, sel); }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}
const document = {
  _byId: {},
  createElement(tag) { return new StubNode(tag); },
  createTextNode(text) { const n = new StubNode("#text"); n._text = text; return n; },
  getElementById(id) {
    if (!this._byId[id]) { const n = new StubNode(id.startsWith("btn-") ? "button" : "div"); n.id = id; this._byId[id] = n; }
    return this._byId[id];
  },
  _query(root, sel) {
    // Supports the selector forms the interface uses: "#id [data-x]" and "tag[name=v]:checked".
    let scope = root;
    let rest = sel.trim();
    const m = rest.match(/^#([\w-]+)\s+(.*)$/);
    if (m) { scope = this.getElementById(m[1]); rest = m[2]; }
    const all = scope.walk([]);
    const data = rest.match(/^\[data-([\w-]+)\]$/);
    if (data) return all.filter((n) => data[1] in n.dataset);
    const named = rest.match(/^(\w+)\[name=([\w-]+)\](:checked)?$/);
    if (named) return all.filter((n) => n.tagName === named[1].toUpperCase() && n.name === named[2] && (!named[3] || n.checked));
    throw new Error("selector not supported by the test DOM: " + sel);
  },
  querySelectorAll(sel) { return this._query(this._root, sel); },
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; },
};
document._root = { walk(out) { for (const id of Object.keys(document._byId)) { const n = document._byId[id]; out.push(n); n.walk(out); } return out; } };
globalThis.document = document;
globalThis.fetch = (path, init) => {
  const i = init || {};
  const body = (i.body && i.body.__upload) ? i.body : (i.body || null);
  const res = JSON.parse(__py_fetch(path, i.method || "GET", typeof body === "string" ? body : JSON.stringify(body)));
  return Promise.resolve({ ok: res.status >= 200 && res.status < 300, status: res.status, json: () => Promise.resolve(res.body) });
};
globalThis.__click = (id) => { const n = document.getElementById(id); return Promise.all((n.listeners.click || []).map((f) => f())); };
globalThis.__text = (id) => document.getElementById(id).textContent;
globalThis.__count = (sel) => document.querySelectorAll(sel).length;
