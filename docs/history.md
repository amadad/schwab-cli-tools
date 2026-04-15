# History and snapshots

Canonical reference for the historical portfolio subsystem.

## Purpose

`cli-schwab` now treats **SQLite history** as the canonical store for time-series
portfolio and market context.

Use cases:
- current portfolio + market capture for agents
- historical comparison across snapshots
- SQL queries over positions, accounts, cash, and market context
- backfilling older JSON artifacts into one queryable store

JSON is still useful as:
- CLI output (`--json`)
- saved report artifacts
- raw import/backfill input

But for historical analysis, prefer the SQLite views described below.

## Canonical workflow

### Capture a fresh snapshot

```bash
uv run schwab snapshot --json
```

This:
- collects current API portfolio state
- merges manual accounts if configured
- collects market context if market auth is available
- persists the snapshot to SQLite
- returns the canonical snapshot JSON envelope

### Save a snapshot artifact

```bash
uv run schwab snapshot --output
uv run schwab snapshot --output ./private/reports/custom-report.json
```

This writes the same canonical snapshot JSON artifact and also persists it to SQLite.
When no path is provided, the default report location is used.

`report` remains available as the export-oriented wrapper:

```bash
uv run schwab report
uv run schwab report -o ./private/reports/custom-report.json
```

### Query history through the CLI

```bash
uv run schwab history
uv run schwab history --dataset portfolio --limit 10
uv run schwab history --dataset positions --symbol AAPL
uv run schwab history --dataset market
```

### Portfolio brief workflow

```bash
uv run schwab brief nightly --json
uv run schwab brief send --json --dry-run
uv run schwab brief status --json
uv run schwab brief show 12 --json
```

The brief pipeline stores its own run state in the same canonical history DB via
`brief_runs` and `brief_deliveries`, keyed to `snapshot_runs.id`. That makes the
briefing flow reproducible from one frozen snapshot/context/scorecard set instead of
matching separate JSON artifacts by date.

### Read or export one exact snapshot

```bash
uv run schwab history --snapshot-id 50 --json
uv run schwab history --snapshot-id 50 --output ./private/reports/snapshot-50.json --json
```

Use `--snapshot-id` when an agent already has a stable snapshot id from discovery and
needs the full canonical payload or a file export for a large response.

### Query history through SQL

```bash
uv run schwab query "SELECT observed_at, total_value FROM portfolio_history ORDER BY observed_at DESC LIMIT 10"
```

### Backfill legacy JSON

```bash
uv run schwab history --import-defaults
uv run schwab history --import ./private/snapshots
uv run schwab history --import ./private/reports
```

## Canonical snapshot shape

High-level shape:

```json
{
  "generated_at": "2026-03-13T09:47:06.310626",
  "portfolio": {
    "summary": {},
    "api_accounts": [],
    "manual_accounts": {
      "source_path": null,
      "last_updated": null,
      "accounts": [],
      "summary": {}
    },
    "positions": [],
    "allocation": {}
  },
  "market": {
    "signals": {},
    "vix": {},
    "indices": {},
    "sectors": {}
  },
  "errors": [],
  "history": {
    "snapshot_id": 11,
    "db_path": "./private/history/schwab_history.db"
  }
}
```

### `portfolio.summary`

Important fields:
- `total_value`: combined API + manual value
- `api_value`: value from Schwab API accounts
- `manual_value`: value from manual accounts file
- `total_cash`: combined API cash + manual cash-category accounts
- `manual_cash`: cash contributed by manual accounts in the `cash` category
- `total_invested`: total value minus total cash
- `cash_percentage`: cash / total value
- `account_count`: API + manual accounts
- `api_account_count`
- `manual_account_count`
- `position_count`: API position count only
- `total_unrealized_pl`: API unrealized P/L only

### `portfolio.api_accounts`

One normalized account snapshot per Schwab API account.

Contains:
- account label / alias / masked last4
- total value
- cash balance
- money market value
- total cash
- invested value
- buying power
- position count
- normalized positions

### `portfolio.manual_accounts`

Manual accounts are account-level only. They do **not** imply full position detail.

Fields:
- `source_path`
- `last_updated`
- `accounts`: original manual account entries
- `summary`: account-level totals by category

