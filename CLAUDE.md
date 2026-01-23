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
uv run schwab-auth
uv run schwab-market-auth
```

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

**CRITICAL: Live trading is DISABLED by default.**

To execute real trades, you must explicitly enable them:

```bash
export SCHWAB_ALLOW_LIVE_TRADES=true
```

Without this, only `--dry-run` is allowed. This prevents accidental trades from
scripts, agents, or automation.

Additional safeguards:
- `--dry-run` previews without placing an order (always allowed).
- `--yes` skips interactive confirmation (still requires `SCHWAB_ALLOW_LIVE_TRADES`).
- `--non-interactive` fails if a prompt would occur.
- In JSON mode, buy/sell require `--yes` or `--dry-run`.

For clawdbot/automation: Use `--dry-run` for reports. Never set `SCHWAB_ALLOW_LIVE_TRADES`
in automated environments unless you have explicit approval workflows.

### Exit Codes

- `0` success
- `1` user/config error
- `2` API/HTTP error

## Structure

```
src/core/           # Shared portfolio + market logic
src/schwab_client/  # Schwab API wrapper + CLI
config/             # Account config (accounts.json gitignored)
tokens/             # Auth tokens (gitignored, repo-local when configured)
private/            # Local notes/snapshots/reports/etc. (gitignored)
```

## Critical Rules

1. Never commit `.env`, `config/accounts.json`, `tokens/`, or anything under `private/`.
   Repo-local tokens live in `./tokens` when configured; otherwise use `~/.schwab-cli-tools`.
2. Never hardcode account numbers or API keys.
3. Use `hashValue` from `get_account_numbers()` for API calls.
