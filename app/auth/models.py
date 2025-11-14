"""
Authentication models and schemas.
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


# Request Models
class RegisterRequest(BaseModel):
    """Anonymous user registration request."""
    device_name: Optional[str] = None
    device_type: str = Field(..., pattern="^(desktop|mobile)$")
    platform: str  # macos, windows, linux, ios, android
    public_key: str  # Client's public key for E2EE


class PairDeviceRequest(BaseModel):
    """Request to pair a new device to existing account."""
    device_name: Optional[str] = None
    device_type: str = Field(..., pattern="^(desktop|mobile)$")
    platform: str
    public_key: str


class LoginRequest(BaseModel):
    """Login request with device credentials."""
    user_id: str
    device_id: str


# Response Models
class TokenResponse(BaseModel):
    """Authentication token response."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class RegisterResponse(BaseModel):
    """Registration response."""
    user_id: str
    device_id: str
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class DeviceInfo(BaseModel):
    """Device information."""
    device_id: str
    device_name: Optional[str]
    device_type: str
    platform: str
    public_key: str
    last_sync_at: Optional[int]
    created_at: int


class UserInfo(BaseModel):
    """User information."""
    user_id: str
    created_at: int
    subscription_tier: str = "free"
    subscription_expires_at: Optional[int] = None


# Internal Models
class TokenPayload(BaseModel):
    """JWT token payload."""
    sub: str  # user_id
    device_id: str
    exp: int  # expiration timestamp
    iat: int  # issued at timestamp
    type: str  # access or refresh
