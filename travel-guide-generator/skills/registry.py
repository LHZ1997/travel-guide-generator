"""Skill registry for dynamic discovery and execution."""
import importlib
import inspect
from pathlib import Path
from typing import Dict, Optional

from .base import BaseSkill


class SkillRegistry:
    """Registry for managing skills."""

    def __init__(self):
        self._skills: Dict[str, BaseSkill] = {}

    def register(self, skill: BaseSkill):
        """Register a skill instance."""
        self._skills[skill.name] = skill

    def unregister(self, name: str):
        """Remove a skill from registry."""
        self._skills.pop(name, None)

    def get(self, name: str) -> Optional[BaseSkill]:
        """Get a skill by name."""
        return self._skills.get(name)

    def list_skills(self) -> list[dict]:
        """List all registered skills."""
        return [
            {
                "name": s.name,
                "description": s.description,
                "parameters": s.parameters,
            }
            for s in self._skills.values()
        ]

    def get_tools(self) -> list[dict]:
        """Get all skills as OpenAI tool schemas."""
        return [s.get_tool_schema() for s in self._skills.values()]

    def execute(self, name: str, **kwargs) -> dict:
        """Execute a skill by name."""
        skill = self.get(name)
        if not skill:
            return {"error": f"Skill '{name}' not found"}
        try:
            return skill.execute(**kwargs)
        except Exception as e:
            return {"error": str(e)}

    def load_from_directory(self, directory: Path):
        """Auto-discover and register skills from a directory."""
        if not directory.exists():
            return

        for file in directory.glob("*_skill.py"):
            module_name = file.stem
            full_module_name = f"skills.{module_name}"
            try:
                module = importlib.import_module(full_module_name)

                for name, obj in inspect.getmembers(module):
                    if (
                        inspect.isclass(obj)
                        and issubclass(obj, BaseSkill)
                        and obj is not BaseSkill
                        and hasattr(obj, "name")
                        and obj.name
                    ):
                        instance = obj()
                        self.register(instance)
            except Exception as e:
                import traceback
                print(f"[SkillRegistry] Failed to load skill {full_module_name}: {e}")
                traceback.print_exc()


# Global registry instance
skill_registry = SkillRegistry()
