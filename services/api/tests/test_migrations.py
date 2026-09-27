import asyncio

import pytest

from musicsheet_api.migrations import cli, runner


class FakeTransaction:
    def __init__(self, connection: "FakeConnection") -> None:
        self.connection = connection

    async def __aenter__(self) -> None:
        self.connection.events.append(("begin",))
        self.connection.pending = []

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        if exc_type is None:
            self.connection.versions.update(self.connection.pending)
            self.connection.events.append(("commit",))
        else:
            self.connection.events.append(("rollback",))
        self.connection.pending = []


class FakeConnection:
    def __init__(self, *, versions: set[int] | None = None, fail_sql: str | None = None) -> None:
        self.versions = set() if versions is None else set(versions)
        self.fail_sql = fail_sql
        self.events: list[tuple] = []
        self.pending: list[int] = []

    async def execute(self, query: str, *args: object) -> str:
        self.events.append(("execute", query, args))
        if self.fail_sql and self.fail_sql in query:
            raise RuntimeError("secret driver error")
        if "INSERT INTO schema_migrations" in query:
            self.pending.append(args[0])
        return "OK"

    async def fetch(self, query: str) -> list[dict[str, int]]:
        self.events.append(("fetch", query))
        return [{"version": version} for version in sorted(self.versions)]

    def transaction(self) -> FakeTransaction:
        return FakeTransaction(self)

    async def close(self) -> None:
        self.events.append(("close",))


def install_connection(monkeypatch: pytest.MonkeyPatch, connection: FakeConnection) -> list[str]:
    urls: list[str] = []

    async def connect(database_url: str) -> FakeConnection:
        urls.append(database_url)
        return connection

    monkeypatch.setattr(runner.asyncpg, "connect", connect)
    return urls


def test_applies_migrations_in_version_order(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = FakeConnection()
    urls = install_connection(monkeypatch, connection)
    migrations = [runner.Migration(2, "SELECT 'second'"), runner.Migration(1, "SELECT 'first'")]

    assert asyncio.run(runner.apply_migrations("postgresql://example/db", migrations=migrations)) == [1, 2]
    assert urls == ["postgresql://example/db"]
    assert connection.versions == {1, 2}
    assert [event[1] for event in connection.events if event[0] == "execute" and "SELECT '" in event[1]] == ["SELECT 'first'", "SELECT 'second'"]
    assert [event[0] for event in connection.events].count("commit") == 2


def test_skips_already_applied_migration(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = FakeConnection(versions={1})
    install_connection(monkeypatch, connection)

    assert asyncio.run(runner.apply_migrations("dsn", migrations=[runner.Migration(1, "SELECT 'old'"), runner.Migration(2, "SELECT 'new'")])) == [2]
    assert not any("SELECT 'old'" in event[1] for event in connection.events if event[0] == "execute")
    assert connection.versions == {1, 2}


def test_uses_one_connection_for_lock_ledger_and_migrations(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = FakeConnection()
    urls = install_connection(monkeypatch, connection)

    asyncio.run(runner.apply_migrations("dsn", migrations=[runner.Migration(1, "SELECT 1")]))

    assert urls == ["dsn"]
    assert any("pg_advisory_lock" in event[1] for event in connection.events if event[0] == "execute")
    assert any("CREATE TABLE IF NOT EXISTS schema_migrations" in event[1] for event in connection.events if event[0] == "execute")
    assert any(event[0] == "fetch" for event in connection.events)
    assert any("SELECT 1" == event[1] for event in connection.events if event[0] == "execute")
    assert connection.events[-1] == ("close",)


def test_acquires_lock_before_ledger_access(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = FakeConnection()
    install_connection(monkeypatch, connection)

    asyncio.run(runner.apply_migrations("dsn", migrations=[]))

    first_lock = next(i for i, event in enumerate(connection.events) if event[0] == "execute" and "pg_advisory_lock" in event[1])
    first_ledger = next(i for i, event in enumerate(connection.events) if "schema_migrations" in event[1])
    assert first_lock < first_ledger


def test_failed_migration_rolls_back_version_record(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = FakeConnection(fail_sql="INSERT INTO schema_migrations")
    install_connection(monkeypatch, connection)

    with pytest.raises(RuntimeError, match="secret driver error"):
        asyncio.run(runner.apply_migrations("dsn", migrations=[runner.Migration(1, "SELECT 1")]))

    assert connection.versions == set()
    assert ("rollback",) in connection.events
    assert any("INSERT INTO schema_migrations" in event[1] for event in connection.events if event[0] == "execute")


def test_releases_lock_and_closes_connection_after_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = FakeConnection(fail_sql="BROKEN")
    install_connection(monkeypatch, connection)

    with pytest.raises(RuntimeError):
        asyncio.run(runner.apply_migrations("dsn", migrations=[runner.Migration(1, "BROKEN")]))

    assert "pg_advisory_unlock" in connection.events[-2][1]
    assert connection.events[-1] == ("close",)


def test_cli_missing_database_url_uses_sanitized_error(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert cli.main() != 0
    output = capsys.readouterr()
    assert "DATABASE_URL" in output.err
    assert "Traceback" not in output.err


def test_cli_migration_failure_omits_dsn_and_driver_details(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    database_url = "postgresql://secret_user:secret_password@secret-host/private"
    monkeypatch.setenv("DATABASE_URL", database_url)

    async def fail(database_url: str) -> list[int]:
        raise RuntimeError(f"driver failure for {database_url}")

    monkeypatch.setattr(cli, "apply_migrations", fail)

    assert cli.main() != 0
    output = capsys.readouterr()
    assert "migration" in output.err.lower()
    assert not any(secret in output.out + output.err for secret in (database_url, "secret_user", "secret_password", "secret-host", "driver failure", "Traceback"))
