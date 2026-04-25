# CLAUDE.md

cli-schwab: agent-friendly Schwab CLI for portfolio analysis, market insights, and trading. Python 3.13+, managed with `uv`.

## Setup

```bash
uv sync
cp .env.example .env
cp config/accounts.template.json config/accounts.json
mkdir -p tokens private
# Optional local policy/profile file
cp config/policy.template.json private/policy.json
```

## Auth

```bash
uv run schwab-auth               # Opens browser for OAuth
uv run schwab-auth --manual      # For headless/SSH (copy-paste URL flow)
uv run schwab-market-auth        # Market data API (opens browser)
uv run schwab-market-auth --manual  # For headless/SSH (copy-paste URL flow)
```

The `--manual` flag prints a URL you can open on any browser (even a different machine),
then prompts you to paste the callback URL. Use this for headless servers or SSH sessions.
Both auth commands support `--manual`.

If the dedicated market OAuth app starts failing with `invalid_client` / `Unauthorized`,
point `SCHWAB_MARKET_APP_KEY`, `SCHWAB_MARKET_CLIENT_SECRET`, and
`SCHWAB_MARKET_CALLBACK_URL` at the working `SCHWAB_INTEL_*` values in local `.env`.
That keeps market auth working while still storing the token separately under the market
slot (`SCHWAB_MARKET_TOKEN_PATH` / `schwab_market_token.json`).

### thinkorswim Enablement (Required for Trading)

Each account must be **thinkorswim enabled** on schwab.com to place orders via API.
Without this, orders are rejected with "No trades are currently allowed".

1. schwab.com → Trade → Trading Platforms → Enable thinkorswim
2. Select accounts to enable (wait for "Pending Enablement" to complete)
3. Re-run `schwab-auth` to refresh token

Read-only access (positions, balances, quotes) works without this step.

Tokens default to `~/.cli-schwab/tokens`. In this repo, keep tokens in
`./tokens` (gitignored) by setting `SCHWAB_CLI_DATA_DIR=.` or explicit
`SCHWAB_TOKEN_PATH` / `SCHWAB_MARKET_TOKEN_PATH`. A sibling SQLite `tokens.db`
sidecar is created automatically for local locking and cached token metadata.

`schwab auth --json`, `schwab auth --market --json`, and `schwab doctor --json`
now perform **live API probes** (portfolio: `get_account_numbers()`, market:
`get_quote("$SPX")`) and report `live_verified: true/false`. If a token file
looks valid but the server rejects it, `valid` is overridden to `false` with a
`live_error` field. Schwab can invalidate refresh tokens server-side before their
nominal 7-day expiry — the live probe catches this.

To re-authenticate:
```bash
uv run schwab auth login --portfolio --manual --force
uv run schwab auth login --market --manual --force
```

Reports default to `~/.cli-schwab/reports`; set
`SCHWAB_REPORT_DIR=./private/reports` to keep them under `private/`. Snapshot
history defaults to `./private/history/schwab_history.db` when `./private/`
exists; override with `SCHWAB_HISTORY_DB_PATH`. Refresh tokens expire after 7 days.

## Local Data Layout

Keep the working tree matching upstream; local artifacts live in gitignored folders:
- `config/accounts.json` (account aliases + numbers)
- `tokens/` (auth tokens when repo-local paths are configured)
- `private/policy.json` (portfolio policy/profile overrides, optional)
- `private/` (notes, snapshots, reports, history DB, journal, reviews, market_cycle, etc.)

Recommended `.env` overrides for repo-local data:

```bash
SCHWAB_CLI_DATA_DIR=.
SCHWAB_REPORT_DIR=./private/reports
SCHWAB_HISTORY_DB_PATH=./private/history/schwab_history.db
SCHWAB_MANUAL_ACCOUNTS_PATH=./private/notes/manual_accounts.json
SCHWAB_POLICY_PATH=./private/policy.json
SCHWAB_ADVISOR_DB_PATH=./private/advisor/advisor.db
# Optional explicit token paths:
SCHWAB_TOKEN_PATH=./tokens/schwab_token.json
SCHWAB_MARKET_TOKEN_PATH=./tokens/schwab_market_token.json
# If the dedicated market app is broken, local .env can reuse the portfolio app:
# SCHWAB_MARKET_APP_KEY=${SCHWAB_INTEL_APP_KEY}
# SCHWAB_MARKET_CLIENT_SECRET=${SCHWAB_INTEL_CLIENT_SECRET}
# SCHWAB_MARKET_CALLBACK_URL=${SCHWAB_INTEL_CALLBACK_URL}
# Optional model override for schwab-advisor recommend:
SCHWAB_ADVISOR_MODEL_COMMAND='codex exec -m gpt-5.4 --skip-git-repo-check --cd .'
```

