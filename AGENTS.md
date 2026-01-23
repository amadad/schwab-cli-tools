# Agent Guidelines

## Focus
- Keep the CLI as the primary interface.
- Maintain the JSON response envelope for agent consumption (`--json` output).
- Put shared portfolio logic in `src/core/portfolio_service.py`.
- Put shared market logic in `src/core/market_service.py`.
- Keep CLI output formatting in `src/schwab_client/cli.py`.

## Safety
- Never commit `.env`, `config/accounts.json`, or anything under `private/` or `tokens/`.
- Keep the repo matching upstream; put local data/artifacts in `private/` and account config in `config/`.
- Avoid hardcoding account numbers or API keys.

## Workflow
- Use `uv` for installs and scripts.
- Prefer targeted tests: `uv run pytest tests/ -v`.
