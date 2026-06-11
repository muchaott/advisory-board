"use strict";

const COLORS = {
  strategist: "#3fd0c9", pm: "#f0b65e", mentor: "#b794f6",
  ai: "#68d391", critic: "#fc8181", translator: "#63b3ed", calendar: "#8b95c9",
};
const INITIALS = {
  strategist: "STR", pm: "PM", mentor: "MEN", ai: "AI", critic: "CRI", translator: "TRA",
};
const color = (k) => COLORS[k] || "#7c8cf8";
const MAX_THREAD = 12;

// convos: viewKey -> [turn]. turn = {t:'user'|'agent'|'divider', ...}
const state = { mode: "single", selected: [], agents: [], byName: {}, busyViews: new Set(), pending: null, convos: {}, attach: null, quote: null };
let pendingQuote = null;

const $ = (s) => document.querySelector(s);
const el = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; };
const escapeHtml = (s) => s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

// ---------- view + conversation store ----------
function viewKey() {
  if (state.mode === "single") return "single:" + (state.selected[0] || "");
  return state.mode; // 'chain' | 'board'
}
function convo() { return (state.convos[viewKey()] ||= []); }
function isBusy(vk) { return state.busyViews.has(vk ?? viewKey()); }
function setBusy(vk, b) { if (b) state.busyViews.add(vk); else state.busyViews.delete(vk); updateComposerEnabled(); }
function updateComposerEnabled() { const dis = isBusy(viewKey()); $("#send").disabled = dis; $("#input").disabled = dis; }

// ---------- persistence ----------
let saveTimer = null;
function saveConvos() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    fetch("/api/conversations", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(state.convos) }).catch(() => {});
  }, 600);
}
function flushConvos() {
  try { navigator.sendBeacon("/api/conversations", new Blob([JSON.stringify(state.convos)], { type: "application/json" })); } catch { /* ignore */ }
}

// ---------- init ----------
async function init() {
  state.agents = await (await fetch("/api/agents")).json();
  state.agents.forEach((a) => (state.byName[a.name] = a.key));
  try {
    const order = await (await fetch("/api/agent-order")).json();
    if (Array.isArray(order) && order.length) {
      state.agents.sort((a, b) => (order.indexOf(a.key) + 1 || 99) - (order.indexOf(b.key) + 1 || 99));
    }
  } catch { /* default order */ }
  try { state.convos = (await (await fetch("/api/conversations")).json()) || {}; } catch { state.convos = {}; }
  renderAgents();
  loadActivity();
  bindUI();
  if (state.agents[0]) { state.selected = [state.agents[0].key]; paintSelection(); }
  renderConvo();
  if (new URLSearchParams(location.search).get("morning")) showMorningBrief();
  window.addEventListener("pagehide", flushConvos);
  window.addEventListener("beforeunload", flushConvos);
}

async function showMorningBrief() {
  try {
    const b = await (await fetch("/api/morning-brief")).json();
    if (!b || !b.text) return;
    clearEmpty();
    domDivider("☀ Morning brief — " + (b.date || ""));
    const { body } = buildAgentBubble("Morning brief", "pm", null, false);
    body.textContent = b.text;
    scrollDown();
  } catch { /* ignore */ }
}

function renderAgents() {
  const wrap = $("#agents"); wrap.innerHTML = "";

  // "The Whole Board" row — avatar shows all 6 roles
  const bcard = el("div", "agent board-row"); bcard.dataset.key = "__board__";
  bcard.style.setProperty("--ac", "#7c8cf8");
  bcard.append(el("div", "av av-board"));
  const bmeta = el("div", "agent-meta");
  bmeta.append(el("div", "agent-name", "The Whole Board"));
  bmeta.append(el("div", "agent-goal", "All 6 weigh in; the Mentor synthesizes."));
  bcard.append(bmeta);
  bcard.onclick = onBoardClick;
  wrap.append(bcard);

  state.agents.forEach((a) => {
    const card = el("div", "agent");
    card.style.setProperty("--ac", color(a.key));
    card.dataset.key = a.key;
    const av = el("div", "av"); av.style.background = color(a.key);
    const meta = el("div", "agent-meta");
    meta.append(el("div", "agent-name", a.name.replace(/^The /, "")));
    meta.append(el("div", "agent-goal", a.goal));
    const badges = el("div", "badges");
    if (a.reads_docs) badges.append(el("span", "badge", "docs"));
    if (a.writes_brag) badges.append(el("span", "badge", "writes"));
    if (a.deep) badges.append(el("span", "badge", "deep"));
    meta.append(badges);
    card.append(av, meta);
    card.onclick = () => onAgentClick(a.key);
    makeDraggable(card);
    wrap.append(card);
  });
  paintSelection();
}

