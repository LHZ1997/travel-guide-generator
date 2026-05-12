"""Service for initializing default data on first startup."""
import json
from pathlib import Path

from models import AgentConfig, AgentRelation, PromptTemplate, db


class InitService:
    """Handles one-time initialization of agents and prompt templates."""

    @classmethod
    def run(cls):
        """Run all initialization steps (idempotent)."""
        cls._init_default_agents()
        cls._upgrade_existing_agents()
        cls._init_default_relations()
        cls._migrate_existing_prompts()

    @classmethod
    def _upgrade_existing_agents(cls):
        """Update existing agents that changed semantics between versions."""
        planner = AgentConfig.query.filter_by(name="planner").first()
        if planner and planner.role_type == "orchestrator":
            planner.role_type = "planner"
            db.session.commit()

    @classmethod
    def _init_default_agents(cls):
        """Create default agents if they don't exist."""
        defaults = [
            {
                "name": "planner",
                "display_name": "行程规划师",
                "description": "与用户一对一友好对话，引导明确旅行需求，展示选项让用户快速选择",
                "role_type": "planner",
                "icon": "🗺️",
            },
            {
                "name": "orchestrator",
                "display_name": "智能调度师",
                "description": "分析用户需求，调度专家智能体分工协作，审核专家结果，汇总生成最终旅行攻略",
                "role_type": "orchestrator",
                "icon": "🧠",
            },
            {
                "name": "checker",
                "display_name": "攻略检查师",
                "description": "负责审查已生成攻略的完整性、逻辑一致性和可执行性",
                "role_type": "checker",
                "icon": "🔍",
            },
            {
                "name": "hotel_expert",
                "display_name": "酒店规划专家",
                "description": "负责根据旅行需求推荐高性价比住宿方案",
                "role_type": "expert",
                "icon": "🏨",
            },
            {
                "name": "scene_expert",
                "display_name": "景点规划专家",
                "description": "负责梳理目的地景点、按片区分类、推荐游览顺序",
                "role_type": "expert",
                "icon": "🎡",
            },
            {
                "name": "food_expert",
                "display_name": "美食搜索专家",
                "description": "负责挖掘本地特色美食、餐厅推荐、必点菜和人均消费",
                "role_type": "expert",
                "icon": "🍜",
            },
            {
                "name": "route_expert",
                "display_name": "路线规划专家",
                "description": "负责根据酒店和景点位置规划最优行程路线和交通方案",
                "role_type": "expert",
                "icon": "🚗",
            },
        ]

        for data in defaults:
            if not AgentConfig.query.filter_by(name=data["name"]).first():
                agent = AgentConfig(
                    name=data["name"],
                    display_name=data["display_name"],
                    description=data["description"],
                    role_type=data["role_type"],
                    llm_config="{}",
                    is_active=True,
                    icon=data["icon"],
                )
                db.session.add(agent)

        db.session.commit()

    @classmethod
    def _init_default_relations(cls):
        """Create default agent relations for EXECUTION stage if they don't exist.

        Optimized dependency chain:
        Group 1: scene_expert (attractions first - determines geographic anchor)
        Group 2: hotel_expert (hotels based on attraction locations)
        Group 3: food_expert (restaurants based on hotel + attraction locations)
        Group 4: route_expert (routes based on all three above)
        """
        # Clean up legacy relations with source_agent="planner"
        old_relations = AgentRelation.query.filter_by(
            source_agent="planner", trigger_stage="EXECUTION"
        ).all()
        for r in old_relations:
            db.session.delete(r)

        relations = [
            {
                "source_agent": "orchestrator",
                "target_agent": "scene_expert",
                "trigger_stage": "EXECUTION",
                "group": 1,
                "order_index": 1,
            },
            {
                "source_agent": "orchestrator",
                "target_agent": "hotel_expert",
                "trigger_stage": "EXECUTION",
                "group": 2,
                "order_index": 2,
            },
            {
                "source_agent": "orchestrator",
                "target_agent": "food_expert",
                "trigger_stage": "EXECUTION",
                "group": 3,
                "order_index": 3,
            },
            {
                "source_agent": "orchestrator",
                "target_agent": "route_expert",
                "trigger_stage": "EXECUTION",
                "group": 4,
                "order_index": 4,
            },
        ]

        for data in relations:
            existing = AgentRelation.query.filter_by(
                source_agent=data["source_agent"],
                target_agent=data["target_agent"],
                trigger_stage=data["trigger_stage"],
            ).first()
            if not existing:
                rel = AgentRelation(
                    source_agent=data["source_agent"],
                    target_agent=data["target_agent"],
                    trigger_stage=data["trigger_stage"],
                    trigger_condition="",
                    input_mapping="{}",
                    output_mapping="{}",
                    order_index=data["order_index"],
                    group=data["group"],
                    depends_on="",
                    is_active=True,
                )
                db.session.add(rel)

        db.session.commit()

    @classmethod
    def _migrate_existing_prompts(cls):
        """Migrate existing .txt prompt files into layered PromptTemplates."""
        prompts_dir = Path(__file__).parent.parent / "agents" / "prompts"

        # Migrate planner prompts
        planner_path = prompts_dir / "planner_system.txt"
        if planner_path.exists():
            cls._migrate_planner_prompt(planner_path.read_text(encoding="utf-8"))

        # Migrate checker prompts
        checker_path = prompts_dir / "checker_system.txt"
        if checker_path.exists():
            cls._migrate_checker_prompt(checker_path.read_text(encoding="utf-8"))

        # Migrate expert prompts (any *_expert.txt file)
        for expert_path in prompts_dir.glob("*_expert.txt"):
            agent_name = expert_path.stem  # e.g. "hotel_expert"
            content = expert_path.read_text(encoding="utf-8")
            cls._migrate_expert_prompt(agent_name, content)

        # Migrate orchestrator prompt
        orch_path = prompts_dir / "orchestrator_system.txt"
        if orch_path.exists():
            cls._migrate_expert_prompt("orchestrator", orch_path.read_text(encoding="utf-8"))

    @classmethod
    def _migrate_planner_prompt(cls, content: str):
        """Split planner prompt into core / role / format layers."""
        lines = content.split("\n")

        # Role layer: first paragraph (character definition)
        role_content = lines[0] if lines else ""

        # Core layer: stage constraints + universal rules
        core_lines = []
        in_stages = False
        in_universal = False
        for line in lines:
            stripped = line.strip()
            if "【绝对强制】" in stripped or "当前阶段行为规范" in stripped:
                in_stages = True
            if "【通用输出约束】" in stripped:
                in_universal = True
            if in_stages or in_universal:
                core_lines.append(line)
            if in_stages and stripped == "" and any(l.startswith("## 【通用") for l in lines[lines.index(line):lines.index(line)+3] if lines.index(line)+3 < len(lines)):
                in_stages = False

        # If parsing failed, use heuristics
        if not core_lines:
            core_lines = lines[2:]  # everything after first line

        core_content = "\n".join(core_lines).strip()

        # Format layer: EXECUTION stage output format
        format_lines = []
        in_execution = False
        for line in lines:
            if "### EXECUTION" in line:
                in_execution = True
            if in_execution:
                format_lines.append(line)
                if line.strip().startswith("-") and "每个模块之间用" in line:
                    break

        format_content = "\n".join(format_lines).strip()

        cls._ensure_template("planner", "core", "system_prompt", core_content, [
            {"name": "stage", "default": "INIT"},
        ], is_editable=False)

        cls._ensure_template("planner", "role", "system_prompt", role_content, [], is_editable=True)

        cls._ensure_template("planner", "format", "execution_template", format_content, [], is_editable=True)

    @classmethod
    def _migrate_checker_prompt(cls, content: str):
        """Split checker prompt into core / role / format layers."""
        lines = content.split("\n")

        # Role layer: first line
        role_content = lines[0] if lines else ""

        # Core layer: check dimensions
        core_lines = []
        in_dimensions = False
        for line in lines:
            if "检查维度" in line or line.strip().startswith("1. 完整性检查"):
                in_dimensions = True
            if in_dimensions:
                core_lines.append(line)
            if in_dimensions and line.strip().startswith("5. 安全与风险提示"):
                # Continue until next section
                pass
            if in_dimensions and line.strip() == "" and any(l.startswith("输出格式") for l in lines[lines.index(line):lines.index(line)+5] if lines.index(line)+5 < len(lines)):
                break

        core_content = "\n".join(core_lines).strip()
        if not core_content:
            core_content = content

        # Format layer: output format requirements
        format_lines = []
        in_format = False
        for line in lines:
            if "输出格式" in line:
                in_format = True
            if in_format:
                format_lines.append(line)

        format_content = "\n".join(format_lines).strip()

        cls._ensure_template("checker", "core", "system_prompt", core_content, [], is_editable=False)
        cls._ensure_template("checker", "role", "system_prompt", role_content, [], is_editable=True)
        cls._ensure_template("checker", "format", "output_template", format_content, [], is_editable=True)

    @classmethod
    def _migrate_expert_prompt(cls, agent_name: str, content: str):
        """Migrate expert prompt as a single role-layer template with variable declaration.

        Experts use the entire prompt as their system prompt, with {requirements}
        as the primary injected variable.
        """
        variables = []
        if "{requirements}" in content:
            variables.append({"name": "requirements", "default": ""})
        if "{hotel_plan}" in content:
            variables.append({"name": "hotel_plan", "default": ""})
        if "{scene_plan}" in content:
            variables.append({"name": "scene_plan", "default": ""})
        if "{food_plan}" in content:
            variables.append({"name": "food_plan", "default": ""})

        cls._ensure_template(agent_name, "role", "system_prompt", content, variables, is_editable=True)

    @classmethod
    def _ensure_template(cls, agent_name: str, layer: str, name: str, content: str, variables: list, is_editable: bool):
        """Create template if it doesn't exist, update if content changed."""
        existing = PromptTemplate.query.filter_by(
            agent_name=agent_name, layer=layer, name=name
        ).first()

        if existing:
            if existing.content.strip() != content.strip():
                existing.content = content
                existing.variables = json.dumps(variables, ensure_ascii=False)
                existing.version = (existing.version or 0) + 1
                db.session.commit()
            return

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
