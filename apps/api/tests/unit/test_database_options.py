"""Opciones del engine: sin pool en serverless y sin sentencias preparadas en modo transacción."""

import pytest
from sqlalchemy.pool import NullPool

from munych_api.shared.database import Database, engine_options

SESSION = "postgresql+asyncpg://postgres.ref:pw@aws-0-us-east-1.pooler.supabase.com:5432/postgres"
TRANSACTION = SESSION.replace(":5432/", ":6543/")


def test_local_server_keeps_a_small_pool() -> None:
    options = engine_options(SESSION, serverless=False)
    assert options["pool_size"] == 5
    assert "poolclass" not in options
    assert "connect_args" not in options


def test_serverless_uses_no_pool() -> None:
    """En Vercel cada instancia con su pool agotaba los 15 clientes de Supavisor."""
    options = engine_options(SESSION, serverless=True)
    assert options["poolclass"] is NullPool
    assert "pool_size" not in options


def test_transaction_pooler_disables_prepared_statements() -> None:
    args = engine_options(TRANSACTION, serverless=True)["connect_args"]
    assert args["statement_cache_size"] == 0
    assert args["prepared_statement_cache_size"] == 0
    first, second = args["prepared_statement_name_func"](), args["prepared_statement_name_func"]()
    assert first != second


def test_database_detects_vercel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERCEL", "1")
    assert Database(SESSION).serverless
    monkeypatch.delenv("VERCEL")
    assert not Database(SESSION).serverless
