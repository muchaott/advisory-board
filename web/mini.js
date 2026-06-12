"use strict";
const $ = (s) => document.querySelector(s);
let dragging = false, moved = false, lastX = 0, lastY = 0, unread = 0;

function host(action, extra) { try { window.webkit.messageHandlers.host.postMessage(Object.assign({ action }, extra || {})); } catch { /* not native */ } }
function setUnread(n) { unread = Math.max(0, n); const b = $("#badge"); b.textContent = unread > 9 ? "9+" : String(unread); b.classList.toggle("show", unread > 0); }
window.__badge = (n) => setUnread(n);
window.__clearBadge = () => setUnread(0);

// drag the avatar anywhere
$("#avatar").addEventListener("mousedown", (e) => { if (e.button !== 0) return; dragging = true; moved = false; lastX = e.screenX; lastY = e.screenY; e.preventDefault(); });
document.addEventListener("mousemove", (e) => {
  if (!dragging) return;
  const dx = e.screenX - lastX, dy = e.screenY - lastY;
  if (dx || dy) { if (Math.abs(dx) + Math.abs(dy) > 2) moved = true; lastX = e.screenX; lastY = e.screenY; host("move", { dx, dy }); }
});
// single click → toggle the options popover; double click → open the full board
let clickTimer = null;
document.addEventListener("mouseup", (e) => {
  if (!dragging) return;
  dragging = false;
  if (moved || e.button !== 0) return;
  if (clickTimer) { clearTimeout(clickTimer); clickTimer = null; host("toggleBoard"); }  // 2nd click within window = double → toggle board
  else { clickTimer = setTimeout(() => { clickTimer = null; host("toggleSug"); }, 260); }
});

// chat button + right-click
$("#chatbtn").addEventListener("click", (e) => { e.stopPropagation(); host("openChat"); });
$("#avatar").addEventListener("contextmenu", (e) => { e.preventDefault(); host("menu"); });

// badge the avatar if there's an unread morning brief
(async () => { try { const b = await (await fetch("/api/morning-brief")).json(); if (b && b.text) setUnread(1); } catch { /* ignore */ } })();
