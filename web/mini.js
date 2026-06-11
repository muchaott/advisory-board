"use strict";
const $ = (s) => document.querySelector(s);
const thread = [];
const MAX = 10;
let busy = false, unread = 0, briefLoaded = false;

function host(action) {
  try { window.webkit.messageHandlers.host.postMessage({ action }); } catch { /* not native */ }
}
function setUnread(n) {
  unread = Math.max(0, n);
  const b = $("#badge");
  b.textContent = unread > 9 ? "9+" : String(unread);
  b.classList.toggle("show", unread > 0);
}
function expand() {
  document.body.className = "expanded"; host("expand"); setUnread(0);
  setTimeout(() => $("#input").focus(), 60); scroll();
}
function collapse() { document.body.className = "collapsed"; host("collapse"); }

function add(cls, text) {
  const m = document.createElement("div"); m.className = "mb " + cls; m.textContent = text || "";
  $("#log").append(m); scroll(); return m;
}
function scroll() { const l = $("#log"); l.scrollTop = l.scrollHeight; }

async function ask(q) {
  if (busy) return;
  busy = true; $("#send").disabled = true;
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

// add the morning brief as a message; badge it if collapsed
async function loadBrief(forceBadge) {
  try {
    const b = await (await fetch("/api/morning-brief")).json();
    if (!b || !b.text) return false;
    add("bot", b.text); briefLoaded = true;
    if (document.body.classList.contains("collapsed") || forceBadge) setUnread(unread + 1);
    return true;
  } catch { return false; }
}
// called natively at 9am
window.__newBrief = () => { loadBrief(true); };

function grow(t) { t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, 110) + "px"; }

$("#orb").addEventListener("click", expand);
$("#collapse").addEventListener("click", collapse);
$("#composer").addEventListener("submit", (e) => {
  e.preventDefault(); const t = $("#input"); const v = t.value.trim(); if (!v || busy) return;
  t.value = ""; grow(t); ask(v);
});
$("#input").addEventListener("input", (e) => grow(e.target));
$("#input").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#composer").requestSubmit(); } });

// on load: greet + surface any morning brief as unread
(async () => {
  add("bot", "Hey — what are we working on?");
  await loadBrief(false);   // if today's brief exists, it badges the orb
})();
