"""Tests for entity normalization logic."""
import pytest
from app.database import upsert_entity, add_alias, create_tables
from app.normalizer.entity_normalizer import normalize_entity, seed_aliases, invalidate_cache


@pytest.fixture(autouse=True)
def setup_entities(temp_db):
    """Seed some test entities."""
    invalidate_cache()
    upsert_entity("METRIC_GMV", "GMV", "METRIC", "成交总额")
    add_alias("METRIC_GMV", "成交总额")
    add_alias("METRIC_GMV", "流水")
    upsert_entity("METRIC_CTR", "CTR", "METRIC", "点击率")
    add_alias("METRIC_CTR", "点击率")
    invalidate_cache()
    yield
    invalidate_cache()


def test_exact_match():
    result = normalize_entity("GMV", "METRIC")
    assert result == "METRIC_GMV"


def test_alias_match():
    result = normalize_entity("成交总额", "METRIC")
    assert result == "METRIC_GMV"


def test_alias_match_2():
    result = normalize_entity("流水", "METRIC")
    assert result == "METRIC_GMV"


def test_new_entity_creation():
    result = normalize_entity("新指标XYZ", "METRIC")
    assert result is not None
    assert "新指标XYZ" in result or "XYZ" in result


def test_case_insensitive():
    result = normalize_entity("gmv", "METRIC")
    assert result == "METRIC_GMV"
