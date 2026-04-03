# Advisor Sidecar Plan

Status: proposed

This document defines a **sidecar recommendation-learning system** for `schwab-cli-tools`.
It is intentionally designed to sit **next to** the existing CLI, snapshot, context,
and history workflows without disrupting them.

## Objective

Build a compounding portfolio learning loop that:

1. reads the current portfolio + market + policy context
2. generates a structured recommendation
3. records what was recommended
4. records whether the operator followed it
5. evaluates whether the recommendation improved the portfolio situation
6. learns from accumulated recommendation episodes over time

## Why a sidecar instead of extending the current CLI first

The existing repo already has stable, valuable workflows for:

- `snapshot`
- `context`
- `history`
- market diagnostics
- dry-run trading

Those should remain stable.

The recommendation-learning loop is still experimental and should be treated as an
**opt-in adjunct system** until it proves useful.

## Guardrails

V1 guardrails:

- Do **not** change current `schwab` command behavior.
- Do **not** change existing snapshot semantics.
- Do **not** change existing history semantics.
- Do **not** move current prompt/policy/context workflows.
- Do **not** place live trading or order execution in the sidecar.
- Do **not** optimize prompts with autoresearch until enough real episodes exist.

The sidecar may **read** from the current repo systems, but should write only to its
own storage in V1.

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

The sidecar CLI should be a separate entrypoint:

```bash
uv run schwab-advisor recommend --json
uv run schwab-advisor feedback 12 --status followed --json
uv run schwab-advisor evaluate --json
uv run schwab-advisor status --json
uv run schwab-advisor review 12 --json
```

## V1 non-goals

Explicitly out of scope for V1:

- stock universe scanning
- free-form signal pattern naming as the primary feature
- LLM-generated pattern extraction without real data backing it
- trade execution
- replacing the current `context` / `snapshot` / `history` workflows
- merging sidecar storage into the canonical history DB before the model proves useful

---

# Architecture

## Sidecar CLI

Add a new script entrypoint:

```toml
[project.scripts]
schwab-advisor = "src.schwab_client.advisor_cli:main"
```

This keeps the main `schwab` parser untouched.

## Proposed file layout

```text
src/schwab_client/
├── advisor_cli.py                # separate CLI entrypoint: schwab-advisor
├── _advisor/
│   ├── __init__.py
│   ├── schema.py                 # sidecar DB schema
│   └── store.py                  # persistence/query API
src/core/
├── advisor_models.py             # sidecar-specific typed models
├── advisor_prompts.py            # structured recommendation prompts
├── advisor_scoring.py            # deterministic outcome scoring
└── advisor_sidecar.py            # orchestration service

docs/
└── advisor-sidecar.md            # this file

tests/unit/
├── test_advisor_store.py
├── test_advisor_service.py
├── test_advisor_scoring.py
└── test_advisor_cli.py
```

## Read-only inputs from the current system

The sidecar should consume, not replace:

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
- model/prompt version used

---

# Storage

## Sidecar database

Use a dedicated DB for V1.

Default path:

```text
./private/advisor/advisor.db
```

Override with:

```bash
export SCHWAB_ADVISOR_DB_PATH=./private/advisor/advisor.db
```

This keeps the experiment isolated from the canonical history store.

## Tables

### `recommendation_runs`

One row per recommendation episode.

Suggested fields:

- `id`
- `created_at`
- `source_snapshot_id`
- `source_history_db_path`
- `template_name`
- `model_name`
- `market_available`
- `manual_accounts_included`
- `market_regime`
- `vix_value`
- `vix_band`
- `summary`
- `primary_action_json`
- `features_json`
- `context_json`
- `raw_prompt`
- `raw_response`
- `status` (`open|evaluated|archived`)

### `recommendation_actions`

One row per action attached to a run.

Suggested fields:

- `id`
- `run_id`
- `priority`
- `action_type`
- `account_alias`
- `bucket`
- `symbol`
- `amount`
- `timing`
- `rationale`
- `expected_effect`
- `is_primary`

### `recommendation_feedback`

Operator feedback on whether the recommendation was followed.

Suggested fields:

- `id`
- `run_id`
- `recorded_at`
- `status` (`followed|partially_followed|ignored|unknown`)
- `notes`

### `recommendation_outcomes`

Evaluation result for a run.

Suggested fields:

- `id`
- `run_id`
- `evaluated_at`
- `evaluation_snapshot_id`
- `horizon_days`
- `policy_score_before`
- `policy_score_after`
- `delta_score`
- `outcome_label` (`improved|neutral|worsened|insufficient_data`)
- `action_metrics_json`
- `notes`

## Views

### `open_recommendations`

Runs needing feedback or evaluation.

### `recommendation_history`

Denormalized view of run + feedback + outcome.

### `recommendation_leaderboard`

Aggregates by action type / regime / VIX band after enough episodes accumulate.

---

# Structured output contract

Recommendations must be machine-readable.

## JSON shape

```json
{
  "summary": "Most important signal and implication",
  "primary_action": {
    "action_type": "deploy_cash",
    "account": "Inherited IRA (Mom)",
    "symbol": "VTI",
    "amount": 50000,
    "timing": "this_week",
    "rationale": "Cash is above target and regime is risk_off, so phase in"
  },
  "secondary_actions": [
    {
      "action_type": "distribute",
      "account": "Inherited IRA (Dad)",
      "amount": 10000,
      "timing": "this_month",
      "rationale": "Buffer is below the minimum threshold"
    }
  ],
  "leave_alone": ["Index", "Business"],
  "confidence": 0.74
}
```

## Required action fields

Each action should support:

- `action_type`
- `account`
- `symbol` optional
- `amount` optional
- `timing`
- `rationale`

