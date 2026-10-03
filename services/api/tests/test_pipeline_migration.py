import asyncio

from musicsheet_api.migrations import runner
from test_migrations import FakeConnection, install_connection


def test_fresh_database_applies_v1_and_v2(monkeypatch):
    c = FakeConnection()
    install_connection(monkeypatch,c)
    assert asyncio.run(runner.apply_migrations("example")) == [1,2]
    assert c.versions=={1,2}


def test_v1_upgrade_is_once(monkeypatch):
    c = FakeConnection(versions={1})
    install_connection(monkeypatch,c)
    assert asyncio.run(runner.apply_migrations("example")) == [2]
    assert asyncio.run(runner.apply_migrations("example")) == []