## CLI Contract

Use `uv run schwab <command>` (or `schwab` if installed). Add `--json` for the
response envelope. For the full historical snapshot/query contract, use
`docs/history.md` as the canonical reference.

`schwab context --json` is the agent-facing context envelope. It includes
`market`, `market_available`, `recent_transactions`, `manual_accounts_included`,
`history`, and `errors`, so partial market-auth failure stays visible instead of
being silently dropped. When the full context is too large, use
`schwab context --json --output <path>` to export it and return a compact pointer.

Experimental recommendation-engine work now lives in the separate,
opt-in `schwab-advisor` CLI; see `docs/advisor-sidecar.md`. Keep the main
`schwab` CLI and canonical history flow stable while iterating on the
operationally isolated recommendation engine.

The morning portfolio brief now has a first-class repo-native flow under
`schwab brief ...`. Nightly build state and delivery history live in the canonical
history DB as `brief_runs` / `brief_deliveries`.

### Commands

| Command | Alias | Description |
|---------|-------|-------------|
| `portfolio [-p]` | `p` | Show portfolio summary (with positions) |
| `positions [--symbol]` | `pos` | Show positions |
| `balance` | `bal` | Show account balances |
| `allocation` | `alloc` | Analyze allocation |
| `vix` | | Show VIX data |
| `indices` | `idx` | Show market indices |
| `sectors` | `sec` | Show sector performance |
| `market` | `mkt` | Show market signals |
| `movers [--gainers\|--losers]` | `mov` | Show top gainers/losers |
| `futures` | `fut` | Show pre-market futures |
| `hours [--date YYYY-MM-DD]` | | Show market hours |
| `fundamentals SYMBOL` | `fund` | Show symbol fundamentals |
| `iv SYMBOL` | | Show implied volatility from the options chain |
| `dividends [--days\|--upcoming]` | `div` | Show dividends |
| `regime` | `reg` | Show market regime |
| `lynch` | `ly` | Run Lynch sell-signal scan |
| `score SYMBOL` | | Show quality-framework score |
| `context [--prompt] [-t brief\|review\|memo] [--output PATH]` | `ctx` | Assemble portfolio + market + policy context |
| `auth` | | Check authentication |
| `doctor` | `dr` | Run diagnostics |
| `accounts` | | List configured accounts |
| `history [--dataset ...] [--snapshot-id SNAPSHOT_ID] [--output PATH]` | `hist` | Query stored snapshot history or read one exact snapshot |
| `query SQL` | | Run read-only SQL against snapshot history |
| `report [--output PATH]` | | Export canonical snapshot JSON |
| `snapshot [--output [PATH]] [--no-market]` | `snap` | Capture canonical snapshot |
| `brief nightly\|send\|status\|show` | `br` | Build, deliver, and inspect the portfolio brief |
| `buy [ACCOUNT] SYMBOL QTY` | | Buy shares |
| `sell [ACCOUNT] SYMBOL QTY` | | Sell shares |
| `orders [ACCOUNT]` | `ord` | Show open orders |

Default account: set `SCHWAB_DEFAULT_ACCOUNT` to omit `ACCOUNT` for buy/sell/orders.

### Recommendation engine (`schwab-advisor`)

Use `uv run schwab-advisor <command>` for the experimental recommendation journal:

```bash
uv run schwab-advisor status --json
uv run schwab-advisor recommend --json
uv run schwab-advisor feedback 12 --status followed --json
uv run schwab-advisor note 12 "buffer constrained by RMD timing" --json
uv run schwab-advisor evaluate --json
uv run schwab-advisor review 12 --json
```

