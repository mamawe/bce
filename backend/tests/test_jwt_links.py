"""Tests for JWT push link generation and validation."""
import os
import time
import pytest

# Set a test secret before importing
os.environ["BCE_JWT_SECRET"] = "test-secret-key-for-unit-tests"

from app.auth.jwt_links import generate_push_link, validate_push_link, check_link_access


def test_generate_and_validate():
    link = generate_push_link("http://localhost:5173", "doc_001", "user_001", "analyst")
    assert "/view/doc_001?auth=" in link
    # Extract token
    token = link.split("?auth=")[1]
    payload = validate_push_link(token)
    assert payload["doc_id"] == "doc_001"
    assert payload["user_id"] == "user_001"
    assert payload["role"] == "analyst"


def test_expired_token():
    import jwt as pyjwt
    from app.auth.jwt_links import SECRET_KEY, ALGORITHM
    payload = {
        "token_type": "push_link",
        "doc_id": "doc_001",
        "user_id": "user_001",
        "role": "analyst",
        "iat": int(time.time()) - 86400 * 8,  # 8 days ago
        "exp": int(time.time()) - 86400,  # expired 1 day ago
    }
    token = pyjwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    with pytest.raises(pyjwt.ExpiredSignatureError):
        validate_push_link(token)


def test_tampered_token():
    import jwt as pyjwt
    link = generate_push_link("http://localhost:5173", "doc_001", "user_001", "analyst")
    token = link.split("?auth=")[1]
    # Tamper with the token
    tampered = token[:-5] + "XXXXX"
    with pytest.raises(pyjwt.InvalidTokenError):
        validate_push_link(tampered)


def test_check_link_access_no_db_user():
    link = generate_push_link("http://localhost:5173", "doc_001", "nonexistent_user", "analyst")
    token = link.split("?auth=")[1]

    class FakeDB:
        def get_user(self, uid):
            return None

    result = check_link_access(token, FakeDB())
    assert result["allowed"] is False
    assert result["reason"] == "user_not_found"
