import re
from pathlib import Path

import pytest

import ragleap


def test_version_matches_pyproject():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    if not pyproject.exists():
        pytest.skip("pyproject.toml is not next to tests/")
    m = re.search(r'^version\s*=\s*"([^"]+)"', pyproject.read_text(encoding="utf-8"), re.M)
    assert m, "no version found in pyproject.toml"
    assert ragleap.__version__ == m.group(1)
