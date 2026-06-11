"use strict";
const $ = (s) => document.querySelector(s);
const body = document.body;
const thread = []; const MAX = 10;
let busy = false, unread = 0, dragging = false, moved = false, lastX = 0, lastY = 0;

function host(action, extra) { try { window.webkit.messageHandlers.host.postMessage(Object.assign({ action }, extra || {})); } catch { /* not native */ } }
function setState(s) { body.className = s; }

function setUnread(n) {
  unread = Math.max(0, n);
  const b = $("#badge");
  b.textContent = unread > 9 ? "9+" : String(unread);
  b.classList.toggle("show", unread > 0);
}

function expand() { setState("expanded"); host("expand"); setUnread(0); setTimeout(() => $("#input").focus(), 60); scroll(); }
function collapse() { setState("collapsed"); host("collapse"); }
function hoverIn() { if (body.classList.contains("collapsed") && !dragging && !body.classList.contains("menu")) { body.classList.add("hover"); host("hover"); } }
function hoverOut() { if (body.classList.contains("collapsed")) { body.classList.remove("hover"); if (!body.classList.contains("menu")) host("collapse"); } }
function openMenu(x, y) { setState("collapsed menu"); host("menu"); const c = $("#ctx"); c.style.left = "10px"; c.style.top = "10px"; }
function closeMenu() { body.classList.remove("menu"); host("collapse"); }

// ---- drag (anywhere on desktop) ----
$("#orb").addEventListener("mousedown", (e) => {
  if (e.button !== 0) return;
  dragging = true; moved = false; lastX = e.screenX; lastY = e.screenY; e.preventDefault();
});
document.addEventListener("mousemove", (e) => {
  if (!dragging) return;
  const dx = e.screenX - lastX, dy = e.screenY - lastY;
  if (dx || dy) { if (Math.abs(dx) + Math.abs(dy) > 2) moved = true; lastX = e.screenX; lastY = e.screenY; host("move", { dx, dy }); }
});
document.addEventListener("mouseup", (e) => {
  if (!dragging) return; dragging = false;
  if (!moved && e.button === 0 && !body.classList.contains("menu")) expand();   // a click opens
});

// ---- hover suggestions ----
$("#orb").addEventListener("mouseenter", hoverIn);
document.addEventListener("mouseleave", () => { if (!dragging) hoverOut(); });

// ---- right-click menu ----
$("#orb").addEventListener("contextmenu", (e) => { e.preventDefault(); openMenu(e.clientX, e.clientY); });
$("#ctx").addEventListener("click", (e) => {
  const act = e.target.dataset.act; if (!act) return;
  if (act === "hide") { host("hide"); body.classList.remove("menu"); }
  else if (act === "board") { host("board"); closeMenu(); }
});

// ---- chat ----
function add(cls, text) { const m = document.createElement("div"); m.className = "mb " + cls; m.textContent = text || ""; $("#log").append(m); scroll(); return m; }
function scroll() { const l = $("#log"); if (l) l.scrollTop = l.scrollHeight; }
function grow(t) { t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, 110) + "px"; }

async function ask(q) {
  if (busy) return; busy = true; $("#send").disabled = true;
  add("you", q);
  const history = thread.slice(-MAX); thread.push(["You", q]);
  const m = add("bot", ""); m.classList.add("streaming");
  try {
    const resp = await fetch("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: "single", agents: ["pm"], message: q, history }) });
    const reader = resp.body.getReader(); const dec = new TextDecoder(); let buf = "";
    for (;;) {
      const { value, done } = await reader.read(); if (done) break;
      buf += dec.decode(value, { stream: true }); let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const line = buf.slice(0, i).split("\n").find((l) => l.startsWith("data: ")); buf = buf.slice(i + 2);
        if (!line) continue;
        const ev = JSON.parse(line.slice(6));
        if (ev.type === "token") { m.textContent += ev.text; scroll(); }
      }
    }
    thread.push(["Design Project Manager", m.textContent]);
  } catch (e) { m.textContent += "  [error: " + e.message + "]"; }
  finally { m.classList.remove("streaming"); busy = false; $("#send").disabled = false; }
}

$("#collapse").addEventListener("click", collapse);
$("#composer").addEventListener("submit", (e) => {
  e.preventDefault(); const t = $("#input"); const v = t.value.trim(); if (!v || busy) return;
  t.value = ""; grow(t); ask(v);
});
$("#input").addEventListener("input", (e) => grow(e.target));
$("#input").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#composer").requestSubmit(); } });

// ---- suggestions + morning brief ----
async function loadSuggestions() {
  try {
    const s = (await (await fetch("/api/suggestions")).json()).suggestions || [];
    const c = $("#chips"); c.innerHTML = "";
    if (!s.length) { const d = document.createElement("div"); d.className = "chip muted"; d.textContent = "Thinking about your day…"; c.append(d); return; }
    s.forEach((txt) => {
      const d = document.createElement("div"); d.className = "chip"; d.textContent = txt;
      d.addEventListener("click", () => { expand(); ask(txt); });
      c.append(d);
    });
  } catch { /* ignore */ }
}
async function loadBrief() {
  try {
    const b = await (await fetch("/api/morning-brief")).json();
    if (b && b.text) { add("bot", b.text); if (body.classList.contains("collapsed")) setUnread(unread + 1); return true; }
  } catch { /* ignore */ }
  return false;
}
window.__newBrief = () => { loadBrief(); };

(async () => { add("bot", "Hey — what are we working on?"); await loadBrief(); loadSuggestions(); })();
