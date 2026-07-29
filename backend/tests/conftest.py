"""Shared test fixtures for BCE backend tests."""
import os
import sys
import pytest
from pathlib import Path

# Ensure app is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Use a temporary database for tests
os.environ["BCE_ENV"] = "test"


@pytest.fixture(autouse=True)
def temp_db(monkeypatch, tmp_path):
    """Use a fresh temporary database for each test."""
    db_path = tmp_path / "test_bce.db"
    monkeypatch.setattr("app.database.DB_PATH", db_path)
    # Create tables
    from app.database import create_tables
    create_tables()
    yield str(db_path)
