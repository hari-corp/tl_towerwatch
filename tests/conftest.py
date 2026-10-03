import os
import tempfile
from pathlib import Path
import pytest

@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    return d

@pytest.fixture
def env(monkeypatch, tmp_data_dir):
    monkeypatch.setenv("TOWERWATCH_DATA_DIR", str(tmp_data_dir))
    return tmp_data_dir