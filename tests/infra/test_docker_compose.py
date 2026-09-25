import json
import shutil
import subprocess
from pathlib import Path
import pytest

ROOT_DIR = Path(__file__).parent.parent.parent
COMPOSE_FILE = ROOT_DIR / "docker" / "docker-compose.yml"
ENV_EXAMPLE_FILE = ROOT_DIR / ".env.example"

def test_compose_files_exist():
    """Verify that docker-compose.yml and .env.example exist in expected paths."""
    assert COMPOSE_FILE.exists(), f"Compose file missing at: {COMPOSE_FILE}"
    assert ENV_EXAMPLE_FILE.exists(), f".env.example missing at: {ENV_EXAMPLE_FILE}"

def test_env_example_contains_required_keys():
    """Verify that .env.example declares all necessary connection variables."""
    content = ENV_EXAMPLE_FILE.read_text(encoding="utf-8")
    required_keys = [
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "DATABASE_URL",
        "REDIS_HOST",
        "REDIS_PORT",
        "REDIS_URL",
        "CELERY_BROKER_URL",
        "CELERY_RESULT_BACKEND",
        "LOCAL_STORAGE_DIR",
    ]
    for key in required_keys:
        assert key in content, f"Key '{key}' must be defined in .env.example"

def test_docker_compose_config_validation():
    """Validate docker-compose.yml structure via 'docker compose config --format json'."""
    docker_bin = shutil.which("docker")
    if not docker_bin:
        pytest.skip("Docker CLI is not installed on this system")

    result = subprocess.run(
        [docker_bin, "compose", "-f", str(COMPOSE_FILE), "config", "--format", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"docker compose config failed: {result.stderr}"

    config = json.loads(result.stdout)
    services = config.get("services", {})
    assert "postgres" in services, "PostgreSQL service must be defined in compose file"
    assert "redis" in services, "Redis service must be defined in compose file"

    postgres_svc = services["postgres"]
    assert "postgres:16" in postgres_svc.get("image", ""), "PostgreSQL image must be 16-alpine"
    assert "healthcheck" in postgres_svc, "PostgreSQL must have healthcheck defined"

    redis_svc = services["redis"]
    assert "redis:7" in redis_svc.get("image", ""), "Redis image must be 7-alpine"
    assert "healthcheck" in redis_svc, "Redis must have healthcheck defined"

    volumes = config.get("volumes", {})
    assert "postgres_data" in volumes, "postgres_data volume must be declared"
    assert "redis_data" in volumes, "redis_data volume must be declared"
