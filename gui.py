#!/usr/bin/env python3
"""Launch the Advisory Board GUI.

Starts the FastAPI server on a free localhost port in a background thread, then
opens a native app window via pywebview. Falls back to the default browser if
pywebview can't open a window.
"""
from __future__ import annotations

import os
import socket
import threading
import time
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _serve(port: int):
    import uvicorn
    config = uvicorn.Config("server:app", host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None  # we're in a worker thread
    server.run()


def _wait(url: str, tries: int = 80) -> bool:
    for _ in range(tries):
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except Exception:
            time.sleep(0.1)
    return False


def main():
    os.chdir(ROOT)  # so `server:app` imports
    port = _free_port()
    threading.Thread(target=_serve, args=(port,), daemon=True).start()
    url = f"http://127.0.0.1:{port}/"
    _wait(url)
    try:
        import webview
        webview.create_window("Advisory Board", url, width=1200, height=800, min_size=(940, 620))
        webview.start()
    except Exception as e:
        print(f"[gui] pywebview unavailable ({e}); opening in browser: {url}")
        import webbrowser
        webbrowser.open(url)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