The recommendation engine writes only to its own DB (`./private/advisor/advisor.db`
by default), stores snapshot-backed recommendation provenance, and evaluates against
later snapshots without modifying the canonical history store. Internally,
recommendation generation now uses `PortfolioContext` as its decision-context contract.

### Portfolio brief flow

```bash
uv run schwab brief nightly --json
uv run schwab brief send --json --dry-run
uv run schwab brief status --json
uv run schwab brief show 12 --json
```

Use `brief nightly` to freeze snapshot/context/scorecard inputs once, attach the
advisor output, and render the morning email into the history DB. Use `brief send`
for readiness checks plus delivery. Do not reconstruct brief state from file names.

For large read payloads in the main CLI, prefer:

```bash
uv run schwab context --json --output ./context.json
uv run schwab history --snapshot-id 50 --output ./snapshot-50.json --json
```

### JSON Envelope

```json
{
  "schema_version": 1,
  "command": "portfolio",
  "timestamp": "2026-01-16T08:03:26",
  "success": true,
  "data": {},
  "error": null
}
```

Errors set `success=false` and populate `error`.

### Trade Safety

**CRITICAL: Live trading is DISABLED by default.**

To execute real trades, use one of these methods:

```bash
# Method 1: --live flag (per-command, recommended)
uv run schwab sell acct_trading AAPL 10 --live

# Method 2: Environment variable (session-wide)
export SCHWAB_ALLOW_LIVE_TRADES=true
uv run schwab sell acct_trading AAPL 10
```

Without `--live` or the env var, only `--dry-run` is allowed. This prevents accidental
trades from scripts, agents, or automation.

Additional safeguards:
- `--dry-run` previews without placing an order (always allowed).
- Live trades require typing "CONFIRM" (cannot be bypassed).
- `--non-interactive` fails if a prompt would occur.
- JSON mode cannot execute live trades (use `--dry-run` only).
- All trade attempts are logged to `~/.cli-schwab/trade_audit.log`.

For clawdbot/automation: Use `--dry-run` for previews. Never use `--live` or set
`SCHWAB_ALLOW_LIVE_TRADES` in automated environments unless you have explicit approval.

### Exit Codes

- `0` success
- `1` user/config error
- `2` API/HTTP error

## Architecture

```
src/schwab_client/
├── advisor_cli.py          # Optional schwab-advisor recommendation-engine entrypoint
├── runtime_env.py          # Explicit runtime-only secret/env loading
├── cli/                    # CLI package (modular)
│   ├── __init__.py         # Package entrypoint + compatibility exports
│   ├── parser.py           # argparse setup and aliases
│   ├── router.py           # Command routing
│   ├── context.py          # Cached clients, trade logger
│   ├── output.py           # JSON envelope, formatters
│   └── commands/           # Lazy command map + handlers
│       ├── __init__.py     # Lazy handler map
│       ├── portfolio.py    # portfolio, positions, balance, allocation
│       ├── market.py       # vix, indices, sectors, movers, futures, hours, iv
│       ├── history.py      # history, query
│       ├── trade.py        # buy, sell, orders (unified execute_trade)
│       ├── admin.py        # auth, doctor, accounts
│       ├── context_cmd.py  # context prompt / memo assembly
│       ├── brief_cmd.py    # brief nightly/send/status/show
│       └── report.py       # report, snapshot
├── _advisor/               # Recommendation store schema + persistence
├── _client/                # Internal client mixins / shared helpers
│   └── protocols.py        # Shared raw Schwab transport protocol
├── _history/               # Internal history schema + normalization + store/mixins
├── auth_tokens.py          # Token paths, locking, metadata sidecar
├── secure_files.py         # Restrictive permissions for tokens/private DBs
├── auth.py                 # Portfolio API auth flows
├── market_auth.py          # Market API auth flows
├── history.py              # Public SQLite history API
├── snapshot.py             # Canonical snapshot collection
└── client.py               # Public SchwabClientWrapper surface

src/core/                   # Pure business logic plus analysis helpers
├── advisor_models.py       # Typed recommendation payloads
├── advisor_prompts.py      # Structured recommendation prompts
├── advisor_scoring.py      # Deterministic outcome scoring
├── advisor_sidecar.py      # Recommendation-engine orchestration (legacy filename)
├── brief_analysis.py       # Brief narrative analysis + fallback
├── brief_render.py         # Brief HTML/text rendering + delivery helper
├── brief_scorecard.py      # Deterministic bucket scorecard
├── brief_service.py        # End-to-end brief orchestration
├── brief_types.py          # Shared brief-pipeline types
├── context.py              # Portfolio context assembly
├── context_models.py       # Context-only helper models
├── json_types.py           # Shared JSON aliases/helpers
├── market_service.py       # Market data processing
├── policy.py               # Policy evaluation and pacing alerts
├── polymarket.py           # Macro probability signal fetch/normalization
├── portfolio_service.py    # Portfolio aggregation
├── prompts.py              # Brief/review/memo templates
├── snapshot_service.py     # Manual-account merge + snapshot helpers
└── errors.py               # Custom exceptions

config/
├── accounts.schema.json    # JSON schema for accounts.json
├── accounts.template.json  # Template (tracked)
├── policy.template.json    # Public-safe policy/profile template
├── accounts.json           # Your config (gitignored)
└── secure_account_config.py
```

