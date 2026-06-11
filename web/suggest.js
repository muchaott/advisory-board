"use strict";
const host = (a, e) => { try { window.webkit.messageHandlers.host.postMessage(Object.assign({ action: a }, e || {})); } catch { /* not native */ } };
let chips = [], loaded = false, loading = false, shown = false;

async function load() {
  if (loading) return;
  loading = true;
  try {
    const s = (await (await fetch("/api/suggestions")).json()).suggestions || [];
    render(s);
    loaded = s.length > 0;  // only "done" once we actually have suggestions
  } catch { render([]); }
  finally { loading = false; }
}
function render(s) {
  const c = document.getElementById("chips"); c.innerHTML = ""; chips = [];
  if (!s.length) { const d = document.createElement("div"); d.className = "chip muted"; d.textContent = "Thinking about your day…"; c.append(d); return; }
  s.forEach((txt) => {
    const d = document.createElement("div"); d.className = "chip"; d.textContent = txt;
    d.addEventListener("click", () => host("ask", { text: txt }));
    c.append(d); chips.push(d);
  });
  if (shown) reveal();  // a load that finishes while the panel is open animates in
}
function reveal() {
  document.body.classList.add("show");
  chips.forEach((d, i) => setTimeout(() => d.classList.add("in"), 40 + i * 75));
}

// staggered reveal / reverse hide, driven by the native window on show/hide
window.__in = () => {
  shown = true;
  if (!loaded) load();  // self-heal: retry if the startup fetch raced or came back empty
  reveal();
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
