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

```bash
./.venv/bin/python main.py
```

### Launch it like an app

- **Spotlight / Launchpad / Dock:** a clickable **Advisory Board.app** lives in
  `~/Applications` (opens Terminal and starts the board). Drag it to your Dock.
- **Double-click file:** `launch-board.command` in this folder.
- **Terminal alias:** `board` (added to `~/.zshrc`).

Recreate the app launcher anytime:

```bash
osacompile -o "$HOME/Applications/Advisory Board.app" \
  -e 'tell application "Terminal" to do script "cd ~/projects/advisory-board && ./.venv/bin/python main.py"'
cp assets/roundtable.icns "$HOME/Applications/Advisory Board.app/Contents/Resources/applet.icns"
touch "$HOME/Applications/Advisory Board.app"
```


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

### Syncing a living Google Doc (e.g. the 1:1)

`sync_gdoc.py` pulls configured Google Docs into `./docs` so the agents read the
latest version. Set `GDOC_1ON1_ID` (→ `docs/1on1-nathan.md`) or `GDOC_SYNC`
(`docId:file.md, ...`) in `.env`.

```bash
./.venv/bin/python sync_gdoc.py     # refresh now
```

The weekly review also runs this best-effort before generating. Notes:

- **Read-only + safe:** it only reads the google-docs token Claude Code already
  keeps in the keychain — never refreshes/writes it — so it can't break Claude's
  MCP auth. If the token is stale, the last synced copy is used.
- **Private:** synced personal docs (the 1:1) are gitignored, never pushed.
- **Freshness:** the token is usually valid right after you've used Claude. For a
  guaranteed-fresh Thursday review, run `sync_gdoc.py` after your Wednesday
  update (or just ask Claude to "sync my 1:1").

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
llm.py           proxy-configured Claude client (key auto-refresh)
context.py       loads ./docs; PM Brag Doc writer
orchestrator.py  router + single / chain / boardroom
main.py          CLI loop
scheduler.py     weekly Career Mentor review
docs/            your working docs + brag-doc.md
```
