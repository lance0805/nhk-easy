import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

const repoRoot = process.cwd();
const appJsPath = path.join(repoRoot, "nhk_easy/webapp/static/app.js");
const listTemplatePath = path.join(repoRoot, "nhk_easy/webapp/templates/list.html");

class EventTargetLike {
  constructor() {
    this._listeners = new Map();
  }

  addEventListener(type, fn) {
    if (!this._listeners.has(type)) this._listeners.set(type, []);
    this._listeners.get(type).push(fn);
  }

  dispatchEvent(event) {
    event.target = event.target || this;
    event.currentTarget = this;
    const listeners = this._listeners.get(event.type) || [];
    for (const fn of listeners) fn.call(this, event);
    return !event.defaultPrevented;
  }
}

class ClassList {
  constructor(node) {
    this.node = node;
    this._set = new Set();
  }

  add(...names) {
    for (const name of names) this._set.add(name);
  }

  remove(...names) {
    for (const name of names) this._set.delete(name);
  }

  contains(name) {
    return this._set.has(name);
  }

  toggle(name, force) {
    if (force === true) {
      this.add(name);
      return true;
    }
    if (force === false) {
      this.remove(name);
      return false;
    }
    if (this.contains(name)) {
      this.remove(name);
      return false;
    }
    this.add(name);
    return true;
  }

  toString() {
    return Array.from(this._set).join(" ");
  }
}

class ElementNode extends EventTargetLike {
  constructor(tagName, attrs = {}) {
    super();
    this.tagName = tagName.toUpperCase();
    this.attributes = new Map();
    this.dataset = {};
    this.children = [];
    this.parentNode = null;
    this.ownerDocument = null;
    this.classList = new ClassList(this);
    this.style = {};
    this.hidden = false;
    this.textContent = "";
    this._value = "";
    this.checked = false;
    this.disabled = false;
    this.currentTime = 0;
    this.duration = 60;
    this.paused = true;
    this._playCalls = 0;
    this.complete = false;
    this.naturalWidth = 0;
    this._applyAttrs(attrs);
  }

  _applyAttrs(attrs) {
    for (const [name, value] of Object.entries(attrs)) {
      this.setAttribute(name, value);
    }
  }

  appendChild(child) {
    child.parentNode = this;
    child.ownerDocument = this.ownerDocument;
    this.children.push(child);
    return child;
  }

  setAttribute(name, value) {
    const next = String(value);
    this.attributes.set(name, next);
    if (name === "id") this.id = next;
    if (name === "class") {
      this.classList = new ClassList(this);
      next.split(/\s+/).filter(Boolean).forEach((part) => this.classList.add(part));
    }
    if (name.startsWith("data-")) {
      const key = name.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
      this.dataset[key] = next;
    }
    if (name === "value") this.value = next;
    if (name === "name") this.name = next;
    if (name === "type") this.type = next;
    if (name === "action") this.action = next;
    if (name === "method") this.method = next;
    if (name === "aria-hidden") this.ariaHidden = next;
  }

  get value() {
    return this._value;
  }

  set value(next) {
    this._value = String(next);
  }

  getAttribute(name) {
    return this.attributes.has(name) ? this.attributes.get(name) : null;
  }

  removeAttribute(name) {
    this.attributes.delete(name);
    if (name === "id") this.id = "";
    if (name === "class") this.classList = new ClassList(this);
    if (name.startsWith("data-")) {
      const key = name.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
      delete this.dataset[key];
    }
  }

  focus() {
    if (this.ownerDocument) this.ownerDocument.activeElement = this;
  }

  blur() {
    if (this.ownerDocument && this.ownerDocument.activeElement === this) {
      this.ownerDocument.activeElement = null;
    }
  }

  click() {
    this.dispatchEvent(createEvent("click"));
  }

  play() {
    this.paused = false;
    this._playCalls += 1;
    this.dispatchEvent(createEvent("play"));
  }

  pause() {
    this.paused = true;
  }

  scrollIntoView() {}

  closest(selector) {
    let node = this;
    while (node) {
      if (matchesSelector(node, selector)) return node;
      node = node.parentNode;
    }
    return null;
  }

  querySelector(selector) {
    return querySelector(this, selector, true);
  }

