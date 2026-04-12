# cli-schwab

Agent-friendly Schwab CLI tools for portfolio analysis, market insights, and trading.

## Disclaimer

This project is built on the open-source `schwab-py` client and is **not**
affiliated with, endorsed by, or supported by Charles Schwab & Co. Use it at
your own risk and ensure you comply with Schwab's terms and API policies.

## Quick Start

```bash
git clone https://github.com/amadad/cli-schwab.git
cd cli-schwab
uv sync
cp .env.example .env
cp config/accounts.template.json config/accounts.json
mkdir -p tokens private
```

## Install for agents

Install the CLI so it works from any folder, not just inside this repo:

```bash
cd /path/to/cli-schwab
uv tool install -e .
# or: pipx install .
```

Verify the installed command:

```bash
command -v schwab
schwab --help
schwab-advisor --help   # optional sidecar CLI
python scripts/verify_agent_cli.py --account <account-alias>
```

Optional shell completion (requires `argcomplete`):

```bash
activate-global-python-argcomplete --user
# or per shell session:
eval "$(register-python-argcomplete schwab)"
```

## Authentication

Preferred root-CLI flow:

```bash
schwab auth                      # Auth status (same as `schwab auth status`)
schwab auth login --portfolio    # Portfolio API (opens browser)
schwab auth login --portfolio --manual
schwab auth login --market       # Market data API (opens browser)
schwab auth login --market --manual
```

Compatibility shims still work too:

```bash
uv run schwab-auth
uv run schwab-market-auth
```

### thinkorswim Enablement (Required for Trading)

To place orders via the API, each Schwab account must be **thinkorswim enabled**:

