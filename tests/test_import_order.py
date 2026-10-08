import subprocess
import sys

import pytest

MODULES = ["core.embedding", "core.settings", "core.generation", "core.employees.memory",
           "core.retrieval", "core.chat", "core.ingest", "core.api", "core.setup_status", "core.vector_dims",
           "core.auth_throttle"]


@pytest.mark.parametrize("module", MODULES)
def test_module_imports_first_in_a_fresh_interpreter(module):
    r = subprocess.run([sys.executable, "-c", "import " + module], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-400:]
