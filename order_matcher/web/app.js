"use strict";

// The page talks to two endpoints: GET /api/bootstrap (restaurants, catalog, examples)
// and POST /api/match (one order). All matching happens on the server.

const ui = {
  badge: document.getElementById("engine-badge"),
  customer: document.getElementById("customer"),
  usualSummary: document.getElementById("usual-summary"),
  usualList: document.getElementById("usual-list"),
  order: document.getElementById("order"),
  lineCount: document.getElementById("line-count"),
  charCount: document.getElementById("char-count"),
  examples: document.getElementById("examples"),
  match: document.getElementById("match"),
  kbdHint: document.getElementById("kbd-hint"),
  formError: document.getElementById("form-error"),
  panel: document.getElementById("result-panel"),
  copy: document.getElementById("copy"),
  summary: document.getElementById("summary"),
  source: document.getElementById("source"),
  status: document.getElementById("status"),
  lines: document.getElementById("lines"),
  evidence: document.getElementById("evidence"),
  footerEngine: document.getElementById("footer-engine"),
  toast: document.getElementById("toast"),
};

const STATUS_LABEL = { ok: "Ready", review: "Check", no_match: "No match", checked: "Checked" };
const REQUEST_TIMEOUT_MS = 60000;

const state = {
  boot: null,
  customers: new Map(),
  catalog: new Map(),
  result: null,     // the last answer from /api/match, plus the restaurant it was for
  decisions: [],    // per line: null, or {item, kept} once a person has checked it
  controller: null,
};

// ---------- small helpers ----------

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : String(value));
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

const plural = (n, one, many = one + "s") => `${n} ${n === 1 ? one : many}`;
const countLines = (text) => text.split(/[\n,;]+/).filter((part) => part.trim()).length;
const formatQty = (qty) => (Number.isInteger(qty) ? String(qty) : String(Number(qty.toFixed(2))));

let toastTimer = 0;
function toast(message) {
  ui.toast.textContent = message;
  ui.toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => ui.toast.classList.remove("show"), 2600);
}

// ---------- start-up ----------

async function init() {
  const isMac = /Mac|iPhone|iPad/.test(navigator.platform || "");
  ui.kbdHint.textContent = isMac ? "⌘ + Enter" : "Ctrl + Enter";

  let boot;
  try {
    const res = await fetch("/api/bootstrap", { headers: { Accept: "application/json" } });
    if (!res.ok) throw new Error(String(res.status));
    boot = await res.json();
  } catch {
    showStatus(errorBox("The demo couldn't load. Refresh the page to try again.", null));
    ui.panel.setAttribute("aria-busy", "false");
    return;
  }
  state.boot = boot;
  boot.customers.forEach((c) => state.customers.set(c.id, c));
  boot.catalog.forEach((item) => state.catalog.set(item.sku, item));

  ui.badge.hidden = false;
  ui.badge.classList.toggle("live", boot.live);
  ui.badge.textContent = boot.live ? "Live · Jev" : "Offline stand-in";
  ui.badge.title = boot.live
    ? "Each line is decided live by Jev, a decision model from TypeSafe AI."
    : "No Jev key is set on this server, so a simple offline matcher makes the decisions.";
  ui.footerEngine.textContent = boot.live
    ? "Decisions are made live by Jev from TypeSafe AI."
    : "Decisions come from an offline stand-in, not Jev.";

  const results = boot.test_results;
  if (results) {
    ui.evidence.hidden = false;
    ui.evidence.replaceChildren(
      "On ", el("strong", { text: String(results.lines) }), " test order lines it had never seen, ",
      el("strong", { text: results.exact }), " were matched exactly and ",
      el("strong", { text: results.skip_review }), " were confident enough to skip review. ",
      el("strong", { text: results.wrong_flagged }), " of the wrong matches were flagged for a person. ",
      "The test data is synthetic, like the rest of this demo.");
  }

  ui.customer.replaceChildren(...boot.customers.map((c) => el("option", { value: c.id, text: c.name })));
  ui.examples.replaceChildren(...boot.examples.map((example, i) => {
    const name = state.customers.get(example.customer_id).name;
    return el("button", { type: "button", class: "chip", "aria-pressed": "false", "data-index": i,
                          "aria-label": `Example: ${name}, ${example.label}`, onclick: () => loadExample(i, true) },
              el("strong", { text: name }), ` · ${example.label}`);
  }));

  ui.customer.disabled = ui.order.disabled = ui.match.disabled = false;
  ui.customer.addEventListener("change", () => { renderUsual(); markExample(-1); markStale(); });
  ui.order.addEventListener("input", () => { updateCounts(); markExample(-1); markStale(); });
  ui.order.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      matchOrder();
    }
  });
  ui.match.addEventListener("click", matchOrder);
  ui.copy.addEventListener("click", copyCsv);

  if (boot.examples.length) loadExample(0, true);
  else { renderUsual(); updateCounts(); ui.panel.setAttribute("aria-busy", "false"); }
}