### `portfolio.positions`

Normalized API positions across all accounts.

Contains:
- symbol
- asset type
- account label / alias / masked last4
- quantity
- market value
- average price
- cost basis
- unrealized P/L
- day P/L when available
- portfolio weight
- `is_money_market`

### `market`

`market` may be `null` if market auth is unavailable.

When present:
- `signals`: aggregate recommendation and high-level interpretation
- `vix`: current VIX state
- `indices`: major index quotes
- `sectors`: sector rotation snapshot

### `errors`

Per-component collection failures, for example:

```json
[
  {"component": "market", "message": "Market API not configured: ..."}
]
```

## SQLite database

Default path when running inside the repo:

```text
./private/history/schwab_history.db
```

Override with:

```bash
export SCHWAB_HISTORY_DB_PATH=./private/history/schwab_history.db
```

## Agent-facing views

These are the preferred historical query surfaces.

### `portfolio_history`

One row per snapshot run.

Columns include:
- `snapshot_id`
- `observed_at`
- `source_command`
- `source_path`
- `total_value`
- `api_value`
- `manual_value`
- `total_cash`
- `manual_cash`
- `total_invested`
- `cash_percentage`
- `account_count`
- `position_count`
- `error_count`

### `account_history`

One row per account per snapshot.

Columns include:
- `snapshot_id`
- `observed_at`
- `account_key`
- `account_source`
- `account_alias`
- `account_label`
- `account_type`
- `tax_status`
- `category`
- `provider`
- `total_value`
- `total_cash`
- `invested_value`
- `position_count`

### `position_history`

One row per account/symbol per snapshot.

Columns include:
- `snapshot_id`
- `observed_at`
- `account_key`
- `account_alias`
- `account_label`
- `account_source`
- `symbol`
- `asset_type`
- `quantity`
- `market_value`
- `average_price`
- `cost_basis`
- `unrealized_pl`
- `day_pl`
- `day_pl_pct`
- `weight_pct`
- `is_money_market`

### `market_history`

One row per snapshot with market context.

Columns include:
- `snapshot_id`
- `observed_at`
- `overall`
- `recommendation`
- `market_sentiment`
- `sector_rotation`
- `vix_value`
- `vix_signal`

## Agent operating guidance

When an agent is asked for portfolio or market analysis:

1. Capture current state first:
   ```bash
   uv run schwab snapshot --json
   ```
2. Query history with `schwab history ... --json` for common paths.
3. Use `schwab query ... --json` when the question is naturally SQL-shaped.
4. Prefer SQLite views over direct reads of `private/snapshots/*.json` or `private/reports/*.json`.
5. Explicitly say whether totals include manual accounts.
6. Explicitly say whether market data was available.

## Caveats

### Legacy imports are heterogeneous

Older files were not all produced from the same canonical model.

Examples:
- legacy snapshots included `api_accounts` + `manual_accounts`
- some saved reports were API-only
- market sections may be partial or absent

The importer normalizes these as best it can, but imported history can still reflect
those original differences.

### Manual accounts are not holdings-level data

Manual accounts contribute household/account totals. They do not create synthetic
positions.

### Market data can be partial

If market auth is missing or an upstream call fails, the snapshot can still succeed with
portfolio data and a populated `errors` section.

## Useful examples

### Portfolio totals over time

```bash
uv run schwab query "SELECT observed_at, total_value, api_value, manual_value, total_cash FROM portfolio_history ORDER BY observed_at DESC LIMIT 20"
```

### A single symbol through time

```bash
uv run schwab query "SELECT observed_at, account_label, quantity, market_value, weight_pct FROM position_history WHERE symbol = 'AAPL' ORDER BY observed_at DESC LIMIT 20"
```

### Latest top holdings

```bash
uv run schwab query "SELECT symbol, account_label, market_value FROM position_history WHERE snapshot_id = (SELECT MAX(snapshot_id) FROM position_history) ORDER BY market_value DESC LIMIT 25"
```

### Market context over time

```bash
uv run schwab query "SELECT observed_at, overall, market_sentiment, sector_rotation, vix_value FROM market_history ORDER BY observed_at DESC LIMIT 20"
```
