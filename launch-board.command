#!/bin/bash
# Double-clickable launcher for the Advisory Board CLI.
# Opens in whatever terminal you double-click it from; portable (uses its own dir).
cd "$(dirname "$0")" || exit 1
clear
exec ./.venv/bin/python main.py