// ---------- drag-to-reorder ----------
let draggingEl = null;
function makeDraggable(card) {
  card.draggable = true;
  card.addEventListener("dragstart", (e) => { draggingEl = card; card.classList.add("dragging"); e.dataTransfer.effectAllowed = "move"; });
  card.addEventListener("dragend", () => { card.classList.remove("dragging"); draggingEl = null; persistOrder(); });
}
function dragAfter(container, y) {
  const els = [...container.querySelectorAll(".agent:not(.board-row):not(.dragging)")];
  let best = { offset: -Infinity, el: null };
  for (const child of els) {
    const box = child.getBoundingClientRect();
    const offset = y - box.top - box.height / 2;
    if (offset < 0 && offset > best.offset) best = { offset, el: child };
  }
  return best.el;
}
function persistOrder() {
  const keys = [...$("#agents").querySelectorAll(".agent:not(.board-row)")].map((c) => c.dataset.key);
  state.agents.sort((a, b) => keys.indexOf(a.key) - keys.indexOf(b.key));
  fetch("/api/agent-order", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(keys) }).catch(() => {});
}

function onAgentClick(key) {
  state.mode = "single"; state.selected = [key];
  paintSelection(); renderConvo(); updateComposerEnabled();
  if (!isBusy() && convo().length === 0) startChat(key);
  else focusComposer();
}

function onBoardClick() {
  state.mode = "board"; state.selected = [];
  paintSelection(); renderConvo(); updateComposerEnabled(); focusComposer();
}

const OPENER = "Start our session. Based on my current focus, recent work, calendar, and 1:1, " +
  "give me a brief high-value opener in your role (2-3 sentences), then ask me one sharp " +
  "question to get going. No preamble, no restating who you are.";

function startChat(key) {
  if (isBusy("single:" + key)) return;
  state.selected = [key]; paintSelection();
  ask("single", [key], OPENER, { showUser: false, divider: `Talking to the ${shortName(key)}` });
}

