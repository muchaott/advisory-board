"use strict";
const $ = (s) => document.querySelector(s);
// thread holds board-shaped turns: {t:"user",text} | {t:"agent",key,name,text} | {t:"divider",text,color}
const thread = []; const MAX = 10;
const DEFAULT_AGENT = "mentor";
const COMPANION_VK = "single:" + DEFAULT_AGENT;   // shared with the board's Career Mentor view
let lastAgentKey = DEFAULT_AGENT;
// same palette as the main board (web/app.js); custom agents fill in from /api/agents
const COLORS = { strategist: "#3fd0c9", pm: "#f0b65e", mentor: "#9ccb6a", ai: "#68d391", critic: "#fc8181", translator: "#63b3ed" };
let AGENT_COLORS = {};
const color = (k) => AGENT_COLORS[k] || COLORS[k] || "#9ccb6a";
async function loadColors() { try { (await (await fetch("/api/agents")).json()).forEach((a) => (AGENT_COLORS[a.key] = a.color)); } catch { /* defaults */ } }
let busy = false, dragging = false, lastX = 0, lastY = 0, attach = null, syncTimer = null;

function host(action, extra) { try { window.webkit.messageHandlers.host.postMessage(Object.assign({ action }, extra || {})); } catch { /* not native */ } }

// keep the board's Career Mentor view in sync with this chat (each turn keeps its agent's color)
function syncToBoard() {
  clearTimeout(syncTimer);
  syncTimer = setTimeout(() => {
    fetch("/api/conversations/update", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ viewKey: COMPANION_VK, turns: thread }) }).catch(() => {});
  }, 400);
}

// rebuild the log from board-shaped turns (used on open / when the board updated it)
function renderThread(turns) {
  $("#log").innerHTML = ""; thread.length = 0;
  for (const t of turns) {
    thread.push(t);
    if (t.t === "user") add("you", t.text, t.image || null);
    else if (t.t === "divider") addNote(t.text, t.color);
    else if (t.t === "agent") {
      const { wrap, body } = addBot((t.name || "").replace(/^The /, ""), t.key);
      body.textContent = t.text; wrap.classList.remove("streaming");
      if (t.key) lastAgentKey = t.key;
    }
  }
  scroll();
}
async function loadThread() {
  try {
    const all = await (await fetch("/api/conversations")).json();
    const turns = (all && all[COMPANION_VK]) || [];
    if (turns.length) { renderThread(turns); return true; }
  } catch { /* ignore */ }
  return false;
}
window.__loadThread = () => { loadThread(); };   // native nudges this when the chat is reopened

// ---- image attachment ----
function setAttach(file) {
  if (!file || !file.type.startsWith("image/")) return;
  const r = new FileReader();
  r.onload = () => {
    const m = /^data:(.*?);base64,(.*)$/.exec(r.result);
    if (!m) return;
    attach = { dataUrl: r.result, media_type: m[1], data: m[2] };
    renderAttach(); $("#input").focus();
  };
  r.readAsDataURL(file);
}
function clearAttach() { attach = null; renderAttach(); }
function renderAttach() {
  const bar = $("#attachBar"); bar.innerHTML = ""; bar.classList.toggle("show", !!attach);
  if (!attach) return;
  const img = document.createElement("img"); img.className = "attach-thumb"; img.src = attach.dataUrl;
  const x = document.createElement("button"); x.className = "attach-x"; x.textContent = "✕"; x.onclick = clearAttach;
  const name = document.createElement("span"); name.className = "attach-name"; name.textContent = "Image attached";
  bar.append(img, name, x);
}
const panel = $("#panel");
["dragenter", "dragover"].forEach((ev) => panel.addEventListener(ev, (e) => { e.preventDefault(); panel.classList.add("drag"); }));
panel.addEventListener("dragleave", (e) => { if (!panel.contains(e.relatedTarget)) panel.classList.remove("drag"); });
panel.addEventListener("drop", (e) => { e.preventDefault(); panel.classList.remove("drag"); const f = e.dataTransfer.files[0]; if (f) setAttach(f); });
document.addEventListener("paste", (e) => { const it = [...(e.clipboardData?.items || [])].find((i) => i.type.startsWith("image/")); if (it) setAttach(it.getAsFile()); });

// drag the chat window by its header
$("#head").addEventListener("mousedown", (e) => { if (e.target.id === "close") return; dragging = true; lastX = e.screenX; lastY = e.screenY; e.preventDefault(); });
document.addEventListener("mousemove", (e) => {
  if (!dragging) return;
  const dx = e.screenX - lastX, dy = e.screenY - lastY;
  if (dx || dy) { lastX = e.screenX; lastY = e.screenY; host("moveChat", { dx, dy }); }
});
document.addEventListener("mouseup", () => { dragging = false; });
$("#close").addEventListener("click", () => host("closeChat"));
$("#enlarge").addEventListener("click", enlarge);

// Push the latest into the shared store, then open the board on this conversation.
async function enlarge() {
  try {
    await fetch("/api/conversations/update", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ viewKey: COMPANION_VK, turns: thread }) });
  } catch { /* board reads its last copy */ }
  host("enlargeChat");   // native opens the board on the Career Mentor view + closes this window
}

