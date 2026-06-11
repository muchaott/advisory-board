"use strict";
const host = (a, e) => { try { window.webkit.messageHandlers.host.postMessage(Object.assign({ action: a }, e || {})); } catch { /* not native */ } };
let chips = [];

async function load() {
  try { render((await (await fetch("/api/suggestions")).json()).suggestions || []); }
  catch { render([]); }
}
function render(s) {
  const c = document.getElementById("chips"); c.innerHTML = ""; chips = [];
  if (!s.length) { const d = document.createElement("div"); d.className = "chip muted"; d.textContent = "Thinking about your day…"; c.append(d); return; }
  s.forEach((txt) => {
    const d = document.createElement("div"); d.className = "chip"; d.textContent = txt;
    d.addEventListener("click", () => host("ask", { text: txt }));
    c.append(d); chips.push(d);
  });
}

// staggered reveal / reverse hide, driven by the native window on show/hide
window.__in = () => {
  document.body.classList.add("show");
  chips.forEach((d, i) => setTimeout(() => d.classList.add("in"), 40 + i * 75));
};
window.__out = () => {
  document.body.classList.remove("show");
  const n = chips.length;
  chips.forEach((d, i) => setTimeout(() => d.classList.remove("in"), (n - 1 - i) * 55));
};

document.body.addEventListener("mouseenter", () => host("sugHoverIn"));
document.body.addEventListener("mouseleave", () => host("sugHoverOut"));
load();
