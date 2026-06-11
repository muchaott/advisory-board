#!/usr/bin/env python3
"""Resident menubar app — the board's "always there" layer.

Single process: owns the FastAPI server, hosts the board window natively
(WKWebView, so there's ONE Dock icon — "Advisory Board" — and clicking it
reopens the window), and provides quick capture (Brag / Ask / Today) + global
hotkeys.

Hotkeys (need macOS Accessibility permission for this app):
  ⌃⌥B  Quick Brag      ⌃⌥A  Quick Ask
"""
from __future__ import annotations

import json
import os
import sys
import threading
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

import objc
import rumps
import rumps.rumps as _rr
from AppKit import NSWindow
from Foundation import NSObject
import gui  # reuse _free_port / _serve / _wait


class KeyableWindow(NSWindow):
    """Borderless window that can still become key (so the chat input accepts typing)."""
    def canBecomeKeyWindow(self): return True
    def canBecomeMainWindow(self): return True


class MiniBridge(NSObject):
    """Receives postMessage({action}) from the mini web UI to expand/collapse."""
    def initWithApp_(self, app):
        self = objc.super(MiniBridge, self).init()
        if self is None:
            return None
        self._app = app
        return self

    def userContentController_didReceiveScriptMessage_(self, ucc, message):
        try:
            body = message.body()
            action = str(body.objectForKey_("action"))
            if action == "move":
                dx = float(body.objectForKey_("dx") or 0)
                dy = float(body.objectForKey_("dy") or 0)
                self._app._mini_move(dx, dy)
            else:
                self._app._mini_action(action)
        except Exception:
            pass

PORT = gui._free_port()
BASE = f"http://127.0.0.1:{PORT}"
ICON = os.path.join(ROOT, "assets", "logo.png")

_BOARD = None  # set to the running app instance


def _get(path):
    return json.load(urllib.request.urlopen(BASE + path, timeout=60))


def _post(path, payload):
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    return json.load(urllib.request.urlopen(req, timeout=90))


# Dock-icon click on a running app fires "reopen" — re-show the window.
class _ReopenApp(_rr.NSApp):
    def applicationShouldHandleReopen_hasVisibleWindows_(self, sender, flag):
        if _BOARD is not None:
            _BOARD._on_main(_BOARD.show_window)
        return True


_rr.NSApp = _ReopenApp  # rumps instantiates this as its app delegate