  querySelectorAll(selector) {
    return querySelector(this, selector, false);
  }
}

class DocumentNode extends EventTargetLike {
  constructor() {
    super();
    this.readyState = "complete";
    this.documentElement = new ElementNode("html");
    this.documentElement.ownerDocument = this;
    this.body = new ElementNode("body");
    this.body.ownerDocument = this;
    this.documentElement.appendChild(this.body);
    this.activeElement = null;
  }

  createElement(tagName) {
    const node = new ElementNode(tagName);
    node.ownerDocument = this;
    return node;
  }

  querySelector(selector) {
    return this.documentElement.querySelector(selector);
  }

  querySelectorAll(selector) {
    return this.documentElement.querySelectorAll(selector);
  }
}

function createEvent(type, extra = {}) {
  return {
    type,
    defaultPrevented: false,
    preventDefault() {
      this.defaultPrevented = true;
    },
    ...extra,
  };
}

function getDescendants(node) {
  const out = [];
  for (const child of node.children || []) {
    out.push(child);
    out.push(...getDescendants(child));
  }
  return out;
}

function matchesSimple(node, raw) {
  let selector = raw.trim();
  let negateMedia = false;
  if (selector.endsWith(":not([media])")) {
    negateMedia = true;
    selector = selector.slice(0, -":not([media])".length);
  }

  const attrMatches = Array.from(selector.matchAll(/\[([^\]=]+)(?:="([^"]*)")?\]/g));
  selector = selector.replace(/\[[^\]]+\]/g, "");

  let tag = "";
  let id = "";
  const classes = [];
  const parts = selector.split(/(?=[.#])/).filter(Boolean);
  for (const part of parts) {
    if (part.startsWith("#")) id = part.slice(1);
    else if (part.startsWith(".")) classes.push(part.slice(1));
    else tag = part;
  }

  if (tag && node.tagName.toLowerCase() !== tag.toLowerCase()) return false;
  if (id && node.id !== id) return false;
  for (const cls of classes) {
    if (!node.classList.contains(cls)) return false;
  }
  for (const [, name, value] of attrMatches) {
    const attr = node.getAttribute(name);
    if (attr == null) return false;
    if (value != null && attr !== value) return false;
  }
  if (negateMedia && node.getAttribute("media") != null) return false;
  return true;
}

function matchesSelector(node, selector) {
  const parts = selector.trim().split(/\s+/);
  if (parts.length === 1) return matchesSimple(node, parts[0]);
  let current = node;
  for (let idx = parts.length - 1; idx >= 0; idx -= 1) {
    if (!current) return false;
    if (!matchesSimple(current, parts[idx])) {
      current = current.parentNode;
      idx += 1;
      continue;
    }
    current = current.parentNode;
  }
  return true;
}

function querySelector(root, selector, firstOnly) {
  const nodes = [root, ...getDescendants(root)];
  const matches = nodes.filter((node) => node !== root || matchesSelector(node, selector)).filter((node) => matchesSelector(node, selector));
  return firstOnly ? matches[0] || null : matches;
}

function createStorage(initial = {}, behavior = {}) {
  const data = new Map(Object.entries(initial));
  return {
    getItem(key) {
      if (behavior.throwOnGet) throw behavior.throwOnGet;
      return data.has(key) ? data.get(key) : null;
    },
    setItem(key, value) {
      if (behavior.throwOnSet) throw behavior.throwOnSet;
      data.set(key, String(value));
    },
    removeItem(key) {
      if (behavior.throwOnRemove) throw behavior.throwOnRemove;
      data.delete(key);
    },
    dump() {
      return Object.fromEntries(data.entries());
    },
  };
}

function buildDetailDocument(storageValues = {}, options = {}) {
  const document = new DocumentNode();
  const article = el(document, "article", { id: "article", "data-id": "news-1" });
  const progressBar = el(document, "div", { id: "progress-bar" });
  const playerCard = el(document, "div", { id: "player-card", class: "player-card" });
  const player = el(document, "audio", { id: "player" });
  const loopControl = el(document, "div", { class: "loop-control" });
  const label = el(document, "label");
  label.setAttribute("for", "loop-count");
  label.textContent = "くり返し";
  const input = el(document, "input", { id: "loop-count", name: "loop-count", type: "number", value: "20" });
  const progress = el(document, "span", { id: "loop-progress" });
  loopControl.appendChild(label);
  loopControl.appendChild(input);
  loopControl.appendChild(progress);
  playerCard.appendChild(player);
  playerCard.appendChild(loopControl);
  article.appendChild(playerCard);
  document.body.appendChild(progressBar);
  document.body.appendChild(article);
  return createEnv(document, storageValues, options);
}

function buildListDocument(storageValues = {}, options = {}) {
  const document = new DocumentNode();
  const tools = el(document, "div", { class: "list-tools" });
  const search = el(document, "div", { class: "search" });
  const searchInput = el(document, "input", { id: "search-input", type: "search", name: "q" });
  const listCount = el(document, "span", { id: "list-count", class: "list-count" });
  const openButton = el(document, "button", {
    id: "listened-open",
    type: "button",
    "aria-expanded": "false",
    "aria-controls": "listened-overlay",
  });
  const badge = el(document, "span", { id: "listened-count" });
  openButton.appendChild(badge);
  search.appendChild(searchInput);
  tools.appendChild(search);
  tools.appendChild(listCount);
  tools.appendChild(openButton);
  document.body.appendChild(tools);

  const grid = el(document, "div", { id: "card-grid", class: "card-grid" });
  grid.appendChild(buildCard(document, {
    id: "news-1",
    title: "台風 ニュース",
    hasAudio: "true",
  }));
  grid.appendChild(buildCard(document, {
    id: "news-2",
    title: "経済 ニュース",
    hasAudio: "false",
  }));
  document.body.appendChild(grid);

  const noResults = el(document, "p", { id: "no-results" });
  noResults.hidden = true;
  document.body.appendChild(noResults);

  const overlay = el(document, "div", {
    id: "listened-overlay",
    class: "overlay",
    role: "dialog",
    "aria-modal": "true",
    "aria-hidden": "true",
  });
  const panel = el(document, "div", { class: "overlay__panel" });
  const title = el(document, "h2", { id: "listened-title" });
  title.textContent = "我听过的新闻";
  const summary = el(document, "p", { id: "listened-summary" });
  const form = el(document, "form", {
    id: "listened-export-form",
    method: "post",
    action: "/audio/archive",
  });
  const inputs = el(document, "div", { id: "listened-hidden-inputs" });
  const exportButton = el(document, "button", { id: "listened-export-button", type: "submit" });
  exportButton.textContent = "一键导出";
  form.appendChild(inputs);
  form.appendChild(exportButton);
  const list = el(document, "ul", { id: "listened-list" });
  const closeButton = el(document, "button", { id: "listened-close", type: "button" });
  closeButton.textContent = "关闭";
  panel.appendChild(title);
  panel.appendChild(summary);
  panel.appendChild(form);
  panel.appendChild(list);
  panel.appendChild(closeButton);
  overlay.appendChild(panel);
  document.body.appendChild(overlay);

  return createEnv(document, storageValues, options);
}

function buildCard(document, { id, title, hasAudio }) {
  const card = el(document, "article", {
    class: "card",
    "data-id": id,
    "data-title": title,
    "data-has-audio": hasAudio,
  });
  const media = el(document, "div", { class: "card__media" });
  const img = el(document, "img", { "data-thumb": "" });
  media.appendChild(img);
  const body = el(document, "div", { class: "card__body" });
  const heading = el(document, "h2", { class: "card__title" });
  const link = el(document, "a");
  link.setAttribute("href", `/article/${id}`);
  link.textContent = title;
  heading.appendChild(link);
  body.appendChild(heading);
  card.appendChild(media);
  card.appendChild(body);
  return card;
}

function el(document, tag, attrs = {}) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs)) node.setAttribute(name, value);
  return node;
}

