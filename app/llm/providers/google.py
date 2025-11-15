"""
Google Gemini provider.
"""
import structlog
import google.generativeai as genai

from app.llm.models import InferenceRequest, InferenceResponse, UsageStats
from app.config import settings


logger = structlog.get_logger()


class GoogleProvider:
    """Google Gemini API provider."""

    def __init__(self):
        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY not configured")

        genai.configure(api_key=settings.gemini_api_key)

    async def generate(self, request: InferenceRequest) -> InferenceResponse:
        """
        Generate response using Google Gemini.

        Args:
            request: Inference request

        Returns:
            InferenceResponse
        """
        try:
            # Get model
            model = genai.GenerativeModel(request.model)

            # Convert messages to Gemini format
            # Gemini uses a simpler format with "user" and "model" roles
            contents = []
            for msg in request.messages:
                role = "model" if msg.role == "assistant" else "user"
                contents.append({"role": role, "parts": [msg.content]})

            # Call Gemini API
            response = await model.generate_content_async(
                contents=contents,
                generation_config=genai.GenerationConfig(
                    max_output_tokens=request.max_tokens or 1024,
                    temperature=request.temperature or 1.0
                )
            )

            # Extract response content
            content = response.text if response.text else ""

            # Gemini doesn't always provide token counts
            input_tokens = getattr(response.usage_metadata, 'prompt_token_count', 0)
            output_tokens = getattr(response.usage_metadata, 'candidates_token_count', 0)

            return InferenceResponse(
                content=content,
                model=request.model,
                usage=UsageStats(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=input_tokens + output_tokens
                ),
                finish_reason=response.candidates[0].finish_reason.name if response.candidates else "STOP"
            )

        except Exception as e:
            logger.error("google_generation_failed", error=str(e))
            raise ValueError(f"Google Gemini API error: {str(e)}")
