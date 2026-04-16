# Agent Guidelines

## Focus
- Keep the CLI as the primary interface.
- Maintain the JSON response envelope for agent consumption (`--json` output).
- Put shared portfolio logic in `src/core/portfolio_service.py`.
- Put shared market logic in `src/core/market_service.py`.
- Put portfolio context assembly in `src/core/context.py`.
- Use `PortfolioContext` from `src/core/context.py` as the canonical decision-context contract for recommendation generation and evaluation.
- Put shared context helper models in `src/core/context_models.py`.
- Put policy loading/evaluation in `src/core/policy.py`.
- Put shared JSON aliases/helpers in `src/core/json_types.py`.
- Put prompt templates in `src/core/prompts.py`.
- Put recommendation-engine orchestration in `src/core/advisor_sidecar.py` and typed recommendation helpers in `src/core/advisor_*.py`.
- Put typed snapshot/account/market models in `src/core/models.py`.
- Put snapshot merge/normalization helpers in `src/core/snapshot_service.py`.
- Put portfolio-brief orchestration in `src/core/brief_service.py` with deterministic helpers in `src/core/brief_*.py`.
- Put shared brief pipeline types in `src/core/brief_types.py`.
- Keep CLI commands in `src/schwab_client/cli/commands/`.
- Use `context.py` for client access (cached singletons).
- Use `src/schwab_client/paths.py` for path/env resolution.
- Use `src/schwab_client/history.py` for canonical SQLite persistence and query views.
- Use `src/schwab_client/_advisor/` for recommendation-store persistence only.
- Use `src/schwab_client/_client/protocols.py` for shared raw Schwab transport protocols.
- Treat `docs/history.md` as the canonical reference for historical snapshot semantics.
- Keep experimental recommendation-engine work in the separate `schwab-advisor` path documented in `docs/advisor-sidecar.md` until it proves useful enough to merge into the main CLI/history flow.

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
    ├── brief_cmd.py
    └── report.py

src/schwab_client/
├── advisor_cli.py   # Separate schwab-advisor recommendation-engine entrypoint
├── _advisor/        # Recommendation store schema + persistence
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

For recommendation-engine-only flows, add subparsers in `src/schwab_client/advisor_cli.py`
instead of extending the main `schwab` parser.

### Key Patterns

- Use `get_client()` from `context.py` - never instantiate clients directly
- Prefer passing `PortfolioContext` objects through recommendation/brief orchestration instead of introducing new ad hoc context dict shapes
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
- The recommendation-engine DB belongs under `private/advisor/` and must stay local.
- Keep the repo matching upstream; put local data/artifacts in `private/`.
- Avoid hardcoding account numbers or API keys.
- Live trading is disabled by default. Never use `--live` or `SCHWAB_ALLOW_LIVE_TRADES` in automation.
- Prefer the root auth flow: `schwab auth`, `schwab auth login --portfolio`, `schwab auth login --market`.
- For headless/SSH auth, use `schwab auth login --portfolio --manual` or `schwab auth login --market --manual`.
- `schwab auth --json` / `schwab doctor --json` perform live API probes (`get_account_numbers()` for portfolio, `get_quote("$SPX")` for market) and report `live_verified: true/false`. If a token file looks valid but the server rejects it, `valid` is overridden to `false`.
- If the dedicated market OAuth app fails with `invalid_client` / `Unauthorized`, reuse the working `SCHWAB_INTEL_*` app values for `SCHWAB_MARKET_*` in local `.env`; the market token still lives in the separate market token path.
- Trading requires **thinkorswim enablement** on schwab.com for each account.
  Without it, orders fail with "No trades are currently allowed".

## Testing

```bash
# Run all tests
uv run pytest

# Run unit tests only
uv run pytest tests/unit/

# Run lint/type gates used in CI
uv run ruff check src tests scripts/check_quality_budget.py
uv run mypy src tests
uv run python scripts/check_quality_budget.py --max-any 20 --max-broad-catches 0
```

`tests/conftest.py` now provides lightweight CLI helpers (`run_cli()`, `CLIResult`, and
`validate_envelope()`) for JSON-envelope assertions; patch command dependencies inside the
specific unit test module when you need mocked clients.

## Workflow

- Use `uv` for installs and scripts.
- Prefer targeted tests: `uv run pytest tests/unit/ -v`.
- Use command aliases for quick testing: `schwab p`, `schwab dr`, `schwab snap`, `schwab ctx`.
- Verify installed-from-any-folder behavior with `python scripts/verify_agent_cli.py --account <alias>`.
- For current portfolio analysis, run `uv run schwab snapshot --json` first.
- For agent-ready synthesis, prefer `uv run schwab context --json` after snapshot capture.
- `schwab context --json` is the canonical agent envelope; it includes `market`, `market_available`, `recent_transactions`, `manual_accounts_included`, `history`, and `errors`.
- When the full context payload is too large for the task, use `uv run schwab context --json --output <path>` and work from the returned file path instead of dumping the whole object inline.
- For the morning brief pipeline, prefer `uv run schwab brief nightly --json`, `uv run schwab brief send --json --dry-run`, `uv run schwab brief status --json`, and `uv run schwab brief show <run_id> --json`.
- Treat `brief_runs` / `brief_deliveries` in the canonical history DB as the source of truth for briefing state and delivery, not JSON filenames.
- For recommendation-engine inspection, prefer `uv run schwab-advisor status --json` or `uv run schwab-advisor review <run_id> --json`; use `recommend` / `evaluate` only when you intend to mutate the recommendation DB.
- For historical analysis, prefer `uv run schwab history ... --json` or `uv run schwab query ... --json`.
- When a task already has a stable snapshot id, prefer `uv run schwab history --snapshot-id <id> --json` or `--output <path>` instead of SQL or broad history listings.
- Treat SQLite history views as canonical. Use legacy JSON files only for backfill/import tasks.
- When reporting totals, say whether manual accounts are included and whether market data was available.
