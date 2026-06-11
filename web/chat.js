"use strict";
const $ = (s) => document.querySelector(s);
// thread holds board-shaped turns: {t:"user",text} | {t:"agent",key,name,text}
const thread = []; const MAX = 10;
const DEFAULT_AGENT = "mentor";
let busy = false, dragging = false, lastX = 0, lastY = 0, attach = null;

function host(action, extra) { try { window.webkit.messageHandlers.host.postMessage(Object.assign({ action }, extra || {})); } catch { /* not native */ } }

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

// Hand this conversation to the big board, then close the small window.
async function enlarge() {
  try {
    await fetch("/api/handoff", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ viewKey: "single:" + DEFAULT_AGENT, turns: thread }) });
  } catch { /* board will just open empty */ }
  host("enlargeChat");
  // reset the small window so reopening it is a fresh chat
  thread.length = 0; $("#log").innerHTML = "";
  add("bot", "Hey — what are we working on?");
}

function add(cls, text, image) {
  const m = document.createElement("div"); m.className = "mb " + cls;
  if (image) { const im = document.createElement("img"); im.className = "msg-img"; im.src = image; m.append(im); }
  if (text) { const t = document.createElement("div"); t.textContent = text; m.append(t); }
  $("#log").append(m); scroll(); return m;
}
function addBot(name) {
  const m = document.createElement("div"); m.className = "mb bot streaming";
  if (name) { const n = document.createElement("div"); n.className = "mb-name"; n.textContent = name; m.append(n); }
  const t = document.createElement("div"); m.append(t);
  $("#log").append(m); scroll();
  return { wrap: m, body: t };
}
function addNote(text) {
  const m = document.createElement("div"); m.className = "mb note"; m.textContent = text;
  $("#log").append(m); scroll();
}
function scroll() { const l = $("#log"); l.scrollTop = l.scrollHeight; }
function grow(t) { t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, 110) + "px"; }

function turnPair(t) { return [t.t === "user" ? "You" : t.name, t.text]; }

async function ask(q, opts = {}) {
  if (busy) return; busy = true; $("#send").disabled = true;
  add("you", q, opts.imageDataUrl);
  const history = thread.slice(-MAX).map(turnPair);
  thread.push({ t: "user", text: q });
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
          if (ev.key !== DEFAULT_AGENT) addNote("Career Mentor → " + ev.name.replace(/^The /, ""));
        } else if (ev.type === "agent_start") {
          curKey = ev.key; curName = ev.agent;
          ({ body } = addBot(ev.agent.replace(/^The /, "")));
        } else if (ev.type === "token" && body) {
          body.textContent += ev.text; scroll();
        } else if (ev.type === "agent_done" && body) {
          body.parentElement.classList.remove("streaming");
          thread.push({ t: "agent", key: curKey, name: curName, text: body.textContent });
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
window.__newBrief = () => { loadBrief(); };

(async () => { add("bot", "Hey — what are we working on?"); await loadBrief(); setTimeout(() => $("#input").focus(), 80); })();
