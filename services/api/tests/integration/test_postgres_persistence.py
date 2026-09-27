"""Opt-in PostgreSQL 16 contract tests. Only a marked disposable DB is reset."""

import asyncio
import os
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

import asyncpg
import pytest
from musicsheet_common import JobStatus, PipelineStage

from musicsheet_api.jobs.repository import JobRepository
from musicsheet_api.migrations.runner import Migration, apply_migrations


pytestmark = pytest.mark.integration
_NAME = "musicsheet_test"
_MARKER = "MUSICSHEET_DISPOSABLE_TEST_DB_V1"


class _SecretUrl(str):
    def __repr__(self):
        return "<redacted PostgreSQL test URL>"


def _run(coroutine):
    try:
        return asyncio.run(coroutine)
    except (AssertionError, ValueError):
        raise
    except Exception:
        pytest.fail("PostgreSQL integration operation failed; check the disposable test database", pytrace=False)


@pytest.fixture(scope="module")
def database_url():
    value = os.getenv("MUSICSHEET_TEST_DATABASE_URL")
    if not value:
        pytest.skip("MUSICSHEET_TEST_DATABASE_URL is unset")
    return _SecretUrl(value)


async def _assert_disposable(connection):
    row = await connection.fetchrow(
        "SELECT current_database() AS name, "
        "shobj_description(oid, 'pg_database') AS marker "
        "FROM pg_database WHERE datname = current_database()"
    )
    if row["name"] != _NAME or row["marker"] != _MARKER:
        raise ValueError("Refusing to reset an unmarked disposable test database")


async def _reset_public(database_url):
    connection = await asyncpg.connect(database_url)
    try:
        await _assert_disposable(connection)
        await connection.execute("DROP SCHEMA public CASCADE")
        await connection.execute("CREATE SCHEMA public")
    finally:
        await connection.close()


@pytest.fixture
def clean_database(database_url):
    _run(_reset_public(database_url))
    return database_url


@pytest.fixture
def migrated_database(clean_database):
    assert _run(apply_migrations(clean_database)) == [1]
    return clean_database


def test_guard_rejects_wrong_database_name(database_url):
    parts = urlsplit(database_url)
    wrong_url = urlunsplit(parts._replace(path="/postgres"))

    async def check():
        connection = await asyncpg.connect(wrong_url)
        try:
            with pytest.raises(ValueError, match="Refusing to reset"):
                await _assert_disposable(connection)
        finally:
            await connection.close()

    _run(check())


def test_guard_rejects_missing_or_wrong_database_marker(database_url):
    async def check():
        connection = await asyncpg.connect(database_url)
        try:
            await _assert_disposable(connection)
            # Only the database comment changes, and it is restored before exit.
            for marker in (None, "WRONG_MARKER"):
                try:
                    if marker is None:
                        await connection.execute("COMMENT ON DATABASE musicsheet_test IS NULL")
                    else:
                        await connection.execute(
                            "COMMENT ON DATABASE musicsheet_test IS 'WRONG_MARKER'"
                        )
                    with pytest.raises(ValueError, match="Refusing to reset"):
                        await _assert_disposable(connection)
                finally:
                    await connection.execute(
                        "COMMENT ON DATABASE musicsheet_test IS 'MUSICSHEET_DISPOSABLE_TEST_DB_V1'"
                    )
        finally:
            await connection.close()

    _run(check())


