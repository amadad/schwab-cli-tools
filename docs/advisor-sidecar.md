# Recommendation Engine Plan

Status: implemented, experimental

This document defines the **recommendation engine** for `cli-schwab`.
The file path remains `docs/advisor-sidecar.md` for continuity, but the architecture
is better understood as a recommendation/evaluation layer built downstream of the
portfolio rail, market rail, canonical state, and decision-signal pipeline.

Operationally, the engine still runs through the separate `schwab-advisor` CLI and its
own SQLite store so experimentation stays isolated from the main `schwab` CLI/history
contract.

## Current status

Implemented today:

- separate `schwab-advisor` entrypoint
- dedicated SQLite store at `./private/advisor/advisor.db`
- in-process snapshot/context/history capture from the canonical services (no `uv run schwab ...` shell-out for snapshot/context/history reads)
- `PortfolioContext` is now the internal decision-context contract for recommendation generation
- structured recommendation capture with raw prompt/response artifacts
- operator feedback and freeform notes
- deterministic policy-health evaluation against later snapshots
- snapshot-backed provenance via `source_snapshot_id`, `source_history_db_path`, and `baseline_state_json`
- open-issue reuse keyed by `issue_key`, plus `novelty_hash` / `why_now_class` metadata so unchanged recommendations do not keep reopening the same episode

Still intentionally unfinished:

- aggregate learning views / leaderboards
- retrospective narrative generation
- prompt optimization or autoresearch on recommendation prompts

## Objective

Build a compounding household-investment learning loop that:

1. reads canonical state assembled from the portfolio rail and market rail
2. applies constraints and signals (policy, pacing, regime, macro, heuristics)
3. generates a structured recommendation
4. records what was recommended
5. records whether the operator followed it
6. evaluates whether the recommendation improved the portfolio situation
7. learns from accumulated recommendation episodes over time

## Architecture model

The repo-level model for this engine is:

1. **Portfolio rail** — Schwab portfolio truth: balances, positions, transactions,
   and account metadata.
2. **Market rail** — Schwab market truth: quotes, VIX, indices, sectors, price
   history, options/IV, and market hours.
3. **Canonical state** — normalized snapshot/context/history artifacts that combine
   the two rails with local config and manual-account data.
4. **Constraints** — policy, pacing rules, cash targets, manual-account inclusion,
   and calendar obligations.
5. **Signals** — regime, Polymarket, heuristics such as Lynch, and future macro inputs.
6. **Recommendation engine** — structured recommendation generation from canonical
   decision context (`PortfolioContext` today).
7. **Evaluation loop** — feedback, later-snapshot comparison, scoring, and review.

In other words: this is not merely a "sidecar" bolted onto the CLI. It is the
recommendation and evaluation layer for the broader portfolio-intelligence system.

## Why it is still operationally isolated instead of folded into the main CLI

The existing repo already has stable, valuable workflows for:

- `snapshot`
- `context`
- `history`
- market diagnostics
- dry-run trading

Those should remain stable.

The recommendation-learning loop is still experimental and should be treated as an
**opt-in, operationally isolated recommendation engine** until it proves useful.

## Guardrails

V1 guardrails:

- Do **not** change current `schwab` command behavior.
- Do **not** change existing snapshot semantics.
- Do **not** change existing history semantics.
- Do **not** move current prompt/policy/context workflows.
- Do **not** place live trading or order execution in the recommendation engine.
- Do **not** optimize prompts with autoresearch until enough real episodes exist.

The recommendation engine may **read** from the current repo systems, but should write
only to its own storage in V1.

---

# V1 product shape

## Core concept: recommendation episode

The primary unit is **not** a symbol thesis.

The primary unit is a **recommendation episode** tied to a specific snapshot and context.

Examples:

- Deploy $50,000 from Mom inherited IRA over 4 weeks into broad index exposure.
- Raise Dad inherited IRA cash buffer before deploying new capital.
- Leave Index and Business buckets alone this week.
- Pace inherited IRA deployment slower because VIX is elevated and regime is risk-off.

This fits the repo better than a generic single-name thesis journal.

## V1 commands

The recommendation engine is currently exposed through a separate CLI entrypoint:

```bash
uv run schwab-advisor recommend --json
uv run schwab-advisor feedback 12 --status followed --json
uv run schwab-advisor note 12 "buffer constrained by RMD timing" --json
uv run schwab-advisor evaluate --json
uv run schwab-advisor status --json
uv run schwab-advisor review 12 --json
```

