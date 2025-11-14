"""
Cryptography helpers for E2EE (End-to-End Encryption).

Note: Server never stores or has access to private keys.
All encryption/decryption happens on client devices.
Server only facilitates key exchange between devices.
"""
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.backends import default_backend
from jose import jwt, JWTError
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import structlog

from app.config import settings


logger = structlog.get_logger()


def create_access_token(user_id: str, device_id: str) -> str:
    """
    Create JWT access token.

    Args:
        user_id: User's UUID
        device_id: Device's UUID

    Returns:
        Encoded JWT token
    """
    now = datetime.utcnow()
    expires = now + timedelta(minutes=settings.access_token_expire_minutes)

    payload = {
        "sub": user_id,
        "device_id": device_id,
        "exp": expires,
        "iat": now,
        "type": "access"
    }

    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token


def create_refresh_token(user_id: str, device_id: str) -> str:
    """
    Create JWT refresh token.

    Args:
        user_id: User's UUID
        device_id: Device's UUID

    Returns:
        Encoded JWT token
    """
    now = datetime.utcnow()
    expires = now + timedelta(days=settings.refresh_token_expire_days)

    payload = {
        "sub": user_id,
        "device_id": device_id,
        "exp": expires,
        "iat": now,
        "type": "refresh"
    }

    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token


def verify_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Verify and decode JWT token.

    Args:
        token: JWT token string

    Returns:
        Decoded token payload or None if invalid
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm]
        )
        return payload
    except JWTError as e:
        logger.warning("token_verification_failed", error=str(e))
        return None


def validate_public_key(public_key_pem: str) -> bool:
    """
    Validate that a public key is properly formatted.

    Args:
        public_key_pem: PEM-encoded public key

    Returns:
        True if valid, False otherwise
    """
    try:
        # Try to load the public key
        serialization.load_pem_public_key(
            public_key_pem.encode(),
            backend=default_backend()
        )
        return True
    except Exception as e:
        logger.warning("invalid_public_key", error=str(e))
        return False


def generate_device_id() -> str:
    """
    Generate a unique device ID.

    Returns:
        Device ID (UUID)
    """
    import uuid
    return str(uuid.uuid4())


def generate_user_id() -> str:
    """
    Generate a unique user ID.

    Returns:
        User ID (UUID)
    """
    import uuid
    return str(uuid.uuid4())


# Note: Actual encryption/decryption of user data happens on client.
# Server only stores encrypted blobs and facilitates key exchange.
# This preserves zero-knowledge architecture.
