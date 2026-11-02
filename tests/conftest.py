from pathlib import Path
import pytest

@pytest.fixture
def fs_chdir(tmp_path, monkeypatch):
    """Run the test in a fresh empty CWD and restore afterwards."""
    monkeypatch.chdir(tmp_path)
    return tmp_path

@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    return d

@pytest.fixture
def env(monkeypatch, tmp_data_dir):
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_data_dir))
    return tmp_data_dir