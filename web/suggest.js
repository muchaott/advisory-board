"use strict";
const host = (a, e) => { try { window.webkit.messageHandlers.host.postMessage(Object.assign({ action: a }, e || {})); } catch { /* not native */ } };
let chips = [], loading = false, shown = false, currentTexts = [];

async function load() {
  if (loading) return;
  loading = true;
  try {
    const s = (await (await fetch("/api/suggestions")).json()).suggestions || [];
    render(s);
  } catch { render([]); }
  finally { loading = false; }
}

function same(s) { return s.length === currentTexts.length && s.every((t, i) => t === currentTexts[i]); }

function render(s) {
  if (!s.length) {                       // a refresh that returned nothing keeps the last good set
    if (chips.length) return;
    const c = document.getElementById("chips"); c.innerHTML = ""; chips = []; currentTexts = [];
    const d = document.createElement("div"); d.className = "chip muted"; d.textContent = "Thinking about your day…"; c.append(d);
    return;
  }
  if (same(s)) { if (shown) reveal(); return; }   // unchanged → don't rebuild (no flicker)
  const c = document.getElementById("chips"); c.innerHTML = ""; chips = []; currentTexts = s.slice();
  s.forEach((txt) => {
    const d = document.createElement("div"); d.className = "chip"; d.textContent = txt;
    d.addEventListener("click", () => host("ask", { text: txt }));
    c.append(d); chips.push(d);
  });
  if (shown) reveal();
}
function reveal() {
  document.body.classList.add("show");
  chips.forEach((d, i) => setTimeout(() => d.classList.add("in"), 40 + i * 75));
}

// driven by the native window on show/hide
window.__in = () => {
  shown = true;
  reveal();   // show whatever we have immediately…
  load();     // …then refresh against today's current context
};
window.__out = () => {
  shown = false;
  document.body.classList.remove("show");
  const n = chips.length;
  chips.forEach((d, i) => setTimeout(() => d.classList.remove("in"), (n - 1 - i) * 55));
};

document.body.addEventListener("mouseenter", () => host("sugHoverIn"));
document.body.addEventListener("mouseleave", () => host("sugHoverOut"));
load();
