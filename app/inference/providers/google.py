"""
Google Gemini provider used by the E2EE inference pipeline.
"""
import hashlib
import structlog
import google.generativeai as genai

from app.config import settings
from app.inference.llm_models import InferenceRequest, InferenceResponse, UsageStats


logger = structlog.get_logger()


class GoogleProvider:
    """Google Gemini API provider."""

    def __init__(self):
        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY not configured")

        genai.configure(api_key=settings.gemini_api_key)

    async def generate(self, request: InferenceRequest) -> InferenceResponse:
        """Generate a response using Google Gemini."""
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
                    temperature=request.temperature or 1.0,
                ),
            )

            # Extract response content
            content = response.text if response.text else ""

            # Gemini doesn't always provide token counts
            input_tokens = getattr(response.usage_metadata, "prompt_token_count", 0)
            output_tokens = getattr(response.usage_metadata, "candidates_token_count", 0)

            inference_response = InferenceResponse(
                content=content,
                model=request.model,
                usage=UsageStats(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=input_tokens + output_tokens,
                ),
                finish_reason=response.candidates[0].finish_reason.name
                if response.candidates
                else "STOP",
            )

            logger.info(
                "google_gemini_generation",
                model=request.model,
                finish_reason=inference_response.finish_reason,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                candidate_count=len(getattr(response, "candidates", []) or []),
                response_length=len(content),
                response_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest()
                if content
                else None,
                is_empty=not bool(content),
                safety_ratings=[
                    {
                        "category": rating.category,
                        "probability": rating.probability,
                    }
                    for rating in getattr(response, "prompt_feedback", {}).get(
                        "safety_ratings", []
                    )
                ]
                if getattr(response, "prompt_feedback", None)
                else None,
            )

            return inference_response

        except Exception as e:
            logger.error("google_generation_failed", error=str(e))
            raise ValueError(f"Google Gemini API error: {str(e)}")