function loadExample(index, run) {
  const example = state.boot.examples[index];
  ui.customer.value = example.customer_id;
  ui.order.value = example.text;
  renderUsual();
  updateCounts();
  markExample(index);
  if (run) matchOrder();
}

function markExample(index) {
  for (const chip of ui.examples.children) {
    chip.setAttribute("aria-pressed", String(Number(chip.dataset.index) === index));
  }
}

function renderUsual() {
  const customer = state.customers.get(ui.customer.value);
  if (!customer) return;
  ui.usualSummary.textContent = `What they usually order (${plural(customer.products, "product")} in 90 days)`;
  ui.usualList.replaceChildren(...customer.usual.map((item) =>
    el("li", {}, el("span", { class: "times", text: `${item.orders}×` }), el("span", { text: item.description }))));
}

function updateCounts() {
  const { max_chars: maxChars, max_lines: maxLines } = state.boot.limits;
  const text = ui.order.value;
  const lines = countLines(text);
  ui.lineCount.textContent = plural(lines, "line");
  ui.lineCount.classList.toggle("over", lines > maxLines);
  ui.charCount.textContent = `${text.length.toLocaleString()} / ${maxChars.toLocaleString()}`;
  ui.charCount.classList.toggle("over", text.length > maxChars);
  ui.formError.hidden = true;
}

// ---------- matching ----------

async function matchOrder() {
  const text = ui.order.value.trim();
  const { max_chars: maxChars, max_lines: maxLines } = state.boot.limits;
  const lines = countLines(text);
  if (!text) return showFormError("Type or paste an order first.");
  if (text.length > maxChars) return showFormError(`That order is too long. Keep it under ${maxChars.toLocaleString()} characters.`);
  if (lines > maxLines) return showFormError(`That order has ${lines} lines. This demo matches up to ${maxLines} at a time.`);

  state.controller?.abort();
  const controller = new AbortController();
  state.controller = controller;
  let timedOut = false;
  const timer = setTimeout(() => { timedOut = true; controller.abort(); }, REQUEST_TIMEOUT_MS);
  const customer = state.customers.get(ui.customer.value);
  showLoading(lines);

  try {
    const res = await fetch("/api/match", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ customer_id: customer.id, order: text }),
      signal: controller.signal,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `The server answered with an error (${res.status}). Try again.`);
    state.result = { ...data, customer };
    state.decisions = data.lines.map(() => null);
    renderResult();
  } catch (error) {
    if (controller.signal.aborted && !timedOut) return;  // a newer request replaced this one
    const message = timedOut ? "Matching took too long. Try again."
      : error instanceof TypeError ? "Couldn't reach the server. Check your connection and try again."
      : error.message;
    showStatus(errorBox(message, matchOrder));
    ui.lines.replaceChildren();
    ui.summary.replaceChildren();
    ui.source.textContent = "";
  } finally {
    clearTimeout(timer);
    if (state.controller === controller) {
      state.controller = null;
      ui.match.disabled = false;
      ui.match.textContent = "Match order";
      ui.panel.setAttribute("aria-busy", "false");
    }
  }
}

function showFormError(message) {
  ui.formError.textContent = message;
  ui.formError.hidden = false;
}

