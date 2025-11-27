"""
Lightweight LLM request/response models used by inference providers.
"""
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class ModelType(str, Enum):
    """Available LLM models."""

    # Anthropic models
    CLAUDE_HAIKU = "claude-3-haiku-20240307"
    CLAUDE_SONNET = "claude-3-5-sonnet-20241022"

    # OpenAI models
    GPT_4O_MINI = "gpt-4o-mini"
    GPT_4O = "gpt-4o"

    # Google models
    GEMINI_FLASH = "gemini-flash-latest"
    GEMINI_PRO = "gemini-2.5-pro"


class Message(BaseModel):
    """Chat message to send to the provider."""

    role: str = Field(..., pattern="^(user|assistant|system)$")
    content: str


class InferenceRequest(BaseModel):
    """LLM inference request."""

    messages: List[Message]
    model: ModelType = ModelType.GEMINI_FLASH
    max_tokens: Optional[int] = Field(default=1024, le=4096)
    temperature: Optional[float] = Field(default=1.0, ge=0.0, le=2.0)
    stream: bool = False


class UsageStats(BaseModel):
    """Token usage statistics."""

    input_tokens: int
    output_tokens: int
    total_tokens: int


class InferenceResponse(BaseModel):
    """LLM inference response."""

    content: str
    model: str
    usage: UsageStats
    finish_reason: str
