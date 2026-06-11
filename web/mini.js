"use strict";
const $ = (s) => document.querySelector(s);
const el = (t, c) => { const e = document.createElement("div"); if (c) e.className = c; return e; };
const thread = [];
const MAX = 10;
let busy = false;

function add(cls, text) {
  const m = el("div", "mb " + cls); m.textContent = text || "";
  $("#log").append(m); scroll();
  return m;
}
function scroll() { const l = $("#log"); l.scrollTop = l.scrollHeight; }

async function greet() {
  try {
    const b = await (await fetch("/api/morning-brief")).json();
    if (b && b.text) { add("bot", b.text); return; }
  } catch { /* ignore */ }
  add("bot", "Hey — what are we working on?");
}

async function ask(q) {
  if (busy) return;
  busy = true; $("#send").disabled = true;
  add("you", q);
  const history = thread.slice(-MAX);
  thread.push(["You", q]);
  const m = add("bot", ""); m.classList.add("streaming");
  try {
    const resp = await fetch("/api/ask", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: "single", agents: ["pm"], message: q, history }),
    });
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

function grow(t) { t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, 120) + "px"; }
$("#composer").addEventListener("submit", (e) => {
  e.preventDefault();
  const t = $("#input"); const v = t.value.trim(); if (!v || busy) return;
  t.value = ""; grow(t); ask(v);
});
$("#input").addEventListener("input", (e) => grow(e.target));
$("#input").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#composer").requestSubmit(); } });
greet();
