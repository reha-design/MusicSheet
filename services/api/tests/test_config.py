from pathlib import Path

from musicsheet_api.config import Settings


def test_relative_storage_dir_resolves_from_working_directory(tmp_path: Path) -> None:
    settings = Settings.from_env(
        {"LOCAL_STORAGE_DIR": "var/artifacts"},
        working_directory=tmp_path,
    )

    assert settings.local_storage_dir == tmp_path / "var" / "artifacts"


def test_absolute_storage_dir_stays_unchanged(tmp_path: Path) -> None:
    absolute_path = tmp_path / "artifacts"

    settings = Settings.from_env(
        {"LOCAL_STORAGE_DIR": str(absolute_path)},
        working_directory=tmp_path / "other-working-directory",
    )

    assert settings.local_storage_dir == absolute_path


def test_storage_dir_defaults_to_outputs(tmp_path: Path) -> None:
    settings = Settings.from_env({}, working_directory=tmp_path)

    assert settings.local_storage_dir == tmp_path / "outputs"


def test_empty_storage_dir_uses_outputs_default(tmp_path: Path) -> None:
    settings = Settings.from_env(
        {"LOCAL_STORAGE_DIR": ""},
        working_directory=tmp_path,
    )

    assert settings.local_storage_dir == tmp_path / "outputs"


def test_missing_service_urls_do_not_prevent_settings_creation(
    tmp_path: Path,
) -> None:
    settings = Settings.from_env({}, working_directory=tmp_path)

    assert settings.database_url is None
    assert settings.redis_url is None


def test_service_urls_are_read_from_environment(tmp_path: Path) -> None:
    settings = Settings.from_env(
        {
            "DATABASE_URL": "postgresql://db.internal/music",
            "REDIS_URL": "redis://cache.internal:6379/0",
        },
        working_directory=tmp_path,
    )

    assert settings.database_url == "postgresql://db.internal/music"
    assert settings.redis_url == "redis://cache.internal:6379/0"


def test_diagnostic_executable_overrides_are_read_from_environment(
    tmp_path: Path,
) -> None:
    settings = Settings.from_env(
        {
            "NVIDIA_SMI_BIN": "nvidia-smi-custom",
            "FFMPEG_BIN": "ffmpeg-custom",
            "MUSESCORE_BIN": "musescore-custom",
        },
        working_directory=tmp_path,
    )

    assert settings.nvidia_smi_bin == "nvidia-smi-custom"
    assert settings.ffmpeg_bin == "ffmpeg-custom"
    assert settings.musescore_bin == "musescore-custom"
