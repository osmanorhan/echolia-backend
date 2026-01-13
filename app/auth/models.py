"""
Authentication models and schemas for OAuth-based authentication.
"""
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime


# ========== OAuth Sign-In Models ==========

class OAuthSignInRequest(BaseModel):
    """OAuth sign-in request from mobile/desktop app."""
    provider: str = Field(..., pattern="^(google|apple)$")
    id_token: Optional[str] = Field(None, description="JWT token from OAuth provider (if simplified flow)")
    code: Optional[str] = Field(None, description="Auth code from OAuth provider (if server-side exchange)")
    redirect_uri: Optional[str] = Field(None, description="Redirect URI used for the code")
    code_verifier: Optional[str] = Field(None, description="PKCE verifier")
    device_id: str = Field(..., description="Platform device ID")
    device_name: str = Field(..., description="User-friendly device name")
    platform: str = Field(..., pattern="^(ios|android|macos|windows|linux)$")
    app_version: Optional[str] = None


class UserAddOns(BaseModel):
    """User's active add-ons."""
    sync_enabled: bool = False
    ai_enabled: bool = False
    supporter: bool = False


class OAuthSignInResponse(BaseModel):
    """OAuth sign-in response with tokens and add-on status."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds
    user_id: str
    add_ons: UserAddOns
    turso_db_url: Optional[str] = None
    turso_auth_token: Optional[str] = None


# ========== Token Models ==========

class RefreshTokenRequest(BaseModel):
    """Refresh token request."""
    refresh_token: str


class RefreshTokenResponse(BaseModel):
    """Refresh token response with new tokens."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class TokenPayload(BaseModel):
    """JWT token payload."""
    sub: str  # user_id
    device_id: str
    exp: int  # expiration timestamp
    iat: int  # issued at timestamp
    type: str  # access or refresh


# ========== Device Models ==========

class DeviceInfo(BaseModel):
    """Device information."""
    device_id: str
    user_id: str
    device_name: str
    platform: str
    app_version: Optional[str]
    last_seen_at: int
    created_at: int


class DevicesResponse(BaseModel):
    """List of user's devices."""
    devices: list[DeviceInfo]


class DeleteDeviceResponse(BaseModel):
    """Device deletion response."""
    success: bool
    message: str


# ========== User Info Models ==========

class UserInfoResponse(BaseModel):
    """Current user info."""
    user_id: str
    provider: str
    email: Optional[str]
    name: Optional[str]
    created_at: int
    add_ons: UserAddOns


# ========== Legacy Models (Deprecated) ==========
# These will be removed after migration is complete

class RegisterRequest(BaseModel):
    """DEPRECATED: Anonymous user registration request."""
    device_name: Optional[str] = None
    device_type: str = Field(..., pattern="^(desktop|mobile)$")
    platform: str  # macos, windows, linux, ios, android
    public_key: str  # Client's public key for E2EE


class PairDeviceRequest(BaseModel):
    """DEPRECATED: Request to pair a new device to existing account."""
    device_name: Optional[str] = None
    device_type: str = Field(..., pattern="^(desktop|mobile)$")
    platform: str
    public_key: str


class LoginRequest(BaseModel):
    """DEPRECATED: Login request with device credentials."""
    user_id: str
    device_id: str


class TokenResponse(BaseModel):
    """DEPRECATED: Authentication token response."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class RegisterResponse(BaseModel):
    """DEPRECATED: Registration response."""
    user_id: str
    device_id: str
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
