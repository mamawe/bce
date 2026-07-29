"""Tests for database operations and migrations."""
import pytest
from app.database import (
    create_tables,
    insert_document,
    upsert_entity,
    insert_event,
    get_events_for_entity,
    add_alias,
    get_entity_aliases,
    get_all_aliases,
    delete_document,
    get_connection,
)


def test_create_tables_idempotent(temp_db):
    """Calling create_tables twice should not error."""
    create_tables()
    create_tables()


def test_insert_and_get_document(temp_db):
    insert_document("doc_001", "Test Doc", "# Hello", "/test.md", "2026-01-01T00:00:00")
    conn = get_connection()
    row = conn.execute("SELECT * FROM documents WHERE doc_id='doc_001'").fetchone()
    conn.close()
    assert row is not None
    assert row["title"] == "Test Doc"


def test_upsert_entity_preserves_fields(temp_db):
    """Upserting an entity should not reset migration-added fields."""
    upsert_entity("METRIC_TEST", "Test", "METRIC", "desc")
    # Simulate a migration adding sensitivity
    conn = get_connection()
    conn.execute("UPDATE entities SET default_sensitivity=3 WHERE entity_id='METRIC_TEST'")
    conn.commit()
    conn.close()
    # Upsert again - should preserve default_sensitivity
    upsert_entity("METRIC_TEST", "Test Updated", "METRIC", "new desc")
    conn = get_connection()
    row = conn.execute("SELECT * FROM entities WHERE entity_id='METRIC_TEST'").fetchone()
    conn.close()
    assert row["entity_name"] == "Test Updated"
    assert row["default_sensitivity"] == 3  # preserved!


def test_insert_event_with_metric_values(temp_db):
    upsert_entity("METRIC_GMV", "GMV", "METRIC", "成交总额")
    insert_document("doc_001", "Test", "content", "/test.md", "2026-01-01T00:00:00")
    insert_event(
        event_id="evt_001",
        entity_id="METRIC_GMV",
        occurred_at="2026-07-01",
        time_granularity="WEEK",
        summary="GMV +3.1%",
        event_type="FLUCTUATION",
        attribution="市场增长",
        document_id="doc_001",
        metric_value=1520.0,
        metric_unit="万元",
        metric_delta=46.0,
        metric_delta_pct=3.1,
    )
    events = get_events_for_entity("METRIC_GMV")
    assert len(events) == 1
    assert events[0]["metric_value"] == 1520.0
    assert events[0]["metric_unit"] == "万元"


def test_get_all_aliases_batch(temp_db):
    upsert_entity("METRIC_GMV", "GMV", "METRIC", "")
    upsert_entity("METRIC_CTR", "CTR", "METRIC", "")
    add_alias("METRIC_GMV", "成交总额")
    add_alias("METRIC_GMV", "流水")
    add_alias("METRIC_CTR", "点击率")

    all_aliases = get_all_aliases()
    assert "METRIC_GMV" in all_aliases
    assert "成交总额" in all_aliases["METRIC_GMV"]
    assert "流水" in all_aliases["METRIC_GMV"]
    assert "METRIC_CTR" in all_aliases
    assert "点击率" in all_aliases["METRIC_CTR"]


def test_alias_unique_constraint(temp_db):
    upsert_entity("METRIC_GMV", "GMV", "METRIC", "")
    add_alias("METRIC_GMV", "成交总额")
    # Adding same alias again should not create duplicate
    add_alias("METRIC_GMV", "成交总额")
    aliases = get_entity_aliases("METRIC_GMV")
    assert aliases.count("成交总额") == 1


def test_delete_document_cascade(temp_db):
    upsert_entity("METRIC_GMV", "GMV", "METRIC", "")
    insert_document("doc_001", "Test", "content", "/test.md", "2026-01-01T00:00:00")
    insert_event("evt_001", "METRIC_GMV", "2026-07-01", "WEEK", "test", "FLUCTUATION", "归因", "doc_001")
    delete_document("doc_001")
    events = get_events_for_entity("METRIC_GMV")
    assert len(events) == 0
