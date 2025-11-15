"""
Anthropic Claude provider.
"""
import structlog
from anthropic import AsyncAnthropic

from app.llm.models import InferenceRequest, InferenceResponse, UsageStats
from app.config import settings


logger = structlog.get_logger()


class AnthropicProvider:
    """Anthropic Claude API provider."""

    def __init__(self):
        if not settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY not configured")

        self.client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def generate(self, request: InferenceRequest) -> InferenceResponse:
        """
        Generate response using Anthropic Claude.

        Args:
            request: Inference request

        Returns:
            InferenceResponse
        """
        try:
            # Convert messages to Anthropic format
            messages = [
                {"role": msg.role, "content": msg.content}
                for msg in request.messages
                if msg.role != "system"  # System messages handled separately
            ]

            # Extract system message if present
            system_messages = [
                msg.content for msg in request.messages if msg.role == "system"
            ]
            system = system_messages[0] if system_messages else None

            # Call Anthropic API
            response = await self.client.messages.create(
                model=request.model,
                max_tokens=request.max_tokens or 1024,
                temperature=request.temperature or 1.0,
                system=system,
                messages=messages
            )

            # Extract response content
            content = response.content[0].text if response.content else ""

            return InferenceResponse(
                content=content,
                model=response.model,
                usage=UsageStats(
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                    total_tokens=response.usage.input_tokens + response.usage.output_tokens
                ),
                finish_reason=response.stop_reason or "end_turn"
            )

        except Exception as e:
            logger.error("anthropic_generation_failed", error=str(e))
            raise ValueError(f"Anthropic API error: {str(e)}")
