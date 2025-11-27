"""
E2EE inference task processors using LLM providers.
"""
import json
import hashlib
import structlog
from typing import Optional

from app.inference.models import (
    InferenceTask,
    MemoryDistillationResult,
    TaggingResult,
    InsightExtractionResult,
    CaptureMetadataResult,
    CaptureIntent,
    ProviderInfo,
    Memory,
    MemoryType,
    Tag
)
from app.inference.llm_models import InferenceRequest, Message, ModelType
from app.inference.providers.anthropic import AnthropicProvider
from app.inference.providers.openai import OpenAIProvider
from app.inference.providers.google import GoogleProvider
from app.config import settings


logger = structlog.get_logger()


class TaskProcessor:
    """
    Processes inference tasks by calling LLM providers.

    Privacy-first: processes in ephemeral memory, no plaintext logging.
    """

    def __init__(self):
        self._provider = None
        self._model = None
        self._provider_name = None

    def _ensure_provider(self):
        """Lazily initialize the LLM provider."""
        if self._provider is not None:
            return

        if settings.gemini_api_key:
            self._provider = GoogleProvider()
            self._model = ModelType.GEMINI_FLASH  # Fast and cheap for simple tasks
            self._provider_name = "google"
        elif settings.openai_api_key:
            self._provider = OpenAIProvider()
            self._model = ModelType.GPT_4O_MINI
            self._provider_name = "openai"
        elif settings.anthropic_api_key:
            self._provider = AnthropicProvider()
            self._model = ModelType.CLAUDE_HAIKU
            self._provider_name = "anthropic"
        else:
            raise ValueError("No LLM provider API key configured")

    def _get_model_for_provider(self):
        """Get the appropriate model for the current provider."""
        self._ensure_provider()
        return self._model

    def get_provider_info(self) -> ProviderInfo:
        """
        Expose the currently configured provider and model without probing availability.
        """
        try:
            self._ensure_provider()
        except ValueError:
            return ProviderInfo(provider=None, model=None)

        model = self._get_model_for_provider()
        model_name = model.value if isinstance(model, ModelType) else str(model)

        return ProviderInfo(provider=self._provider_name, model=model_name)

    async def process_task(self, task: InferenceTask, plaintext_content: str) -> str:
        """
        Process an inference task on plaintext content.

        Args:
            task: The inference task to execute
            plaintext_content: Decrypted user content

        Returns:
            JSON string of task result

        Note: plaintext_content should be cleared from memory after this call
        """
        try:
            if task == InferenceTask.MEMORY_DISTILLATION:
                result = await self._memory_distillation(plaintext_content)
                result_json = result.model_dump_json(by_alias=True)
            elif task == InferenceTask.TAGGING:
                result = await self._tagging(plaintext_content)
                result_json = result.model_dump_json(by_alias=True)
            elif task == InferenceTask.INSIGHT_EXTRACTION:
                result = await self._insight_extraction(plaintext_content)
                result_json = result.model_dump_json(by_alias=True)
            elif task == InferenceTask.CAPTURE_METADATA:
                metadata = await self._capture_metadata(plaintext_content)
                # Wrap to match client-side InferenceResult schema
                result_json = json.dumps(
                    {
                        "capture_metadata": metadata.model_dump(by_alias=True),
                        "confidence": metadata.confidence,
                    }
                )
            else:
                raise ValueError(f"Unknown task: {task}")

            logger.info(
                "task_result_summary",
                task=task,
                provider=self._provider_name,
                model=str(self._get_model_for_provider()),
                result_length=len(result_json),
                result_sha256=hashlib.sha256(result_json.encode("utf-8")).hexdigest(),
            )

            return result_json

        except Exception as e:
            logger.error("task_processing_failed", task=task, error=str(e))
            raise

    async def _memory_distillation(self, content: str) -> MemoryDistillationResult:
        """
        Extract memories (commitments, facts, insights, patterns, preferences) from text.
        """
        system_prompt = """You are a memory extraction assistant. Your task is to identify and extract important memories from journal entries. Focus on:

1. Commitments - Future actions or promises ("I will...", "Need to...", "Should call...")
2. Facts - Learned information ("Flutter uses Dart", "The meeting is at 3pm")
3. Insights - Realizations or conclusions ("I realized that...", "Understood why...")
4. Patterns - Recurring behaviors ("I always...", "Every time...")
5. Preferences - Personal preferences ("I prefer...", "I like...")

Return a JSON object with this exact structure:
{
  "memories": [
    {"type": "commitment|fact|insight|pattern|preference", "content": "extracted memory", "confidence": 0.0-1.0}
  ],
  "confidence": 0.0-1.0
}

Only extract clear, meaningful memories. Assign confidence based on how explicit the memory is in the text."""

        user_prompt = f"Extract memories from this journal entry:\n\n{content}"

        response = await self._call_llm(
            system_prompt, user_prompt, task=InferenceTask.MEMORY_DISTILLATION
        )

        try:
            result_dict = json.loads(response)
            # Validate and convert to Pydantic model
            memories = []
            for mem in result_dict.get("memories", []):
                memories.append(Memory(
                    type=MemoryType(mem["type"]),
                    content=mem["content"],
                    confidence=float(mem["confidence"])
                ))

            return MemoryDistillationResult(
                memories=memories,
                confidence=float(result_dict.get("confidence", 0.8))
            )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning("memory_distillation_parse_error", error=str(e))
            # Return empty result on parse error
            return MemoryDistillationResult(memories=[], confidence=0.0)

    async def _tagging(self, content: str) -> TaggingResult:
        """
        Extract relevant tags from text.
        """
        system_prompt = """You are a tagging assistant. Your task is to extract relevant tags from journal entries.

Common tag categories:
- Topics: work, personal, family, health, finance, learning
- Types: task, reminder, question, idea, reflection, gratitude
- Entities: project, meeting, deadline, goal, event

Return a JSON object with this exact structure:
{
  "tags": [
    {"tag": "lowercase_tag", "confidence": 0.0-1.0}
  ],
  "confidence": 0.0-1.0
}

Extract 3-7 most relevant tags. Use lowercase, single words. Assign confidence based on relevance."""

        user_prompt = f"Extract tags from this journal entry:\n\n{content}"

        response = await self._call_llm(system_prompt, user_prompt, task=InferenceTask.TAGGING)

        try:
            result_dict = json.loads(response)
            tags = []
            for tag_data in result_dict.get("tags", []):
                tags.append(Tag(
                    tag=tag_data["tag"].lower(),
                    confidence=float(tag_data["confidence"])
                ))

            return TaggingResult(
                tags=tags,
                confidence=float(result_dict.get("confidence", 0.8))
            )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning("tagging_parse_error", error=str(e))
            return TaggingResult(tags=[], confidence=0.0)

    async def _insight_extraction(self, content: str) -> InsightExtractionResult:
        """
        Extract insights and patterns from text.
        """
        system_prompt = """You are an insight extraction assistant. Your task is to identify deeper insights, patterns, and connections in journal entries.

Focus on:
- Recurring themes or patterns
- Connections to broader goals or values
- Emotional patterns or trends
- Areas of growth or concern
- Underlying motivations

Return a JSON object with this exact structure:
{
  "insights": [
    "First insight as a complete sentence",
    "Second insight as a complete sentence"
  ],
  "confidence": 0.0-1.0
}

Provide 1-3 meaningful insights. Write them as helpful observations that could aid self-reflection."""

        user_prompt = f"Extract insights from this journal entry:\n\n{content}"

        response = await self._call_llm(
            system_prompt, user_prompt, task=InferenceTask.INSIGHT_EXTRACTION
        )

        try:
            result_dict = json.loads(response)
            return InsightExtractionResult(
                insights=result_dict.get("insights", []),
                confidence=float(result_dict.get("confidence", 0.7))
            )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning("insight_extraction_parse_error", error=str(e))
            return InsightExtractionResult(insights=[], confidence=0.0)

    async def _call_llm(
        self,
        system_prompt: str,
        user_prompt: str,
        task: Optional[InferenceTask] = None,
    ) -> str:
        """
        Call the LLM provider with the given prompts.

        Args:
            system_prompt: System instructions
            user_prompt: User message with content

        Returns:
            LLM response content string
        """
        self._ensure_provider()

        request = InferenceRequest(
            messages=[
                Message(role="system", content=system_prompt),
                Message(role="user", content=user_prompt)
            ],
            model=self._get_model_for_provider(),
            max_tokens=1024,
            temperature=0.3  # Lower temperature for more consistent JSON output
        )

        response = await self._provider.generate(request)

        # Extract JSON from response (handle markdown code blocks)
        content = response.content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]

        content = content.strip()

        logger.info(
            "llm_response_summary",
            provider=self._provider_name,
            model=str(request.model),
            task=task,
            response_length=len(content),
            response_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest()
            if content
            else None,
            is_empty=not bool(content),
        )

        return content

    async def _capture_metadata(self, content: str) -> CaptureMetadataResult:
        """
        Extract capture metadata: intent, entities, time, tags.
        """
        from datetime import datetime

        now = datetime.utcnow()
        day_of_week = now.strftime("%A")
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M")

        system_prompt = f"""You are a metadata extraction assistant. Analyze journal entries and extract structured metadata.

CURRENT TIME CONTEXT (use for reminder time calculations):
- UTC time: {now.isoformat()}Z
- Day: {day_of_week}
- Date: {date_str}
- Time: {time_str}

Return a JSON object with this exact structure:
{{
  "intent": "question|reminder|task|note|reflection|quote|idea",
  "extractedQuestion": "string or null",
  "extractedTask": "string or null",
  "inferredReminderTime": "ISO8601 string or null",
  "extractedEntities": ["entity1", "entity2"],
  "suggestedTags": ["tag1", "tag2"],
  "confidence": 0.0-1.0,
  "requiresResponse": true|false
}}

Guidelines:
- intent: Classify the primary intent
- extractedQuestion: If question intent, extract the core question
- extractedTask: If task intent, extract the action item
- inferredReminderTime: If reminder intent, parse time expressions (e.g., "tomorrow at 2pm", "in 2 hours") into ISO8601 UTC timestamp
- extractedEntities: Extract people, places, concepts mentioned (max 5)
- suggestedTags: Extract 1-5 relevant tags (work, personal, health, urgent, family, etc.)
- requiresResponse: true if the user expects an AI response (questions, complex requests)"""

        user_prompt = f"Extract metadata from this entry:\n\n{content}"

        response = await self._call_llm(
            system_prompt, user_prompt, task=InferenceTask.CAPTURE_METADATA
        )

        try:
            result_dict = json.loads(response)

            return CaptureMetadataResult(
                intent=CaptureIntent(result_dict.get("intent", "note")),
                extracted_question=result_dict.get("extractedQuestion"),
                extracted_task=result_dict.get("extractedTask"),
                inferred_reminder_time=result_dict.get("inferredReminderTime"),
                extracted_entities=result_dict.get("extractedEntities", []),
                suggested_tags=result_dict.get("suggestedTags", []),
                confidence=float(result_dict.get("confidence", 0.7)),
                requires_response=bool(result_dict.get("requiresResponse", False))
            )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning(
                "capture_metadata_parse_error",
                error=str(e),
                response_length=len(response),
                is_empty=not bool(response),
            )
            # Return minimal result on parse error
            return CaptureMetadataResult(
                intent=CaptureIntent.NOTE,
                confidence=0.3,
                requires_response=False,
                extracted_entities=[],
                suggested_tags=[]
            )


# Global task processor instance
task_processor = TaskProcessor()
