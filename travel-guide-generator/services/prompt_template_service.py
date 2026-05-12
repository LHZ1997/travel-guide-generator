"""Prompt template management with rendering and validation."""
import json
import re
from typing import Optional

from models import PromptTemplate, db


class PromptTemplateService:
    """Manages prompt templates with layer support and variable injection."""

    VARIABLE_PATTERN = re.compile(r"\{(\w+)\}")

    def __init__(self):
        self._cache: dict[str, list[dict]] = {}  # agent_name -> list of templates
        self._load_cache()

    def _load_cache(self):
        """Load all active templates into memory."""
        self._cache = {}
        templates = PromptTemplate.query.filter_by(is_active=True).order_by(PromptTemplate.layer).all()
        for t in templates:
            key = t.agent_name
            if key not in self._cache:
                self._cache[key] = []
            self._cache[key].append(t.to_dict())

    def refresh_cache(self):
        """Refresh cache from database."""
        self._load_cache()

    def get_templates_for_agent(self, agent_name: str) -> dict[str, dict]:
        """Get all templates for an agent grouped by layer."""
        result = {}
        for t in self._cache.get(agent_name, []):
            result[t["layer"]] = t
        return result

    def get_template(self, agent_name: str, layer: str, name: str = "system_prompt") -> Optional[dict]:
        """Get a specific template."""
        for t in self._cache.get(agent_name, []):
            if t["layer"] == layer and t["name"] == name:
                return t
        return None

    def render_prompt(self, agent_name: str, variables: dict) -> tuple[str, list[str]]:
        """Render full system prompt for an agent.

        Returns:
            (rendered_prompt, missing_variables)
        """
        templates = self.get_templates_for_agent(agent_name)

        # Merge layers: core + role + format
        layers_order = ["core", "role", "format"]
        parts = []
        for layer in layers_order:
            t = templates.get(layer)
            if t and t.get("content"):
                parts.append(t["content"])

        full_prompt = "\n\n".join(parts)

        # Inject variables
        missing = []
        declared_vars = {}
        for t in templates.values():
            for v in t.get("variables", []):
                declared_vars[v["name"]] = v.get("default", "")

        # Merge provided variables with defaults
        merged = {**declared_vars, **variables}

        for key, value in merged.items():
            placeholder = f"{{{key}}}"
            if placeholder in full_prompt:
                full_prompt = full_prompt.replace(placeholder, str(value))

        # Check for unresolved variables
        unresolved = self.VARIABLE_PATTERN.findall(full_prompt)
        missing = [v.strip() for v in unresolved]

        return full_prompt, missing

    def validate_template(self, content: str, variables: list[dict]) -> list[str]:
        """Validate that all variables in content are declared.

        Returns list of undeclared variable names.
        """
        used = set(self.VARIABLE_PATTERN.findall(content))
        declared = {v["name"] for v in variables}
        return [v for v in used if v not in declared]

    def create_or_update_template(
        self,
        agent_name: str,
        layer: str,
        name: str,
        content: str,
        variables: list[dict],
        is_editable: bool = True,
    ) -> dict:
        """Create or update a prompt template."""
        existing = PromptTemplate.query.filter_by(
            agent_name=agent_name, layer=layer, name=name
        ).first()

        if existing:
            existing.content = content
            existing.variables = json.dumps(variables, ensure_ascii=False)
            existing.is_editable = is_editable
            existing.version += 1
            db.session.commit()
            return existing.to_dict()

        t = PromptTemplate(
            agent_name=agent_name,
            layer=layer,
            name=name,
            content=content,
            variables=json.dumps(variables, ensure_ascii=False),
            is_editable=is_editable,
            is_active=True,
            version=1,
        )
        db.session.add(t)
        db.session.commit()
        return t.to_dict()
