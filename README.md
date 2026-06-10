# Advisory Board

A local, always-available board of 6 AI agents that coach my **L4 → L5** push at
SoFi. Run it from the terminal, keep working docs in `./docs`, and ask the board
for strategy, critique, project tracking, and exec-ready framing. Runs on the
SoFi llm-proxy (Claude); no personal API key or billing.

## The 6 agents

| Handle | Agent | What it does | Files |
|---|---|---|---|
| `@strategist` | Product & Design Strategist | First-principles fintech strategy: retention, txn volume, ops efficiency | reads `./docs` |
| `@pm` | Design Project Manager | Tracks work, sorts into Business Impact / AI Leverage / Cross-functional, writes the Brag Doc | reads + writes |
| `@mentor` | Career Mentor | Weekly long-view review, candor, burnout check | reads `./docs` |
| `@ai` | AI Specialist | Automates manual work (scripts, Figma plugins, Cursor prompts) | — |
| `@critic` | Red Team Critic | Edge cases, cognitive load, fraud, accessibility | — |
| `@translator` | Executive Translator | Rewrites UX rationale into CAC/LTV/business-moat language | — |

## Setup

```bash
cd ~/projects/advisory-board
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
llm-proxy-keys -q          # mint a proxy key (expires ~every 3 days)
# paste the key into ANTHROPIC_API_KEY in .env  (or let the app auto-refresh)
```

The app auto-refreshes the proxy key via `llm-proxy-keys -q` if the key is
missing or rejected, so you usually only set it once.

## Run

Same backend, three ways in:

- **Menubar app** (default) — **Advisory Board.app** in `~/Applications` lives in
  your menubar (roundtable icon) and owns the local server. Menu: **Open Board ·
  Today · Quick Brag · Quick Ask · Quit**. Opens the window on launch.
  - **Quick Brag / Quick Ask** — a tiny input from the menubar (or global hotkey),
    so you capture a win or ask a question in seconds without hunting for a window.
  - **Global hotkeys**: `⌃⌥B` Quick Brag, `⌃⌥A` Quick Ask. *Needs macOS
    Accessibility permission* (System Settings → Privacy & Security → Accessibility
    → enable "Advisory Board"). Menubar still works without it.
  - **Notifications**: the weekly review posts a native notification when ready.
- **Window only** — `gui` alias or `./.venv/bin/python gui.py` (server + window in one).
- **CLI** — `board` alias, `launch-board.command`, or `./.venv/bin/python main.py`.

Architecture: `menubar.py` (rumps) is a single process that owns the FastAPI
server and hosts the board window natively (WKWebView) — so there's **one** Dock
icon ("Advisory Board"); clicking it reopens the window (closing just hides it).
`gui.py` remains a standalone pywebview launcher for the `gui` alias.

### GUI overview

- **Left — agents:** card per agent; cards light up + show "speaking…" as they
  stream. Toolbar: **New chat · Morning · Brag**. Each agent keeps its **own
  conversation** — click "Critic" to see only your Critic history; click "PM" to
  switch; click **The Whole Board** for all six. (Chain by typing `@a > @b …`.)
  Weekly review + 1:1 sync run on a schedule, not from the toolbar.
- **Center — conversation:** color-coded bubbles stream token-by-token; chain/board
  show a "↑ reacting to …" connector. **Drag an image in (or paste one)** to add
  visual context — it's sent to the agent (vision).
- **Right — activity:** timeline of weekly reviews + brag entries (click to expand).

Stack: FastAPI (`server.py`) + SSE streaming over the existing modules, rendered
by a vanilla-JS dark SPA in `web/`, hosted in a `pywebview` window (`gui.py`,
auto-falls back to the browser). No agent logic changes — the CLI and scheduled
jobs are untouched.

Rebuild the GUI app bundle anytime: `osascript`-free, it's a plain bundle whose
`Contents/MacOS/AdvisoryBoard` runs `./.venv/bin/python gui.py` with
`assets/roundtable.icns` as the icon.


Then talk to the board:

```
@critic review this flow: user taps a pending P2P payment and sees ...
@strategist > @critic > @translator redesign the Activity L1 module
@board should scheduled payments sit above or below pending in the list?
/brag Shipped the Activity redesign spec; cut support tickets 12%
/weekly      # run the Career Mentor's weekly review now
/agents      # list the board
/quit
```

### The three modes (how they talk to each other)

- **Single** — `@agent <msg>` → one agent answers.
- **Chain** — `@a > @b > @c <msg>` → each agent's output flows into the next.
- **Boardroom** — `@board <msg>` → agents respond in turn over a shared
  transcript, reacting to each other; the Mentor synthesizes at the end. Bounded
  by `MAX_BOARD_TURNS` so it can't loop or run up cost.

## Working docs

Drop PRDs, research, and your Brag Doc into `./docs` (Markdown/txt). The
read-access agents get them as context. The PM appends categorized, dated
bullets to `docs/brag-doc.md` whenever you run `/brag`.

### Google Workspace access

`gsuite.py` gives the board **read-only** access to your Google Workspace via the
OAuth tokens Claude Code keeps in the macOS keychain — it never refreshes or
writes them, so it can't break Claude's MCP auth.

- **Calendar is wired into the board's context** (`context.agent_context()`):
  today + the next 7 days, so the planning agents (Strategist / PM / Mentor) and
  the morning check-in are schedule-aware. Cached ~5 min. **📆 Today** button +
  `GET /api/calendar`.
- **Docs** sync as before (`sync_gdoc.py`, the 1:1).
- **All six MCPs reachable** via `gsuite.call(server, tool, args)` for
  `calendar / docs / drive / sheets / slides / gmail` — available on demand;
  Drive/Sheets/Slides/Gmail aren't auto-injected into every prompt (token cost).

