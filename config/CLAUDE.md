# Account configuration notes

Use [`../docs/account-config.md`](../docs/account-config.md) as the canonical reference for
`config/accounts.json`, field meanings, setup, and security rules.

## Local reminder

- `accounts.json` is gitignored and must stay local.
- `accounts.template.json` is the tracked starting point.
- `policy.template.json` is the tracked public-safe policy/profile template.
- Real policy aliases and thresholds belong in `private/policy.json` (or `SCHWAB_POLICY_PATH`).
- `secure_account_config.py` is the loader used by the CLI.

Quick setup:

```bash
cp accounts.template.json accounts.json
uv run schwab accounts --json
```
