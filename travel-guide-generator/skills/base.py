"""Base class for Skills (external tool integrations)."""
from abc import ABC, abstractmethod
from typing import Any


class BaseSkill(ABC):
    """Abstract base class for all Skills."""

    name: str = ""
    description: str = ""
    parameters: dict = {}

    @abstractmethod
    def execute(self, **kwargs) -> dict:
        """Execute the skill and return structured data."""
        pass

    def get_tool_schema(self) -> dict:
        """Return OpenAI-compatible tool schema."""
        clean_properties = {}
        for key, val in self.parameters.items():
            clean_properties[key] = {k: v for k, v in val.items() if k != "required"}

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": clean_properties,
                    "required": [
                        k for k, v in self.parameters.items()
                        if v.get("required", False)
                    ],
                },
            },
        }
