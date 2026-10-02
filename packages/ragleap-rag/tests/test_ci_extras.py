"""Fails in CI (CI=true) if an optional extra the suite depends on is
missing, so tests that need it cannot silently become skips. Locally
these are skipped."""
import importlib
import os

import pytest

REQUIRED = [
    "faiss", "jsonschema", "qdrant_client", "weaviate", "pinecone", "pymilvus",
    "openpyxl", "xlrd", "xlwt", "pptx", "odf", "striprtf", "bs4", "ebooklib",
    "yaml", "pyarrow", "pandas", "trafilatura", "lxml_html_clean",
]


@pytest.mark.skipif(not os.environ.get("CI"), reason="extras are only enforced in CI")
@pytest.mark.parametrize("module", REQUIRED)
def test_extra_is_installed_in_ci(module):
    importlib.import_module(module)
