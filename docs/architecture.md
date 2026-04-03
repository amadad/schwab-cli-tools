# Architecture

High-level module boundaries for `schwab-cli-tools`.

## Guiding principle

Keep the CLI thin and push reusable logic into focused modules.

## Layers

### `src/core/`
Business logic and analysis assembly.

Put here:
- portfolio aggregation
- market signal calculations
- snapshot merge helpers
- policy / scoring heuristics
- policy profile loading from public templates or ignored local files
- context assembly for agent-facing analysis

Prefer to keep most modules here free of side effects.
`context.py` is the main exception today: it orchestrates wrapper calls,
optional market inputs, and config-backed account metadata into one
agent-friendly analysis object.

Avoid putting here:
- CLI printing
- ad hoc filesystem writes
- environment/config loading spread across many modules
- duplicated API orchestration when one focused assembler will do

### `src/schwab_client/cli/`
Command-line interface.

Responsibilities:
- parse args
- call the appropriate service or wrapper
- format text output
- emit JSON envelopes
- map errors to CLI exit behavior

### `src/schwab_client/_client/`
Internal client mixins and shared wrapper helpers.

Responsibilities:
- account and quote accessors
- order entry and order-management helpers
- public wrapper implementation details for `SchwabClientWrapper`

Public entry point remains:
- `src/schwab_client/client.py`

### `src/schwab_client/_history/`
Internal history subsystem.

Responsibilities:
- SQLite schema
- document normalization
- import/backfill logic
- persistence/query implementation

Public entry point remains:
- `src/schwab_client/history.py`

### `src/schwab_client/paths.py`
Centralized path and env-var resolution.

Responsibilities:
- history DB path
- report/export paths
- manual accounts path
- default import roots

### `src/schwab_client/snapshot.py`
Snapshot orchestration.

Responsibilities:
- collect current portfolio state
- merge manual accounts
- collect market context
- sanitize account identifiers
- produce the canonical snapshot document

The CLI should treat `snapshot` as the primary capture path; `report` is the
export-oriented wrapper that writes the same canonical snapshot JSON to disk.

## Docs layering

- `AGENTS.md`: agent workflow and operating rules
- `README.md`: overview and quickstart
- `CLAUDE.md`: runtime/local operator notes
- `docs/history.md`: canonical history/snapshot reference
- `docs/account-config.md`: canonical account-config reference
- `docs/advisor-sidecar.md`: proposed opt-in recommendation-learning sidecar plan

## Preferred extension points

### Add a CLI command
1. Implement the handler in `src/schwab_client/cli/commands/`
2. Move reusable logic into `src/core/` or a focused integration module if needed
3. Register it in `cli/__init__.py`

### Add historical fields
1. update canonical snapshot collection in `snapshot.py`
2. update normalization in `_history/normalizer.py` if imports need to support it
3. update schema or views in `_history/schema.py`
4. update persistence in `_history/store.py`
5. update `docs/history.md`

### Add account metadata behavior
1. update `config/accounts.template.json` if needed
2. update `config/secure_account_config.py`
3. update `docs/account-config.md`

### Change portfolio policy defaults
1. update `config/policy.template.json` for the public generic template
2. keep real household/account aliases in `private/policy.json` or `SCHWAB_POLICY_PATH`
3. update `src/core/policy.py` only when the policy schema/engine changes