# (type, maximum varchar length, nullable, default)
_COLUMNS = {
    "jobs": {
        "id": ("character varying", 36, "NO", None),
        "user_id": ("character varying", 64, "YES", None),
        "source_type": ("character varying", 16, "NO", None),
        "source_url": ("text", None, "YES", None),
        "target_instrument": ("character varying", 32, "YES", "'piano'::character varying"),
        "status": ("character varying", 20, "NO", "'PENDING'::character varying"),
        "current_stage": ("character varying", 20, "NO", "'DOWNLOAD'::character varying"),
        "stage_progress": ("integer", None, "YES", "0"),
        "overall_progress": ("integer", None, "YES", "0"),
        "error_code": ("character varying", 64, "YES", None),
        "error_message": ("text", None, "YES", None),
        "created_at": ("timestamp with time zone", None, "YES", "CURRENT_TIMESTAMP"),
        "updated_at": ("timestamp with time zone", None, "YES", "CURRENT_TIMESTAMP"),
        "completed_at": ("timestamp with time zone", None, "YES", None),
    },
    "stage_attempts": {
        "id": ("character varying", 36, "NO", None),
        "job_id": ("character varying", 36, "YES", None),
        "stage": ("character varying", 20, "NO", None),
        "attempt": ("integer", None, "NO", "1"),
        "status": ("character varying", 20, "NO", None),
        "provider": ("character varying", 64, "YES", None),
        "model_version": ("character varying", 32, "YES", None),
        "started_at": ("timestamp with time zone", None, "YES", "CURRENT_TIMESTAMP"),
        "completed_at": ("timestamp with time zone", None, "YES", None),
        "duration_ms": ("integer", None, "YES", None),
        "error_code": ("character varying", 64, "YES", None),
        "error_detail": ("text", None, "YES", None),
    },
    "artifacts": {
        "id": ("character varying", 36, "NO", None),
        "job_id": ("character varying", 36, "YES", None),
        "role": ("character varying", 32, "NO", None),
        "filename": ("character varying", 255, "NO", None),
        "uri": ("text", None, "NO", None),
        "mime_type": ("character varying", 64, "NO", None),
        "size_bytes": ("bigint", None, "NO", None),
        "sha256": ("character varying", 64, "NO", None),
        "producer": ("character varying", 64, "YES", None),
        "producer_version": ("character varying", 32, "YES", None),
        "created_at": ("timestamp with time zone", None, "YES", "CURRENT_TIMESTAMP"),
    },
}


def test_initial_migration_creates_all_canonical_tables_indexes_foreign_keys_and_column_metadata(migrated_database):
    async def check():
        connection = await asyncpg.connect(migrated_database)
        try:
            tables = await connection.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            )
            assert {r["tablename"] for r in tables} == {
                "jobs", "stage_attempts", "artifacts", "schema_migrations"
            }
            columns = await connection.fetch(
                "SELECT table_name, column_name, data_type, "
                "character_maximum_length, is_nullable, column_default "
                "FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name IN "
                "('jobs', 'stage_attempts', 'artifacts')"
            )
            actual = {table: {} for table in _COLUMNS}
            for r in columns:
                actual[r["table_name"]][r["column_name"]] = (
                    r["data_type"], r["character_maximum_length"],
                    r["is_nullable"], r["column_default"]
                )
            assert actual == _COLUMNS
            indexes = await connection.fetch(
                "SELECT tablename, indexname, indexdef FROM pg_indexes "
                "WHERE schemaname = 'public'"
            )
            assert {(r["tablename"], r["indexname"]) for r in indexes} == {
                ("jobs", "jobs_pkey"), ("jobs", "idx_jobs_status"),
                ("stage_attempts", "stage_attempts_pkey"),
                ("stage_attempts", "idx_stage_attempts_job_id"),
                ("artifacts", "artifacts_pkey"),
                ("artifacts", "idx_artifacts_job_id"),
                ("schema_migrations", "schema_migrations_pkey"),
            }
            by_name = {r["indexname"]: r["indexdef"] for r in indexes}
            for name, column in (("jobs_pkey", "id"),
                                 ("stage_attempts_pkey", "id"),
                                 ("artifacts_pkey", "id"),
                                 ("schema_migrations_pkey", "version")):
                assert by_name[name].startswith(f"CREATE UNIQUE INDEX {name} ")
                assert by_name[name].endswith(f"USING btree ({column})")
            for name, column in (("idx_jobs_status", "status"),
                                 ("idx_stage_attempts_job_id", "job_id"),
                                 ("idx_artifacts_job_id", "job_id")):
                assert by_name[name].startswith(f"CREATE INDEX {name} ")
                assert by_name[name].endswith(f"USING btree ({column})")
            foreign_keys = await connection.fetch(
                "SELECT c.conname, child.relname AS child_table, "
                "parent.relname AS parent_table, c.confdeltype, "
                "pg_get_constraintdef(c.oid) AS definition "
                "FROM pg_constraint c "
                "JOIN pg_class child ON child.oid = c.conrelid "
                "JOIN pg_class parent ON parent.oid = c.confrelid "
                "JOIN pg_namespace n ON n.oid = child.relnamespace "
                "WHERE n.nspname = 'public' AND c.contype = 'f'"
            )
            assert {(r["conname"], r["child_table"], r["parent_table"],
                     r["confdeltype"].decode(), r["definition"]) for r in foreign_keys} == {
                ("stage_attempts_job_id_fkey", "stage_attempts", "jobs", "c",
                 "FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE"),
                ("artifacts_job_id_fkey", "artifacts", "jobs", "c",
                 "FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE"),
            }
            job_id = str(uuid4())
            row = await connection.fetchrow(
                "INSERT INTO jobs (id, source_type) VALUES ($1, $2) RETURNING "
                "target_instrument, status, current_stage, stage_progress, "
                "overall_progress, created_at, updated_at", job_id, "UPLOAD"
            )
            assert tuple(row[:5]) == ("piano", "PENDING", "DOWNLOAD", 0, 0)
            assert row["created_at"].tzinfo is not None
            assert row["updated_at"].tzinfo is not None
            attempt = await connection.fetchrow(
                "INSERT INTO stage_attempts (id, job_id, stage, status) "
                "VALUES ($1, $2, $3, $4) RETURNING attempt, started_at",
                str(uuid4()), job_id, "DOWNLOAD", "RUNNING"
            )
            assert attempt["attempt"] == 1
            assert attempt["started_at"].tzinfo is not None
            artifact = await connection.fetchrow(
                "INSERT INTO artifacts (id, job_id, role, filename, uri, mime_type, size_bytes, sha256) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING created_at",
                str(uuid4()), job_id, "SOURCE", "input.wav", "file:///tmp/input.wav",
                "audio/wav", 10, "a" * 64
            )
            assert artifact["created_at"].tzinfo is not None
        finally:
            await connection.close()

    _run(check())