function shortName(key) {
  const a = state.agents.find((x) => x.key === key);
  return a ? a.name.replace(/^The /, "").replace(/"/g, "") : key;
}
function focusComposer() {
  const i = $("#input");
  if (state.pending) return;
  const names = state.selected.map(shortName);
  if (state.mode === "single" && names[0]) i.placeholder = `Ask the ${names[0]}…`;
  else if (state.mode === "chain" && names.length) i.placeholder = `Ask ${names.join(" → ")}…`;
  else i.placeholder = "Ask the board…  (@critic review this flow: …)";
  i.focus();
}

function paintSelection() {
  document.querySelectorAll(".agent").forEach((c) => {
    const k = c.dataset.key;
    c.querySelector(".order-pill")?.remove();
    const on = (k === "__board__") ? state.mode === "board"
      : (state.mode !== "board" && state.selected.includes(k));
    c.classList.toggle("selected", on);
    if (on && state.mode === "chain" && k !== "__board__") {
      c.append(el("div", "order-pill", String(state.selected.indexOf(k) + 1)));
    }
  });
}

// ---------- modes ----------
function setMode(m) {
  state.mode = m;
  if (m === "single" && state.selected.length > 1) state.selected = state.selected.slice(0, 1);
  paintSelection();
  renderConvo();
  updateComposerEnabled();
  focusComposer();
}

// ---------- @mention parsing ----------
function parseMentions(text) {
  const t = text.trim();
  if (!t.startsWith("@")) return null;
  if (/^@board\b/i.test(t)) return { mode: "board", keys: [], message: t.replace(/^@board\b/i, "").trim() };
  const tokens = t.split(/\s+/);
  const keys = []; let i = 0;
  while (i < tokens.length) {
    const tok = tokens[i];
    if (tok === ">") { i++; continue; }
    if (tok.startsWith("@")) {
      keys.push(tok.slice(1).toLowerCase()); i++;
      if (tokens[i] === ">") { i++; continue; }
      if (tokens[i] && tokens[i].startsWith("@")) continue;
      break;
    }
    break;
  }
  const message = tokens.slice(i).join(" ").trim();
  if (!keys.length) return null;
  return { mode: keys.length > 1 ? "chain" : "single", keys, message };
}

// ---------- DOM builders ----------
function emptyStateNode() {
  const wrap = el("div", "empty"); wrap.id = "emptyState";
  wrap.append(el("div", "empty-table"));
  const p = el("p");
  p.innerHTML = "Pick an agent on the left to open a conversation — or <strong>The Whole Board</strong> " +
    "to hear from all six. Each keeps its own history. Type below and press Enter, or drag an image in.";
  const p2 = el("p", "empty-eg");
  p2.innerHTML = "Chain agents by typing <code>@strategist &gt; @critic &gt; @translator …</code>";
  wrap.append(p, p2);
  return wrap;
}
function clearEmpty() { $("#emptyState")?.remove(); }

function domUser(text, image, quote) {
  clearEmpty();
  const m = el("div", "msg user");
  if (image) { const img = el("img", "msg-img"); img.src = image; m.append(img); }
  if (quote) m.append(el("div", "msg-quote", quote));
  if (text) m.append(el("div", null, text));
  $("#conversation").append(m);
}
function domDivider(text) { clearEmpty(); const d = el("div", "divider"); d.append(el("span", null, text)); $("#conversation").append(d); }

function buildAgentBubble(name, key, reacting, streaming) {
  clearEmpty();
  const wrap = el("div", "msg agent");
  wrap.style.setProperty("--ac", color(key));
  if (reacting) { const r = el("div", "reacting"); r.innerHTML = `↑ reacting to <b>${escapeHtml(reacting)}</b>`; wrap.append(r); }
  const b = el("div", "bubble");
  const head = el("div", "bubble-head");
  const av = el("div", "av"); av.style.background = color(key);
  head.append(av, el("div", "bubble-name", name));
  const body = el("div", "bubble-body" + (streaming ? " streaming" : ""));
  b.append(head, body); wrap.append(b); $("#conversation").append(wrap);
  return { wrap, body };
}
function addReacting(wrap, prior) { const r = el("div", "reacting"); r.innerHTML = `↑ reacting to <b>${escapeHtml(prior)}</b>`; wrap.insertBefore(r, wrap.firstChild); }

function renderTurn(turn) {
  if (turn.t === "divider") domDivider(turn.text);
  else if (turn.t === "user") domUser(turn.text, turn.image, turn.quote);
  else if (turn.t === "agent") { const { body } = buildAgentBubble(turn.name, turn.key, turn.reacting, false); body.textContent = turn.text; }
}
function renderConvo() {
  const conv = $("#conversation"); conv.innerHTML = "";
  const arr = convo();
  if (!arr.length) { conv.append(emptyStateNode()); return; }
  arr.forEach(renderTurn); scrollDown();
}
function scrollDown() { const c = $("#conversation"); c.scrollTop = c.scrollHeight; }
function nearBottom() { const c = $("#conversation"); return c.scrollHeight - c.scrollTop - c.clientHeight < 90; }

function markSpeaking(key, on) {
  const card = document.querySelector(`.agent[data-key="${key}"]`);
  if (!card) return;
  card.classList.toggle("speaking", on);
  card.querySelector(".speaking-tag")?.remove();
  if (on) { const tag = el("div", "speaking-tag"); for (let i = 0; i < 3; i++) tag.append(el("i")); card.append(tag); }
}

// ---------- ask (SSE stream) ----------
async function ask(mode, keys, message, opts = {}) {
  const vk = viewKey();
  if (isBusy(vk)) { toast("This conversation is still generating — switch agents or wait.", true); return; }
  setBusy(vk, true);
  const arr = convo();
  const record = mode === "single";
  const startedKeys = new Set();
  const history = record
    ? arr.filter((x) => x.t === "user" || x.t === "agent").map((x) => [x.t === "user" ? "You" : x.name, x.text]).slice(-MAX_THREAD)
    : [];
  const images = opts.images || [];

  if (opts.divider) { domDivider(opts.divider); arr.push({ t: "divider", text: opts.divider }); }
  if (opts.showUser !== false) {
    const disp = opts.display ?? message;
    domUser(disp, opts.imageDataUrl, opts.quote);
    arr.push({ t: "user", text: disp, image: opts.imageDataUrl || null, quote: opts.quote || null });
    scrollDown();  // jump to the message you just sent
  } else clearEmpty();

  let body = null, wrap = null, reacting = null;
  try {
    const resp = await fetch("/api/ask", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode, agents: keys, message, history, images }),
    });
    if (!resp.ok) { toast((await resp.json()).error || "request failed", true); setBusy(vk, false); return; }
    const reader = resp.body.getReader(); const dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, idx); buf = buf.slice(idx + 2);
        const line = chunk.split("\n").find((l) => l.startsWith("data: "));
        if (!line) continue;
        const ev = JSON.parse(line.slice(6));
        if (ev.type === "agent_start") { const was = nearBottom(); reacting = null; startedKeys.add(ev.key); const r = buildAgentBubble(ev.agent, ev.key, null, true); wrap = r.wrap; body = r.body; markSpeaking(ev.key, true); if (was) scrollDown(); }
        else if (ev.type === "reacting_to" && wrap) { reacting = ev.prior; addReacting(wrap, ev.prior); }
        else if (ev.type === "token" && body) { const was = nearBottom(); body.textContent += ev.text; if (body.isConnected && was) scrollDown(); }
        else if (ev.type === "agent_done") {
          body?.classList.remove("streaming"); markSpeaking(ev.key, false);
          if (body) arr.push({ t: "agent", key: ev.key, name: ev.agent, text: body.textContent, reacting });
        }
      }
    }
  } catch (e) {
    toast("stream error: " + e.message, true);
  } finally {
    startedKeys.forEach((k) => markSpeaking(k, false));
    setBusy(vk, false);
    loadActivity();
    saveConvos();
  }
}

