import re
from pathlib import Path

import ragleap_agents

ROOT = Path(__file__).resolve().parents[1]


def test_version_matches_pyproject():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    assert m and ragleap_agents.__version__ == m.group(1)


def test_only_one_import_package_is_shipped():
    """ragleap-rag installs the import package `ragleap`; a second package of that
    name in this wheel would overwrite its files."""
    src = ROOT / "src"
    dirs = sorted(p.name for p in src.iterdir() if p.is_dir() and p.name != "__pycache__" and not p.name.endswith(".egg-info"))
    assert dirs == ["ragleap_agents"]
