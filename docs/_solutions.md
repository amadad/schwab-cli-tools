# Solutions Log

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
