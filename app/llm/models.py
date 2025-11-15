"""
LLM inference models and schemas.
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum


class ModelType(str, Enum):
    """Available LLM models."""
    # Anthropic models
    CLAUDE_HAIKU = "claude-3-haiku-20240307"
    CLAUDE_SONNET = "claude-3-5-sonnet-20241022"

    # OpenAI models
    GPT_4O_MINI = "gpt-4o-mini"
    GPT_4O = "gpt-4o"

    # Google models
    GEMINI_FLASH = "gemini-1.5-flash"
    GEMINI_PRO = "gemini-1.5-pro"


class Message(BaseModel):
    """Chat message."""
    role: str = Field(..., pattern="^(user|assistant|system)$")
    content: str


class InferenceRequest(BaseModel):
    """LLM inference request."""
    messages: List[Message]
    model: ModelType = ModelType.CLAUDE_HAIKU
    max_tokens: Optional[int] = Field(default=1024, le=4096)
    temperature: Optional[float] = Field(default=1.0, ge=0.0, le=2.0)
    stream: bool = False


class InferenceResponse(BaseModel):
    """LLM inference response."""
    content: str
    model: str
    usage: "UsageStats"
    finish_reason: str


class UsageStats(BaseModel):
    """Token usage statistics."""
    input_tokens: int
    output_tokens: int
    total_tokens: int


class UsageTier(str, Enum):
    """Usage tier for the user."""
    FREE = "free"
    AI_ADD_ON = "ai_add_on"


class UsageQuota(BaseModel):
    """User's usage quota information."""
    tier: UsageTier
    requests_today: int
    daily_limit: int
    requests_remaining: int
    hourly_limit: Optional[int] = None
    can_make_request: bool


class ModelInfo(BaseModel):
    """Information about an available model."""
    id: str
    name: str
    provider: str
    context_window: int
    requires_add_on: bool


class ModelsResponse(BaseModel):
    """List of available models."""
    models: List[ModelInfo]
    user_tier: UsageTier


class UsageResponse(BaseModel):
    """User's usage statistics."""
    tier: UsageTier
    quota: UsageQuota
    total_requests_all_time: int
    total_tokens_all_time: int
