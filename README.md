# schwab-cli-tools

Agent-friendly Schwab CLI tools for portfolio analysis, market insights, and trading.

## Disclaimer

This project is built on the open-source `schwab-py` client and is **not**
affiliated with, endorsed by, or supported by Charles Schwab & Co. Use it at
your own risk and ensure you comply with Schwab's terms and API policies.

## Quick Start

```bash
git clone https://github.com/amadad/schwab-cli-tools.git
cd schwab-cli-tools
uv sync
cp .env.example .env
cp config/accounts.template.json config/accounts.json
mkdir -p tokens private
```

## Authentication

```bash
uv run schwab-auth               # Portfolio API (opens browser)
uv run schwab-auth --manual      # For headless/remote machines (copy-paste flow)
uv run schwab-market-auth        # Market data API (opens browser)
uv run schwab-market-auth --manual  # For headless/remote machines (copy-paste flow)
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
the market auth flow. Token JSON files are stored under `~/.schwab-cli-tools/tokens`
by default, with a sibling SQLite `tokens.db` sidecar used for local locking and
cached token metadata. Refresh tokens expire after 7 days.

## CLI Commands

All commands support `--json` for machine-readable output.

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
```

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
- All trade attempts are logged to `~/.schwab-cli-tools/trade_audit.log`

For automation: Use `--dry-run` only. Never enable live trading in automated environments.

## Configuration

### Environment Variables

```bash
# Default output format (text or json)
export SCHWAB_OUTPUT=json

# Default account alias for buy/sell/orders
export SCHWAB_DEFAULT_ACCOUNT=acct_trading

# Data directory (defaults to ~/.schwab-cli-tools)
export SCHWAB_CLI_DATA_DIR=~/.schwab-cli-tools

# Report directory
export SCHWAB_REPORT_DIR=~/.schwab-cli-tools/reports

# History database (defaults to ./private/history/schwab_history.db when available)
export SCHWAB_HISTORY_DB_PATH=~/.schwab-cli-tools/history/schwab_history.db

# Optional manual accounts file for holistic household totals
export SCHWAB_MANUAL_ACCOUNTS_PATH=./private/notes/manual_accounts.json

# Optional policy profile (defaults to ./private/policy.json when present,
# otherwise falls back to config/policy.template.json)
export SCHWAB_POLICY_PATH=./private/policy.json

# Token paths (override data dir)
export SCHWAB_TOKEN_PATH=~/.schwab-cli-tools/tokens/schwab_token.json
export SCHWAB_MARKET_TOKEN_PATH=~/.schwab-cli-tools/tokens/schwab_market_token.json
# A local SQLite sidecar (tokens.db) is created next to the token files automatically

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

```
src/schwab_client/
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
├── _client/                # Internal client mixins / shared helpers
├── _history/               # Internal history schema + normalization + store
├── auth.py                 # Portfolio API authentication
├── market_auth.py          # Market API authentication
├── history.py              # Public SQLite history API
├── snapshot.py             # Canonical snapshot collection
└── client.py               # Public SchwabClientWrapper surface

src/core/                   # Business logic and portfolio analysis helpers
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
└── account-config.md       # Canonical account config reference
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
5. Trade audit logs are written to `~/.schwab-cli-tools/trade_audit.log`

## Exit Codes

- `0` - Success
- `1` - User/configuration error
- `2` - API/HTTP error