Current commands: `recommend`, `feedback`, `note`, `evaluate`, `status`, and `review`.

The main `schwab brief nightly` flow now calls the recommendation engine from the same
frozen snapshot/context payload used by the morning brief, then records the linked
`advisor_run_id` on the brief run. That keeps the brief and recommendation layers
aligned on one source snapshot while preserving separate storage.

## V1 non-goals

Explicitly out of scope for V1:

- stock universe scanning
- free-form signal pattern naming as the primary feature
- LLM-generated pattern extraction without real data backing it
- trade execution
- replacing the current `context` / `snapshot` / `history` workflows
- merging recommendation storage into the canonical history DB before the model proves useful

---

# Architecture

## Recommendation CLI

The recommendation engine currently ships as a separate script entrypoint:

```toml
[project.scripts]
schwab-advisor = "src.schwab_client.advisor_cli:main"
```

This keeps the main `schwab` parser untouched while the engine remains experimental.

## Current file layout

```text
src/schwab_client/
├── advisor_cli.py                # separate CLI entrypoint: schwab-advisor
├── _advisor/
│   ├── __init__.py
│   ├── schema.py                 # recommendation-store schema
│   └── store.py                  # recommendation persistence/query API
src/core/
├── advisor_models.py             # recommendation payload models
├── advisor_prompts.py            # structured recommendation prompts
├── advisor_scoring.py            # deterministic outcome scoring
└── advisor_sidecar.py            # recommendation-engine orchestration (legacy filename)

docs/
└── advisor-sidecar.md            # this file (legacy filename)

tests/unit/
├── test_advisor_store.py
├── test_advisor_service.py
├── test_advisor_scoring.py
└── test_advisor_cli.py
```

## Read-only inputs from the current system

The recommendation engine should consume, not replace:

- canonical snapshot capture
- SQLite history data
- `PortfolioContext`
- `PolicyDelta`
- existing market + portfolio models where useful

### Required provenance on every recommendation run

Every run should record:

- `source_snapshot_id`
- `source_history_db_path`
- `assembled_at`
- whether manual accounts were included
- whether market data was available
- the model command and raw prompt used

---

# Storage

## Recommendation database

Use a dedicated DB for V1.

Default path:

```text
./private/advisor/advisor.db
```

Override with:

```bash
export SCHWAB_ADVISOR_DB_PATH=./private/advisor/advisor.db
```

This keeps the recommendation engine isolated from the canonical history store.

## Tables

### `recommendation_runs`

One row per recommendation episode.

Current fields include:

- `id`, `created_at`, `assembled_at`
- `source_snapshot_id`, `source_history_db_path`
- `recommendation_type`, `thesis`, `rationale`
- `target_type`, `target_id`, `direction`, `horizon_days`
- `benchmark_symbol`, `baseline_price`
- `baseline_state_json`
- `market_regime`, `vix_value`, `confidence`, `tags_json`
- `raw_prompt`, `raw_response`, `parsed_response_json`
- `market_available`, `manual_accounts_included`
- `model_command`
- `status` (`open|evaluated` today)

### `recommendation_feedback`

Operator feedback on whether the recommendation was followed.

Fields:

- `id`
- `run_id`
- `recorded_at`
- `status` (`followed|partially_followed|ignored|unknown`)
- `notes`

### `recommendation_evaluations`

Evaluation result for a run.

Current fields include:

- `id`, `run_id`, `evaluated_at`
- `evaluation_snapshot_id`
- `horizon_days`
- `price_then`, `price_now`, `benchmark_then`, `benchmark_now`
- `absolute_return`, `benchmark_return`, `excess_return`
- `policy_score_before`, `policy_score_after`, `delta_score`
- `feedback_status`
- `outcome` (`improved|neutral|worsened|insufficient_data`)
- `notes`

### `recommendation_notes`

Freeform lessons or operator notes attached to a run.

Fields:

- `id`
- `run_id`
- `created_at`
- `note_type`
- `body`

Action-specific tables and aggregate leaderboards are intentionally deferred until the
recommendation-episode model proves useful.

---

# Structured output contract

Recommendations must be machine-readable.

## JSON shape

`schwab-advisor recommend` expects a single normalized recommendation object:

