"""
Tests for core/api.py's sync_integration() endpoint - covers the new
learn_from_integration_action() call added after a successful/failed
sync, using integrations_service.sync_data_source()'s and
get_data_source()'s real return shapes. Called directly (plain
function under @app.post), integrations_service and employee_learning
mocked, no live DB/API needed.
"""
import os
import sys
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://ragleap:ragleap@localhost:5433/ragleap_core")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.api import sync_integration, integrations_service, employee_learning
from core.integrations.base import DataSource


def _make_data_source(name="My CRM"):
    return DataSource(id="ds-1", name=name, source_type="rest_api")


def test_successful_sync_records_learned_skill():
    with patch.object(integrations_service, "sync_data_source",
                       return_value={"success": True, "records_synced": 42}), \
         patch.object(integrations_service, "get_data_source",
                       return_value=_make_data_source("Salesforce")), \
         patch.object(employee_learning, "learn_from_integration_action") as mock_learn:
        result = sync_integration("ds-1")
    assert result == {"success": True, "records_synced": 42}
    mock_learn.assert_called_once_with("Salesforce", "sync", "success: 42 records synced")


def test_failed_sync_records_learned_skill_with_error():
    with patch.object(integrations_service, "sync_data_source",
                       return_value={"success": False, "error": "connection timeout"}), \
         patch.object(integrations_service, "get_data_source",
                       return_value=_make_data_source("HubSpot")), \
         patch.object(employee_learning, "learn_from_integration_action") as mock_learn:
        result = sync_integration("ds-1")
    assert result == {"success": False, "error": "connection timeout"}
    mock_learn.assert_called_once_with("HubSpot", "sync", "failed: connection timeout")


def test_data_source_not_found_raises_404_and_does_not_learn():
    from fastapi import HTTPException
    with patch.object(integrations_service, "sync_data_source",
                       return_value={"success": False, "error": "Data source not found"}), \
         patch.object(employee_learning, "learn_from_integration_action") as mock_learn:
        try:
            sync_integration("nonexistent")
            assert False, "expected HTTPException"
        except HTTPException as e:
            assert e.status_code == 404
    mock_learn.assert_not_called()
