# Account configuration

Canonical reference for `config/accounts.json` and related account metadata.

## Quick setup

```bash
cp config/accounts.template.json config/accounts.json
```

Then edit `config/accounts.json` with your real account numbers and local metadata.

## File layout

```text
config/
├── accounts.schema.json    # JSON schema for the config file
├── accounts.template.json  # tracked template
├── accounts.json           # local config (gitignored)
└── secure_account_config.py
```

## Config shape

```json
{
  "accounts": {
    "acct_trading": {
      "account_number": "12345678",
      "label": "Trading",
      "name": "Individual Brokerage",
      "type": "individual",
      "tax_status": "taxable",
      "category": "trading",
      "notes": "Active trading account"
    }
  }
}
```

## Fields

### Required
- `account_number`: full Schwab account number (digits only)

### Optional
- `label`: short display name
- `name`: full human-friendly account name
- `type`: account type
- `tax_status`: tax treatment
- `category`: custom grouping used across the CLI
- `notes`: freeform notes
- `distribution_deadline`: useful for inherited accounts
- `beneficiary`: useful for education / beneficiary-linked accounts

## Typical values

### `type`
- `individual`
- `joint`
- `ira`
- `roth_ira`
- `401k`
- `trust`
- `custodial`
- `other`

### `tax_status`
- `taxable`
- `tax_deferred`
- `tax_free`

### `category`
Project-specific, but commonly:
- `trading`
- `retirement`
- `inherited`
- `education`
- `business`
- `personal`

## Security

`config/accounts.json` is gitignored and must never be committed.

Recommended checks:

```bash
# should not show accounts.json as tracked
git status config/

# validate JSON syntax
jq . < config/accounts.json

# test that the app can read your config
uv run schwab accounts --json
```

## How it is used

`config/secure_account_config.py` loads this file and provides:
- alias -> account number mapping
- masked display labels
- category grouping
- account metadata lookups

This metadata is used by:
- portfolio display labels
- trade account resolution
- snapshot account masking
- history/account enrichment