## Suggested action types

- `deploy_cash`
- `distribute`
- `rebalance`
- `hold`
- `buy`
- `sell`
- `trim`
- `review`

---

# Evaluation philosophy

The evaluator should be mostly deterministic.

This repo is strongest when:

- calculations are done in code
- prompts interpret deterministic results
- outputs are structured for later measurement

The sidecar should follow the same pattern.

## Do not evaluate only on price movement

This repo’s goals are broader than stock picking.

A recommendation can succeed by:

- reducing inherited IRA distribution risk
- moving cash closer to policy targets
- improving household portfolio alignment
- avoiding bad deployment in a bad regime

## Deterministic score: policy health / portfolio health

Create a compact sidecar scoring module that measures health before and after.

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

This should:

- read the latest or specified snapshot
- assemble current context
- generate a structured recommendation
- persist the episode in the sidecar DB

## Step 3: record operator feedback

```bash
uv run schwab-advisor feedback 12 --status followed --json
```

## Step 4: evaluate later

```bash
uv run schwab-advisor evaluate --json
```

This should compare the original run with a later snapshot and compute an outcome.

## Step 5: inspect results

```bash
uv run schwab-advisor status --json
uv run schwab-advisor review 12 --json
```

---

# Phased implementation plan

## PR 0 — Sidecar scaffold

- [ ] Add `docs/advisor-sidecar.md`
- [ ] Add `schwab-advisor` CLI entrypoint in `pyproject.toml`
- [ ] Add `src/schwab_client/advisor_cli.py`
- [ ] Add `SCHWAB_ADVISOR_DB_PATH` resolution
- [ ] Add sidecar DB schema in `src/schwab_client/_advisor/schema.py`
- [ ] Add sidecar store in `src/schwab_client/_advisor/store.py`

### Acceptance criteria

- `uv run schwab-advisor --help` works
- sidecar DB initializes in `./private/advisor/advisor.db`
- existing `schwab` commands behave exactly as before

## PR 1 — Recommendation capture

- [ ] Add `src/core/advisor_models.py`
- [ ] Add `src/core/advisor_prompts.py`
- [ ] Add `src/core/advisor_sidecar.py`
- [ ] Implement read-only bridge from snapshot/history/context/policy
- [ ] Implement recommendation generation + persistence
- [ ] Add `schwab-advisor recommend`
- [ ] Add tests for models/store/service/CLI recommend flow

### Acceptance criteria

- `uv run schwab-advisor recommend --json` returns a valid recommendation envelope
- each run stores snapshot provenance and raw model artifacts
- malformed model JSON is handled safely
- no existing CLI paths are changed

## PR 2 — Feedback and evaluation

- [ ] Add `schwab-advisor feedback RUN_ID`
- [ ] Add `src/core/advisor_scoring.py`
- [ ] Implement deterministic before/after health scoring
- [ ] Implement outcome evaluator
- [ ] Add `schwab-advisor evaluate`
- [ ] Add tests for followed / ignored / insufficient-data paths

### Acceptance criteria

- operator feedback is stored separately from recommendation content
- evaluations produce deterministic labels
- recommendations with no valid later snapshot are marked `insufficient_data`

## PR 3 — Visibility and learning summaries

- [ ] Add `schwab-advisor status`
- [ ] Add `schwab-advisor review RUN_ID`
- [ ] Add aggregate queries by action type / regime / VIX band / bucket
- [ ] Add JSON + text views for recent outcomes and improvement rates
- [ ] Add tests for empty and populated states

### Acceptance criteria

- user can inspect the full lifecycle of a recommendation episode
- status command answers whether the loop is healthy and accumulating learnings

## PR 4 — Optional narrative layer

- [ ] Add LLM retrospective prompt consuming stored structured outcomes
- [ ] Add `schwab-advisor retrospective RUN_ID`
- [ ] Keep narrative synthesis separate from deterministic scoring

### Acceptance criteria

- narrative output distinguishes facts from interpretation
- evaluator remains deterministic even if LLM synthesis is unavailable

## PR 5 — Optimization only after data exists

- [ ] Build eval cases from real sidecar recommendation episodes
- [ ] Create sidecar-specific autoresearch program
- [ ] Optimize only the sidecar recommendation prompt or scoring config

### Acceptance criteria

- no prompt optimization starts before enough real episodes exist
- evals are grounded in actual recommendation outcomes, not imagined cases

---

# Priorities

## P0

1. sidecar scaffold
2. models
3. schema/store
4. `recommend`

## P1

5. feedback
6. deterministic scoring
7. `evaluate`

## P2

8. `status`
9. `review`
10. aggregate insights

## Later

11. retrospective narratives
12. autoresearch
13. any scan/candidate-generation work

---

# Design decisions

## Keep it separate from canonical history in V1

Reason:

- easier rollback
- less migration risk
- fewer accidental changes to stable CLI/history semantics
- faster experimentation

If the sidecar proves useful, a later migration can fold parts of it into the main history subsystem.

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

Only consider merging sidecar pieces into the main CLI/history flow after:

- repeated successful real-world use
- stable command semantics
- clear evidence that the recommendation episode model is valuable
- confidence that the scoring logic is useful and not noisy

Until then, keep it isolated.

---

# First concrete build order

If implementing now, start in this order:

1. Add sidecar CLI entrypoint
2. Add sidecar DB schema + store
3. Add sidecar models
4. Add structured prompt and recommendation generation
5. Add `schwab-advisor recommend`
6. Add feedback
7. Add deterministic scoring
8. Add `schwab-advisor evaluate`
9. Add `status` and `review`
10. Add retrospectives and autoresearch later
