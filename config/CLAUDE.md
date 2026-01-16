# Account Configuration

This directory contains account configuration files for the Schwab portfolio management system.

## Setup Instructions

### 1. Create Your Account Configuration

Copy the template and fill in your actual account numbers:

```bash
cp accounts.template.json accounts.json
```

### 2. Fill In Account Numbers

Edit `accounts.json` and replace all `"XXXXXXXX"` placeholders with your actual Schwab account numbers.

### 3. Update Account Labels

Customize the labels to match your account naming preferences:

- `label`: Short display name (e.g., "Trading", "Inherited IRA", "Roth")
- `name`: Full account identifier (e.g., "Example.Trading - Brokerage")
- `category`: Account grouping (personal, inherited, retirement, education, business)

### 4. Verify Configuration

The system will automatically load your configuration on startup. You should see:

```
Loaded 5 accounts from /path/to/config/accounts.json
```

## File Structure

```
config/
├── CLAUDE.md                # This file
├── accounts.schema.json     # JSON schema
├── accounts.template.json   # Template (tracked in git)
├── accounts.json            # Your config (gitignored, NEVER commit!)
└── secure_account_config.py # Configuration loader
```

## JSON Schema

Each account entry follows this structure:

```json
{
  "alias": {
    "account_number": "12345678",
    "name": "Full Account Name",
    "label": "Short Label",
    "type": "account_type",
    "tax_status": "tax_treatment",
    "category": "grouping",
    "notes": "Optional description",
    "distribution_deadline": "2034-12-31",  // Optional: for inherited accounts
    "beneficiary": "Name"                    // Optional: for education accounts
  }
}
```

### Account Types

- `individual_taxable`: Regular brokerage account
- `retirement`: IRA, Roth IRA, SEP-IRA
- `inherited_ira`: Inherited traditional IRA
- `inherited_roth`: Inherited Roth IRA
- `education`: 529, Coverdell ESA
- `business`: Business brokerage accounts

### Tax Status

- `taxable`: Taxed annually
- `tax_deferred`: Taxed on withdrawal (traditional IRA, 401k)
- `tax_free`: Never taxed (Roth IRA, Roth 401k)

### Categories

- `personal`: Individual accounts
- `inherited`: Inherited IRAs (with 10-year distribution rule)
- `retirement`: Personal retirement accounts
- `education`: Education savings accounts
- `business`: Business accounts

## Security

**CRITICAL**: `accounts.json` is automatically gitignored and should NEVER be committed to version control.

### Best Practices

1. ✅ Use `accounts.template.json` as a starting point
2. ✅ Keep `accounts.json` local only
3. ✅ Regularly backup `accounts.json` to secure storage
4. ✅ Use descriptive labels that don't expose sensitive information
5. ❌ NEVER commit `accounts.json`
6. ❌ NEVER hardcode account numbers in code
7. ❌ NEVER share account configuration files

### Verification

Before committing code, verify sensitive files aren't tracked:

```bash
git status config/
# Should NOT show accounts.json
```

## Usage in Code

```python
from config.secure_account_config import secure_config

# Get account info by alias
info = secure_config.get_account_info('acct_trading')
print(info.label)  # "Trading"
print(info.get_display_label())  # "Trading (...5678)"

# Get account number by alias
account_number = secure_config.get_account_number('acct_trading')

# Get display label from account number
label = secure_config.get_account_label('12345678')  # "Trading (...5678)"

# Get accounts by category
inherited = secure_config.get_accounts_by_category('inherited')
```

## Troubleshooting

### "WARNING: accounts.json not found"

You need to create the configuration file:

```bash
cp config/accounts.template.json config/accounts.json
```

Then edit `accounts.json` and fill in your account numbers.

### Labels Not Showing Correctly

Verify your `accounts.json`:
1. Account numbers match exactly what Schwab API returns
2. JSON is valid (use `jq . < accounts.json` to validate)
3. All required fields are present (account_number, name, label, type, tax_status, category)

### "Unknown (...1234)" Labels

This means the account number from Schwab doesn't match any entry in `accounts.json`. Check:
1. Account number is correct (no spaces or dashes)
2. Entry exists in `accounts.json`
3. Configuration loaded successfully (check logs)

## Migration from Environment Variables

If you're migrating from the old `.env`-based system:

1. Your old `ACCOUNT_MAPPINGS` in `.env` can be removed
2. Account categories (`INHERITED_ACCOUNTS`, etc.) can be removed
3. All configuration is now in `accounts.json`

The new system is more maintainable and provides richer metadata for better account labeling.