// ---------- submit ----------
function onSubmit(e) {
  e?.preventDefault();
  if (isBusy()) return;
  const inputEl = $("#input"); const raw = inputEl.value.trim();
  if (!raw && !state.attach && !state.quote) return;

  const parsed = parseMentions(raw);
  let mode, keys, display, switched = false;
  if (parsed) {
    mode = parsed.mode; keys = parsed.keys; display = parsed.message;
    if (parsed.mode) { setMode(parsed.mode); switched = true; }
    if (keys.length) { state.selected = keys; paintSelection(); switched = true; }
  } else { mode = state.mode; keys = state.selected.slice(); display = raw; }

  if (mode !== "board" && keys.length === 0) { toast("Pick an agent (left) or @mention one.", true); return; }
  if (switched) renderConvo();

  const quote = state.quote;
  let message = display;
  if (quote) {
    message = `Regarding this excerpt from our conversation:\n"""\n${quote}\n"""\n\n` +
      (display || "Say more about this — what should I take from it?");
  }

  const images = state.attach ? [{ media_type: state.attach.media_type, data: state.attach.data }] : [];
  const imageDataUrl = state.attach ? state.attach.dataUrl : null;
  inputEl.value = ""; autoGrow(inputEl); clearAttach(); clearQuote();
  ask(mode, keys, message, { images, imageDataUrl, display, quote });
}

// ---------- quote-from-selection ----------
function showQuoteButton(rect) {
  const btn = $("#quoteBtn");
  const top = Math.max(8, rect.top - 36);
  const left = Math.min(window.innerWidth - 90, Math.max(8, rect.left + rect.width / 2 - 34));
  btn.style.top = top + "px"; btn.style.left = left + "px"; btn.style.display = "block";
}
function hideQuoteButton() { $("#quoteBtn").style.display = "none"; }

function onSelectionChange() {
  const sel = window.getSelection();
  const text = (sel && sel.toString().trim()) || "";
  const conv = $("#conversation");
  if (text.length > 1 && sel.rangeCount && conv.contains(sel.getRangeAt(0).commonAncestorContainer)) {
    pendingQuote = text;
    showQuoteButton(sel.getRangeAt(0).getBoundingClientRect());
  } else { pendingQuote = null; hideQuoteButton(); }
}

function takeQuote() {
  if (!pendingQuote) return;
  state.quote = pendingQuote;
  renderQuoteBar(); hideQuoteButton();
  window.getSelection()?.removeAllRanges();
  focusComposer();
}
function clearQuote() { state.quote = null; renderQuoteBar(); }
function renderQuoteBar() {
  const bar = $("#quoteBar");
  if (!state.quote) { bar.hidden = true; bar.innerHTML = ""; return; }
  bar.hidden = false; bar.innerHTML = "";
  const text = state.quote.length > 220 ? state.quote.slice(0, 220) + "…" : state.quote;
  const x = el("button", "attach-x", "✕"); x.title = "Remove quote"; x.onclick = clearQuote;
  bar.append(el("span", "q-mark", "❝"), el("div", "q-text", text), x);
}

