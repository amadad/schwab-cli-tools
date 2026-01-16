# CLAUDE.md

schwab-cli-tools: agent-friendly Schwab CLI for portfolio analysis, market insights, and trading. Python 3.13+, managed with `uv`.

## Setup

```bash
uv sync
cp .env.example .env
cp config/accounts.template.json config/accounts.json
```

## Auth

```bash
uv run schwab-auth
uv run schwab-market-auth
```

Tokens live under `~/.schwab-cli-tools/tokens` by default (override with
`SCHWAB_CLI_DATA_DIR`, `SCHWAB_TOKEN_PATH`, `SCHWAB_MARKET_TOKEN_PATH`). Reports
default to `~/.schwab-cli-tools/reports` (override `SCHWAB_REPORT_DIR`). Refresh
tokens expire after 7 days.

## CLI Contract

Use `uv run schwab <command>` (or `schwab` if installed). Add `--json` for the
response envelope.

### Commands

- portfolio [-p]
- positions [--symbol SYMBOL]
- balance
- allocation
- performance
- vix
- indices
- sectors
- market
- auth
- doctor
- report [--output PATH] [--no-market]
- accounts
- buy [ACCOUNT] SYMBOL QTY [--limit PRICE] [--dry-run] [--yes]
- sell [ACCOUNT] SYMBOL QTY [--limit PRICE] [--dry-run] [--yes]
- orders [ACCOUNT] [--json|--text]

Default account: set `SCHWAB_DEFAULT_ACCOUNT` to omit `ACCOUNT` for buy/sell/orders.

Report output defaults to `~/.schwab-cli-tools/reports` (override with
`--output` or `SCHWAB_REPORT_DIR`). Use `--no-market` to skip market data.

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

- `--dry-run` previews without placing an order.
- `--yes` skips confirmation prompts.
- `--non-interactive` fails if a prompt would occur.
- In JSON mode, buy/sell require `--yes` or `--dry-run`.

### Exit Codes

- `0` success
- `1` user/config error
- `2` API/HTTP error

## Structure

```
src/core/           # Shared portfolio + market logic
src/schwab_client/  # Schwab API wrapper + CLI
config/             # Account config (accounts.json gitignored)
```

## Critical Rules

1. Never commit `.env` or `config/accounts.json`. Tokens live under `~/.schwab-cli-tools/`.
2. Never hardcode account numbers or API keys.
3. Use `hashValue` from `get_account_numbers()` for API calls.
