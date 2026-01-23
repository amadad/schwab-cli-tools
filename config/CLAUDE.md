# Account Configuration

This directory contains account configuration files for the Schwab CLI tools.

## Quick Setup

```bash
cp accounts.template.json accounts.json
# Edit accounts.json with your account numbers
```

## File Structure

```
config/
├── CLAUDE.md                # This file
├── accounts.schema.json     # JSON schema for validation
├── accounts.template.json   # Template (tracked in git)
├── accounts.json            # Your config (gitignored, NEVER commit!)
└── secure_account_config.py # Configuration loader
```

## JSON Schema

Each account entry follows this structure:

```json
{
  "alias_name": {
    "account_number": "12345678",
    "label": "Short Label",
    "name": "Full Account Name",
    "account_type": "individual|joint|ira|roth_ira|401k|trust|custodial|other",
    "tax_status": "taxable|tax_deferred|tax_free",
    "category": "trading|retirement|inherited|education|business",
    "description": "Optional description",
    "notes": "Additional notes",
    "distribution_deadline": "2034-12-31",
    "beneficiary": "Name"
  }
}
```

### Required Fields

- `account_number`: Full Schwab account number (digits only)

### Optional Fields

- `label`: Short display name (e.g., "Trading", "Roth IRA")
- `name`: Full account identifier
- `account_type`: Account type enum
- `tax_status`: Tax treatment
- `category`: Custom grouping
- `description`: Brief description
- `notes`: Additional notes
- `distribution_deadline`: RMD deadline (inherited accounts)
- `beneficiary`: Beneficiary name (education accounts)

### Account Types

| Type | Description |
|------|-------------|
| `individual` | Regular brokerage account |
| `joint` | Joint brokerage account |
| `ira` | Traditional IRA |
| `roth_ira` | Roth IRA |
| `401k` | 401(k) account |
| `trust` | Trust account |
| `custodial` | Custodial account |
| `other` | Other account type |

### Tax Status

| Status | Description |
|--------|-------------|
| `taxable` | Taxed annually (brokerage) |
| `tax_deferred` | Taxed on withdrawal (traditional IRA, 401k) |
| `tax_free` | Never taxed (Roth IRA) |

### Example Configuration

```json
{
  "acct_trading": {
    "account_number": "12345678",
    "label": "Trading",
    "name": "Individual Brokerage",
    "account_type": "individual",
    "tax_status": "taxable",
    "category": "trading",
    "description": "Active trading account"
  },
  "acct_roth": {
    "account_number": "87654321",
    "label": "Roth IRA",
    "name": "Retirement Roth",
    "account_type": "roth_ira",
    "tax_status": "tax_free",
    "category": "retirement"
  },
  "acct_inherited": {
    "account_number": "11223344",
    "label": "Inherited IRA",
    "name": "Inherited Traditional IRA",
    "account_type": "ira",
    "tax_status": "tax_deferred",
    "category": "inherited",
    "distribution_deadline": "2034-12-31"
  }
}
```

## Security

**CRITICAL**: `accounts.json` is gitignored and should NEVER be committed.

### Best Practices

1. Use `accounts.template.json` as a starting point
2. Keep `accounts.json` local only
3. Backup `accounts.json` to secure storage
4. Use descriptive labels that don't expose sensitive information

### Verification

```bash
# Verify accounts.json is not tracked
git status config/
# Should NOT show accounts.json

# Validate JSON syntax
jq . < config/accounts.json

# Test configuration
uv run schwab accounts --json
```

## Usage in Code

```python
from config.secure_account_config import secure_config

# Get account info by alias
info = secure_config.get_account_info('acct_trading')
print(info.label)           # "Trading"
print(info.account_number)  # "12345678"

# Get account number by alias
account_number = secure_config.get_account_number('acct_trading')

# Get display label from account number
label = secure_config.get_account_label('12345678')  # "Trading"

# List all accounts
for alias, info in secure_config.get_all_accounts().items():
    print(f"{alias}: {info.label}")

# Get accounts by category
inherited = secure_config.get_accounts_by_category('inherited')
```

## CLI Integration

```bash
# List all configured accounts
schwab accounts

# Use account alias in commands
schwab buy acct_trading AAPL 10 --dry-run
schwab orders acct_trading

# Set default account
export SCHWAB_DEFAULT_ACCOUNT=acct_trading
schwab buy AAPL 10 --dry-run  # Uses default account
```

## Troubleshooting

### "WARNING: accounts.json not found"

Create the configuration file:

```bash
cp config/accounts.template.json config/accounts.json
```

### "Unknown account alias"

1. Check alias exists in `accounts.json`
2. Verify JSON syntax: `jq . < config/accounts.json`
3. Run `schwab accounts` to see loaded accounts

### Labels Not Showing Correctly

1. Account numbers must match exactly what Schwab API returns
2. Check for extra spaces or dashes in account numbers
3. Verify configuration loaded: `schwab doctor --json`

## Schema Validation

The `accounts.schema.json` file defines the JSON schema. To validate:

```python
import json
import jsonschema

with open('config/accounts.schema.json') as f:
    schema = json.load(f)

with open('config/accounts.json') as f:
    config = json.load(f)

jsonschema.validate(config, schema)
```
