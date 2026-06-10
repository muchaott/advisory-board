#!/usr/bin/env python3
"""Resident menubar app — the board's "always there" layer.

Owns the FastAPI server, opens the full window on demand, and provides quick
capture (Brag / Ask / Today) plus global hotkeys, so the board integrates into
the day without hunting for a window.

Hotkeys (need macOS Accessibility permission for this app):
  ⌃⌥B  Quick Brag      ⌃⌥A  Quick Ask
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

import rumps
import gui  # reuse _free_port / _serve / _wait

PORT = gui._free_port()
BASE = f"http://127.0.0.1:{PORT}"
ICON = os.path.join(ROOT, "assets", "roundtable.png")


def _get(path):
    return json.load(urllib.request.urlopen(BASE + path, timeout=60))


def _post(path, payload):
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    return json.load(urllib.request.urlopen(req, timeout=90))


class BoardApp(rumps.App):
    def __init__(self):
        super().__init__("Advisory Board", icon=ICON if os.path.exists(ICON) else None,
                         title=None if os.path.exists(ICON) else "◎", quit_button=None)
        self.win_proc = None
        self._mainq = []
        self.menu = ["Open Board", "Today", None, "Quick Brag", "Quick Ask", None, "Quit"]

        threading.Thread(target=gui._serve, args=(PORT,), daemon=True).start()
        threading.Thread(target=self._boot, daemon=True).start()
        rumps.Timer(self._drain, 0.25).start()   # run queued work on the main (Cocoa) thread
        self._start_hotkeys()

    def _boot(self):
        gui._wait(BASE + "/")
        self._on_main(self.open_window)

    # ---- main-thread marshalling ----
    def _on_main(self, fn): self._mainq.append(fn)

    def _drain(self, _):
        while self._mainq:
            fn = self._mainq.pop(0)
            try:
                fn()
            except Exception as e:
                rumps.notification("Advisory Board", "error", str(e)[:90])

    # ---- window ----
    def open_window(self, _=None):
        if self.win_proc and self.win_proc.poll() is None:
            return
        self.win_proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "gui.py"), "--attach", str(PORT)])

    @rumps.clicked("Open Board")
    def _open(self, _): self.open_window()

    @rumps.clicked("Today")
    def _today(self, _):
        try:
            c = _get("/api/calendar"); t = c.get("today", [])
            rumps.notification("Today", f"{len(t)} events", "\n".join(t[:6]) if t else "Nothing on the calendar — clear runway.")
        except Exception as e:
            rumps.notification("Today", "error", str(e)[:90])

    @rumps.clicked("Quick Brag")
    def quick_brag(self, _):
        r = rumps.Window("Log a win — it goes straight to your Brag Doc.", "＋ Quick Brag",
                         dimensions=(360, 90), ok="Log", cancel="Cancel").run()
        if r.clicked and r.text.strip():
            try:
                res = _post("/api/brag", {"text": r.text.strip()})
                rumps.notification("Logged ✓", res.get("section", ""), res.get("entry", ""))
            except Exception as e:
                rumps.notification("Brag failed", "", str(e)[:90])

    @rumps.clicked("Quick Ask")
    def quick_ask(self, _):
        r = rumps.Window("Ask the board (your PM answers).", "Quick Ask",
                         dimensions=(380, 100), ok="Ask", cancel="Cancel").run()
        if r.clicked and r.text.strip():
            q = r.text.strip()
            rumps.notification("Asking the board…", "", q[:90])
            threading.Thread(target=self._ask, args=(q,), daemon=True).start()

    def _ask(self, q):
        try:
            import agents as A
            import orchestrator as O
            ans = O.ask(A.resolve("pm"), q)
            self._on_main(lambda: (rumps.notification("The board says", "", ans[:200]),
                                   rumps.alert("Advisory Board", ans[:1800])))
        except Exception as e:
            self._on_main(lambda: rumps.notification("Ask failed", "", str(e)[:90]))

    @rumps.clicked("Quit")
    def _quit(self, _):
        if self.win_proc and self.win_proc.poll() is None:
            self.win_proc.terminate()
        rumps.quit_application()

    # ---- global hotkeys (best-effort; needs Accessibility permission) ----
    def _start_hotkeys(self):
        try:
            from pynput import keyboard
            self._hk = keyboard.GlobalHotKeys({
                "<ctrl>+<alt>+b": lambda: self._on_main(lambda: self.quick_brag(None)),
                "<ctrl>+<alt>+a": lambda: self._on_main(lambda: self.quick_ask(None)),
            })
            self._hk.start()
        except Exception:
            pass  # menubar still works without global hotkeys


if __name__ == "__main__":
    BoardApp().run()
