"""Agent registry service with in-memory caching."""
import json
from typing import Optional

from config import LLMConfig, app_config
from models import AgentConfig, AgentRelation, db
from services.llm_service import LLMFactory


class AgentRegistryService:
    """Central registry for managing agents and their relations."""

    def __init__(self):
        self._agents_cache: dict[str, dict] = {}
        self._relations_cache: list[dict] = []
        self._load_cache()

    def _load_cache(self):
        """Load all active agents and relations into memory."""
        self._agents_cache = {}
        agents = AgentConfig.query.filter_by(is_active=True).all()
        for a in agents:
            self._agents_cache[a.name] = a.to_dict()

        self._relations_cache = []
        relations = AgentRelation.query.filter_by(is_active=True).order_by(AgentRelation.order_index).all()
        for r in relations:
            self._relations_cache.append(r.to_dict())

    def refresh_cache(self):
        """Refresh cache from database."""
        self._load_cache()

    def get_orchestrator(self) -> Optional[dict]:
        """Get the orchestrator agent (should be exactly one)."""
        for name, agent in self._agents_cache.items():
            if agent.get("role_type") == "orchestrator":
                return agent
        return None

    def get_agent(self, name: str) -> Optional[dict]:
        """Get agent by name."""
        return self._agents_cache.get(name)

    def list_agents(self, role_type: Optional[str] = None) -> list[dict]:
        """List all active agents, optionally filtered by role_type."""
        result = list(self._agents_cache.values())
        if role_type:
            result = [a for a in result if a.get("role_type") == role_type]
        return result

    def get_experts_for_stage(self, stage: str, source: str = "planner") -> list[dict]:
        """Get experts that should be triggered for a given stage."""
        experts = []
        for rel in self._relations_cache:
            if rel.get("source_agent") == source and rel.get("trigger_stage") == stage:
                target = self.get_agent(rel.get("target_agent"))
                if target:
                    experts.append({
                        **target,
                        "group": rel.get("group", 0),
                        "depends_on": rel.get("depends_on", ""),
                        "order_index": rel.get("order_index", 0),
                        "relation": rel,
                    })
        return experts

    def get_relations_for_source(self, source_name: str) -> list[dict]:
        """Get all outgoing relations for a source agent."""
        return [r for r in self._relations_cache if r.get("source_agent") == source_name]

    def has_cycle(self, source: str, target: str) -> bool:
        """Check if adding source->target would create a cycle."""
        visited = set()
        stack = [target]
        while stack:
            current = stack.pop()
            if current == source:
                return True
            if current in visited:
                continue
            visited.add(current)
            for rel in self._relations_cache:
                if rel.get("source_agent") == current:
                    stack.append(rel.get("target_agent"))
        return False

    def create_llm_client(self, agent_name: str):
        """Create LLMClient for an agent based on its llm_config.

        Falls back to global planner_config if agent has no custom config.
        """
        agent = self.get_agent(agent_name)
        llm_config_data = agent.get("llm_config", {}) if agent else {}

        if llm_config_data and llm_config_data.get("api_key"):
            config = LLMConfig.from_dict(llm_config_data)
        else:
            # Fallback to global planner config
            config = app_config.planner_config

        return LLMFactory.create(config)
