"""
E2EE inference models and schemas.
"""
from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum
from datetime import datetime


class InferenceTask(str, Enum):
    """Available inference tasks."""
    MEMORY_DISTILLATION = "memory_distillation"
    TAGGING = "tagging"
    INSIGHT_EXTRACTION = "insight_extraction"


class PublicKeyResponse(BaseModel):
    """Server's X25519 public key for E2EE."""
    public_key: str = Field(..., description="Base64-encoded X25519 public key")
    key_id: str = Field(..., description="Key identifier for rotation")
    expires_at: str = Field(..., description="ISO 8601 timestamp of key expiration")
    algorithm: str = Field(default="X25519", description="Key exchange algorithm")


class E2EEInferenceRequest(BaseModel):
    """Encrypted inference request from client."""
    task: InferenceTask = Field(..., description="Inference task to execute")
    encrypted_content: str = Field(..., description="Base64-encoded ChaCha20-Poly1305 ciphertext")
    nonce: str = Field(..., description="Base64-encoded 12-byte nonce")
    mac: str = Field(..., description="Base64-encoded 16-byte authentication tag")
    ephemeral_public_key: str = Field(..., description="Base64-encoded client ephemeral X25519 public key")
    client_version: str = Field(..., description="Client app version for compatibility")


class UsageInfo(BaseModel):
    """User's usage quota information."""
    requests_remaining: int
    reset_at: str = Field(..., description="ISO 8601 timestamp of quota reset")
    tier: str


class E2EEInferenceResponse(BaseModel):
    """Encrypted inference response."""
    encrypted_result: str = Field(..., description="Base64-encoded ChaCha20-Poly1305 ciphertext")
    nonce: str = Field(..., description="Base64-encoded 12-byte nonce")
    mac: str = Field(..., description="Base64-encoded 16-byte authentication tag")
    usage: UsageInfo


class RateLimitErrorResponse(BaseModel):
    """Rate limit exceeded error response."""
    error: str
    usage: UsageInfo


# === Task Output Models ===

class MemoryType(str, Enum):
    """Types of memories that can be extracted."""
    COMMITMENT = "commitment"
    FACT = "fact"
    INSIGHT = "insight"
    PATTERN = "pattern"
    PREFERENCE = "preference"


class Memory(BaseModel):
    """A single extracted memory."""
    type: MemoryType
    content: str
    confidence: float = Field(..., ge=0.0, le=1.0)


class MemoryDistillationResult(BaseModel):
    """Result from memory distillation task."""
    memories: List[Memory]
    confidence: float = Field(..., ge=0.0, le=1.0)


class Tag(BaseModel):
    """A single extracted tag."""
    tag: str
    confidence: float = Field(..., ge=0.0, le=1.0)


class TaggingResult(BaseModel):
    """Result from tagging task."""
    tags: List[Tag]
    confidence: float = Field(..., ge=0.0, le=1.0)


class InsightExtractionResult(BaseModel):
    """Result from insight extraction task."""
    insights: List[str]
    confidence: float = Field(..., ge=0.0, le=1.0)
