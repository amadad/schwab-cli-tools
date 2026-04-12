# Agent Guidelines

## Focus
- Keep the CLI as the primary interface.
- Maintain the JSON response envelope for agent consumption (`--json` output).
- Put shared portfolio logic in `src/core/portfolio_service.py`.
- Put shared market logic in `src/core/market_service.py`.
- Put portfolio context assembly in `src/core/context.py`.
- Put policy loading/evaluation in `src/core/policy.py`.
- Put prompt templates in `src/core/prompts.py`.
- Put advisor-sidecar orchestration in `src/core/advisor_sidecar.py` and typed recommendation helpers in `src/core/advisor_*.py`.
- Put typed snapshot/account/market models in `src/core/models.py`.
- Put snapshot merge/normalization helpers in `src/core/snapshot_service.py`.
- Keep CLI commands in `src/schwab_client/cli/commands/`.
- Use `context.py` for client access (cached singletons).
- Use `src/schwab_client/paths.py` for path/env resolution.
- Use `src/schwab_client/history.py` for canonical SQLite persistence and query views.
- Use `src/schwab_client/_advisor/` for advisor-sidecar persistence only.
- Treat `docs/history.md` as the canonical reference for historical snapshot semantics.
- Keep experimental recommendation-learning work in the separate `schwab-advisor` sidecar path documented in `docs/advisor-sidecar.md` until it proves useful enough to merge into the main CLI/history flow.

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
    ├── context_cmd.py
    └── report.py

src/schwab_client/
├── advisor_cli.py   # Separate schwab-advisor entrypoint
├── _advisor/        # Advisor schema + persistence
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

For sidecar-only recommendation flows, add subparsers in `src/schwab_client/advisor_cli.py`
instead of extending the main `schwab` parser.

### Key Patterns

- Use `get_client()` from `context.py` - never instantiate clients directly
- Use `handle_cli_error()` from `output.py` for consistent error handling
- Use `print_json_response()` from `output.py` for JSON output
- Use `format_header()` from `output.py` for text section headers
- Keep public policy defaults in `config/policy.template.json`; use `private/policy.json`
  or `SCHWAB_POLICY_PATH` for local aliases and thresholds
- Reuse the managed token storage in `auth.py` / `market_auth.py`; token JSON files
  are paired with a local SQLite `tokens.db` sidecar for locking and metadata

## Safety

- Never commit `.env`, `config/accounts.json`, `private/policy.json`, or anything under `private/` or `tokens/`.
- The SQLite history database belongs under `private/history/` and must stay local.
- The advisor sidecar DB belongs under `private/advisor/` and must stay local.
- Keep the repo matching upstream; put local data/artifacts in `private/`.
- Avoid hardcoding account numbers or API keys.
- Live trading is disabled by default. Never use `--live` or `SCHWAB_ALLOW_LIVE_TRADES` in automation.
- Prefer the root auth flow: `schwab auth`, `schwab auth login --portfolio`, `schwab auth login --market`.
- For headless/SSH auth, use `schwab auth login --portfolio --manual` or `schwab auth login --market --manual`.
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
- Use command aliases for quick testing: `schwab p`, `schwab dr`, `schwab snap`, `schwab ctx`.
- Verify installed-from-any-folder behavior with `python scripts/verify_agent_cli.py --account <alias>`.
- For current portfolio analysis, run `uv run schwab snapshot --json` first.
- For agent-ready synthesis, prefer `uv run schwab context --json` after snapshot capture.
- `schwab context --json` is the canonical agent envelope; it includes `market`, `market_available`, `recent_transactions`, `manual_accounts_included`, `history`, and `errors`.
- When the full context payload is too large for the task, use `uv run schwab context --json --output <path>` and work from the returned file path instead of dumping the whole object inline.
- For advisor-sidecar inspection, prefer `uv run schwab-advisor status --json` or `uv run schwab-advisor review <run_id> --json`; use `recommend` / `evaluate` only when you intend to mutate the sidecar DB.
- For historical analysis, prefer `uv run schwab history ... --json` or `uv run schwab query ... --json`.
- When a task already has a stable snapshot id, prefer `uv run schwab history --snapshot-id <id> --json` or `--output <path>` instead of SQL or broad history listings.
- Treat SQLite history views as canonical. Use legacy JSON files only for backfill/import tasks.
- When reporting totals, say whether manual accounts are included and whether market data was available.
