"""
E2EE inference task processors using LLM providers.
"""
import json
import structlog
from typing import Optional

from app.inference.models import (
    InferenceTask,
    MemoryDistillationResult,
    TaggingResult,
    InsightExtractionResult,
    Memory,
    MemoryType,
    Tag
)
from app.llm.models import InferenceRequest, Message, ModelType
from app.llm.providers.anthropic import AnthropicProvider
from app.llm.providers.openai import OpenAIProvider
from app.llm.providers.google import GoogleProvider
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

    def _ensure_provider(self):
        """Lazily initialize the LLM provider."""
        if self._provider is not None:
            return

        if settings.anthropic_api_key:
            self._provider = AnthropicProvider()
            self._model = ModelType.CLAUDE_HAIKU  # Fast and cheap for simple tasks
        elif settings.openai_api_key:
            self._provider = OpenAIProvider()
            self._model = ModelType.GPT_4O_MINI
        elif settings.gemini_api_key:
            self._provider = GoogleProvider()
            self._model = ModelType.GEMINI_FLASH
        else:
            raise ValueError("No LLM provider API key configured")

    def _get_model_for_provider(self):
        """Get the appropriate model for the current provider."""
        self._ensure_provider()
        return self._model

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
            elif task == InferenceTask.TAGGING:
                result = await self._tagging(plaintext_content)
            elif task == InferenceTask.INSIGHT_EXTRACTION:
                result = await self._insight_extraction(plaintext_content)
            else:
                raise ValueError(f"Unknown task: {task}")

            return result.model_dump_json()

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

        response = await self._call_llm(system_prompt, user_prompt)

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

        response = await self._call_llm(system_prompt, user_prompt)

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

        response = await self._call_llm(system_prompt, user_prompt)

        try:
            result_dict = json.loads(response)
            return InsightExtractionResult(
                insights=result_dict.get("insights", []),
                confidence=float(result_dict.get("confidence", 0.7))
            )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning("insight_extraction_parse_error", error=str(e))
            return InsightExtractionResult(insights=[], confidence=0.0)

    async def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
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

        return content.strip()


# Global task processor instance
task_processor = TaskProcessor()