function add(cls, text, image) {
  const m = document.createElement("div"); m.className = "mb " + cls;
  if (image) { const im = document.createElement("img"); im.className = "msg-img"; im.src = image; m.append(im); }
  if (text) { const t = document.createElement("div"); t.textContent = text; m.append(t); }
  $("#log").append(m); scroll(); return m;
}
function addBot(name, key) {
  const c = color(key);
  const m = document.createElement("div"); m.className = "mb bot streaming";
  m.style.borderLeftColor = c; m.style.setProperty("--cur", c);
  if (name) {
    const head = document.createElement("div"); head.className = "mb-head";
    const n = document.createElement("div"); n.className = "mb-name"; n.textContent = name; n.style.color = c;
    head.append(n);
    m.append(head);
  }
  const t = document.createElement("div"); m.append(t);
  const doc = document.createElement("button"); doc.className = "mb-doc"; doc.textContent = "⤓ Doc"; doc.title = "Save to Google Doc";
  doc.onclick = () => saveToDoc(t.textContent, name);
  m.append(doc);
  $("#log").append(m); scroll();
  return { wrap: m, body: t };
}
function docTitle(text, name) {
  const first = (text.split("\n").find((l) => l.trim()) || "").replace(/^#+\s*/, "").replace(/\*\*/g, "").trim();
  return first ? first.slice(0, 80) : (name ? name.replace(/^The /, "") : "Yoda note");
}
async function saveToDoc(text, name) {
  if (!text || !text.trim()) return;
  try {
    const r = await fetch("/api/savedoc", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: docTitle(text, name), text }) });
    const d = await r.json();
    if (!r.ok || !d.url) { addNote(d.error || "couldn't create the doc"); return; }
    addNote("Saved to Google Doc ✓"); host("openURL", { url: d.url });
  } catch (e) { addNote("save failed: " + e.message); }
}
function addNote(text, col) {
  const m = document.createElement("div"); m.className = "mb note"; m.textContent = text;
  if (col) m.style.color = col;
  $("#log").append(m); scroll();
}
function scroll() { const l = $("#log"); l.scrollTop = l.scrollHeight; }
function grow(t) { t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, 110) + "px"; }

function turnPair(t) { return [t.t === "user" ? "You" : t.name, t.text]; }

async function ask(q, opts = {}) {
  if (busy) return; busy = true; $("#send").disabled = true;
  add("you", q, opts.imageDataUrl);
  const history = thread.filter((t) => t.t === "user" || t.t === "agent").slice(-MAX).map(turnPair);
  thread.push({ t: "user", text: q, image: opts.imageDataUrl || null });
  syncToBoard();
  let body = null, curKey = null, curName = null;
  try {
    const resp = await fetch("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: "auto", agents: [], message: q, history, images: opts.images || [] }) });
    const reader = resp.body.getReader(); const dec = new TextDecoder(); let buf = "";
    for (;;) {
      const { value, done } = await reader.read(); if (done) break;
      buf += dec.decode(value, { stream: true }); let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const line = buf.slice(0, i).split("\n").find((l) => l.startsWith("data: ")); buf = buf.slice(i + 2);
        if (!line) continue;
        const ev = JSON.parse(line.slice(6));
        if (ev.type === "routed") {
          if (ev.key !== DEFAULT_AGENT) {
            const note = "Career Mentor → " + ev.name.replace(/^The /, "");
            addNote(note, color(ev.key));
            thread.push({ t: "divider", text: note, color: color(ev.key) });
          }
        } else if (ev.type === "agent_start") {
          curKey = ev.key; curName = ev.agent; lastAgentKey = ev.key;
          ({ body } = addBot(ev.agent.replace(/^The /, ""), ev.key));
        } else if (ev.type === "token" && body) {
          body.textContent += ev.text; scroll();
        } else if (ev.type === "doc") {
          const n = document.createElement("div"); n.className = "mb note"; n.textContent = "📄 Open Google Doc";
          n.style.cursor = "pointer"; n.style.color = "#9ccb6a"; n.onclick = () => host("openURL", { url: ev.url });
          $("#log").append(n); scroll(); host("openURL", { url: ev.url });
        } else if (ev.type === "auth_needed") {
          addNote("🔑 " + (ev.message || ("Needs " + (ev.service || "access"))));
        } else if (ev.type === "agent_done" && body) {
          body.parentElement.classList.remove("streaming");
          thread.push({ t: "agent", key: curKey, name: curName, text: body.textContent });
          syncToBoard();
        }
      }
    }
  } catch (e) {
    if (body) body.textContent += "  [error: " + e.message + "]"; else addNote("[error: " + e.message + "]");
  } finally {
    if (body) body.parentElement.classList.remove("streaming");
    busy = false; $("#send").disabled = false;
  }
}

// called natively when a suggestion chip is clicked
window.__ask = (t) => { const i = $("#input"); if (i) i.focus(); ask(t); };

$("#composer").addEventListener("submit", (e) => {
  e.preventDefault(); const t = $("#input"); const v = t.value.trim();
  if ((!v && !attach) || busy) return;
  const opts = attach ? { images: [{ media_type: attach.media_type, data: attach.data }], imageDataUrl: attach.dataUrl } : {};
  t.value = ""; grow(t); clearAttach();
  ask(v || "(see attached image)", opts);
});
$("#input").addEventListener("input", (e) => grow(e.target));
$("#input").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#composer").requestSubmit(); } });

let briefShown = false;
async function loadBrief() {
  if (briefShown) return;
  try { const b = await (await fetch("/api/morning-brief")).json(); if (b && b.text) { add("bot", b.text); briefShown = true; } } catch { /* ignore */ }
}
// a new brief is a Mentor turn in the synced thread now — just reload it
window.__newBrief = () => { loadThread(); };

(async () => {
  await loadColors();
  const had = await loadThread();   // resume the synced conversation (includes today's brief)
  if (!had) add("bot", "Hey — what are we working on?");
  setTimeout(() => $("#input").focus(), 80);
})();
