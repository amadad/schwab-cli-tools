# Errors

## [ERR-20260211-001] codex_cli_auth

**Logged**: 2026-02-11T15:57:30Z
**Priority**: high
**Status**: pending
**Area**: infra

### Summary
Codex CLI failed with 401 Unauthorized due to missing auth header.

### Error
```
401 Unauthorized: Missing bearer or basic authentication in header
```

### Context
- Command: codex exec --full-auto 'Refactor schwab-cli-tools...'
- Workdir: /Users/amadad/base/projects/schwab-cli-tools
- PTY: true (background session)

### Suggested Fix
Ensure Codex CLI is authenticated (login/session token configured) before running.
Check codex config/credentials or run codex auth/login.

### Metadata
- Reproducible: yes
- Related Files: /Users/amadad/base/projects/schwab-cli-tools/.learnings/ERRORS.md

---
