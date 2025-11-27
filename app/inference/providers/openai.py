"""
OpenAI GPT provider used by the E2EE inference pipeline.
"""
import structlog
from openai import AsyncOpenAI

from app.config import settings
from app.inference.llm_models import InferenceRequest, InferenceResponse, UsageStats


logger = structlog.get_logger()


class OpenAIProvider:
    """OpenAI GPT API provider."""

    def __init__(self):
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY not configured")

        self.client = AsyncOpenAI(api_key=settings.openai_api_key)

    async def generate(self, request: InferenceRequest) -> InferenceResponse:
        """Generate a response using OpenAI GPT."""
        try:
            # Convert messages to OpenAI format
            messages = [
                {"role": msg.role, "content": msg.content} for msg in request.messages
            ]

            # Call OpenAI API
            response = await self.client.chat.completions.create(
                model=request.model,
                messages=messages,
                max_tokens=request.max_tokens or 1024,
                temperature=request.temperature or 1.0,
            )

            # Extract response content
            content = response.choices[0].message.content or ""

            return InferenceResponse(
                content=content,
                model=response.model,
                usage=UsageStats(
                    input_tokens=response.usage.prompt_tokens,
                    output_tokens=response.usage.completion_tokens,
                    total_tokens=response.usage.total_tokens,
                ),
                finish_reason=response.choices[0].finish_reason or "stop",
            )

        except Exception as e:
            logger.error("openai_generation_failed", error=str(e))
            raise ValueError(f"OpenAI API error: {str(e)}")
