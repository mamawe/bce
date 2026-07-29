"""Tests for permission checking logic."""
import pytest
from app.auth.permissions import (
    check_entity_access,
    filter_events_by_sensitivity,
    get_user_max_sensitivity,
)


def test_role_sensitivity_mapping():
    assert get_user_max_sensitivity("admin") == 4
    assert get_user_max_sensitivity("executive") == 4
    assert get_user_max_sensitivity("dept_lead") == 3
    assert get_user_max_sensitivity("analyst") == 2
    assert get_user_max_sensitivity("guest") == 1
    assert get_user_max_sensitivity("unknown_role") == 1


def test_check_entity_access_allowed():
    user = {"max_sensitivity": 3, "has_global_view": True, "categories": []}
    entity = {"default_sensitivity": 2, "is_overall": True, "category_scope": None}
    result = check_entity_access(user, entity)
    assert result["allowed"] is True


def test_check_entity_access_level_denied():
    user = {"max_sensitivity": 1, "has_global_view": True, "categories": []}
    entity = {"default_sensitivity": 3, "is_overall": True, "category_scope": None}
    result = check_entity_access(user, entity)
    assert result["allowed"] is False
    assert result["reason"] == "level_denied"


def test_check_entity_access_category_denied():
    user = {"max_sensitivity": 4, "has_global_view": False, "categories": ["肉类"]}
    entity = {"default_sensitivity": 1, "is_overall": True, "category_scope": None}
    result = check_entity_access(user, entity)
    assert result["allowed"] is False
    assert result["reason"] == "category_denied"


def test_check_entity_access_no_user():
    entity = {"default_sensitivity": 4, "is_overall": True, "category_scope": None}
    result = check_entity_access(None, entity)
    assert result["allowed"] is True  # backward compatible


def test_filter_events_by_sensitivity():
    events = [
        {"event_id": "e1", "sensitivity_level": 1, "summary": "public"},
        {"event_id": "e2", "sensitivity_level": 3, "summary": "sensitive"},
        {"event_id": "e3", "sensitivity_level": 4, "summary": "confidential"},
    ]
    user = {"max_sensitivity": 2, "has_global_view": True, "categories": []}
    filtered = filter_events_by_sensitivity(events, user)
    assert len(filtered) == 1
    assert filtered[0]["event_id"] == "e1"


def test_filter_events_no_user():
    events = [{"event_id": "e1", "sensitivity_level": 4}]
    filtered = filter_events_by_sensitivity(events, None)
    assert len(filtered) == 1  # no auth = see everything