```json
{
  "thesis": "Deploy excess inherited-IRA cash into broad index exposure over the next month.",
  "rationale": "Cash is above target, policy health is being dragged down by idle cash, and regime is risk_off rather than panic.",
  "recommendation_type": "portfolio",
  "target_type": "account",
  "target_id": "acct_inherited_ira",
  "direction": "deploy",
  "horizon_days": 30,
  "benchmark_symbol": "SPY",
  "confidence": 0.74,
  "tags": ["cash", "policy", "deployment"]
}
```

## Required fields

- `thesis`
- `rationale`
- `recommendation_type`
- `target_type`
- `target_id`
- `direction`
- `horizon_days`

`benchmark_symbol`, `confidence`, and `tags` are optional.

Malformed or incomplete model output is rejected instead of being silently defaulted.

---

# Evaluation philosophy

The evaluator should be mostly deterministic.

This repo is strongest when:

- calculations are done in code
- prompts interpret deterministic results
- outputs are structured for later measurement

The recommendation engine should follow the same pattern.

## Do not evaluate only on price movement

This repo’s goals are broader than stock picking.

A recommendation can succeed by:

- reducing inherited IRA distribution risk
- moving cash closer to policy targets
- improving household portfolio alignment
- avoiding bad deployment in a bad regime

## Deterministic score: policy health / portfolio health

Create a compact recommendation-evaluation scoring module that measures health before and after.

Suggested components:

- critical alert count
- warning alert count
- inherited IRA pacing gap
- cash distance from target bands
- optional later: concentration / drift penalties

## Action-specific evaluation

### `deploy_cash`

Success signals:

- cash moved toward target band
- no new critical alert created
- deployment did not obviously worsen the portfolio state

### `distribute`

Success signals:

- pacing gap decreased
- annual-floor risk improved
- deadline pressure reduced

### `rebalance`

Success signals:

- drift or concentration improved
- no deterioration in policy health

### `hold`

Success signals:

- avoided unnecessary churn
- key risk metrics did not worsen materially

### `buy` / `sell`

Optional later:

- relative return vs benchmark over horizon
- only as a supplement, not the sole metric

---

# Workflow

## Step 1: capture current state

```bash
uv run schwab snapshot --json
```

## Step 2: generate recommendation

```bash
uv run schwab-advisor recommend --json
```

This command currently:

- captures a fresh canonical snapshot via `schwab snapshot --json`
- layers in context-only inputs such as regime, Polymarket, Lynch, YTD distributions, and recent transactions
- generates a structured recommendation
- persists the run plus raw prompt/response artifacts in the recommendation DB

The stored `baseline_state_json` is rebuilt from the captured source snapshot so the
recorded baseline matches `source_snapshot_id`.

## Step 3: record operator feedback

```bash
uv run schwab-advisor feedback 12 --status followed --json
```

## Step 4: evaluate later

```bash
uv run schwab-advisor evaluate --json
```

This compares the original run with the first later snapshot on or after the recommendation horizon and computes a deterministic outcome.

It skips evaluation when no later snapshot exists or when required distribution-history
inputs are missing. Recommendations explicitly marked `ignored` are recorded as
`insufficient_data` rather than scored like executed actions.

## Step 5: inspect results

```bash
uv run schwab-advisor status --json
uv run schwab-advisor review 12 --json
```

---

# Implementation status and roadmap

## Completed

- [x] Add `docs/advisor-sidecar.md`
- [x] Add `schwab-advisor` CLI entrypoint in `pyproject.toml`
- [x] Add `src/schwab_client/advisor_cli.py`
- [x] Add `SCHWAB_ADVISOR_DB_PATH` resolution
- [x] Add recommendation-store DB schema in `src/schwab_client/_advisor/schema.py`
- [x] Add recommendation store in `src/schwab_client/_advisor/store.py`
- [x] Add `src/core/advisor_models.py`
- [x] Add `src/core/advisor_prompts.py`
- [x] Add `src/core/advisor_sidecar.py`
- [x] Implement read-only bridge from snapshot/history/context/policy
- [x] Implement recommendation generation + persistence
- [x] Add `schwab-advisor recommend`
- [x] Add `schwab-advisor feedback RUN_ID`
- [x] Add `src/core/advisor_scoring.py`
- [x] Implement deterministic before/after health scoring
- [x] Implement outcome evaluator
- [x] Add `schwab-advisor evaluate`
- [x] Add `schwab-advisor status`
- [x] Add `schwab-advisor review RUN_ID`
- [x] Add tests for models/store/service/CLI recommend flow
- [x] Add tests for followed / ignored / insufficient-data paths
- [x] Add tests for empty and populated status/review states

