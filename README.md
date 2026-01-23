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
uv run schwab-auth          # Portfolio API
uv run schwab-market-auth   # Market data API
```

Market commands (`vix`, `indices`, `sectors`, `market`, `movers`, `futures`) require
the market auth flow. Tokens are stored under `~/.schwab-cli-tools/tokens` by default.

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
schwab performance         # Performance metrics
schwab perf                # Alias
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
schwab fundamentals AAPL   # Symbol fundamentals
schwab fund AAPL           # Alias
schwab dividends           # Recent dividends
schwab div --upcoming      # Upcoming ex-dates
```

### Admin Commands

```bash
schwab auth                # Check authentication status
schwab doctor              # Run diagnostics
schwab dr                  # Alias
schwab accounts            # List configured accounts
```

### Report Commands

```bash
schwab report              # Generate portfolio report
schwab report -o ./out.json
schwab report --no-market  # Skip market data
schwab snapshot            # Complete data snapshot
schwab snap --json         # For automation (alias)
```

### Trade Commands

```bash
schwab buy ACCOUNT AAPL 10 --dry-run    # Preview buy
schwab sell ACCOUNT AAPL 10 --dry-run   # Preview sell
schwab orders ACCOUNT                    # Show open orders
schwab ord                               # Alias
```

## Command Aliases

| Full Command | Alias |
|--------------|-------|
| portfolio | p |
| positions | pos |
| balance | bal |
| allocation | alloc |
| performance | perf |
| indices | idx |
| sectors | sec |
| market | mkt |
| movers | mov |
| futures | fut |
| fundamentals | fund |
| dividends | div |
| doctor | dr |
| snapshot | snap |
| orders | ord |

## Trade Safety

**Live trading is DISABLED by default.** This is a critical safety feature.

```bash
# Enable live trading (required for real orders)
export SCHWAB_ALLOW_LIVE_TRADES=true
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

# Token paths (override data dir)
export SCHWAB_TOKEN_PATH=~/.schwab-cli-tools/tokens/schwab_token.json
export SCHWAB_MARKET_TOKEN_PATH=~/.schwab-cli-tools/tokens/schwab_market_token.json

# Trade safety (NEVER enable in automation)
export SCHWAB_ALLOW_LIVE_TRADES=true
```

### Account Configuration

Create `config/accounts.json` from the template:

```bash
cp config/accounts.template.json config/accounts.json
```

See `config/CLAUDE.md` for the JSON schema and field documentation.

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

## Architecture

```
src/schwab_client/
├── cli/                    # Modular CLI package
│   ├── __init__.py         # Entry point, argparse, routing
│   ├── context.py          # Cached clients, trade logger
│   ├── output.py           # JSON envelope, formatters
│   └── commands/           # Command handlers
│       ├── portfolio.py    # portfolio, positions, balance, allocation
│       ├── market.py       # vix, indices, sectors, movers, etc.
│       ├── trade.py        # buy, sell, orders
│       ├── admin.py        # auth, doctor, accounts
│       └── report.py       # report, snapshot
├── auth.py                 # Portfolio API authentication
├── market_auth.py          # Market API authentication
└── client.py               # SchwabClientWrapper

src/core/                   # Pure business logic
├── portfolio_service.py    # Portfolio aggregation
├── market_service.py       # Market data processing
└── errors.py               # Custom exceptions

config/
├── accounts.schema.json    # JSON schema for accounts
├── accounts.template.json  # Template (tracked)
├── accounts.json           # Your config (gitignored)
└── secure_account_config.py
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
