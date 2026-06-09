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

## Weekly review (scheduling)

Nothing schedules itself. Run on demand:

```bash
./.venv/bin/python scheduler.py          # PM summary -> Mentor review, printed
```

Keep it resident (Fridays 16:00 local):

```bash
./.venv/bin/python scheduler.py --daemon
```

Or wire `./.venv/bin/python scheduler.py` to cron/launchd for a hands-off setup.

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