// ---------- image attachment ----------
function setAttach(file) {
  if (!file || !file.type.startsWith("image/")) { toast("Only images can be attached.", true); return; }
  const reader = new FileReader();
  reader.onload = () => {
    const m = /^data:(.*?);base64,(.*)$/.exec(reader.result);
    if (!m) { toast("Could not read that image.", true); return; }
    state.attach = { dataUrl: reader.result, media_type: m[1], data: m[2] };
    renderAttachBar(); $("#input").focus();
  };
  reader.readAsDataURL(file);
}
function clearAttach() { state.attach = null; renderAttachBar(); }
function renderAttachBar() {
  const bar = $("#attachBar");
  if (!state.attach) { bar.hidden = true; bar.innerHTML = ""; return; }
  bar.hidden = false; bar.innerHTML = "";
  const img = el("img", "attach-thumb"); img.src = state.attach.dataUrl;
  const x = el("button", "attach-x", "✕"); x.title = "Remove"; x.onclick = clearAttach;
  bar.append(img, el("span", "attach-name", "Image attached — it'll be sent with your next message"), x);
}

// ---------- quick actions ----------
function pushAgentTurn(name, key, text) { convo().push({ t: "agent", key, name, text, reacting: null }); saveConvos(); }

async function doMorning() {
  const vk = viewKey(); setBusy(vk, true);
  try {
    const qs = (await (await fetch("/api/morning")).json()).questions || [];
    clearEmpty();
    const form = el("div", "msg agent"); form.style.setProperty("--ac", "#f0b65e");
    const card = el("div", "mform");
    card.append(el("h4", null, "☀ Good morning"));
    const cal = el("div", "morning-cal", "Loading your day…");
    card.append(cal);
    fetch("/api/calendar").then((r) => r.json()).then((c) => {
      const t = c.today || [];
      cal.textContent = t.length ? "Today (" + t.length + "):\n" + t.map((x) => "• " + x).join("\n") : "No meetings today — clear runway.";
    }).catch(() => { cal.remove(); });
    card.append(el("div", "brag-label", "A few questions to set your focus (optional):"));
    qs.forEach((q, i) => {
      const mq = el("div", "mq");
      const lab = el("label", null, `${i + 1}. ${q}`); lab.htmlFor = `mq${i}`;
      const ta = el("textarea"); ta.id = `mq${i}`; ta.rows = 2;
      mq.append(lab, ta); card.append(mq);
    });
    const actions = el("div", "mform-actions");
    const submit = el("button", "btn", "Get today's focus");
    const skip = el("button", "btn ghost", "Dismiss");
    actions.append(submit, skip); card.append(actions);
    form.append(card); $("#conversation").append(form); scrollDown();
    skip.onclick = () => form.remove();
    submit.onclick = async () => {
      const answers = qs.map((q, i) => ({ q, a: $(`#mq${i}`).value.trim() })).filter((x) => x.a);
      if (!answers.length) { toast("Answer at least one.", true); return; }
      submit.disabled = true; submit.textContent = "Synthesizing…";
      const res = await (await fetch("/api/morning/plan", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ answers }) })).json();
      form.remove();
      const { body } = buildAgentBubble("The Design Project Manager", "pm", null, false);
      body.textContent = res.plan || "(no plan)";
      pushAgentTurn("Morning focus", "pm", res.plan || "(no plan)");
    };
  } catch (e) { toast("morning failed: " + e.message, true); }
  finally { setBusy(vk, false); }
}

function doNewChat() {
  if (isBusy()) { toast("Wait for the current response to finish.", true); return; }
  state.convos[viewKey()] = [];
  renderConvo(); saveConvos();
  if (state.mode === "single" && state.selected[0]) startChat(state.selected[0]);
  else focusComposer();
}

async function doBrag(text) {
  try {
    const res = await (await fetch("/api/brag", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) })).json();
    toast(`Logged → ${res.section}`); loadActivity();
  } catch (e) { toast("brag failed: " + e.message, true); }
}

