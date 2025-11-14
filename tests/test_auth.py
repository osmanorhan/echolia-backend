"""
Tests for authentication endpoints.
"""
import pytest
from fastapi.testclient import TestClient

# Note: These are basic structure tests.
# Full integration tests require Turso setup.


def test_root_endpoint():
    """Test root endpoint returns basic info."""
    from app.main import app
    client = TestClient(app)

    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "service" in data
    assert "version" in data
    assert data["status"] == "operational"


def test_health_check():
    """Test health check endpoint."""
    from app.main import app
    client = TestClient(app)

    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


def test_register_validation():
    """Test registration request validation."""
    from app.auth.models import RegisterRequest
    from pydantic import ValidationError

    # Valid request
    valid_request = RegisterRequest(
        device_name="Test Device",
        device_type="desktop",
        platform="macos",
        public_key="test_key"
    )
    assert valid_request.device_type == "desktop"

    # Invalid device_type
    with pytest.raises(ValidationError):
        RegisterRequest(
            device_name="Test Device",
            device_type="invalid",
            platform="macos",
            public_key="test_key"
        )


def test_token_creation():
    """Test JWT token creation."""
    from app.auth.crypto import create_access_token, create_refresh_token, verify_token

    user_id = "test-user-id"
    device_id = "test-device-id"

    # Create access token
    access_token = create_access_token(user_id, device_id)
    assert access_token is not None
    assert len(access_token) > 0

    # Verify access token
    payload = verify_token(access_token)
    assert payload is not None
    assert payload["sub"] == user_id
    assert payload["device_id"] == device_id
    assert payload["type"] == "access"

    # Create refresh token
    refresh_token = create_refresh_token(user_id, device_id)
    assert refresh_token is not None

    # Verify refresh token
    payload = verify_token(refresh_token)
    assert payload is not None
    assert payload["type"] == "refresh"


def test_id_generation():
    """Test ID generation functions."""
    from app.auth.crypto import generate_user_id, generate_device_id

    user_id = generate_user_id()
    assert len(user_id) > 0
    assert "-" in user_id  # UUID format

    device_id = generate_device_id()
    assert len(device_id) > 0
    assert "-" in device_id

    # Should be unique
    assert generate_user_id() != generate_user_id()
    assert generate_device_id() != generate_device_id()


# Integration tests (require Turso setup)
# Uncomment when Turso is configured

# @pytest.mark.asyncio
# async def test_register_user():
#     """Test user registration flow."""
#     from app.main import app
#     client = TestClient(app)
#
#     response = client.post("/auth/register", json={
#         "device_name": "Test Device",
#         "device_type": "desktop",
#         "platform": "macos",
#         "public_key": "-----BEGIN PUBLIC KEY-----\ntest\n-----END PUBLIC KEY-----"
#     })
#
#     assert response.status_code == 200
#     data = response.json()
#     assert "user_id" in data
#     assert "device_id" in data
#     assert "access_token" in data
#     assert "refresh_token" in data
