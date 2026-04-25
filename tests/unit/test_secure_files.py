import os
import stat

import pytest

from src.schwab_client._advisor.store import AdvisorStore
from src.schwab_client._history.store import HistoryStore
from src.schwab_client.auth_tokens import TokenManager
from src.schwab_client.secure_files import prepare_sensitive_file, restrict_sqlite_permissions

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX mode assertions")


def mode(path):
    return stat.S_IMODE(path.stat().st_mode)


def test_token_manager_writes_owner_only_token_and_db(tmp_path):
    token_path = tmp_path / ".cli-schwab" / "tokens" / "schwab_token.json"
    manager = TokenManager(token_path=token_path)

    manager.write_token_object({"creation_timestamp": 1_700_000_000, "expires_in": 3600})

    assert mode(token_path.parent.parent) == 0o700
    assert mode(token_path.parent) == 0o700
    assert mode(manager.db_path.parent) == 0o700
    assert mode(token_path) == 0o600
    assert mode(manager.db_path) == 0o600


def test_history_and_advisor_databases_are_owner_only(tmp_path):
    history_path = tmp_path / "private" / "history" / "schwab_history.db"
    advisor_path = tmp_path / "private" / "advisor" / "advisor.db"

    HistoryStore(history_path)
    AdvisorStore(advisor_path).initialize()

    assert mode(history_path.parent.parent) == 0o700
    assert mode(history_path.parent) == 0o700
    assert mode(history_path) == 0o600
    assert mode(advisor_path.parent.parent) == 0o700
    assert mode(advisor_path.parent) == 0o700
    assert mode(advisor_path) == 0o600


def test_prepare_sensitive_file_does_not_chmod_arbitrary_existing_parent(tmp_path):
    tmp_path.chmod(0o755)

    prepare_sensitive_file(tmp_path / "history.db")

    assert mode(tmp_path) == 0o755
    assert mode(tmp_path / "history.db") == 0o600


def test_sqlite_sidecars_are_restricted(tmp_path):
    db_path = tmp_path / "state.db"
    sidecars = [db_path, tmp_path / "state.db-wal", tmp_path / "state.db-shm"]
    for path in sidecars:
        path.write_text("x")
        path.chmod(0o666)

    restrict_sqlite_permissions(db_path)

    for path in sidecars:
        assert mode(path) == 0o600
