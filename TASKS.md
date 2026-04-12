# TASKS

Source: review against OpenAI's agent-friendly CLI guide:
https://developers.openai.com/codex/use-cases/agent-friendly-clis

## Goal
Make `cli-schwab` fully agent-friendly for installed, repeatable, safe CLI use from any folder.

## P0

- [x] **SCHWAB-1: Add install-from-any-folder workflow**
  - Document `uv tool install -e .` and/or `pipx install .`
  - Verify `command -v schwab` works outside the repo
  - Add CI smoke test from a temp directory
  - **Acceptance:** `schwab --help` and `schwab doctor --json` work outside the repo

- [x] **SCHWAB-2: Add agent verification smoke script**
  - Script should verify:
    - installed command is on PATH
    - `schwab --help`
    - `schwab doctor --json`
    - `schwab history --json --limit 1`
    - `schwab snapshot --output <path>`
    - `schwab buy <acct> <symbol> <qty> --dry-run --json`
  - **Acceptance:** one command/script proves the CLI satisfies the guide's baseline workflow

- [x] **SCHWAB-3: Consolidate auth under the root CLI**
  - Add a root flow like:
    - `schwab auth status`
    - `schwab auth login --portfolio`
    - `schwab auth login --market`
  - Keep `schwab-auth` and `schwab-market-auth` as compatibility shims if needed
  - **Acceptance:** agent-facing docs can stay on one root command surface

## P1

- [x] **SCHWAB-4: Tighten large-output patterns**
  - Audit heavy commands and ensure each supports either narrowing (`--limit`, filters) or file export
  - Prefer small default terminal output and explicit file output for full payloads
  - **Acceptance:** docs clearly show "narrow in terminal, export full payload to file"

- [x] **SCHWAB-5: Refresh skill/docs for recurring agent use**
  - Update README + skill with:
    - shortest reusable prompt
    - safe commands to run first
    - write approval rules
    - file output locations
  - **Acceptance:** a new agent can reuse the CLI without rereading full repo docs

## P2

- [x] **SCHWAB-6: Completion/install polish**
  - Document shell completion setup
  - Add release/install notes for `uv tool` / `pipx`
  - **Acceptance:** installed CLI is ergonomic for both humans and agents

## Notes from current review
- Strong JSON envelope already exists
- Strong dry-run/live trade safety already exists
- Existing companion skill is already good
- Biggest gap is the installed-from-any-folder story
