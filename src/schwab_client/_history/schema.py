"""Schema and path helpers for the SQLite history store."""

from __future__ import annotations

from .. import paths as path_utils

HISTORY_DB_ENV_VAR = path_utils.HISTORY_DB_ENV_VAR
resolve_history_db_path = path_utils.resolve_history_db_path

SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS snapshot_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        observed_at TEXT NOT NULL,
        source_command TEXT NOT NULL,
        source_path TEXT UNIQUE,
        includes_manual_accounts INTEGER NOT NULL DEFAULT 0,
        includes_market INTEGER NOT NULL DEFAULT 0,
        error_count INTEGER NOT NULL DEFAULT 0,
        raw_json TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS snapshot_components (
        snapshot_id INTEGER NOT NULL REFERENCES snapshot_runs(id) ON DELETE CASCADE,
        component TEXT NOT NULL,
        success INTEGER NOT NULL,
        error_message TEXT,
        PRIMARY KEY (snapshot_id, component)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS portfolio_snapshots (
        snapshot_id INTEGER PRIMARY KEY REFERENCES snapshot_runs(id) ON DELETE CASCADE,
        total_value REAL NOT NULL,
        api_value REAL NOT NULL DEFAULT 0,
        manual_value REAL NOT NULL DEFAULT 0,
        total_cash REAL NOT NULL DEFAULT 0,
        manual_cash REAL NOT NULL DEFAULT 0,
        total_invested REAL NOT NULL DEFAULT 0,
        total_unrealized_pl REAL NOT NULL DEFAULT 0,
        cash_percentage REAL NOT NULL DEFAULT 0,
        account_count INTEGER NOT NULL DEFAULT 0,
        api_account_count INTEGER NOT NULL DEFAULT 0,
        manual_account_count INTEGER NOT NULL DEFAULT 0,
        position_count INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS accounts (
        account_key TEXT PRIMARY KEY,
        source TEXT NOT NULL,
        external_id TEXT,
        account_alias TEXT,
        account_label TEXT NOT NULL,
        account_type TEXT,
        tax_status TEXT,
        category TEXT,
        provider TEXT,
        last_four TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS account_snapshots (
        snapshot_id INTEGER NOT NULL REFERENCES snapshot_runs(id) ON DELETE CASCADE,
        account_key TEXT NOT NULL REFERENCES accounts(account_key),
        total_value REAL NOT NULL DEFAULT 0,
        cash_balance REAL NOT NULL DEFAULT 0,
        money_market_value REAL NOT NULL DEFAULT 0,
        total_cash REAL NOT NULL DEFAULT 0,
        invested_value REAL NOT NULL DEFAULT 0,
        buying_power REAL NOT NULL DEFAULT 0,
        position_count INTEGER,
        PRIMARY KEY (snapshot_id, account_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS position_snapshots (
        snapshot_id INTEGER NOT NULL REFERENCES snapshot_runs(id) ON DELETE CASCADE,
        account_key TEXT NOT NULL REFERENCES accounts(account_key),
        symbol TEXT NOT NULL,
        asset_type TEXT,
        quantity REAL NOT NULL DEFAULT 0,
        market_value REAL NOT NULL DEFAULT 0,
        average_price REAL NOT NULL DEFAULT 0,
        cost_basis REAL NOT NULL DEFAULT 0,
        unrealized_pl REAL,
        day_pl REAL,
        day_pl_pct REAL,
        weight_pct REAL,
        is_money_market INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (snapshot_id, account_key, symbol)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS market_snapshots (
        snapshot_id INTEGER PRIMARY KEY REFERENCES snapshot_runs(id) ON DELETE CASCADE,
        overall TEXT,
        recommendation TEXT,
        market_sentiment TEXT,
        sector_rotation TEXT,
        vix_value REAL,
        vix_signal TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS index_snapshots (
        snapshot_id INTEGER NOT NULL REFERENCES snapshot_runs(id) ON DELETE CASCADE,
        symbol TEXT NOT NULL,
        name TEXT,
        price REAL,
        change_value REAL,
        change_pct REAL,
        PRIMARY KEY (snapshot_id, symbol)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sector_snapshots (
        snapshot_id INTEGER NOT NULL REFERENCES snapshot_runs(id) ON DELETE CASCADE,
        symbol TEXT NOT NULL,
        sector TEXT,
        price REAL,
        change_pct REAL,
        rank INTEGER,
        PRIMARY KEY (snapshot_id, symbol)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        observed_at TEXT NOT NULL,
        account_key TEXT NOT NULL,
        transaction_date TEXT NOT NULL,
        transaction_type TEXT NOT NULL,
        description TEXT,
        net_amount REAL NOT NULL DEFAULT 0,
        symbol TEXT,
        quantity REAL,
        is_distribution INTEGER NOT NULL DEFAULT 0,
        raw_json TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(account_key, transaction_date, transaction_type, net_amount, description)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_transactions_account ON transactions(account_key)",
    "CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(transaction_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_transactions_distribution ON transactions(is_distribution) WHERE is_distribution = 1",
    """
    CREATE VIEW IF NOT EXISTS distribution_history AS
    SELECT
        t.id,
        t.observed_at,
        t.account_key,
        a.account_label,
        a.account_alias,
        t.transaction_date,
        t.net_amount,
        t.description,
        t.raw_json
    FROM transactions AS t
    JOIN accounts AS a ON a.account_key = t.account_key
    WHERE t.is_distribution = 1
    ORDER BY t.transaction_date DESC
    """,
    """
    CREATE VIEW IF NOT EXISTS distribution_ytd AS
    SELECT
        a.account_label,
        a.account_alias,
        t.account_key,
        SUM(ABS(t.net_amount)) AS ytd_total,
        COUNT(*) AS distribution_count,
        MIN(t.transaction_date) AS first_distribution,
        MAX(t.transaction_date) AS last_distribution
    FROM transactions AS t
    JOIN accounts AS a ON a.account_key = t.account_key
    WHERE t.is_distribution = 1
      AND t.transaction_date >= strftime('%Y-01-01', 'now')
    GROUP BY t.account_key
    """,
    "CREATE INDEX IF NOT EXISTS idx_snapshot_runs_observed_at ON snapshot_runs(observed_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_position_snapshots_symbol ON position_snapshots(symbol)",
    "CREATE INDEX IF NOT EXISTS idx_position_snapshots_account_key ON position_snapshots(account_key)",
    "CREATE INDEX IF NOT EXISTS idx_account_snapshots_account_key ON account_snapshots(account_key)",
    """
    CREATE VIEW IF NOT EXISTS portfolio_history AS
    SELECT
        runs.id AS snapshot_id,
        runs.observed_at,
        runs.source_command,
        runs.source_path,
        runs.error_count,
        portfolio.total_value,
        portfolio.api_value,
        portfolio.manual_value,
        portfolio.total_cash,
        portfolio.manual_cash,
        portfolio.total_invested,
        portfolio.total_unrealized_pl,
        portfolio.cash_percentage,
        portfolio.account_count,
        portfolio.api_account_count,
        portfolio.manual_account_count,
        portfolio.position_count
    FROM snapshot_runs AS runs
    JOIN portfolio_snapshots AS portfolio ON portfolio.snapshot_id = runs.id
    ORDER BY runs.observed_at DESC, runs.id DESC
    """,
    """
    CREATE VIEW IF NOT EXISTS account_history AS
    SELECT
        runs.id AS snapshot_id,
        runs.observed_at,
        accounts.account_key,
        accounts.source AS account_source,
        accounts.external_id,
        accounts.account_alias,
        accounts.account_label,
        accounts.account_type,
        accounts.tax_status,
        accounts.category,
        accounts.provider,
        accounts.last_four,
        snapshots.total_value,
        snapshots.cash_balance,
        snapshots.money_market_value,
        snapshots.total_cash,
        snapshots.invested_value,
        snapshots.buying_power,
        snapshots.position_count
    FROM account_snapshots AS snapshots
    JOIN accounts ON accounts.account_key = snapshots.account_key
    JOIN snapshot_runs AS runs ON runs.id = snapshots.snapshot_id
    ORDER BY runs.observed_at DESC, accounts.account_label ASC
    """,
    """
    CREATE VIEW IF NOT EXISTS position_history AS
    SELECT
        runs.id AS snapshot_id,
        runs.observed_at,
        accounts.account_key,
        accounts.account_alias,
        accounts.account_label,
        accounts.source AS account_source,
        positions.symbol,
        positions.asset_type,
        positions.quantity,
        positions.market_value,
        positions.average_price,
        positions.cost_basis,
        positions.unrealized_pl,
        positions.day_pl,
        positions.day_pl_pct,
        positions.weight_pct,
        positions.is_money_market
    FROM position_snapshots AS positions
    JOIN accounts ON accounts.account_key = positions.account_key
    JOIN snapshot_runs AS runs ON runs.id = positions.snapshot_id
    ORDER BY runs.observed_at DESC, positions.market_value DESC
    """,
    """
    CREATE VIEW IF NOT EXISTS market_history AS
    SELECT
        runs.id AS snapshot_id,
        runs.observed_at,
        market.overall,
        market.recommendation,
        market.market_sentiment,
        market.sector_rotation,
        market.vix_value,
        market.vix_signal
    FROM market_snapshots AS market
    JOIN snapshot_runs AS runs ON runs.id = market.snapshot_id
    ORDER BY runs.observed_at DESC, runs.id DESC
    """,
]
