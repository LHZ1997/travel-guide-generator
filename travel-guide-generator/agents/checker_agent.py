"""TravelChecker Agent - guide quality inspector."""
from pathlib import Path

from config import LLMConfig
from services.llm_service import LLMClient, LLMFactory


class CheckerAgent:
    """Agent responsible for reviewing generated travel guides."""

    def __init__(self, config: LLMConfig):
        self.client: LLMClient = LLMFactory.create(config)
        self.system_prompt = self._load_system_prompt()
        self._prompt_service = None

    def _load_system_prompt(self) -> str:
        prompt_path = Path(__file__).parent / "prompts" / "checker_system.txt"
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
        return "You are a guide quality checker."

    def _get_prompt_service(self):
        """Lazy init prompt template service."""
        if self._prompt_service is None:
            from services.prompt_template_service import PromptTemplateService
            self._prompt_service = PromptTemplateService()
        return self._prompt_service

    def _build_system_prompt(self) -> str:
        """Build system prompt, prefer database templates over txt file."""
        svc = self._get_prompt_service()
        try:
            rendered, missing = svc.render_prompt("checker", {})
            if rendered and not missing:
                return rendered
        except Exception:
            pass
        return self.system_prompt

    def check(self, guide_content: str) -> str:
        """Review the generated guide and return issues."""
        messages = [
            {"role": "system", "content": self._build_system_prompt()},
            {
                "role": "user",
                "content": f"请审查以下旅游攻略，输出检查发现的问题列表：\n\n---\n{guide_content}\n---",
            },
        ]
        return self.client.chat(messages)