## Current behavior guarantees

- `uv run schwab-advisor --help` works
- recommendation DB initializes in `./private/advisor/advisor.db`
- existing `schwab` commands remain unchanged
- each run stores snapshot provenance and raw model artifacts
- malformed model JSON is handled safely
- operator feedback is stored separately from recommendation content
- evaluations produce deterministic labels and skip misleading cases

## Remaining roadmap

- [ ] Add aggregate queries by action type / regime / tag / bucket
- [ ] Add richer JSON + text views for recent outcomes and improvement rates
- [ ] Add narrative retrospectives while keeping deterministic scoring separate
- [ ] Build eval cases from real recommendation episodes
- [ ] Optimize prompts or scoring only after enough real data exists

---

# Priorities

## Current

1. keep recommendation provenance anchored to the captured snapshot
2. keep evaluation deterministic and skip misleading cases
3. accumulate clean operator feedback and notes
4. preserve the main `schwab` CLI/history contract

## Next

5. add aggregate insights by action type / regime / tag
6. add richer outcome views beyond raw run inspection
7. add narrative retrospectives only after enough real episodes exist

## Later

8. build eval cases from real recommendation episodes
9. optimize the recommendation prompt/scoring config only with grounded data
10. consider broader candidate-generation work only after the loop proves useful

---

# Design decisions

## Keep it separate from canonical history in V1

Reason:

- easier rollback
- less migration risk
- fewer accidental changes to stable CLI/history semantics
- faster experimentation

If the recommendation engine proves useful, a later migration can fold parts of it into the main history subsystem.

## Store both structured and raw artifacts

Store:

- normalized recommendation fields
- raw prompt
- raw model output
- parsed JSON

This gives:

- auditability
- debugging
- future eval case generation

## Recommendation episodes should reference snapshots, not recreate them

A recommendation must always be traceable back to the exact portfolio state it was based on.

## Feedback matters as much as outcomes

Without feedback, the system cannot distinguish:

- bad recommendation
- ignored recommendation
- partially followed recommendation

That makes learning ambiguous.

---

# Future migration criteria

Only consider merging recommendation-engine pieces into the main CLI/history flow after:

- repeated successful real-world use
- stable command semantics
- clear evidence that the recommendation episode model is valuable
- confidence that the scoring logic is useful and not noisy

Until then, keep it isolated.

---

# Staged alignment plan

## Vocabulary map

- **Recommendation engine** — preferred architecture term for the subsystem currently
  exposed via `schwab-advisor`
- **Recommendation store** — preferred term for the separate SQLite DB under
  `./private/advisor/advisor.db`
- **Recommendation episode** — the primary unit of recommendation + feedback + evaluation
- **Operational isolation** — the reason the engine still lives behind a separate CLI/store

## Now

- use **recommendation engine** as the primary architecture term in docs
- keep `schwab-advisor`, `advisor_cli.py`, `advisor_sidecar.py`, and `_advisor/` as
  implementation names for continuity
- describe the current isolation boundary explicitly: separate CLI, separate SQLite store,
  same canonical snapshot/context inputs
- consume canonical snapshot/context/history services in-process instead of shelling out to
  `uv run schwab ...`

## Next

- keep recommendation generation centered on `PortfolioContext` unless a narrower
  dedicated decision-context model earns its keep
- reduce the remaining snapshot + supplemental reconstruction path if a cleaner canonical
  state handoff emerges

## Later

- rename internal modules/classes only if the churn is worth it after the model stabilizes
- decide whether `_advisor/` should remain a historical implementation path or become a
  more neutral recommendation/evaluation package
- revisit whether the recommendation store still needs to be separate once the workflow is
  proven and stable

---

# Remaining build order

From the current implementation, the next useful sequence is:

1. Add aggregate insight queries and summary views
2. Add richer outcome metrics beyond policy-health deltas
3. Add narrative retrospectives that clearly separate facts from interpretation
4. Build eval cases from real recommendation episodes
5. Optimize prompts or scoring only after enough grounded data exists
