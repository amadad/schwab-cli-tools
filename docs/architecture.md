# Architecture

High-level module boundaries for `cli-schwab`.

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
- morning-brief scorecard / analysis / rendering / orchestration helpers
- advisor-sidecar prompt/model/scoring helpers

Prefer to keep most modules here free of side effects.
`context.py` is the main exception today. The notable orchestration boundaries are
`brief_service.py` for the morning brief pipeline and `advisor_sidecar.py` for the
recommendation sidecar: both bridge snapshot/context capture, model execution, and
SQLite-backed persistence.

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

### `src/schwab_client/advisor_cli.py`
Separate opt-in CLI entrypoint for the recommendation sidecar.

Responsibilities:
- parse `schwab-advisor` subcommands
- keep recommendation-journal workflows out of the main `schwab` parser
- emit the same agent-friendly JSON envelope style as the main CLI

### `src/schwab_client/_advisor/`
Internal advisor sidecar store.

Responsibilities:
- sidecar SQLite schema
- schema migrations for experimental recommendation data
- persistence/query implementation for runs, feedback, evaluations, and notes

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
- DB-backed morning brief state (`brief_runs`, `brief_deliveries`)

Public entry point remains:
- `src/schwab_client/history.py`

### `src/schwab_client/runtime_env.py`
Explicit runtime-only environment loading.

Responsibilities:
- load shell-exported secrets for CLI entrypoints when cron shells do not provide them
- keep environment mutation out of library-module import side effects

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
- `docs/history.md`: canonical history/snapshot reference, including the DB-backed brief flow
- `docs/account-config.md`: canonical account-config reference
- `docs/advisor-sidecar.md`: experimental opt-in recommendation-learning sidecar reference
- `docs/_solutions.md`: append-only solved-problems log

## Preferred extension points

### Add a CLI command
1. Implement the handler in `src/schwab_client/cli/commands/`
2. Move reusable logic into `src/core/` or a focused integration module if needed
3. Register it in `cli/__init__.py`

### Add historical or brief-run fields
1. update canonical snapshot collection in `snapshot.py` when the snapshot shape changes
2. update normalization in `_history/normalizer.py` if imports need to support it
3. update schema or views in `_history/schema.py`
4. update persistence in `_history/store.py`
5. update `docs/history.md`

### Extend the morning brief or advisor sidecar
- **Brief flow**
  1. update deterministic helpers in `src/core/brief_*.py`
  2. keep end-to-end orchestration in `src/core/brief_service.py`
  3. update CLI wiring in `src/schwab_client/cli/commands/brief_cmd.py`
  4. update history-backed run state in `src/schwab_client/_history/`
  5. document behavior changes in `docs/history.md`
- **Advisor sidecar**
  1. update `src/core/advisor_models.py` / `advisor_prompts.py` / `advisor_scoring.py` as needed
  2. keep orchestration in `src/core/advisor_sidecar.py`
  3. update sidecar persistence in `src/schwab_client/_advisor/`
  4. document behavior changes in `docs/advisor-sidecar.md`

### Add account metadata behavior
1. update `config/accounts.template.json` if needed
2. update `config/secure_account_config.py`
3. update `docs/account-config.md`

### Change portfolio policy defaults
1. update `config/policy.template.json` for the public generic template
2. keep real household/account aliases in `private/policy.json` or `SCHWAB_POLICY_PATH`
3. update `src/core/policy.py` only when the policy schema/engine changes
