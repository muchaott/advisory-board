"use strict";

const COLORS = {
  strategist: "#3fd0c9", pm: "#f0b65e", mentor: "#b794f6",
  ai: "#68d391", critic: "#fc8181", translator: "#63b3ed",
};
const INITIALS = {
  strategist: "STR", pm: "PM", mentor: "MEN", ai: "AI", critic: "CRI", translator: "TRA",
};
const color = (k) => COLORS[k] || "#7c8cf8";

const state = { mode: "single", selected: [], agents: [], byName: {}, busy: false, pending: null };

const $ = (s) => document.querySelector(s);
const el = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; };

// ---------- init ----------
async function init() {
  const r = await fetch("/api/agents");
  state.agents = await r.json();
  state.agents.forEach((a) => (state.byName[a.name] = a.key));
  renderAgents();
  loadActivity();
  bindUI();
  if (state.agents[0]) selectAgent(state.agents[0].key); // default single pick
}

function renderAgents() {
  const wrap = $("#agents"); wrap.innerHTML = "";
  state.agents.forEach((a) => {
    const card = el("div", "agent");
    card.style.setProperty("--ac", color(a.key));
    card.dataset.key = a.key;
    const av = el("div", "av", INITIALS[a.key] || a.key.slice(0, 2).toUpperCase());
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
    wrap.append(card);
  });
  paintSelection();
}

function onAgentClick(key) {
  if (state.mode === "board") { toast("Board mode uses all agents — just type your question."); return; }
  if (state.mode === "single") state.selected = [key];
  else { // chain: toggle, preserve order
    const i = state.selected.indexOf(key);
    if (i >= 0) state.selected.splice(i, 1); else state.selected.push(key);
  }
  paintSelection();
  focusComposer();
}
function selectAgent(key) { state.selected = [key]; paintSelection(); }

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
    const idx = state.selected.indexOf(k);
    const on = state.mode !== "board" && idx >= 0;
    c.classList.toggle("selected", on);
    if (on && state.mode === "chain") {
      const pill = el("div", "order-pill", String(idx + 1)); c.append(pill);
    }
  });
}

// ---------- modes ----------
function setMode(m) {
  state.mode = m;
  document.querySelectorAll(".mode").forEach((b) => b.classList.toggle("active", b.dataset.mode === m));
  const hints = {
    single: "Pick one agent, then ask.",
    chain: "Pick agents in order — each sees the prior replies.",
    board: "All agents weigh in; the Mentor synthesizes.",
  };
  $("#modeHint").textContent = hints[m];
  if (m === "single" && state.selected.length > 1) state.selected = state.selected.slice(0, 1);
  paintSelection();
  focusComposer();
}

// ---------- @mention parsing (mirror of the CLI) ----------
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

// ---------- conversation ----------
function clearEmpty() { $("#emptyState")?.remove(); }
function addUser(text) {
  clearEmpty();
  const m = el("div", "msg user", text); $("#conversation").append(m); scrollDown();
}
function addAgentBubble(name, key) {
  clearEmpty();
  const wrap = el("div", "msg agent");
  wrap.style.setProperty("--ac", color(key));
  const b = el("div", "bubble");
  const head = el("div", "bubble-head");
  head.append(el("div", "av", INITIALS[key] || key.slice(0, 2).toUpperCase()));
  head.querySelector(".av").style.background = color(key);
  head.append(el("div", "bubble-name", name));
  const body = el("div", "bubble-body streaming");
  b.append(head, body); wrap.append(b); $("#conversation").append(wrap); scrollDown();
  return { wrap, body };
}
function addReacting(wrap, prior) {
  const r = el("div", "reacting"); r.innerHTML = `↑ reacting to <b>${escapeHtml(prior)}</b>`;
  wrap.insertBefore(r, wrap.firstChild);
}
function scrollDown() { const c = $("#conversation"); c.scrollTop = c.scrollHeight; }
function escapeHtml(s) { return s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c])); }

function markSpeaking(key, on) {
  const card = document.querySelector(`.agent[data-key="${key}"]`);
  if (!card) return;
  card.classList.toggle("speaking", on);
  card.querySelector(".speaking-tag")?.remove();
  if (on) { const t = el("div", "speaking-tag", "speaking…"); card.append(t); }
}

// ---------- ask (SSE stream) ----------
async function ask(mode, keys, message) {
  setBusy(true);
  addUser(message);
  let body = null, wrap = null;
  try {
    const resp = await fetch("/api/ask", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode, agents: keys, message }),
    });
    if (!resp.ok) { toast((await resp.json()).error || "request failed", true); setBusy(false); return; }
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
        if (ev.type === "agent_start") { const r = addAgentBubble(ev.agent, ev.key); wrap = r.wrap; body = r.body; markSpeaking(ev.key, true); }
        else if (ev.type === "reacting_to" && wrap) { addReacting(wrap, ev.prior); }
        else if (ev.type === "token" && body) { body.textContent += ev.text; scrollDown(); }
        else if (ev.type === "agent_done") { body?.classList.remove("streaming"); markSpeaking(ev.key, false); }
        else if (ev.type === "done") { /* finished */ }
      }
    }
  } catch (e) {
    toast("stream error: " + e.message, true);
  } finally {
    document.querySelectorAll(".agent.speaking").forEach((c) => { c.classList.remove("speaking"); c.querySelector(".speaking-tag")?.remove(); });
    setBusy(false);
    loadActivity();
  }
}