function bragPanel() {
  clearEmpty();
  const wrap = el("div", "msg agent"); wrap.style.setProperty("--ac", "#f0b65e");
  const card = el("div", "mform");
  card.append(el("h4", null, "＋ Log a win"));
  const sugWrap = el("div", "brag-suggest");
  sugWrap.append(el("div", "brag-loading", "Scanning your recent work for wins…"));
  card.append(sugWrap);
  const row = el("div", "mq");
  const ta = el("textarea"); ta.id = "bragInput"; ta.rows = 2; ta.placeholder = "…or write your own win";
  row.append(ta); card.append(row);
  const actions = el("div", "mform-actions");
  const save = el("button", "btn", "Log it");
  const done = el("button", "btn ghost", "Done");
  actions.append(save, done); card.append(actions);
  wrap.append(card); $("#conversation").append(wrap); scrollDown();

  done.onclick = () => wrap.remove();
  save.onclick = async () => { const t = ta.value.trim(); if (!t) return; await doBrag(t); ta.value = ""; toast("Logged ✓"); };

  fetch("/api/brag/suggest").then((r) => r.json()).then(({ suggestions }) => {
    sugWrap.innerHTML = "";
    if (!suggestions || !suggestions.length) { sugWrap.append(el("div", "brag-loading", "No obvious wins to suggest — log one below.")); return; }
    sugWrap.append(el("div", "brag-label", "Suggested wins — tap to log:"));
    suggestions.forEach((s) => {
      const chip = el("div", "brag-chip");
      chip.append(el("span", "brag-chip-text", s));
      const add = el("button", "brag-add", "＋ Add");
      add.onclick = async () => { add.disabled = true; add.textContent = "✓"; await doBrag(s); chip.classList.add("added"); };
      chip.append(add); sugWrap.append(chip);
    });
  }).catch(() => { sugWrap.innerHTML = ""; });
}

// ---------- activity ----------
async function loadActivity() {
  try {
    const items = await (await fetch("/api/activity")).json();
    const tl = $("#timeline"); tl.innerHTML = "";
    if (!items.length) { tl.append(el("div", "tl-empty", "No activity yet. Brag, sync, or run a review.")); return; }
    items.forEach((it) => {
      const card = el("div", `tl-item tl-kind-${it.kind}`);
      const top = el("div", "tl-top");
      top.append(el("div", "tl-title", it.title), el("div", "tl-date", it.date || ""));
      card.append(top);
      if (it.body) card.append(el("div", "tl-body", it.body));
      card.onclick = () => openModal(it.title + (it.date ? " · " + it.date : ""), it.body || "");
      tl.append(card);
    });
  } catch { /* ignore */ }
}
function openModal(title, body) { $("#modalTitle").textContent = title; $("#modalBody").textContent = body; $("#modal").hidden = false; }

// ---------- toasts ----------
function toast(msg, err) { const t = el("div", "toast" + (err ? " err" : ""), msg); $("#toasts").append(t); setTimeout(() => t.remove(), 4200); }

// ---------- ui binding ----------
function autoGrow(t) { t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, 220) + "px"; }
function bindUI() {
  $("#composer").addEventListener("submit", onSubmit);

  // reorder agents by dragging
  $("#agents").addEventListener("dragover", (e) => {
    if (!draggingEl) return;
    e.preventDefault();
    const after = dragAfter($("#agents"), e.clientY);
    if (after == null) $("#agents").appendChild(draggingEl);
    else $("#agents").insertBefore(draggingEl, after);
  });
  const input = $("#input");
  input.addEventListener("input", () => autoGrow(input));
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); onSubmit(e); }
  });
  document.querySelectorAll(".act").forEach((b) => (b.onclick = () => {
    const a = b.dataset.action;
    if (a === "new") doNewChat();
    else if (a === "morning") doMorning();
    else if (a === "brag") bragPanel();
  }));
  $("#modalClose").onclick = () => ($("#modal").hidden = true);
  $("#modal").onclick = (e) => { if (e.target.id === "modal") $("#modal").hidden = true; };

  // drag-and-drop + paste images
  const center = document.querySelector(".center");
  ["dragenter", "dragover"].forEach((ev) => center.addEventListener(ev, (e) => { e.preventDefault(); center.classList.add("drag-over"); }));
  center.addEventListener("dragleave", (e) => { if (!center.contains(e.relatedTarget)) center.classList.remove("drag-over"); });
  center.addEventListener("drop", (e) => { e.preventDefault(); center.classList.remove("drag-over"); const f = e.dataTransfer.files[0]; if (f) setAttach(f); });
  document.addEventListener("paste", (e) => { const it = [...(e.clipboardData?.items || [])].find((i) => i.type.startsWith("image/")); if (it) setAttach(it.getAsFile()); });

  // quote-from-selection
  document.addEventListener("mouseup", () => setTimeout(onSelectionChange, 0));
  document.addEventListener("mousedown", (e) => { if (e.target.id !== "quoteBtn") hideQuoteButton(); });
  $("#conversation").addEventListener("scroll", hideQuoteButton);
  $("#quoteBtn").addEventListener("click", takeQuote);
}

init();