function createEnv(document, storageValues, options = {}) {
  const storage = createStorage(storageValues, options.storageBehavior);
  const history = { replaceState() {} };
  const location = { pathname: "/", search: "", href: "/" };
  const window = new EventTargetLike();
  window.document = document;
  window.localStorage = storage;
  window.history = history;
  window.location = location;
  window.matchMedia = () => ({ matches: false, addEventListener() {}, addListener() {} });
  window.requestAnimationFrame = (fn) => {
    fn();
    return 1;
  };
  window.setTimeout = setTimeout;
  window.clearTimeout = clearTimeout;
  window.innerHeight = 900;
  window.scrollY = 0;
  window.getComputedStyle = () => ({
    getPropertyValue() {
      return "1";
    },
  });

  const context = {
    window,
    document,
    localStorage: storage,
    history,
    location,
    console,
    setTimeout,
    clearTimeout,
    requestAnimationFrame: window.requestAnimationFrame,
    URLSearchParams,
    Event: function Event(type) {
      return createEvent(type);
    },
    CustomEvent: function CustomEvent(type, detail) {
      return createEvent(type, detail);
    },
    getComputedStyle: window.getComputedStyle,
  };
  return { context, document, storage, window };
}

function runApp(env) {
  const source = fs.readFileSync(appJsPath, "utf8");
  vm.runInNewContext(source, env.context, { filename: appJsPath });
}