function showLoading(lineCount) {
  ui.formError.hidden = true;
  ui.match.disabled = true;
  ui.match.textContent = "Matching…";
  ui.panel.setAttribute("aria-busy", "true");
  ui.copy.hidden = true;
  ui.summary.replaceChildren();
  ui.source.textContent = "";
  const engine = state.boot.live ? "Jev" : "the offline stand-in";
  showStatus(el("p", { class: "note", text: `Matching ${plural(lineCount, "line")} with ${engine}…` }));
  ui.lines.classList.remove("is-stale");
  ui.lines.replaceChildren(...Array.from({ length: Math.min(lineCount, 10) }, () =>
    el("li", { class: "skeleton", "aria-hidden": "true" },
       el("span"), el("div", {}, el("span", { class: "wide" }), el("span", { class: "narrow" })), el("span"))));
}

function showStatus(node) {
  ui.status.replaceChildren(...(node ? [node] : []));
}

function errorBox(message, retry) {
  return el("div", { class: "error", role: "alert" }, el("p", { text: message }),
            retry ? el("button", { type: "button", class: "btn small", text: "Try again", onclick: retry }) : null);
}

function markStale() {
  if (!state.result || state.controller) return;
  ui.lines.classList.add("is-stale");
  showStatus(el("p", { class: "stale", text: `These results are for the order sent for ${state.result.customer.name}. Match again to update them.` }));
}

// ---------- results ----------

function renderResult() {
  showStatus(null);
  ui.lines.classList.remove("is-stale");
  ui.lines.replaceChildren(...state.result.lines.map((line, i) => renderLine(line, i)));
  ui.copy.hidden = false;
  renderSummary();
}

function renderSummary() {
  const { result, decisions } = state;
  let ready = 0;
  result.lines.forEach((line, i) => { if (decisions[i] || line.status === "ok") ready += 1; });
  const toCheck = result.lines.length - ready;
  const seconds = (result.match_ms / 1000).toFixed(1);

  ui.summary.replaceChildren(
    stat(result.lines.length, result.lines.length === 1 ? "line" : "lines"),
    stat(ready, "ready", "ok"),
    stat(toCheck, "to check", toCheck ? "mark" : ""),
    stat(seconds, "to match", "", "s"));

  const engine = result.decider === "jev" ? "Matched by Jev" : "Matched by the offline stand-in";
  const saved = result.cached ? " (saved result for this exact order)" : "";
  const next = toCheck
    ? `${plural(toCheck, "line")} under ${state.boot.review_below.toFixed(2)} confidence ${toCheck === 1 ? "waits" : "wait"} for a person.`
    : "Every line is ready to send.";
  ui.source.textContent = `${engine} for ${result.customer.name}${saved}. ${next}`;
}

function stat(value, label, tone = "", unit = "") {
  return el("div", { class: `stat ${tone}`.trim() },
            el("span", { class: "stat-num" }, String(value), unit ? el("small", { text: unit }) : null),
            el("span", { class: "stat-label", text: label }));
}

function reasons(line) {
  if (!line.item) return ["Nothing in the catalog matched this wording"];
  const out = [line.usual ? "Ordered often by this restaurant" : "New for this restaurant, found in what others buy"];
  if (line.unit_fixed) out.push("Switched to the unit written in the order");
  else if (line.unit_named) out.push("Unit taken from the order");
  else out.push("No unit given, so their usual one");
  if (line.status === "review") out.push(`Under ${state.boot.review_below.toFixed(2)} confidence`);
  return out;
}

