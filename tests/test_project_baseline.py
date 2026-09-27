import sys
from pathlib import Path
import tomllib

def test_python_runtime_version():
    """Verify that the active runtime is Python 3.13."""
    assert sys.version_info.major == 3, f"Expected Python 3, got {sys.version_info.major}"
    assert sys.version_info.minor == 13, f"Expected Python 3.13, got 3.{sys.version_info.minor}"

def test_project_root_structure():
    """Verify that root pyproject.toml exists and declares the Python 3.13 range."""
    root_dir = Path(__file__).parent.parent
    pyproject_file = root_dir / "pyproject.toml"
    assert pyproject_file.exists(), "pyproject.toml must exist in project root"

    project = tomllib.loads(pyproject_file.read_text(encoding="utf-8"))
    assert project["project"]["requires-python"] == ">=3.13,<3.14"


def test_workspace_packages_share_python_313_requirement():
    """Verify every Python workspace package uses the same runtime range."""
    root_dir = Path(__file__).parent.parent
    package_files = [
        root_dir / "pyproject.toml",
        root_dir / "packages" / "common" / "pyproject.toml",
        root_dir / "packages" / "storage" / "pyproject.toml",
    ]

    for package_file in package_files:
        project = tomllib.loads(package_file.read_text(encoding="utf-8"))
        assert project["project"]["requires-python"] == ">=3.13,<3.14", package_file