test("detail page persists completed play counts and keeps loop replay behavior", () => {
  const env = buildDetailDocument({
    "nhk-listen-counts": JSON.stringify({ "news-1": 7 }),
    "nhk-easy-loop-count": "3",
  });

  runApp(env);

  const media = env.document.querySelector("#player");
  const progress = env.document.querySelector("#loop-progress");
  const input = env.document.querySelector("#loop-count");

  assert.equal(input.value, "3");
  assert.equal(progress.textContent, "7 / 20");

  media.dispatchEvent(createEvent("ended"));
  assert.equal(progress.textContent, "8 / 20");
  assert.equal(media.currentTime, 0);
  assert.equal(media._playCalls, 1);

  media.dispatchEvent(createEvent("ended"));
  assert.equal(media._playCalls, 2);

  media.dispatchEvent(createEvent("ended"));
  assert.equal(media._playCalls, 2);

  const storedCounts = JSON.parse(env.storage.getItem("nhk-listen-counts"));
  assert.equal(storedCounts["news-1"], 10);

  const reload = buildDetailDocument(env.storage.dump());
  runApp(reload);
  assert.equal(reload.document.querySelector("#loop-progress").textContent, "10 / 20");
});

test("detail page marks article listened after 20 completed plays and keeps it sticky", () => {
  const env = buildDetailDocument({
    "nhk-listen-counts": JSON.stringify({ "news-1": 19 }),
  });

  runApp(env);

  const media = env.document.querySelector("#player");
  media.dispatchEvent(createEvent("ended"));

  assert.deepEqual(
    JSON.parse(env.storage.getItem("nhk-listened-ids")),
    ["news-1"],
  );
  assert.equal(env.document.querySelector("#loop-progress").textContent, "20 / 20");

  media.dispatchEvent(createEvent("ended"));
  assert.equal(env.document.querySelector("#loop-progress").textContent, "20 / 20");
  assert.deepEqual(
    JSON.parse(env.storage.getItem("nhk-listened-ids")),
    ["news-1"],
  );
});

test("detail page survives storage errors on ended and still updates progress and loop playback", () => {
  const env = buildDetailDocument(
    { "nhk-easy-loop-count": "2" },
    { storageBehavior: { throwOnGet: new Error("SecurityError"), throwOnSet: new Error("QuotaExceededError") } },
  );

  runApp(env);

  const media = env.document.querySelector("#player");
  const progress = env.document.querySelector("#loop-progress");

  media.dispatchEvent(createEvent("ended"));

  assert.equal(progress.textContent, "1 / 20");
  assert.equal(media._playCalls, 1);
  assert.equal(media.currentTime, 0);
});

test("detail page safely degrades malformed persisted shapes and persists corrected listened state", () => {
  const env = buildDetailDocument({
    "nhk-listen-counts": JSON.stringify([]),
    "nhk-listened-ids": JSON.stringify("oops"),
    "nhk-easy-loop-count": "1",
  });

  runApp(env);

  const media = env.document.querySelector("#player");
  const progress = env.document.querySelector("#loop-progress");

  assert.equal(progress.textContent, "0 / 20");

  for (let i = 0; i < 20; i += 1) media.dispatchEvent(createEvent("ended"));

  assert.equal(media._playCalls, 0);
  assert.equal(progress.textContent, "20 / 20");
  assert.deepEqual(JSON.parse(env.storage.getItem("nhk-listen-counts")), { "news-1": 20 });
  assert.deepEqual(JSON.parse(env.storage.getItem("nhk-listened-ids")), ["news-1"]);
});

