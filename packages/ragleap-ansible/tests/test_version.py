import re
from pathlib import Path

import ragleap_ansible


def test_version_matches_pyproject():
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    match = re.search(r'^version = "([^"]+)"', pyproject.read_text(encoding="utf-8"), re.MULTILINE)
    assert match, "no version line found in pyproject.toml"
    assert ragleap_ansible.__version__ == match.group(1)
