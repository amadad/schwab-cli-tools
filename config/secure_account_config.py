"""
Secure Account Configuration - reads from JSON config file
No hardcoded account numbers! Uses config/accounts.json (gitignored)
"""

import json
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Config file paths
CONFIG_DIR = Path(__file__).parent
ACCOUNTS_FILE = CONFIG_DIR / "accounts.json"
ACCOUNTS_TEMPLATE = CONFIG_DIR / "accounts.template.json"


class AccountType(Enum):
    INDIVIDUAL_TAXABLE = "Individual Taxable"
    RETIREMENT = "Retirement"
    INHERITED_IRA = "Inherited IRA"
    INHERITED_ROTH = "Inherited Roth IRA"
    EDUCATION = "Education"
    BUSINESS = "Business"


class TaxStatus(Enum):
    TAXABLE = "Taxable"
    TAX_DEFERRED = "Tax-Deferred"
    TAX_FREE = "Tax-Free"


@dataclass
class AccountInfo:
    """Account information"""

    alias: str
    account_number: str
    name: str
    label: str
    account_type: str
    tax_status: str
    category: str
    notes: str
    distribution_deadline: str | None = None
    beneficiary: str | None = None

    def __repr__(self):
        return f"AccountInfo(alias='{self.alias}', label='{self.label}', name='{self.name}')"

    def get_display_label(self) -> str:
        """Get formatted display label with masked account number"""
        return f"{self.label} (...{self.account_number[-4:]})"


class SecureAccountConfig:
    """Secure configuration that reads from JSON config file"""

    def __init__(self):
        self._load_from_json()

    def _load_from_json(self):
        """Load account configuration from JSON file"""
        if not ACCOUNTS_FILE.exists():
            logger.warning(
                f"{ACCOUNTS_FILE} not found. Copy {ACCOUNTS_TEMPLATE} and fill in your account numbers. "
                f"Run: cp {ACCOUNTS_TEMPLATE} {ACCOUNTS_FILE}"
            )
            self.account_info = {}
            self.account_mappings = {}
            self.categories = {}
            return

        try:
            with open(ACCOUNTS_FILE) as f:
                config = json.load(f)

            # Build account info and mappings
            self.account_info = {}
            self.account_mappings = {}
            self.categories = {
                "personal": [],
                "inherited": [],
                "retirement": [],
                "education": [],
                "taxable": [],
                "business": [],
            }

            for alias, account_data in config.get("accounts", {}).items():
                # Create AccountInfo object
                account_info = AccountInfo(
                    alias=alias,
                    account_number=account_data["account_number"],
                    name=account_data["name"],
                    label=account_data["label"],
                    account_type=account_data["type"],
                    tax_status=account_data["tax_status"],
                    category=account_data["category"],
                    notes=account_data.get("notes", ""),
                    distribution_deadline=account_data.get("distribution_deadline"),
                    beneficiary=account_data.get("beneficiary"),
                )

                self.account_info[alias] = account_info
                self.account_mappings[alias] = account_data["account_number"]

                # Add to category
                category = account_data["category"]
                if category in self.categories:
                    self.categories[category].append(account_data["account_number"])

            logger.info(f"Loaded {len(self.account_info)} accounts from {ACCOUNTS_FILE}")

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in {ACCOUNTS_FILE}: {e}")
            self.account_info = {}
            self.account_mappings = {}
            self.categories = {}
        except Exception as e:
            logger.error(f"Error loading account config: {e}")
            self.account_info = {}
            self.account_mappings = {}
            self.categories = {}

    def get_account_number(self, alias: str) -> str | None:
        """Get actual account number for an alias"""
        return self.account_mappings.get(alias)

    def get_account_info(self, alias: str) -> AccountInfo | None:
        """Get account metadata for an alias"""
        return self.account_info.get(alias)

    def get_account_info_by_number(self, account_number: str) -> AccountInfo | None:
        """Get account metadata by account number"""
        for info in self.account_info.values():
            if info.account_number == account_number:
                return info
        return None

    def get_accounts_by_category(self, category: str) -> list[str]:
        """Get account numbers by category"""
        return self.categories.get(category, [])

    def get_account_label(self, account_number: str) -> str:
        """Get a display label for an account number"""
        info = self.get_account_info_by_number(account_number)
        if info:
            return info.get_display_label()
        return f"Unknown (...{account_number[-4:]})"

    def mask_account_number(self, account_number: str) -> str:
        """Mask account number for display"""
        if len(account_number) <= 4:
            return "****"
        return "*" * (len(account_number) - 4) + account_number[-4:]

    def get_all_accounts(self) -> dict[str, AccountInfo]:
        """Get all account information"""
        return self.account_info.copy()


# Global instance
secure_config = SecureAccountConfig()
