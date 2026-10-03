import os
import stat
import tempfile
import textwrap
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

@pytest.fixture
def fake_claude(tmp_path: Path, monkeypatch):
    """Create a fake `claude` binary in tmp_path that emits one finding."""
    bin_path = tmp_path / "claude"
    bin_path.write_text(textwrap.dedent("""\
        #!/usr/bin/env python3
        import sys, json
        prompt = sys.stdin.read()
        print("reasoning ...", flush=True)
        print("<!-- TLTW:FINDINGS -->")
        print(json.dumps([
            {"severity":"high","file_path":"a.py","line":3,
             "description":"missing null check",
             "finding_key":"a.py:3:missing-null-check"}
        ]))
        print("<!-- TLTW:DONE -->")
    """))
    bin_path.chmod(bin_path.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    return bin_path