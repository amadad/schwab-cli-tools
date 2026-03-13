# Agent Guidelines

## Focus
- Keep the CLI as the primary interface.
- Maintain the JSON response envelope for agent consumption (`--json` output).
- Put shared portfolio logic in `src/core/portfolio_service.py`.
- Put shared market logic in `src/core/market_service.py`.
- Put typed snapshot/account/market models in `src/core/models.py`.
- Put snapshot merge/normalization helpers in `src/core/snapshot_service.py`.
- Keep CLI commands in `src/schwab_client/cli/commands/`.
- Use `context.py` for client access (cached singletons).
- Use `src/schwab_client/paths.py` for path/env resolution.
- Use `src/schwab_client/history.py` for SQLite persistence and query views.
- Treat `docs/history.md` as the canonical reference for historical snapshot semantics.

## Architecture

```
src/schwab_client/cli/
├── __init__.py      # Entry point, argparse
├── context.py       # get_client(), get_cached_market_client()
├── output.py        # JSON envelope, formatters
└── commands/        # One file per command group
    ├── portfolio.py
    ├── market.py
    ├── history.py
    ├── trade.py
    ├── admin.py
    └── report.py

src/schwab_client/
├── _client/         # Internal client mixins / shared helpers
├── _history/        # Internal history schema + normalization + store
├── history.py       # Public SQLite persistence + query surface
├── paths.py         # Centralized path/env resolution
└── snapshot.py      # Canonical snapshot collection
```

### Adding a New Command

1. Add handler function to appropriate `commands/*.py` file
2. Import in `commands/__init__.py`
3. Add argparse subparser in `cli/__init__.py`
4. Add routing in `main()` function

### Key Patterns

- Use `get_client()` from `context.py` - never instantiate clients directly
- Use `handle_cli_error()` from `output.py` for consistent error handling
- Use `print_json_response()` from `output.py` for JSON output
- Use `format_header()` from `output.py` for text section headers

## Safety

- Never commit `.env`, `config/accounts.json`, or anything under `private/` or `tokens/`.
- The SQLite history database belongs under `private/history/` and must stay local.
- Keep the repo matching upstream; put local data/artifacts in `private/`.
- Avoid hardcoding account numbers or API keys.
- Live trading is disabled by default. Never use `--live` or `SCHWAB_ALLOW_LIVE_TRADES` in automation.
- For headless/SSH auth, use `schwab-auth --manual` (copy-paste URL flow).
- Trading requires **thinkorswim enablement** on schwab.com for each account.
  Without it, orders fail with "No trades are currently allowed".

## Testing

```bash
# Run all tests
uv run pytest

# Run with mock clients (no credentials needed)
uv run pytest tests/unit/

# Use mock fixtures
def test_portfolio(mock_schwab_client):
    # Client is mocked, no real API calls
    ...
```

## Workflow

- Use `uv` for installs and scripts.
- Prefer targeted tests: `uv run pytest tests/unit/ -v`.
- Use command aliases for quick testing: `schwab p`, `schwab dr`, `schwab snap`.
- For current portfolio analysis, run `uv run schwab snapshot --json` first.
- For historical analysis, prefer `uv run schwab history ... --json` or `uv run schwab query ... --json`.
- Treat SQLite history views as canonical. Use legacy JSON files only for backfill/import tasks.
- When reporting totals, say whether manual accounts are included and whether market data was available.