def test_migration_is_repeatable(migrated_database):
    assert _run(apply_migrations(migrated_database)) == []

    async def check():
        connection = await asyncpg.connect(migrated_database)
        try:
            assert await connection.fetchval("SELECT count(*) FROM schema_migrations") == 1
            assert await connection.fetchval("SELECT version FROM schema_migrations") == 1
            assert await connection.fetchval("SELECT count(*) FROM pg_tables WHERE schemaname = 'public'") == 4
        finally:
            await connection.close()

    _run(check())


def test_concurrent_migration_runners_apply_once(clean_database):
    async def check():
        results = await asyncio.gather(
            apply_migrations(clean_database), apply_migrations(clean_database)
        )
        assert sorted(results) == [[], [1]]
        connection = await asyncpg.connect(clean_database)
        try:
            assert await connection.fetchval("SELECT count(*) FROM schema_migrations WHERE version = 1") == 1
            assert await connection.fetchval("SELECT count(*) FROM pg_tables WHERE schemaname = 'public'") == 4
        finally:
            await connection.close()

    _run(check())


def test_failed_migration_rolls_back_ddl_and_ledger_entry(clean_database):
    async def check():
        migration = Migration(99, "CREATE TABLE rollback_probe (id INTEGER); SELECT 1 / 0;")
        with pytest.raises(asyncpg.PostgresError):
            await apply_migrations(clean_database, migrations=[migration])
        connection = await asyncpg.connect(clean_database)
        try:
            assert await connection.fetchval("SELECT to_regclass('public.rollback_probe')") is None
            assert await connection.fetchval("SELECT count(*) FROM schema_migrations") == 0
        finally:
            await connection.close()

    _run(check())