Limitation: those tokens expire ~daily and are refreshed when you use Claude.
Google works **reliably while you're actively using the board**; the headless
9am/Thursday jobs use it **best-effort** and fall back to local data if a token
is stale (`gsuite.status()` shows which are live).

### Syncing a living Google Doc (e.g. the 1:1)

`sync_gdoc.py` pulls configured Google Docs into `./docs` so the agents read the
latest version. Set `GDOC_1ON1_ID` (→ `docs/1on1-nathan.md`) or `GDOC_SYNC`
(`docId:file.md, ...`) in `.env`.

```bash
./.venv/bin/python sync_gdoc.py     # refresh now
```

A launchd job also syncs the 1:1 automatically **every Wednesday 16:00**
(`com.mtang.advisory-board.sync.plist`) — right after your usual Wednesday
update — so Thursday's 9am weekly review reads a fresh copy. The weekly review
also runs this best-effort before generating. Notes:

- **Read-only + safe:** it only reads the google-docs token Claude Code already
  keeps in the keychain — never refreshes/writes it — so it can't break Claude's
  MCP auth. If the token is stale, the last synced copy is used.
- **Private:** synced personal docs (the 1:1) are gitignored, never pushed.
- **Freshness:** the token is usually valid right after you've used Claude. For a
  guaranteed-fresh Thursday review, run `sync_gdoc.py` after your Wednesday
  update (or just ask Claude to "sync my 1:1").

## Morning check-in (weekdays 9am)

Every weekday at 09:00 a launchd job
(`~/Library/LaunchAgents/com.mtang.advisory-board.morning.plist`) pops open the
board and runs `/morning`: the PM asks a few **personalized** questions (drawn
from recent activity + the 1:1 + current focus) to set up a high-leverage day,
then synthesizes `TODAY'S FOCUS / SAY NO TO / L5 ANGLE` from your answers. Run it
anytime in the CLI with `/morning` (aliases `/standup`, `/today`).

```bash
launchctl bootout  gui/$(id -u)/com.mtang.advisory-board.morning      # disable
launchctl kickstart -k gui/$(id -u)/com.mtang.advisory-board.morning  # run now
```

## Weekly review (scheduling)

Runs every **Thursday 09:00 local** via launchd
(`~/Library/LaunchAgents/com.mtang.advisory-board.weekly.plist`), scoped to the
**last 7 days (since last Thursday)**: the PM summarizes only the important things
done in that window — dated Brag Doc entries + working docs touched in the window —
then the Mentor reviews it. Output saved to `reviews/weekly-<date>.md`
(log: `~/Library/Logs/advisory-board-weekly.log`).

Run on demand / test:

```bash
./.venv/bin/python scheduler.py          # print the windowed review
./.venv/bin/python scheduler.py --write  # save to reviews/weekly-<date>.md
```

Manage the scheduled job:

```bash
launchctl bootout  gui/$(id -u)/com.mtang.advisory-board.weekly   # disable
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.mtang.advisory-board.weekly.plist  # enable
launchctl kickstart -k gui/$(id -u)/com.mtang.advisory-board.weekly  # run now
```

Or keep it resident instead of launchd: `./.venv/bin/python scheduler.py --daemon`.

### Delivery (Slack + email)

The weekly review is also pushed to Slack and/or email (`deliver.py`), so you
don't have to remember to open the file. Both are opt-in via `.env` and skipped
if unconfigured — the job never fails on a missing secret.

- **Slack** — set `SLACK_WEBHOOK_URL` (an incoming webhook), or `SLACK_BOT_TOKEN`
  + `SLACK_CHANNEL`.
- **Email** — set `EMAIL_TO` + `SMTP_HOST` (Gmail: `smtp.gmail.com`, `SMTP_PASS`
  = a Google App Password). `SMTP_TLS_NOVERIFY=1` is an escape hatch if corp TLS
  interception breaks cert verification.

Delivery is intentionally **not** wired to Claude's Gmail/Slack OAuth — those
tokens refresh through Claude Code and a cron job sharing them could break that
auth. The job uses its own durable webhook + SMTP credentials instead.

## Config (`.env`)

| Var | Default | Notes |
|---|---|---|
| `ANTHROPIC_BASE_URL` | SoFi llm-proxy | proxy endpoint |
| `ANTHROPIC_API_KEY` | — | from `llm-proxy-keys -q`; auto-refreshed |
| `DEFAULT_MODEL` | `claude-sonnet-4-6` | most agents |
| `DEEP_MODEL` | `claude-opus-4-6` | Strategist + Mentor when `DEEP_THINKERS=1` |
| `DEEP_THINKERS` | `1` | route deep agents to Opus |
| `DOCS_DIR` | `docs` | folder the agents read |
| `MAX_BOARD_TURNS` | `7` | boardroom safety cap |

## Files

```
agents.py        the 6 personas (system prompts + global context)
llm.py           proxy-configured Claude client (complete + stream, key auto-refresh)
context.py       loads ./docs; PM Brag Doc writer
orchestrator.py  router + single / chain / boardroom (+ run_stream for the GUI)
morning.py       weekday morning check-in
scheduler.py     weekly Career Mentor review
gsuite.py        read-only Google Workspace client (calendar wired into context)
sync_gdoc.py     read-only Google Doc sync (1:1)
deliver.py       Slack + email delivery
main.py          CLI loop
server.py        FastAPI: JSON + SSE API over the modules
menubar.py       resident menubar app (owns server, quick capture, hotkeys)
gui.py           pywebview window (own server, or --attach <port>)
web/             dark SPA (index.html, app.js, styles.css)
docs/            your working docs + brag-doc.md
```
