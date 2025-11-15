"""
OpenAI GPT provider.
"""
import structlog
from openai import AsyncOpenAI

from app.llm.models import InferenceRequest, InferenceResponse, UsageStats
from app.config import settings


logger = structlog.get_logger()


class OpenAIProvider:
    """OpenAI GPT API provider."""

    def __init__(self):
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY not configured")

        self.client = AsyncOpenAI(api_key=settings.openai_api_key)

    async def generate(self, request: InferenceRequest) -> InferenceResponse:
        """
        Generate response using OpenAI GPT.

        Args:
            request: Inference request

        Returns:
            InferenceResponse
        """
        try:
            # Convert messages to OpenAI format
            messages = [
                {"role": msg.role, "content": msg.content}
                for msg in request.messages
            ]

            # Call OpenAI API
            response = await self.client.chat.completions.create(
                model=request.model,
                messages=messages,
                max_tokens=request.max_tokens or 1024,
                temperature=request.temperature or 1.0
            )

            # Extract response content
            content = response.choices[0].message.content or ""

            return InferenceResponse(
                content=content,
                model=response.model,
                usage=UsageStats(
                    input_tokens=response.usage.prompt_tokens,
                    output_tokens=response.usage.completion_tokens,
                    total_tokens=response.usage.total_tokens
                ),
                finish_reason=response.choices[0].finish_reason or "stop"
            )

        except Exception as e:
            logger.error("openai_generation_failed", error=str(e))
            raise ValueError(f"OpenAI API error: {str(e)}")