1. Log into [schwab.com](https://www.schwab.com)
2. Go to **Trade** → **Trading Platforms**
3. Click **"Learn how to enable thinkorswim"**
4. Select the accounts you want to enable for API trading
5. Wait for "Pending Enablement" to complete (may take minutes to hours)
6. Re-run `schwab-auth` to refresh your token

Without thinkorswim enablement, orders will be rejected with "No trades are currently allowed".
Read-only access (positions, balances, quotes) works without this step.

The `--manual` flag is for headless servers or SSH sessions where a browser can't open
locally. It prints a URL you can open on any device (phone, laptop, etc.), then prompts
you to paste the callback URL. Both auth commands support this flag.

Market commands (`vix`, `indices`, `sectors`, `market`, `movers`, `futures`) require
the market auth flow. Token JSON files are stored under `~/.cli-schwab/tokens`
by default, with a sibling SQLite `tokens.db` sidecar used for local locking and
cached token metadata. `schwab auth --json` and `schwab doctor --json` expose that
storage state for diagnostics. Refresh tokens expire after 7 days.

## CLI Commands

All commands support `--json` for machine-readable output.
Prefer narrow terminal output and explicit file output for large payloads.

### Portfolio Commands

```bash
schwab portfolio           # Portfolio summary
schwab p -p                # Portfolio with positions (alias)
schwab positions           # All positions
schwab pos --symbol AAPL   # Filter by symbol (alias)
schwab balance             # Account balances
schwab bal                 # Alias
schwab allocation          # Allocation analysis
schwab alloc               # Alias
```

### Market Commands

```bash
schwab vix                 # VIX data and interpretation
schwab indices             # Major indices (S&P, Nasdaq, Dow)
schwab idx                 # Alias
schwab sectors             # Sector performance
schwab sec                 # Alias
schwab market              # Aggregated market signals
schwab mkt                 # Alias
schwab movers              # Top gainers/losers
schwab mov --gainers       # Gainers only
schwab futures             # Pre-market futures (/ES, /NQ)
schwab fut                 # Alias
schwab hours               # Market hours for today or a given date
schwab fundamentals AAPL   # Symbol fundamentals
schwab fund AAPL           # Alias
schwab iv AAPL             # Implied volatility from the options chain
schwab dividends           # Recent dividends
schwab div --upcoming      # Upcoming ex-dates
```

### Analysis / Context Commands

```bash
schwab regime              # Market regime (risk-on/off)
schwab reg                 # Alias
schwab lynch               # Lynch sell-signal scan for holdings
schwab ly                  # Alias
schwab score AAPL          # Quality framework score for a symbol
schwab context             # Assemble portfolio + market + policy context
schwab ctx --prompt        # LLM-ready prompt block
schwab context -t memo     # Wrap the context in a memo template
schwab context --json --output ./context.json  # Write the full context to a file
```

`schwab context --json` is the agent-facing context envelope. It includes
`market`, `market_available`, `recent_transactions`, `manual_accounts_included`,
`history`, and `errors`. If market auth is unavailable, the command still succeeds
and surfaces that degradation in `errors` instead of failing silently. Add
`--output PATH` when you want the full payload or rendered prompt/template written
to disk while the CLI returns a compact pointer.

### Admin Commands

```bash
schwab auth                # Check authentication status
schwab doctor              # Run diagnostics
schwab dr                  # Alias
schwab accounts            # List configured accounts
```

### History Commands

```bash
schwab history                               # Recent snapshot runs
schwab hist --dataset portfolio --limit 10   # Portfolio history (alias)
schwab history --dataset positions --symbol AAPL
schwab history --dataset market              # Market context history
schwab history --snapshot-id 50 --json       # Read one exact canonical snapshot
schwab history --snapshot-id 50 --output ./snapshot-50.json --json
schwab history --import-defaults             # Backfill private/snapshots + private/reports
schwab query "SELECT * FROM portfolio_history LIMIT 5"
```

### Snapshot / Export Commands

```bash
schwab snapshot            # Capture canonical snapshot and store in SQLite
schwab snap --json         # Primary automation path (alias)
schwab snapshot --output   # Also write JSON to default report location
schwab snapshot -o ./out.json
schwab snapshot --no-market
schwab report              # Export-oriented wrapper around snapshot
schwab report -o ./out.json
schwab report --no-market
```

### Advisor Sidecar Commands

The advisor loop is intentionally separate from the main `schwab` CLI. It writes only
to its own SQLite store under `./private/advisor/advisor.db` by default.

```bash
schwab-advisor status --json
schwab-advisor recommend --json
schwab-advisor feedback 12 --status followed --json
schwab-advisor note 12 "buffer constrained by RMD timing" --json
schwab-advisor evaluate --json
schwab-advisor review 12 --json
```

`recommend` stores the source snapshot provenance, raw prompt/response artifacts, and a
snapshot-backed `baseline_state_json`. `evaluate` compares the run against the first later
snapshot on or after the horizon, skips when required data is missing, and treats
explicitly ignored recommendations as `insufficient_data` rather than scoring them like
executed actions.

### Trade Commands

```bash
schwab buy acct_trading AAPL 10 --dry-run   # Preview buy
schwab sell acct_trading AAPL 10 --dry-run  # Preview sell
schwab buy acct_trading AAPL 10 --live      # Execute with --live flag
schwab sell acct_trading AAPL 10 --live     # Execute with --live flag
schwab orders acct_trading                   # Show open orders
schwab ord                                   # Alias
```

## Command Aliases

| Full Command | Alias |
|--------------|-------|
| portfolio | p |
| positions | pos |
| balance | bal |
| allocation | alloc |
| indices | idx |
| sectors | sec |
| market | mkt |
| movers | mov |
| futures | fut |
| fundamentals | fund |
| dividends | div |
| context | ctx |
| lynch | ly |
| regime | reg |
| doctor | dr |
| history | hist |
| snapshot | snap |
| orders | ord |

## Agent verification checklist

Test the installed CLI the same way a later agent will use it:

```bash
command -v schwab
schwab --help
schwab-advisor --help
schwab doctor --json
schwab history --json --limit 1
schwab snapshot --json --output ./snapshot.json
schwab-advisor status --json
schwab buy <account-alias> AAPL 1 --dry-run --json
```

## Trade Safety

**Live trading is DISABLED by default.** This is a critical safety feature.

To execute real trades, use one of these methods:

```bash
# Method 1: --live flag (per-command, recommended)
schwab sell acct_trading AAPL 10 --live

# Method 2: Environment variable (session-wide)
export SCHWAB_ALLOW_LIVE_TRADES=true
schwab sell acct_trading AAPL 10
```

Additional safeguards:
- `--dry-run` always works (preview mode)
- Live trades require typing "CONFIRM" (cannot be bypassed)
- JSON mode cannot execute live trades
- All trade attempts are logged to `~/.cli-schwab/trade_audit.log`

For automation: Use `--dry-run` only. Never enable live trading in automated environments.

## Shortest reusable prompt

```text
Use the cli-schwab workflow: run `schwab doctor --json`, then `schwab snapshot --json` or `schwab history --json` as needed, keep output narrow, and only use `--dry-run` for trades.
```

## Configuration

### Environment Variables

```bash
# Default output format (text or json)
export SCHWAB_OUTPUT=json

# Default account alias for buy/sell/orders
export SCHWAB_DEFAULT_ACCOUNT=acct_trading

# Data directory (defaults to ~/.cli-schwab)
export SCHWAB_CLI_DATA_DIR=~/.cli-schwab

# Report directory
export SCHWAB_REPORT_DIR=~/.cli-schwab/reports

# History database (defaults to ./private/history/schwab_history.db when available)
export SCHWAB_HISTORY_DB_PATH=~/.cli-schwab/history/schwab_history.db

# Optional manual accounts file for holistic household totals
export SCHWAB_MANUAL_ACCOUNTS_PATH=./private/notes/manual_accounts.json

# Optional policy profile (defaults to ./private/policy.json when present,
# otherwise falls back to config/policy.template.json)
export SCHWAB_POLICY_PATH=./private/policy.json

# Token paths (override data dir)
export SCHWAB_TOKEN_PATH=~/.cli-schwab/tokens/schwab_token.json
export SCHWAB_MARKET_TOKEN_PATH=~/.cli-schwab/tokens/schwab_market_token.json
# A local SQLite sidecar (tokens.db) is created next to the token files automatically

# Advisor sidecar
export SCHWAB_ADVISOR_DB_PATH=./private/advisor/advisor.db
export SCHWAB_ADVISOR_MODEL_COMMAND='codex exec -m gpt-5.4 --skip-git-repo-check --cd .'

# Trade safety (NEVER enable in automation)
export SCHWAB_ALLOW_LIVE_TRADES=true
```

### Account Configuration

Create `config/accounts.json` from the template:

```bash
cp config/accounts.template.json config/accounts.json
```

See [`docs/account-config.md`](docs/account-config.md) for the account config schema and field documentation.

### Optional policy profile

The public repo ships a generic `config/policy.template.json`. For real household or
portfolio-specific rules, copy it to an ignored local file and customize the
account aliases and thresholds there:

```bash
cp config/policy.template.json private/policy.json
# or set SCHWAB_POLICY_PATH to another local file
```

This keeps the repo public-safe while preserving your real local policy logic.

## JSON Response Envelope

All `--json` output follows this schema:

```json
{
  "schema_version": 1,
  "command": "portfolio",
  "timestamp": "2026-01-23T12:00:00",
  "success": true,
  "data": { ... },
  "error": null
}
```

Errors set `success: false` and populate `error`.

## History Database

`snapshot` is the primary capture path, and both `snapshot` and `report` persist
canonical snapshots to SQLite. See [`docs/history.md`](docs/history.md) for the
canonical data model, agent workflow, view definitions, and import semantics.

When running inside this repo, the history database defaults to
`./private/history/schwab_history.db`. The entire `private/` tree is gitignored,
so the database stays local and must not be committed.

The database exposes agent-friendly views:

- `portfolio_history`
- `account_history`
- `position_history`
- `market_history`

Example:

```bash
schwab query "SELECT observed_at, total_value, manual_value FROM portfolio_history ORDER BY observed_at DESC LIMIT 10"
```

Use `schwab history --import-defaults` to backfill legacy `private/snapshots/*.json`
and `private/reports/*.json` into the database.

## Architecture

See [`docs/architecture.md`](docs/architecture.md) for module boundaries and extension points.
The opt-in recommendation-learning adjunct is documented separately in
[`docs/advisor-sidecar.md`](docs/advisor-sidecar.md) so it can evolve without
changing the main CLI/history contract.

```
src/schwab_client/
├── advisor_cli.py          # Optional schwab-advisor entrypoint
├── cli/                    # Modular CLI package
│   ├── __init__.py         # Entry point, argparse, routing
│   ├── context.py          # Cached clients, trade logger
│   ├── output.py           # JSON envelope, formatters
│   └── commands/           # Command handlers
│       ├── portfolio.py    # portfolio, positions, balance, allocation
│       ├── market.py       # vix, indices, sectors, movers, etc.
│       ├── history.py      # history, query
│       ├── trade.py        # buy, sell, orders
│       ├── admin.py        # auth, doctor, accounts
│       ├── context_cmd.py  # context prompt / memo assembly
│       └── report.py       # report, snapshot
├── _advisor/               # Advisor sidecar schema + persistence
├── _client/                # Internal client mixins / shared helpers
├── _history/               # Internal history schema + normalization + store
├── auth.py                 # Portfolio API authentication
├── market_auth.py          # Market API authentication
├── history.py              # Public SQLite history API
├── snapshot.py             # Canonical snapshot collection
└── client.py               # Public SchwabClientWrapper surface

src/core/                   # Business logic and portfolio analysis helpers
├── advisor_models.py       # Typed recommendation payloads
├── advisor_prompts.py      # Structured recommendation prompts
├── advisor_scoring.py      # Deterministic outcome scoring
├── advisor_sidecar.py      # Sidecar orchestration
├── context.py              # Portfolio context assembly
├── portfolio_service.py    # Portfolio aggregation
├── market_service.py       # Market data processing
├── snapshot_service.py     # Manual-account merge + snapshot helpers
├── policy.py               # Policy evaluation and pacing alerts
├── polymarket.py           # External macro probability signals
├── prompts.py              # Brief/review/memo templates
├── lynch_service.py        # Lynch sell-signal heuristics
├── score_service.py        # Quality scoring heuristics
└── errors.py               # Custom exceptions

config/
├── accounts.schema.json    # JSON schema for accounts
├── accounts.template.json  # Account template (tracked)
├── policy.template.json    # Generic policy/profile template (tracked)
├── accounts.json           # Your config (gitignored)
└── secure_account_config.py

docs/
├── history.md              # Canonical snapshot/history/query reference
├── account-config.md       # Canonical account config reference
├── advisor-sidecar.md      # Experimental opt-in recommendation-learning sidecar
└── _solutions.md           # Append-only solved-problems log
```

## Development

```bash
# Run tests
uv run pytest tests/ -v

# Run with mock clients (no credentials needed)
uv run pytest tests/unit/ -v

# Lint and format
uv run ruff check . --fix
uv run black .
```

### Shell Completion

If `argcomplete` is installed, enable shell completion:

```bash
# Bash
eval "$(register-python-argcomplete schwab)"

# Add to ~/.bashrc for persistence
```

## Security Rules

1. Never commit `.env`, `config/accounts.json`, `tokens/`, or `private/`
2. Never hardcode account numbers or API keys
3. Refresh tokens expire after 7 days - re-run auth commands
4. Use `schwab doctor` to check configuration status
5. Trade audit logs are written to `~/.cli-schwab/trade_audit.log`

## Exit Codes

- `0` - Success
- `1` - User/configuration error
- `2` - API/HTTP error
