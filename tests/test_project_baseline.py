import sys
from pathlib import Path

def test_python_runtime_version():
    """Verify that the active runtime is Python 3.12."""
    assert sys.version_info.major == 3, f"Expected Python 3, got {sys.version_info.major}"
    assert sys.version_info.minor == 12, f"Expected Python 3.12, got 3.{sys.version_info.minor}"

def test_project_root_structure():
    """Verify that root pyproject.toml exists and declares Python 3.12 requirement."""
    root_dir = Path(__file__).parent.parent
    pyproject_file = root_dir / "pyproject.toml"
    assert pyproject_file.exists(), "pyproject.toml must exist in project root"

    content = pyproject_file.read_text(encoding="utf-8")
    assert "requires-python" in content, "requires-python must be declared in pyproject.toml"
    assert "3.12" in content, "Python 3.12 constraint must be specified in requires-python"
