"""Orchestrator Agent - the brain that coordinates expert agents and composes the final guide."""

from pathlib import Path

from config import LLMConfig
from services.llm_service import LLMClient, LLMFactory


class OrchestratorAgent:
    """Agent responsible for reviewing expert results and composing the final travel guide.

    This is separate from PlannerAgent (which handles conversation and requirement gathering).
    The orchestrator operates in the EXECUTION stage, receiving expert outputs and producing
    a polished, cross-checked final guide.
    """

    def __init__(self, config: LLMConfig):
        self.client: LLMClient = LLMFactory.create(config)
        self.system_prompt = self._load_system_prompt()
        self._prompt_service = None

    def _get_prompt_service(self):
        if self._prompt_service is None:
            from services.prompt_template_service import PromptTemplateService
            self._prompt_service = PromptTemplateService()
        return self._prompt_service

    def _load_system_prompt(self) -> str:
        prompt_path = Path(__file__).parent / "prompts" / "orchestrator_system.txt"
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
        return "You are an expert travel guide editor and orchestrator."

    def _build_system_prompt(self, stage: str | None) -> str:
        svc = self._get_prompt_service()
        stage_display = stage or "EXECUTION"
        try:
            rendered, missing = svc.render_prompt("orchestrator", {"stage": stage_display})
            if rendered and not missing:
                return rendered
        except Exception:
            pass
        return self.system_prompt

    def generate(self, messages: list[dict], stage: str | None = None) -> str:
        system_msg = {"role": "system", "content": self._build_system_prompt(stage)}
        full_messages = [system_msg] + messages
        return self.client.chat(full_messages)

    def stream(self, messages: list[dict], stage: str | None = None):
        system_msg = {"role": "system", "content": self._build_system_prompt(stage)}
        full_messages = [system_msg] + messages
        return self.client.chat(full_messages, stream=True)
