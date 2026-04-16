# Solutions Log

## 2026-04-16 — Recommendation generation still accepted loose JSON blobs instead of canonical state objects

- **Symptom:** even after snapshot/context/history capture moved in-process, recommendation generation still flowed through ad hoc context dicts, which left the engine’s main input contract fuzzy and kept `recommend_from_context(...)` anchored to serialized payload shape instead of the canonical state object.
- **Fix:** made `PortfolioContext` the internal decision-context contract for the recommendation engine: `src/core/advisor_sidecar.py` now exposes `recommend_from_decision_context(...)`, derives provenance/novelty/why-now metadata from the typed context object, rebuilds evaluation contexts as `PortfolioContext`, and keeps the older dict entrypoint only as a thin compatibility wrapper. `src/core/advisor_scoring.py` now also accepts `PortfolioContext` directly.
- **Follow-up:** only introduce a narrower dedicated decision-context model if recommendation needs truly diverge from `PortfolioContext`; until then, prefer tightening around the existing canonical state object instead of adding another parallel payload shape.

## 2026-04-16 — Recommendation capture still depended on shelling back through the CLI

- **Symptom:** `src/core/advisor_sidecar.py` still called `uv run schwab snapshot`, `uv run schwab context`, and `uv run schwab history --snapshot-id ...` through `subprocess`, which kept the recommendation engine coupled to CLI presentation boundaries even after the architecture had been reframed around canonical state.
- **Fix:** switched recommendation orchestration to reuse the in-process snapshot/context/history services directly: live snapshot capture now uses `collect_snapshot(...)` + `HistoryStore.store_snapshot(...)`, snapshot reuse now reads through `HistoryStore.get_snapshot_payload(...)`, context capture now uses `PortfolioContext.assemble(...)`, and baseline symbol prices now come from the quote client instead of the `fundamentals` CLI command. Added unit coverage to prove recommendation capture, snapshot reuse, context capture, and baseline-price lookup no longer need CLI subprocesses.
- **Follow-up:** the next architecture-tightening step is to define one explicit decision-context input contract so recommendation generation can depend on canonical state objects directly rather than rebuilding context from mixed snapshot + supplemental payloads.

## 2026-04-16 — Code-quality drift had started to outpace the repo's internal guardrails

- **Symptom:** shared payload shapes were spreading as ad hoc dicts/tuples, broad exception handlers kept accumulating around orchestration code, dead helpers lingered after refactors, and CI only checked `ruff` + `pytest`, so type-safety and cleanup regressions could sneak back in.
- **Fix:** consolidated reusable types into `src/core/brief_types.py`, `src/core/context_models.py`, `src/core/json_types.py`, and `src/schwab_client/_client/protocols.py`; removed verified-dead helpers; narrowed broad catches to explicit boundary errors; and added `scripts/check_quality_budget.py` plus CI gates for `ruff`, `mypy`, `pytest`, `Any <= 20`, and zero broad `except Exception` handlers.
- **Follow-up:** when new shared payload shapes appear, add them to the dedicated type/helper modules instead of copying inline dict contracts, and treat the quality-budget script as the regression tripwire rather than weakening it with broad ignores.

## 2026-04-15 — Dedicated market OAuth app could fail headless auth even while portfolio auth still worked

- **Symptom:** `schwab auth login --market --manual` could die at the Schwab authorize step with `invalid_client` / `Unauthorized`, while portfolio auth still worked and the market token remained missing.
- **Fix:** verified the headless/manual flow itself was sound by completing market auth with the working portfolio OAuth app, then updated local `.env` so `SCHWAB_MARKET_APP_KEY`, `SCHWAB_MARKET_CLIENT_SECRET`, and `SCHWAB_MARKET_CALLBACK_URL` mirror `SCHWAB_INTEL_*`. Market auth now succeeds again while still writing to the separate `schwab_market_token.json` token slot.
- **Follow-up:** if a separate market app is reintroduced later, verify its Schwab-side callback/app registration before switching the local env back.

## 2026-04-15 — Morning brief state could drift across snapshots, files, and legacy sidecar DBs

