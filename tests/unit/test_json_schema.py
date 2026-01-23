"""Tests for JSON schema validation of CLI output."""

import json
from pathlib import Path

import pytest

try:
    import jsonschema
    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False

from tests.conftest import validate_envelope

SCHEMAS_DIR = Path(__file__).parent.parent.parent / "schemas"


def load_schema(name: str) -> dict:
    """Load a JSON schema from the schemas directory."""
    schema_path = SCHEMAS_DIR / f"{name}.json"
    return json.loads(schema_path.read_text())


class TestEnvelopeSchema:
    """Tests for the envelope schema."""

    def test_schema_file_exists(self):
        """Test envelope.json schema file exists."""
        assert (SCHEMAS_DIR / "envelope.json").exists()

    def test_schema_is_valid_json(self):
        """Test envelope schema is valid JSON."""
        schema = load_schema("envelope")
        assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"

    def test_schema_has_required_properties(self):
        """Test schema defines required properties."""
        schema = load_schema("envelope")
        assert "schema_version" in schema["properties"]
        assert "command" in schema["properties"]
        assert "timestamp" in schema["properties"]
        assert "success" in schema["properties"]

    @pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
    def test_valid_success_response(self):
        """Test valid success response passes validation."""
        schema = load_schema("envelope")
        valid = {
            "schema_version": 1,
            "command": "portfolio",
            "timestamp": "2025-01-20T10:30:00",
            "success": True,
            "data": {"total_value": 100000},
            "error": None,
        }
        jsonschema.validate(valid, schema)

    @pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
    def test_valid_error_response(self):
        """Test valid error response passes validation."""
        schema = load_schema("envelope")
        valid = {
            "schema_version": 1,
            "command": "portfolio",
            "timestamp": "2025-01-20T10:30:00",
            "success": False,
            "data": None,
            "error": {
                "message": "Token expired",
                "type": "AuthError",
            },
        }
        jsonschema.validate(valid, schema)

    @pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
    def test_invalid_schema_version_fails(self):
        """Test wrong schema version fails validation."""
        schema = load_schema("envelope")
        invalid = {
            "schema_version": 2,  # Wrong version
            "command": "portfolio",
            "timestamp": "2025-01-20T10:30:00",
            "success": True,
            "data": {},
            "error": None,
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(invalid, schema)

    @pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
    def test_extra_field_fails(self):
        """Test extra fields fail validation."""
        schema = load_schema("envelope")
        invalid = {
            "schema_version": 1,
            "command": "portfolio",
            "timestamp": "2025-01-20T10:30:00",
            "success": True,
            "data": {},
            "error": None,
            "extra_field": "not allowed",
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(invalid, schema)


class TestPortfolioSchema:
    """Tests for portfolio response schema."""

    def test_schema_file_exists(self):
        """Test portfolio.json schema file exists."""
        assert (SCHEMAS_DIR / "portfolio.json").exists()

    @pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
    def test_valid_portfolio_data(self):
        """Test valid portfolio data passes validation."""
        schema = load_schema("portfolio")
        valid = {
            "summary": {
                "total_value": 150000.00,
                "total_cash": 25000.00,
                "total_invested": 125000.00,
                "account_count": 2,
                "position_count": 15,
                "total_unrealized_pl": 12500.00,
                "positions": [
                    {
                        "symbol": "AAPL",
                        "market_value": 50000.00,
                        "unrealized_pl": 5000.00,
                        "quantity": 100,
                        "average_price": 450.00,
                    }
                ],
            }
        }
        jsonschema.validate(valid, schema)

    @pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
    def test_missing_required_field_fails(self):
        """Test missing required field fails validation."""
        schema = load_schema("portfolio")
        invalid = {
            "summary": {
                "total_value": 150000.00,
                # Missing total_cash, total_invested, etc.
            }
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(invalid, schema)


class TestDoctorSchema:
    """Tests for doctor response schema."""

    def test_schema_file_exists(self):
        """Test doctor.json schema file exists."""
        assert (SCHEMAS_DIR / "doctor.json").exists()

    @pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
    def test_valid_doctor_data(self):
        """Test valid doctor data passes validation."""
        schema = load_schema("doctor")
        valid = {
            "data_dir": "/Users/test/.schwab-cli-tools",
            "portfolio": {
                "credentials_present": True,
                "token_path": "/Users/test/.schwab-cli-tools/tokens/token.json",
                "token": {
                    "exists": True,
                    "valid": True,
                    "expires": "2025-01-27T10:00:00",
                },
            },
            "market": {
                "credentials_present": True,
                "token_path": "/Users/test/.schwab-cli-tools/tokens/market_token.json",
                "token": {
                    "exists": True,
                    "valid": True,
                    "expires": "2025-01-27T10:00:00",
                },
            },
            "accounts": {
                "configured": True,
                "count": 3,
                "path": "/Users/test/config/accounts.json",
            },
            "warnings": [],
        }
        jsonschema.validate(valid, schema)


class TestEnvelopeValidator:
    """Tests for the Python envelope validator in conftest."""

    def test_valid_envelope_passes(self):
        """Test valid envelope passes Python validator."""
        valid = {
            "schema_version": 1,
            "command": "test",
            "timestamp": "2025-01-20T10:30:00",
            "success": True,
            "data": {},
            "error": None,
        }
        errors = validate_envelope(valid)
        assert errors == []

    def test_missing_field_detected(self):
        """Test missing field is detected."""
        invalid = {
            "schema_version": 1,
            "command": "test",
            # Missing timestamp and success
        }
        errors = validate_envelope(invalid)
        assert len(errors) >= 2

    def test_wrong_schema_version_detected(self):
        """Test wrong schema version is detected."""
        invalid = {
            "schema_version": 99,
            "command": "test",
            "timestamp": "2025-01-20T10:30:00",
            "success": True,
        }
        errors = validate_envelope(invalid)
        assert any("schema_version" in e for e in errors)

    def test_empty_command_detected(self):
        """Test empty command is detected."""
        invalid = {
            "schema_version": 1,
            "command": "",
            "timestamp": "2025-01-20T10:30:00",
            "success": True,
        }
        errors = validate_envelope(invalid)
        assert any("command" in e for e in errors)

    def test_wrong_success_type_detected(self):
        """Test wrong success type is detected."""
        invalid = {
            "schema_version": 1,
            "command": "test",
            "timestamp": "2025-01-20T10:30:00",
            "success": "true",  # Should be boolean
        }
        errors = validate_envelope(invalid)
        assert any("success" in e for e in errors)

    def test_extra_fields_detected(self):
        """Test extra fields are detected."""
        invalid = {
            "schema_version": 1,
            "command": "test",
            "timestamp": "2025-01-20T10:30:00",
            "success": True,
            "unexpected": "field",
        }
        errors = validate_envelope(invalid)
        assert any("unexpected" in e.lower() or "extra" in e.lower() for e in errors)