// reacting connector: we know prior agent at start for i>0, so peek via a tiny lookahead.
// Simpler: handle reacting_to by attaching to the latest bubble before tokens arrive.
// (We add it live below.)

function setBusy(b) { state.busy = b; $("#send").disabled = b; $("#input").disabled = b; }

// ---------- submit ----------
function onSubmit(e) {
  e?.preventDefault();
  if (state.busy) return;
  const inputEl = $("#input"); const raw = inputEl.value.trim();
  if (!raw) return;

  if (state.pending === "brag") { doBrag(raw); inputEl.value = ""; cancelPending(); return; }

  const parsed = parseMentions(raw);
  let mode, keys, message;
  if (parsed) { mode = parsed.mode; keys = parsed.keys; message = parsed.message; if (parsed.mode) setMode(parsed.mode); if (keys.length) { state.selected = keys; paintSelection(); } }
  else { mode = state.mode; keys = state.selected.slice(); message = raw; }

  if (!message) { toast("Add a message after the agent(s).", true); return; }
  if (mode !== "board" && keys.length === 0) { toast("Pick an agent (left) or @mention one.", true); return; }

  inputEl.value = ""; autoGrow(inputEl);
  ask(mode, keys, message);
}

// ---------- quick actions ----------
async function doMorning() {
  setBusy(true);
  try {
    const qs = (await (await fetch("/api/morning")).json()).questions || [];
    clearEmpty();
    const form = el("div", "msg agent"); form.style.setProperty("--ac", "#f0b65e");
    const card = el("div", "mform");
    card.append(el("h4", null, "☀ Morning check-in"));
    qs.forEach((q, i) => {
      const mq = el("div", "mq");
      const lab = el("label", null, `${i + 1}. ${q}`); lab.htmlFor = `mq${i}`;
      const ta = el("textarea"); ta.id = `mq${i}`; ta.rows = 2; ta.dataset.q = q;
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
      const { body } = addAgentBubble("The Design Project Manager", "pm");
      body.classList.remove("streaming"); body.textContent = res.plan || "(no plan)";
    };
  } catch (e) { toast("morning failed: " + e.message, true); }
  finally { setBusy(false); }
}

async function doWeekly() {
  setBusy(true);
  clearEmpty();
  const { body } = addAgentBubble("Weekly review", "mentor");
  body.textContent = "Running weekly review (PM summary → Mentor)…";
  try {
    const res = await (await fetch("/api/weekly", { method: "POST" })).json();
    body.classList.remove("streaming"); body.textContent = res.review || "(no review)";
    loadActivity();
  } catch (e) { body.textContent = "weekly failed: " + e.message; }
  finally { setBusy(false); }
}

async function doSync() {
  toast("Syncing Google Docs…");
  try {
    const res = (await (await fetch("/api/sync", { method: "POST" })).json()).results || [];
    res.forEach((r) => toast(`${r.file}: ${r.status}`, r.status.startsWith("err")));
  } catch (e) { toast("sync failed: " + e.message, true); }
}

function startBrag() {
  state.pending = "brag";
  const i = $("#input"); i.placeholder = "What did you do? (logged to your Brag Doc) — Esc to cancel"; i.focus();
  $("#send").textContent = "＋";
}
function cancelPending() {
  state.pending = null;
  $("#input").placeholder = "Ask the board…  (@critic review this flow: …)";
  $("#send").textContent = "▶";
}
async function doBrag(text) {
  try {
    const res = await (await fetch("/api/brag", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) })).json();
    toast(`Logged → ${res.section}`);
    loadActivity();
  } catch (e) { toast("brag failed: " + e.message, true); }
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
      top.append(el("div", "tl-title", it.title));
      top.append(el("div", "tl-date", it.date || ""));
      card.append(top);
      if (it.body) card.append(el("div", "tl-body", it.body));
      card.onclick = () => openModal(it.title + (it.date ? " · " + it.date : ""), it.body || "");
      tl.append(card);
    });
  } catch { /* ignore */ }
}

function openModal(title, body) { $("#modalTitle").textContent = title; $("#modalBody").textContent = body; $("#modal").hidden = false; }

// ---------- toasts ----------
function toast(msg, err) {
  const t = el("div", "toast" + (err ? " err" : ""), msg);
  $("#toasts").append(t);
  setTimeout(() => t.remove(), 4200);
}

// ---------- ui binding ----------
function autoGrow(t) { t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, 160) + "px"; }
function bindUI() {
  document.querySelectorAll(".mode").forEach((b) => (b.onclick = () => setMode(b.dataset.mode)));
  $("#composer").addEventListener("submit", onSubmit);
  const input = $("#input");
  input.addEventListener("input", () => autoGrow(input));
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); onSubmit(e); }
    if (e.key === "Escape" && state.pending) cancelPending();
  });
  document.querySelectorAll(".act").forEach((b) => (b.onclick = () => {
    const a = b.dataset.action;
    if (a === "morning") doMorning();
    else if (a === "weekly") doWeekly();
    else if (a === "sync") doSync();
    else if (a === "brag") startBrag();
  }));
  $("#modalClose").onclick = () => ($("#modal").hidden = true);
  $("#modal").onclick = (e) => { if (e.target.id === "modal") $("#modal").hidden = true; };
}

init();
