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
```

## Authentication

```bash
uv run schwab-auth
uv run schwab-market-auth
```

Market commands (`vix`, `indices`, `sectors`, `market`) require the market auth flow.
Tokens are stored under `~/.schwab-cli-tools/tokens` by default (override with
`SCHWAB_CLI_DATA_DIR`, `SCHWAB_TOKEN_PATH`, or `SCHWAB_MARKET_TOKEN_PATH`).

## CLI Usage

```bash
uv run schwab auth
uv run schwab portfolio
uv run schwab portfolio -p
uv run schwab positions --symbol AAPL
uv run schwab allocation
uv run schwab performance
uv run schwab vix
uv run schwab indices
uv run schwab sectors
uv run schwab market --json
uv run schwab doctor
uv run schwab balance
uv run schwab accounts
uv run schwab buy ACCOUNT SYMBOL QTY --yes
uv run schwab sell ACCOUNT SYMBOL QTY --yes
uv run schwab orders ACCOUNT
```

See `CLAUDE.md` for the CLI contract and JSON schema.

## Agent Skill

The skill template lives under `.pi/skills/schwab-cli-tools/` and is ignored by
git. Copy or install it into your user-level Pi skills directory if you want
agents to auto-load it.

## Configuration

```bash
# Default output format (text or json)
export SCHWAB_OUTPUT=json

# Default account alias for buy/sell/orders when ACCOUNT is omitted
export SCHWAB_DEFAULT_ACCOUNT=acct_trading

# Optional data directory (defaults to ~/.schwab-cli-tools)
export SCHWAB_CLI_DATA_DIR=~/.schwab-cli-tools

# Optional token paths (override data dir)
export SCHWAB_TOKEN_PATH=~/.schwab-cli-tools/tokens/schwab_token.json
export SCHWAB_MARKET_TOKEN_PATH=~/.schwab-cli-tools/tokens/schwab_market_token.json
```

## Safety

- Use `--dry-run` to preview orders without executing.
- Use `--yes` to skip confirmation.
- Use `--non-interactive` to fail if a prompt would occur.

## Repository Layout

```
src/core/           # Portfolio + market logic
src/schwab_client/  # Schwab API wrappers + CLI
config/             # Account config template + loader
CLAUDE.md           # CLI contract + agent notes
```

## Local Data

Runtime data (tokens) is stored under `~/.schwab-cli-tools/` by default. Override
with `SCHWAB_CLI_DATA_DIR`, or set explicit token paths via `SCHWAB_TOKEN_PATH` and
`SCHWAB_MARKET_TOKEN_PATH`. Use `config/accounts.template.json` to create your local
`config/accounts.json`.

## Development

```bash
uv run pytest tests/ -v
uv run ruff check . --fix
uv run black .
```

## Security Rules

- Never commit `.env` or `config/accounts.json`.
- Tokens live under `~/.schwab-cli-tools/` by default; keep them out of the repo.
- Use account hash values for API calls.
- Refresh tokens expire after 7 days.