class BoardApp(rumps.App):
    def __init__(self):
        super().__init__("Advisory Board", icon=ICON if os.path.exists(ICON) else None,
                         title=None if os.path.exists(ICON) else "◎", quit_button=None)
        global _BOARD
        _BOARD = self
        self._window = None
        self._webview = None
        self._mini = None
        self._mini_wv = None
        self._bridge = None
        self._mainq = []
        self.menu = ["Mini Companion", "Open Full Board", "Today", None, "Quick Brag", "Quick Ask", None, "Quit"]

        self._last_morning = None
        threading.Thread(target=gui._serve, args=(PORT,), daemon=True).start()
        threading.Thread(target=self._boot, daemon=True).start()
        rumps.Timer(self._drain, 0.25).start()
        rumps.Timer(self._tick, 45).start()   # checks for the 9am morning brief
        self._start_hotkeys()

    def _tick(self, _):
        from datetime import datetime
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        if now.hour == 9 and self._last_morning != today:
            self._last_morning = today
            threading.Thread(target=self._morning, daemon=True).start()

    def _morning(self):
        try:
            import morning
            morning.write_brief()
            self._on_main(self._show_morning)
        except Exception as e:
            msg = str(e)[:90]
            self._on_main(lambda: rumps.notification("Morning brief failed", "", msg))

    def _show_morning(self):
        rumps.notification("☀ Good morning", "Your morning brief is ready", "Tap the companion to read it")
        self.show_mini()  # ensure the orb is up
        try:
            if self._mini_wv:
                self._mini_wv.evaluateJavaScript_completionHandler_("window.__newBrief && window.__newBrief()", None)
        except Exception:
            pass

    def _boot(self):
        gui._wait(BASE + "/")
        self._on_main(self._install_edit_menu)
        self._on_main(self.show_mini)   # the floating companion is the default presence

    def _install_edit_menu(self):
        """A rumps app has no main menu, so ⌘C/⌘V/⌘A/⌘Z don't bind to anything.
        Install a standard Edit menu (actions go down the responder chain to the
        focused WKWebView) so copy/paste/select-all/undo work in the chat."""
        from AppKit import NSMenu, NSMenuItem, NSApp
        main = NSMenu.alloc().init()

        app_item = NSMenuItem.alloc().init(); main.addItem_(app_item)
        app_menu = NSMenu.alloc().init()
        app_menu.addItemWithTitle_action_keyEquivalent_("Quit Advisory Board", "terminate:", "q")
        app_item.setSubmenu_(app_menu)

        edit_item = NSMenuItem.alloc().init(); main.addItem_(edit_item)
        edit = NSMenu.alloc().initWithTitle_("Edit")
        edit.addItemWithTitle_action_keyEquivalent_("Undo", "undo:", "z")
        edit.addItemWithTitle_action_keyEquivalent_("Redo", "redo:", "Z")
        edit.addItem_(NSMenuItem.separatorItem())
        edit.addItemWithTitle_action_keyEquivalent_("Cut", "cut:", "x")
        edit.addItemWithTitle_action_keyEquivalent_("Copy", "copy:", "c")
        edit.addItemWithTitle_action_keyEquivalent_("Paste", "paste:", "v")
        edit.addItemWithTitle_action_keyEquivalent_("Select All", "selectAll:", "a")
        edit_item.setSubmenu_(edit)

        NSApp.setMainMenu_(main)

    # ---- main-thread marshalling ----
    def _on_main(self, fn): self._mainq.append(fn)

    def _drain(self, _):
        while self._mainq:
            fn = self._mainq.pop(0)
            try:
                fn()
            except Exception as e:
                rumps.notification("Advisory Board", "error", str(e)[:90])

    # ---- native window (WKWebView, in-process) ----
    def show_window(self, _=None):
        from AppKit import NSApp
        if self._window is None:
            self._window = self._make_window()
        self._window.makeKeyAndOrderFront_(None)
        NSApp.activateIgnoringOtherApps_(True)

    def _make_window(self):
        from AppKit import (NSWindow, NSBackingStoreBuffered, NSWindowStyleMaskTitled,
                            NSWindowStyleMaskClosable, NSWindowStyleMaskResizable,
                            NSWindowStyleMaskMiniaturizable)
        from WebKit import WKWebView, WKWebViewConfiguration
        from Foundation import NSURL, NSURLRequest, NSMakeRect
        mask = (NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
                | NSWindowStyleMaskResizable | NSWindowStyleMaskMiniaturizable)
        rect = NSMakeRect(0, 0, 1200, 800)
        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, mask, NSBackingStoreBuffered, False)
        win.setTitle_("Advisory Board")
        win.setReleasedWhenClosed_(False)  # closing hides; reopen re-shows
        win.setMinSize_((940, 620))
        wv = WKWebView.alloc().initWithFrame_configuration_(rect, WKWebViewConfiguration.alloc().init())
        win.setContentView_(wv)
        wv.loadRequest_(NSURLRequest.requestWithURL_(NSURL.URLWithString_(BASE + "/")))
        win.center()
        self._webview = wv
        return win

    @rumps.clicked("Open Full Board")
    def _open(self, _): self.show_window()

    @rumps.clicked("Mini Companion")
    def _mini_click(self, _): self.show_mini()

    def show_mini(self, _=None):
        from AppKit import (NSBackingStoreBuffered, NSWindowStyleMaskBorderless,
                            NSFloatingWindowLevel, NSWindowCollectionBehaviorCanJoinAllSpaces,
                            NSApp, NSColor)
        from WebKit import WKWebView, WKWebViewConfiguration, WKUserContentController
        from Foundation import NSURL, NSURLRequest, NSMakeRect
        if self._mini is None:
            rect = NSMakeRect(0, 0, 92, 92)   # starts as the avatar orb
            win = KeyableWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                rect, NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False)
            win.setLevel_(NSFloatingWindowLevel)                 # always on top
            win.setOpaque_(False); win.setBackgroundColor_(NSColor.clearColor())
            win.setHasShadow_(True)
            win.setMovableByWindowBackground_(False)             # JS handles dragging
            win.setReleasedWhenClosed_(False)
            win.setCollectionBehavior_(NSWindowCollectionBehaviorCanJoinAllSpaces)
            conf = WKWebViewConfiguration.alloc().init()
            ucc = WKUserContentController.alloc().init()
            self._bridge = MiniBridge.alloc().initWithApp_(self)
            ucc.addScriptMessageHandler_name_(self._bridge, "host")
            conf.setUserContentController_(ucc)
            wv = WKWebView.alloc().initWithFrame_configuration_(rect, conf)
            try: wv.setValue_forKey_(False, "drawsBackground")   # transparent webview
            except Exception: pass
            win.setContentView_(wv)
            wv.loadRequest_(NSURLRequest.requestWithURL_(NSURL.URLWithString_(BASE + "/mini")))
            sf = win.screen().visibleFrame() if win.screen() else None
            if sf:
                win.setFrameOrigin_((sf.origin.x + sf.size.width - 120, sf.origin.y + sf.size.height - 120))
            self._mini = win; self._mini_wv = wv
        self._mini.orderFront_(None)
        NSApp.activateIgnoringOtherApps_(True)

    _SIZES = {"collapse": (92, 92), "orb": (92, 92), "hover": (320, 210),
              "menu": (200, 110), "expand": (346, 478)}

    def _mini_action(self, action):
        if not self._mini:
            return
        if action == "board":
            self.show_window(); return
        if action == "hide":
            self._mini_resize("orb"); self._mini.orderOut_(None); return
        if action in self._SIZES:
            self._mini_resize(action)
            if action == "expand":
                self._mini.makeKeyAndOrderFront_(None)

    def _mini_resize(self, action):
        from Foundation import NSMakeRect
        f = self._mini.frame()
        right = f.origin.x + f.size.width
        top = f.origin.y + f.size.height
        w, h = self._SIZES.get(action, (92, 92))
        self._mini.setFrame_display_animate_(NSMakeRect(right - w, top - h, w, h), True, True)

    def _mini_move(self, dx, dy):
        f = self._mini.frame()
        self._mini.setFrameOrigin_((f.origin.x + dx, f.origin.y - dy))

    @rumps.clicked("Today")
    def _today(self, _):
        try:
            c = _get("/api/calendar"); t = c.get("today", [])
            rumps.notification("Today", f"{len(t)} events",
                               "\n".join(t[:6]) if t else "Nothing on the calendar — clear runway.")
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
            msg = str(e)[:90]
            self._on_main(lambda: rumps.notification("Ask failed", "", msg))

    @rumps.clicked("Quit")
    def _quit(self, _):
        rumps.quit_application()

    def _start_hotkeys(self):
        try:
            from pynput import keyboard
            self._hk = keyboard.GlobalHotKeys({
                "<ctrl>+<alt>+b": lambda: self._on_main(lambda: self.quick_brag(None)),
                "<ctrl>+<alt>+a": lambda: self._on_main(lambda: self.quick_ask(None)),
            })
            self._hk.start()
        except Exception:
            pass


if __name__ == "__main__":
    BoardApp().run()
