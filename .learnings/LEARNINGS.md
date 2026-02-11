
## [LRN-20260211-001] correction

**Logged**: 2026-02-11T17:15:06.803544+00:00
**Priority**: high
**Status**: pending
**Area**: infra

### Summary
Use `codex exec` for non-interactive agent runs; `codex --full-auto` still launches TUI requiring TTY.

### Details
Codex runs failed because `codex --full-auto` starts the interactive TUI and needs a TTY. For agent automation, use `codex exec` (or `codex exec --dangerously-bypass-approvals-and-sandbox`) to avoid prompts and TTY requirements.

### Suggested Action
Switch all agent runs to `codex exec` and avoid `--full-auto` in headless workflows.

### Metadata
- Source: user_feedback
- Related Files: AGENTS.md, TOOLS.md
- Tags: codex, tty, automation

---