test("threshold crossing to listened is independent from loop count", () => {
  const env = buildDetailDocument({
    "nhk-listen-counts": JSON.stringify({ "news-1": 19 }),
    "nhk-easy-loop-count": "1",
  });

  runApp(env);

  const media = env.document.querySelector("#player");
  media.dispatchEvent(createEvent("ended"));

  assert.equal(media._playCalls, 0);
  assert.equal(env.document.querySelector("#loop-progress").textContent, "20 / 20");
  assert.deepEqual(JSON.parse(env.storage.getItem("nhk-listened-ids")), ["news-1"]);
});

test("list template exposes listened export seam", () => {
  const template = fs.readFileSync(listTemplatePath, "utf8");

  assert.match(template, /id="listened-open"/);
  assert.match(template, /id="listened-overlay"/);
  assert.match(template, /action="\/audio\/archive"/);
  assert.match(template, /method="post"/);
  assert.match(template, /target="listened-download-frame"/);
  assert.match(template, /<iframe[^>]*name="listened-download-frame"[^>]*title="音声ダウンロード"/);
  assert.match(template, /data-has-audio/);
});

test("list page dialog shows listened cards from persisted state and disables export when audio is unavailable", () => {
  const env = buildListDocument({
    "nhk-listen-counts": JSON.stringify({ "news-1": 20, "news-2": 20 }),
    "nhk-listened-ids": JSON.stringify(["news-1", "news-2"]),
  });

  runApp(env);

  const button = env.document.querySelector("#listened-open");
  const overlay = env.document.querySelector("#listened-overlay");
  const exportButton = env.document.querySelector("#listened-export-button");
  const hiddenInputs = env.document.querySelectorAll('#listened-hidden-inputs input[name="news_id"]');

  assert.equal(env.document.querySelector("#listened-count").textContent, "2");

  button.click();

  assert.equal(button.getAttribute("aria-expanded"), "true");
  assert.equal(overlay.getAttribute("aria-hidden"), "false");
  assert.equal(hiddenInputs.length, 1);
  assert.equal(hiddenInputs[0].value, "news-1");
  assert.equal(exportButton.disabled, false);
});

test("list page restores focus on escape and disables export when no listened card has audio", () => {
  const env = buildListDocument({
    "nhk-listen-counts": JSON.stringify({ "news-2": 20 }),
    "nhk-listened-ids": JSON.stringify(["news-2"]),
  });

  runApp(env);

  const button = env.document.querySelector("#listened-open");
  const exportButton = env.document.querySelector("#listened-export-button");
  const summary = env.document.querySelector("#listened-summary");

  button.focus();
  button.click();
  env.document.dispatchEvent(createEvent("keydown", { key: "Escape", target: env.document.body }));

  assert.equal(env.document.activeElement, button);
  assert.equal(exportButton.disabled, true);
  assert.match(summary.textContent, /音声/);
});

test("list page traps Tab focus inside dialog and '/' does not focus background search while open", () => {
  const env = buildListDocument({
    "nhk-listen-counts": JSON.stringify({ "news-1": 20 }),
    "nhk-listened-ids": JSON.stringify({ bad: true }),
  });

  runApp(env);

  const button = env.document.querySelector("#listened-open");
  const closeButton = env.document.querySelector("#listened-close");
  const exportButton = env.document.querySelector("#listened-export-button");
  const searchInput = env.document.querySelector("#search-input");

  button.focus();
  button.click();

  assert.equal(env.document.activeElement, exportButton);

  env.document.dispatchEvent(createEvent("keydown", { key: "Tab", target: exportButton }));
  assert.equal(env.document.activeElement, closeButton);

  env.document.dispatchEvent(createEvent("keydown", { key: "Tab", shiftKey: true, target: closeButton }));
  assert.equal(env.document.activeElement, exportButton);

  env.document.dispatchEvent(createEvent("keydown", { key: "/", target: exportButton }));
  assert.notEqual(env.document.activeElement, searchInput);

  env.document.dispatchEvent(createEvent("keydown", { key: "Escape", target: exportButton }));
  assert.equal(env.document.activeElement, button);
});