### Key Design Patterns

1. **Client Caching**: `context.py` provides lazy singletons for portfolio and market
   clients. Token I/O happens once per CLI invocation.

2. **Managed Token Storage**: `auth_tokens.py`, `auth.py`, and `market_auth.py` keep JSON token files
   paired with a sibling SQLite `tokens.db` sidecar for locking and cached metadata.

3. **Unified Trade Execution**: `trade.py` uses a single `execute_trade()` function
   for both buy and sell, eliminating duplication.

4. **Command Aliases**: Short aliases (`p`, `dr`, `snap`, `ctx`) defined in `cli/parser.py`.

5. **Lazy CLI Imports**: command modules, public package exports, and Schwab order/auth imports are loaded on demand so help/version output stays fast and warning-free.

6. **Centralized Output**: `output.py` handles JSON envelope, formatters, and error
   handling consistently across all commands.

7. **Shared Payload Boundaries**: `brief_types.py`, `context_models.py`, `json_types.py`,
   and `_client/protocols.py` hold small reusable types/protocols instead of repeating
   ad hoc tuple/dict shapes inside orchestrators.

8. **Canonical Decision Context**: the recommendation engine should consume
   `PortfolioContext` objects internally; only use dict payloads at serialization or
   CLI boundaries.

## Testing

```bash
# Run all tests
uv run pytest

# Run unit tests only
uv run pytest tests/unit/

# Run specific test
uv run pytest tests/unit/test_cli.py -v

# Run lint/type/quality gates
uv run ruff check src tests config scripts
uv run mypy src tests config scripts
uv run python scripts/check_quality_budget.py --root src --max-any 20 --max-broad-catches 0
uv run python scripts/check_quality_budget.py --root config --max-any 0 --max-broad-catches 0
uv run python scripts/check_quality_budget.py --root scripts --max-any 11 --max-broad-catches 0
uv export --no-dev --format requirements-txt --no-hashes --no-emit-project --output-file /tmp/schwab-requirements.txt
uv run --with pip-audit pip-audit -r /tmp/schwab-requirements.txt --no-deps --disable-pip --progress-spinner off
uv run bandit -q -r src config scripts -ll --skip B310,B608
```

`tests/conftest.py` now provides lightweight CLI helpers (`run_cli()`, `CLIResult`, and
`validate_envelope()`) for JSON-envelope assertions. Patch command dependencies inside
individual test modules when you need mocked clients.

## Critical Rules

1. Never commit `.env`, `config/accounts.json`, `tokens/`, or anything under `private/`.
2. Never hardcode account numbers or API keys.
3. Use `hashValue` from `get_account_numbers()` for API calls.
4. Use `get_client()` and `get_cached_market_client()` from `context.py` - never
   instantiate clients directly in commands.
5. Keep household-specific policy aliases and thresholds in `private/policy.json`
   or `SCHWAB_POLICY_PATH`, not in tracked source files.
