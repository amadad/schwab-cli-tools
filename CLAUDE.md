# CLAUDE.md

schwab-cli-tools: agent-friendly Schwab CLI for portfolio analysis, market insights, and trading. Python 3.13+, managed with `uv`.

## Setup

```bash
uv sync
cp .env.example .env
cp config/accounts.template.json config/accounts.json
mkdir -p tokens private
```

## Auth

```bash
uv run schwab-auth            # Opens browser for OAuth
uv run schwab-auth --manual   # For headless/SSH (copy-paste URL flow)
uv run schwab-market-auth     # Market data API
```

The `--manual` flag prints a URL you can open on any browser (even a different machine),
then prompts you to paste the callback URL. Use this for headless servers or SSH sessions.

### thinkorswim Enablement (Required for Trading)

Each account must be **thinkorswim enabled** on schwab.com to place orders via API.
Without this, orders are rejected with "No trades are currently allowed".

1. schwab.com → Trade → Trading Platforms → Enable thinkorswim
2. Select accounts to enable (wait for "Pending Enablement" to complete)
3. Re-run `schwab-auth` to refresh token

Read-only access (positions, balances, quotes) works without this step.

Tokens default to `~/.schwab-cli-tools/tokens`. In this repo, keep tokens in
`./tokens` (gitignored) by setting `SCHWAB_CLI_DATA_DIR=.` or explicit
`SCHWAB_TOKEN_PATH` / `SCHWAB_MARKET_TOKEN_PATH`. Reports default to
`~/.schwab-cli-tools/reports`; set `SCHWAB_REPORT_DIR=./private/reports` to keep
them under `private/`. Refresh tokens expire after 7 days.

## Local Data Layout

Keep the working tree matching upstream; local artifacts live in gitignored folders:
- `config/accounts.json` (account aliases + numbers)
- `tokens/` (auth tokens when repo-local paths are configured)
- `private/` (notes, snapshots, reports, journal, reviews, market_cycle, etc.)

Recommended `.env` overrides for repo-local data:

```bash
SCHWAB_CLI_DATA_DIR=.
SCHWAB_REPORT_DIR=./private/reports
# Optional explicit token paths:
SCHWAB_TOKEN_PATH=./tokens/schwab_token.json
SCHWAB_MARKET_TOKEN_PATH=./tokens/schwab_market_token.json
```

## CLI Contract

Use `uv run schwab <command>` (or `schwab` if installed). Add `--json` for the
response envelope.

### Commands

| Command | Alias | Description |
|---------|-------|-------------|
| `portfolio [-p]` | `p` | Show portfolio summary (with positions) |
| `positions [--symbol]` | `pos` | Show positions |
| `balance` | `bal` | Show account balances |
| `allocation` | `alloc` | Analyze allocation |
| `performance` | `perf` | Show performance metrics |
| `vix` | | Show VIX data |
| `indices` | `idx` | Show market indices |
| `sectors` | `sec` | Show sector performance |
| `market` | `mkt` | Show market signals |
| `movers [--gainers\|--losers]` | `mov` | Show top gainers/losers |
| `futures` | `fut` | Show pre-market futures |
| `fundamentals SYMBOL` | `fund` | Show symbol fundamentals |
| `dividends [--days\|--upcoming]` | `div` | Show dividends |
| `auth` | | Check authentication |
| `doctor` | `dr` | Run diagnostics |
| `accounts` | | List configured accounts |
| `report [--output PATH]` | | Generate portfolio report |
| `snapshot` | `snap` | Get complete data snapshot |
| `buy [ACCOUNT] SYMBOL QTY` | | Buy shares |
| `sell [ACCOUNT] SYMBOL QTY` | | Sell shares |
| `orders [ACCOUNT]` | `ord` | Show open orders |

Default account: set `SCHWAB_DEFAULT_ACCOUNT` to omit `ACCOUNT` for buy/sell/orders.

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
- All trade attempts are logged to `~/.schwab-cli-tools/trade_audit.log`.

For clawdbot/automation: Use `--dry-run` for previews. Never use `--live` or set
`SCHWAB_ALLOW_LIVE_TRADES` in automated environments unless you have explicit approval.

### Exit Codes

- `0` success
- `1` user/config error
- `2` API/HTTP error

## Architecture

```
src/schwab_client/
├── cli/                    # CLI package (modular)
│   ├── __init__.py         # Entry point, argparse, routing
│   ├── context.py          # Cached clients, trade logger
│   ├── output.py           # JSON envelope, formatters
│   └── commands/           # Command handlers
│       ├── portfolio.py    # portfolio, positions, balance, allocation
│       ├── market.py       # vix, indices, sectors, movers, futures
│       ├── trade.py        # buy, sell, orders (unified execute_trade)
│       ├── admin.py        # auth, doctor, accounts
│       └── report.py       # report, snapshot
├── auth.py                 # Portfolio API authentication
├── market_auth.py          # Market API authentication
└── client.py               # SchwabClientWrapper

src/core/                   # Pure business logic (no I/O)
├── portfolio_service.py    # Portfolio aggregation
├── market_service.py       # Market data processing
└── errors.py               # Custom exceptions

config/
├── accounts.schema.json    # JSON schema for accounts.json
├── accounts.template.json  # Template (tracked)
├── accounts.json           # Your config (gitignored)
└── secure_account_config.py
```

### Key Design Patterns

1. **Client Caching**: `context.py` provides lazy singletons for portfolio and market
   clients. Token I/O happens once per CLI invocation.

2. **Unified Trade Execution**: `trade.py` uses a single `execute_trade()` function
   for both buy and sell, eliminating duplication.

3. **Command Aliases**: Short aliases (`p`, `dr`, `snap`) defined in `cli/__init__.py`.

4. **Centralized Output**: `output.py` handles JSON envelope, formatters, and error
   handling consistently across all commands.

## Testing

```bash
# Run all tests
uv run pytest

# Run with mock clients (no credentials needed)
uv run pytest tests/unit/

# Run specific test
uv run pytest tests/unit/test_cli.py -v
```

Mock fixtures in `conftest.py`:
- `mock_schwab_client` - mocked portfolio client
- `mock_market_client` - mocked market client
- `reset_cli_context` - reset cached clients between tests

## Critical Rules

1. Never commit `.env`, `config/accounts.json`, `tokens/`, or anything under `private/`.
2. Never hardcode account numbers or API keys.
3. Use `hashValue` from `get_account_numbers()` for API calls.
4. Use `get_client()` and `get_cached_market_client()` from `context.py` - never
   instantiate clients directly in commands.