function renderLine(line, index) {
  const decision = state.decisions[index];
  const item = decision ? decision.item : line.item;
  const status = decision ? "checked" : line.status;

  const main = el("div", { class: "line-main" },
    el("p", { class: "chef" }, el("span", { class: "chef-text", text: line.text })),
    item
      ? el("p", { class: "match" },
           el("span", { class: "arrow", "aria-hidden": "true", text: "→" }),
           el("span", { class: "item-name", text: item.description }),
           el("code", { class: "sku", text: item.sku }))
      : el("p", { class: "match none", text: "No catalog item matched" }),
    el("p", { class: "why", text: decision
      ? (decision.kept ? "Checked and kept by you" : "Changed by you")
      : reasons(line).join(" · ") }));

  if (decision) {
    main.append(el("div", { class: "decided" },
      el("button", { type: "button", class: "link", text: "Undo", onclick: () => decide(index, null) })));
  } else if (status !== "ok") {
    main.append(renderReview(line, index));
  }

  const side = el("div", { class: "line-side" },
    el("span", { class: "qty", text: item ? `${formatQty(line.qty)} × ${item.unit}` : formatQty(line.qty) }),
    renderConfidence(line.confidence),
    el("span", { class: `pill ${status}`, text: STATUS_LABEL[status] }));

  return el("li", { class: `line is-${status}` }, el("span", { class: "stripe", "aria-hidden": "true" }), main, side);
}

function renderConfidence(confidence) {
  const fill = el("span", { class: "meter-fill" });
  fill.style.width = `${Math.round(confidence * 100)}%`;
  const tick = el("span", { class: "meter-tick" });
  tick.style.left = `${state.boot.review_below * 100}%`;
  const label = `Confidence ${confidence.toFixed(2)}`;
  return el("span", { class: "conf", title: `${label}. Lines under ${state.boot.review_below.toFixed(2)} are checked by a person.` },
            el("span", { class: "conf-num", text: confidence.toFixed(2) }),
            el("span", { class: "meter", role: "img", "aria-label": label }, fill, tick));
}

function renderReview(line, index) {
  const box = el("div", { class: "review", role: "group", "aria-label": `Check "${line.text}"` },
    el("span", { class: "review-q", text: line.item ? "Is this right?"
      : line.alternatives.length ? "Closest guesses:" : "Pick the item:" }));
  if (line.item) {
    box.append(el("button", { type: "button", class: "btn small solid", text: "Yes, keep it",
                              onclick: () => decide(index, { item: line.item, kept: true }) }));
  }
  for (const alt of line.alternatives) {
    box.append(el("button", { type: "button", class: "btn small", text: alt.description,
                              onclick: () => decide(index, { item: alt, kept: false }) }));
  }
  const picker = el("select", { class: "picker", "aria-label": "Choose another item from the catalog" },
    el("option", { value: "", text: "Another item…" }),
    state.boot.catalog.map((item) => el("option", { value: item.sku, text: item.description })));
  picker.addEventListener("change", () => {
    const item = state.catalog.get(picker.value);
    if (item) decide(index, { item, kept: false });
  });
  box.append(picker);
  return box;
}

function decide(index, decision) {
  state.decisions[index] = decision;
  const fresh = renderLine(state.result.lines[index], index);
  ui.lines.children[index].replaceWith(fresh);
  renderSummary();
  fresh.querySelector(decision ? ".decided button" : ".review button, .review select")?.focus();
}

// ---------- export ----------

function orderCsv() {
  const cell = (value) => {
    let text = String(value ?? "");
    if (/^[=+\-@]/.test(text)) text = "'" + text;  // keep spreadsheets from running it as a formula
    return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  const rows = [["order line", "quantity", "unit", "sku", "item", "status"]];
  state.result.lines.forEach((line, i) => {
    const decision = state.decisions[i];
    const item = decision ? decision.item : line.item;
    const status = decision ? "checked" : line.status === "ok" ? "automatic" : "needs check";
    rows.push([line.text, formatQty(line.qty), item?.unit, item?.sku, item?.description, status]);
  });
  return rows.map((row) => row.map(cell).join(",")).join("\r\n");
}

async function copyCsv() {
  const csv = orderCsv();
  try {
    await navigator.clipboard.writeText(csv);
    toast(`Copied ${plural(state.result.lines.length, "line")} as CSV`);
  } catch {
    const area = el("textarea", { readonly: true, "aria-label": "Order as CSV" });
    area.value = csv;
    showStatus(el("div", { class: "csv-fallback" },
      el("p", { class: "note", text: "Your browser blocked copying. Select the text below and copy it." }), area));
    area.focus();
    area.select();
  }
}

init();