def test_job_crud_round_trip(migrated_database):
    async def check():
        pool = await asyncpg.create_pool(migrated_database)
        try:
            repository = JobRepository(pool)
            async with pool.acquire() as connection:
                before = await connection.fetchval("SELECT CURRENT_TIMESTAMP")
            created = await repository.create_job(
                source_type="YOUTUBE", source_url="https://example.test/watch?v=1",
                user_id="user-1"
            )
            async with pool.acquire() as connection:
                after = await connection.fetchval("SELECT CURRENT_TIMESTAMP")
            assert str(UUID(created.id)) == created.id
            assert created.user_id == "user-1"
            assert created.source_type == "YOUTUBE"
            assert created.source_url == "https://example.test/watch?v=1"
            assert created.target_instrument == "piano"
            assert created.status is JobStatus.PENDING
            assert created.current_stage is PipelineStage.DOWNLOAD
            assert (created.stage_progress, created.overall_progress) == (0, 0)
            assert created.error_code is created.error_message is created.completed_at is None
            assert before <= created.created_at <= after
            assert before <= created.updated_at <= after
            assert created.created_at.tzinfo is not None
            assert await repository.get_job(created.id) == created
            updated = await repository.update_progress(
                job_id=created.id, status=JobStatus.COMPLETED,
                current_stage=PipelineStage.RENDER,
                stage_progress=100, overall_progress=100,
                error_message="x'); DROP TABLE jobs; --"
            )
            assert updated.status is JobStatus.COMPLETED
            assert updated.current_stage is PipelineStage.RENDER
            assert updated.completed_at is not None
            assert updated.updated_at >= created.updated_at
            assert updated.completed_at == updated.updated_at
            assert updated.error_message == "x'); DROP TABLE jobs; --"
            assert await repository.get_job(created.id) == updated
            missing = str(uuid4())
            assert await repository.get_job(missing) is None
            assert await repository.update_progress(
                job_id=missing, status=JobStatus.PENDING,
                current_stage=PipelineStage.DOWNLOAD,
                stage_progress=0, overall_progress=0
            ) is None
            assert await repository.get_job(created.id) == updated
        finally:
            await pool.close()

    _run(check())


def test_progress_boundary_values(migrated_database):
    async def check():
        pool = await asyncpg.create_pool(migrated_database)
        try:
            repository = JobRepository(pool)
            job = await repository.create_job(source_type="UPLOAD", source_url=None)
            for value in (0, 100):
                updated = await repository.update_progress(
                    job_id=job.id, status=JobStatus.RUNNING,
                    current_stage=PipelineStage.DOWNLOAD,
                    stage_progress=value, overall_progress=value
                )
                assert (updated.stage_progress, updated.overall_progress) == (value, value)
            for value in (-1, 101, True, 1.5):
                with pytest.raises(ValueError):
                    await repository.update_progress(
                        job_id=job.id, status=JobStatus.RUNNING,
                        current_stage=PipelineStage.DOWNLOAD,
                        stage_progress=value, overall_progress=50
                    )
                with pytest.raises(ValueError):
                    await repository.update_progress(
                        job_id=job.id, status=JobStatus.RUNNING,
                        current_stage=PipelineStage.DOWNLOAD,
                        stage_progress=50, overall_progress=value
                    )
            assert (await repository.get_job(job.id)).overall_progress == 100
        finally:
            await pool.close()

    _run(check())


def test_job_delete_cascades_to_stage_attempts_and_artifacts(migrated_database):
    async def check():
        pool = await asyncpg.create_pool(migrated_database)
        try:
            repository = JobRepository(pool)
            job = await repository.create_job(source_type="UPLOAD", source_url=None)
            async with pool.acquire() as connection:
                await connection.execute(
                    "INSERT INTO stage_attempts (id, job_id, stage, status) VALUES ($1, $2, $3, $4)",
                    str(uuid4()), job.id, "DOWNLOAD", "COMPLETED"
                )
                await connection.execute(
                    "INSERT INTO artifacts (id, job_id, role, filename, uri, mime_type, size_bytes, sha256) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
                    str(uuid4()), job.id, "SOURCE", "input.wav", "file:///tmp/input.wav",
                    "audio/wav", 10, "a" * 64
                )
                assert await connection.fetchval("SELECT count(*) FROM stage_attempts WHERE job_id = $1", job.id) == 1
                assert await connection.fetchval("SELECT count(*) FROM artifacts WHERE job_id = $1", job.id) == 1
                await connection.execute("DELETE FROM jobs WHERE id = $1", job.id)
                assert await connection.fetchval("SELECT count(*) FROM stage_attempts WHERE job_id = $1", job.id) == 0
                assert await connection.fetchval("SELECT count(*) FROM artifacts WHERE job_id = $1", job.id) == 0
        finally:
            await pool.close()

    _run(check())
