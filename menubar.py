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
    def animationResizeTime_(self, newFrame): return 0.16  # smooth, quick resize


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
                self._app._mini_move(float(body.objectForKey_("dx") or 0), float(body.objectForKey_("dy") or 0))
            elif action == "moveChat":
                self._app._move_chat(float(body.objectForKey_("dx") or 0), float(body.objectForKey_("dy") or 0))
            elif action == "ask":
                self._app._ask_from_sug(str(body.objectForKey_("text") or ""))
            elif action == "orbHoverIn":
                self._app._hover("orb", True)
            elif action == "orbHoverOut":
                self._app._hover("orb", False)
            elif action == "sugHoverIn":
                self._app._hover("sug", True)
            elif action == "sugHoverOut":
                self._app._hover("sug", False)
            else:
                self._app._mini_action(action)
        except Exception:
            pass

    def ctxBoard_(self, sender):
        self._app.show_window()

    def ctxHide_(self, sender):
        self._app._hide_mini()

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
        self._sug = None
        self._sug_wv = None
        self._chat = None
        self._chat_wv = None
        self._bridge = None
        self._sug_visible = False
        self._leave_ticks = 0
        self._mainq = []
        self.menu = ["Mini Companion", "Open Full Board", "Today", None, "Quick Brag", "Quick Ask", None, "Quit"]

        self._last_morning = None
        threading.Thread(target=gui._serve, args=(PORT,), daemon=True).start()
        threading.Thread(target=self._boot, daemon=True).start()
        rumps.Timer(self._drain, 0.25).start()
        rumps.Timer(self._tick, 45).start()          # checks for the 9am morning brief
        rumps.Timer(self._hover_poll, 0.12).start()  # robust hover tracking for the orb+suggestions
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
        rumps.notification("☀ Good morning", "Your morning brief is ready", "Tap the chat button to read it")
        self.show_mini()  # ensure the avatar is up
        try:
            if self._mini_wv:
                self._mini_wv.evaluateJavaScript_completionHandler_("window.__badge && window.__badge(1)", None)
            if self._chat_wv:  # refresh an already-open chat
                self._chat_wv.evaluateJavaScript_completionHandler_("window.__newBrief && window.__newBrief()", None)
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

    SUG_W, SUG_H = 280, 230   # suggestions window

    def _new_borderless(self, w, h, url, keyable):
        from AppKit import (NSBackingStoreBuffered, NSWindowStyleMaskBorderless,
                            NSFloatingWindowLevel, NSWindowCollectionBehaviorCanJoinAllSpaces, NSColor)
        from WebKit import WKWebView, WKWebViewConfiguration, WKUserContentController
        from Foundation import NSURL, NSURLRequest, NSMakeRect
        cls = KeyableWindow if keyable else NSWindow
        win = cls.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, w, h), NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False)
        win.setLevel_(NSFloatingWindowLevel)
        win.setOpaque_(False); win.setBackgroundColor_(NSColor.clearColor())
        win.setHasShadow_(False)
        win.setMovableByWindowBackground_(False)
        win.setReleasedWhenClosed_(False)
        win.setCollectionBehavior_(NSWindowCollectionBehaviorCanJoinAllSpaces)
        win.setAcceptsMouseMovedEvents_(True)
        conf = WKWebViewConfiguration.alloc().init()
        ucc = WKUserContentController.alloc().init()
        ucc.addScriptMessageHandler_name_(self._bridge, "host")
        conf.setUserContentController_(ucc)
        wv = WKWebView.alloc().initWithFrame_configuration_(NSMakeRect(0, 0, w, h), conf)
        try: wv.setValue_forKey_(False, "drawsBackground")
        except Exception: pass
        win.setContentView_(wv)
        wv.loadRequest_(NSURLRequest.requestWithURL_(NSURL.URLWithString_(BASE + url)))
        return win, wv

    def show_mini(self, _=None):
        from AppKit import NSApp
        if self._bridge is None:
            self._bridge = MiniBridge.alloc().initWithApp_(self)
        if self._mini is None:
            self._mini, self._mini_wv = self._new_borderless(84, 84, "/mini", True)   # avatar + chat button
            sf = self._mini.screen().visibleFrame() if self._mini.screen() else None
            if sf:
                self._mini.setFrameOrigin_((sf.origin.x + sf.size.width - 124, sf.origin.y + sf.size.height - 124))
            self._sug, self._sug_wv = self._new_borderless(self.SUG_W, self.SUG_H, "/suggest", True)  # keyable → proper pointer cursor
        self._mini.orderFront_(None)
        NSApp.activateIgnoringOtherApps_(True)

    CHAT_W, CHAT_H = 340, 470

    def _mini_action(self, action):
        if action == "board":
            self.show_window()
        elif action == "menu":
            self._show_ctx_menu()
        elif action == "hide":
            self._hide_mini()
        elif action == "openChat":
            self._open_chat()
        elif action == "closeChat":
            self._close_chat()

    # ---- chat: a separate window; the avatar always stays put ----
    def _open_chat(self, prompt=None):
        from AppKit import NSApp
        if prompt is None and self._chat is not None and self._chat.isVisible():
            self._close_chat(); return   # tapping the chat icon toggles open/closed
        if self._chat is None:
            self._chat, self._chat_wv = self._new_borderless(self.CHAT_W, self.CHAT_H, "/chat", True)
        self._position_chat()
        self._chat.makeKeyAndOrderFront_(None)
        NSApp.activateIgnoringOtherApps_(True)
        if self._mini_wv:
            self._mini_wv.evaluateJavaScript_completionHandler_("window.__clearBadge && window.__clearBadge()", None)
        if prompt and self._chat_wv:
            self._chat_wv.evaluateJavaScript_completionHandler_("window.__ask(" + json.dumps(prompt) + ")", None)

    def _close_chat(self):
        if self._chat:
            self._chat.orderOut_(None)

    def _position_chat(self):
        of = self._mini.frame()
        x = of.origin.x - self.CHAT_W - 10
        sf = self._mini.screen().visibleFrame() if self._mini.screen() else None
        if sf and x < sf.origin.x + 6:                       # off the left edge → put it to the right
            x = of.origin.x + of.size.width + 10
        y = of.origin.y + of.size.height - self.CHAT_H
        if sf and y < sf.origin.y + 6:
            y = sf.origin.y + 6
        self._chat.setFrameOrigin_((x, y))

    def _move_chat(self, dx, dy):
        if self._chat:
            f = self._chat.frame()
            self._chat.setFrameOrigin_((f.origin.x + dx, f.origin.y - dy))

    def _mini_move(self, dx, dy):
        f = self._mini.frame()
        self._mini.setFrameOrigin_((f.origin.x + dx, f.origin.y - dy))
        if self._sug_visible:
            self._position_sug()

    # ---- hover → separate suggestions window (avatar window never changes) ----
    def _hover(self, who, on):
        # Showing is triggered by the orb reporting hover-in; hiding is handled by
        # _hover_poll (polling the real cursor against both windows is far more
        # reliable than DOM enter/leave events crossing two separate windows).
        if who == "orb" and on and not self._sug_visible:
            self._show_sug()

    def _hover_poll(self, _):
        if not self._sug_visible or not self._mini or not self._sug:
            return
        from AppKit import NSEvent
        p = NSEvent.mouseLocation()

        def over(win, pad=14):
            f = win.frame()
            return (f.origin.x - pad <= p.x <= f.origin.x + f.size.width + pad and
                    f.origin.y - pad <= p.y <= f.origin.y + f.size.height + pad)

        if over(self._mini) or over(self._sug):
            self._leave_ticks = 0
        else:
            self._leave_ticks += 1
            if self._leave_ticks >= 2:   # ~0.24s outside both → dismiss
                self._hide_sug()

    def _position_sug(self):
        of = self._mini.frame()
        self._sug.setFrameOrigin_((of.origin.x - self.SUG_W - 6, of.origin.y + of.size.height - self.SUG_H))

    def _show_sug(self):
        if self._sug is None:
            return
        self._sug_visible = True
        self._leave_ticks = 0
        self._position_sug()
        self._sug.orderFront_(None)
        if self._sug_wv:
            self._sug_wv.evaluateJavaScript_completionHandler_("window.__in && window.__in()", None)

    def _hide_sug(self):
        self._sug_visible = False
        if self._sug_wv:
            self._sug_wv.evaluateJavaScript_completionHandler_("window.__out && window.__out()", None)
        threading.Timer(0.34, lambda: self._on_main(lambda: self._sug and self._sug.orderOut_(None))).start()

    def _ask_from_sug(self, text):
        self._hide_sug()
        self._open_chat(prompt=text)

    def _hide_mini(self):
        if self._sug:
            self._sug_visible = False; self._sug.orderOut_(None)
        if self._chat:
            self._chat.orderOut_(None)
        if self._mini:
            self._mini.orderOut_(None)

    def _show_ctx_menu(self):
        from AppKit import NSMenu, NSEvent
        m = NSMenu.alloc().init()
        for title, sel in (("Open full board", "ctxBoard:"), ("Hide avatar", "ctxHide:")):
            it = m.addItemWithTitle_action_keyEquivalent_(title, sel, "")
            it.setTarget_(self._bridge)
        m.popUpMenuPositioningItem_atLocation_inView_(None, NSEvent.mouseLocation(), None)

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
