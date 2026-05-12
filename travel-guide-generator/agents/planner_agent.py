"""TravelPlanner Agent - itinerary planning specialist."""
from pathlib import Path

from config import LLMConfig
from services.llm_service import LLMClient, LLMFactory
from skills.registry import skill_registry


class PlannerAgent:
    """Agent responsible for collecting requirements and generating travel guides."""

    def __init__(self, config: LLMConfig):
        self.client: LLMClient = LLMFactory.create(config)
        self.system_prompt = self._load_system_prompt()
        self._prompt_service = None

    def _get_prompt_service(self):
        """Lazy init prompt template service."""
        if self._prompt_service is None:
            from services.prompt_template_service import PromptTemplateService
            self._prompt_service = PromptTemplateService()
        return self._prompt_service

    def _load_system_prompt(self) -> str:
        prompt_path = Path(__file__).parent / "prompts" / "planner_system.txt"
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
        return "You are a travel planning assistant."

    def _build_system_prompt(self, stage: str | None) -> str:
        """Build system prompt with stage injected.

        Priority:
        1. Use PromptTemplateService (database) if templates exist
        2. Fallback to txt file content
        """
        stage_display = stage or "INIT"
        svc = self._get_prompt_service()

        # Try database templates first
        try:
            rendered, missing = svc.render_prompt("planner", {"stage": stage_display})
            if rendered and not missing:
                return rendered
        except Exception:
            pass

        # Fallback to txt file
        return self.system_prompt.replace("{stage}", stage_display)

    def generate(self, messages: list[dict], stage: str | None = None) -> str:
        """Generate response based on conversation history."""
        system_msg = {"role": "system", "content": self._build_system_prompt(stage)}
        full_messages = [system_msg] + messages

        # Check if we have skills and should use tool calling
        tools = skill_registry.get_tools()
        if tools:
            available_functions = {
                s.name: s.execute for s in skill_registry._skills.values()
            }
            return self.client.chat_with_tools(
                full_messages, tools, available_functions
            )

        return self.client.chat(full_messages)

    def stream(self, messages: list[dict], stage: str | None = None):
        """Stream response for real-time display."""
        system_msg = {"role": "system", "content": self._build_system_prompt(stage)}
        full_messages = [system_msg] + messages
        return self.client.chat(full_messages, stream=True)
