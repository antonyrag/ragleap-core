import tempfile
from pathlib import Path

import pytest

from ragleap_tools.file_ops import FileOpsConfig, read_file, write_file, list_files, make_file_tools


@pytest.fixture
def sandbox():
    with tempfile.TemporaryDirectory() as d:
        yield FileOpsConfig(root_dir=d)


def test_write_then_read(sandbox):
    r = write_file(sandbox, "hello.txt", "hello world")
    assert r.success
    r = read_file(sandbox, "hello.txt")
    assert r.success
    assert r.result == "hello world"


def test_write_creates_parent_dirs(sandbox):
    r = write_file(sandbox, "sub/dir/file.txt", "nested")
    assert r.success
    r = read_file(sandbox, "sub/dir/file.txt")
    assert r.success and r.result == "nested"


def test_read_nonexistent_file(sandbox):
    r = read_file(sandbox, "does_not_exist.txt")
    assert not r.success
    assert "not found" in r.error.lower()


def test_read_directory_as_file_fails(sandbox):
    Path(sandbox.root_dir, "adir").mkdir()
    r = read_file(sandbox, "adir")
    assert not r.success


@pytest.mark.parametrize("bad_path", [
    "../../../etc/passwd",
    "../../etc/shadow",
    "/etc/passwd",
    "subdir/../../etc/passwd",
])
def test_path_escape_rejected_on_read(sandbox, bad_path):
    r = read_file(sandbox, bad_path)
    assert not r.success


@pytest.mark.parametrize("bad_path", [
    "../../../etc/passwd",
    "/etc/passwd",
])
def test_path_escape_rejected_on_write(sandbox, bad_path):
    r = write_file(sandbox, bad_path, "pwned")
    assert not r.success


def test_symlink_escape_rejected(sandbox):
    real_secret = Path(tempfile.gettempdir()) / "ragleap_tools_pytest_secret.txt"
    real_secret.write_text("SECRET")
    try:
        symlink_path = Path(sandbox.root_dir) / "escape_link"
        symlink_path.symlink_to(real_secret)
        r = read_file(sandbox, "escape_link")
        assert not r.success
    finally:
        real_secret.unlink()


def test_list_files(sandbox):
    write_file(sandbox, "a.txt", "x")
    write_file(sandbox, "b.txt", "y")
    r = list_files(sandbox)
    assert r.success
    assert "a.txt" in r.result
    assert "b.txt" in r.result


def test_list_files_shows_subdirs_with_trailing_slash(sandbox):
    write_file(sandbox, "subdir/file.txt", "x")
    r = list_files(sandbox)
    assert r.success
    assert "subdir/" in r.result


def test_write_content_too_large(sandbox):
    r = write_file(sandbox, "big.txt", "x" * 2_000_000)
    assert not r.success


def test_make_file_tools_returns_three_bound_tools(sandbox):
    tools = make_file_tools(sandbox)
    assert len(tools) == 3
    names = {t.name for t in tools}
    assert names == {"read_file", "write_file", "list_files"}

    write_tool = next(t for t in tools if t.name == "write_file")
    r = write_tool.call(path="via_tool.txt", content="from tool")
    assert r.success
    read_tool = next(t for t in tools if t.name == "read_file")
    r = read_tool.call(path="via_tool.txt")
    assert r.success and r.result == "from tool"