- **Symptom:** the portfolio brief flow still depended on separate scripts, file/date matching, and `sent.json`, so analysis and delivery could drift from the source snapshot. The sidecar also grew `issue_key`-based dedupe, which exposed a legacy migration edge case: indexing the new field before adding the column would fail on older advisor DBs.
- **Fix:** moved the brief flow into repo-native commands (`schwab brief nightly/send/status/show`) backed by `brief_runs` / `brief_deliveries` in the canonical history DB, reused one frozen snapshot/context/scorecard set for analysis plus advisor output, and updated `src/schwab_client/_advisor/store.py` to ensure column migrations run before the `issue_key` index is created.
- **Follow-up:** treat the history DB as the source of truth for briefing state, keep runtime secret loading at CLI entrypoints instead of library imports, and rely on CI (`ruff` + `pytest`) to catch drift before delivery changes ship.

## 2026-04-12 — Agent-facing read paths were too blob-shaped for large context and snapshot payloads

- **Symptom:** `schwab context --json` could produce a payload that was awkward for agents to consume inline, and `schwab history` had no first-class exact-read/export path once an agent already knew a stable `snapshot_id`.
- **Fix:** `src/schwab_client/cli/commands/context_cmd.py` now supports `--output PATH` so the full context JSON or rendered prompt/template can be written to disk while the CLI returns compact metadata. `src/schwab_client/cli/commands/history.py` now supports `--snapshot-id` and `--output PATH` for exact canonical snapshot reads and exports.
- **Follow-up:** prefer narrow discovery responses plus file exports for large payloads, and use stable snapshot ids for exact history reads before reaching for SQL.

## 2026-04-12 — Advisor evaluation could persist misleading outcomes and drift from the source snapshot

- **Symptom:** recommendation runs mixed a captured snapshot with a separate live `schwab context --json` fetch, and evaluation could still persist outcomes when required distribution-history inputs were missing. Ignored recommendations were also being scored like executed ones.
- **Fix:** `src/core/advisor_sidecar.py` now rebuilds baseline context from the captured source snapshot, keeps `market_available` aligned with actual snapshot market payloads, skips evaluation when distribution history is missing, and records ignored feedback as `insufficient_data`. `src/schwab_client/_advisor/schema.py` and `store.py` now persist `feedback_status` with evaluations.
- **Follow-up:** keep recommendation provenance snapshot-backed and treat sidecar evaluations as advisory until enough grounded episodes accumulate.

## 2026-04-12 — Context JSON could hide policy/auth problems from agents

- **Symptom:** policy evaluation could key off unstable display labels instead of canonical aliases, and `schwab context --json` could silently degrade when market auth was missing or partial context fields were omitted.
- **Fix:** `src/core/context.py`, `src/core/policy.py`, and `src/schwab_client/cli/commands/context_cmd.py` now normalize account aliases for policy evaluation, serialize the full context envelope, and surface market-auth degradation through `errors` while still returning `market`, `market_available`, `recent_transactions`, and `manual_accounts_included`.
- **Follow-up:** treat `schwab context --json` as the canonical agent envelope and preserve partial-failure visibility instead of swallowing it.

## 2026-04-01 — Token refresh state could race and had poor diagnostics

- **Symptom:** token writes relied on plain files, which made locking fragile and left
  `schwab auth --json` / `schwab doctor --json` without useful storage metadata.
- **Fix:** `src/schwab_client/auth.py` and `src/schwab_client/market_auth.py` now pair
  the token JSON files with a sibling SQLite `tokens.db` sidecar for locking,
  atomic writes, and cached token metadata.
- **Follow-up:** reuse the managed token helpers instead of adding new ad hoc file locks.

## 2026-04-01 — Household-specific policy leaked into tracked source

- **Symptom:** personal account aliases and household rules were hardcoded in tracked
  policy/context code and prompt text.
- **Fix:** moved public defaults into `config/policy.template.json` and resolved real
  local rules from `private/policy.json` or `SCHWAB_POLICY_PATH`.
- **Follow-up:** keep tracked docs/templates generic and keep live household policy in
  ignored local files only.
