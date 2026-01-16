"""Tests for secure account configuration system"""

import json
from unittest.mock import patch

from config.secure_account_config import AccountInfo, AccountType, SecureAccountConfig


def test_account_type_enum():
    """Test AccountType enum values"""
    assert AccountType.INDIVIDUAL_TAXABLE.value == "Individual Taxable"
    assert AccountType.RETIREMENT.value == "Retirement"
    assert AccountType.INHERITED_IRA.value == "Inherited IRA"


def test_account_info_dataclass():
    """Test AccountInfo dataclass creation"""
    info = AccountInfo(
        alias="test_account",
        account_number="12345678",
        label="Test",
        name="Test Account",
        account_type="individual_taxable",
        tax_status="taxable",
        category="personal",
        notes="Test notes",
    )
    assert info.account_number == "12345678"
    assert info.label == "Test"
    assert info.account_type == "individual_taxable"


def test_secure_config_with_missing_file(tmp_path):
    """Test SecureAccountConfig handles missing file gracefully"""
    config_path = tmp_path / "nonexistent.json"
    with patch("config.secure_account_config.ACCOUNTS_FILE", config_path):
        config = SecureAccountConfig()
        assert len(config.account_info) == 0
        assert len(config.categories) == 0  # Empty when file missing


def test_secure_config_loads_valid_file(tmp_path):
    """Test SecureAccountConfig loads valid JSON configuration"""
    config_path = tmp_path / "accounts.json"
    test_data = {
        "version": "1.0",
        "last_updated": "2025-01-15",
        "accounts": {
            "test_account": {
                "account_number": "12345678",
                "label": "Test",
                "name": "Test Account",
                "type": "individual_taxable",
                "tax_status": "taxable",
                "category": "personal",
                "notes": "Test notes",
            }
        },
    }

    config_path.write_text(json.dumps(test_data))
    with patch("config.secure_account_config.ACCOUNTS_FILE", config_path):
        config = SecureAccountConfig()

        assert "test_account" in config.account_info
        assert config.account_info["test_account"].account_number == "12345678"
        assert config.account_info["test_account"].label == "Test"


def test_get_account_by_alias(tmp_path):
    """Test getting account by alias"""
    config_path = tmp_path / "accounts.json"
    test_data = {
        "version": "1.0",
        "accounts": {
            "my_trading": {
                "account_number": "12345678",
                "label": "Trading",
                "name": "My Trading Account",
                "type": "individual_taxable",
                "tax_status": "taxable",
                "category": "personal",
                "notes": "",
            }
        },
    }

    config_path.write_text(json.dumps(test_data))
    with patch("config.secure_account_config.ACCOUNTS_FILE", config_path):
        config = SecureAccountConfig()

        account = config.account_info.get("my_trading")
        assert account is not None
        assert account.account_number == "12345678"
        assert account.label == "Trading"


def test_get_nonexistent_account(tmp_path):
    """Test getting non-existent account returns None"""
    config_path = tmp_path / "accounts.json"
    test_data = {"version": "1.0", "accounts": {}}

    config_path.write_text(json.dumps(test_data))
    with patch("config.secure_account_config.ACCOUNTS_FILE", config_path):
        config = SecureAccountConfig()

        account = config.account_info.get("nonexistent")
        assert account is None


def test_get_accounts_by_category(tmp_path):
    """Test getting accounts by category"""
    config_path = tmp_path / "accounts.json"
    test_data = {
        "version": "1.0",
        "accounts": {
            "personal1": {
                "account_number": "11111111",
                "label": "Personal 1",
                "name": "Personal Account 1",
                "type": "individual_taxable",
                "tax_status": "taxable",
                "category": "personal",
                "notes": "",
            },
            "personal2": {
                "account_number": "22222222",
                "label": "Personal 2",
                "name": "Personal Account 2",
                "type": "retirement",
                "tax_status": "tax_deferred",
                "category": "personal",
                "notes": "",
            },
            "inherited1": {
                "account_number": "33333333",
                "label": "Inherited",
                "name": "Inherited IRA",
                "type": "inherited_ira",
                "tax_status": "tax_deferred",
                "category": "inherited",
                "notes": "",
            },
        },
    }

    config_path.write_text(json.dumps(test_data))
    with patch("config.secure_account_config.ACCOUNTS_FILE", config_path):
        config = SecureAccountConfig()

        personal_accounts = config.categories.get("personal", [])
        assert len(personal_accounts) == 2

        inherited_accounts = config.categories.get("inherited", [])
        assert len(inherited_accounts) == 1
        assert "33333333" in inherited_accounts


def test_display_label_generation(tmp_path):
    """Test display label generation"""
    config_path = tmp_path / "accounts.json"
    test_data = {
        "version": "1.0",
        "accounts": {
            "test": {
                "account_number": "12345678",
                "label": "Trading",
                "name": "My Trading Account",
                "type": "individual_taxable",
                "tax_status": "taxable",
                "category": "personal",
                "notes": "",
            }
        },
    }

    config_path.write_text(json.dumps(test_data))
    with patch("config.secure_account_config.ACCOUNTS_FILE", config_path):
        config = SecureAccountConfig()

        account = config.account_info.get("test")
        display = account.get_display_label()

        assert "Trading" in display
        assert "...5678" in display  # Last 4 digits
