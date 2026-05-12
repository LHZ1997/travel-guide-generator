"""Unified orchestration configuration for Travel Guide Generator.

Centralizes all agent definitions, stage flow, skill mappings, and variable
mappings that were previously scattered across multiple files.
"""
from dataclasses import dataclass, field
from typing import Optional


# ============================================================
# Stage Definitions
# ============================================================

class Stage:
    REQUIREMENT = "REQUIREMENT"
    REQUIREMENT_CONFIRMED = "REQUIREMENT_CONFIRMED"
    EXECUTION = "EXECUTION"
    COMPLETE = "COMPLETE"

STAGE_FLOW = [
    Stage.REQUIREMENT,
    Stage.REQUIREMENT_CONFIRMED,
    Stage.EXECUTION,
    Stage.COMPLETE,
]


# ============================================================
# Agent Definitions (what runs at each stage, with what skills)
# ============================================================

@dataclass
class AgentDef:
    name: str
    display_name: str
    icon: str
    role_type: str  # orchestrator / expert / checker
    description: str
    stage: str  # which stage this agent is active in
    group: int = 0  # execution order within stage (0 = orchestrator)
    depends_on: str = ""  # agent name this one depends on (for variable passing)
    skills: list[str] = field(default_factory=list)  # skill names available to this agent
    input_vars: list[str] = field(default_factory=list)  # variables injected from context
    output_key: str = ""  # key for result storage (expert_name -> result)


AGENTS = [
    AgentDef(
        name="planner",
        display_name="行程规划师",
        icon="🗺️",
        role_type="planner",
        description="与用户进行一对一友好对话，引导用户明确旅行需求，展示选项让用户快速选择",
        stage=Stage.REQUIREMENT,
        group=0,
        skills=[],
    ),
    AgentDef(
        name="orchestrator",
        display_name="智能调度师",
        icon="🧠",
        role_type="orchestrator",
        description="分析用户需求，调度专家智能体分工协作，审核专家结果，汇总生成最终旅行攻略",
        stage=Stage.EXECUTION,
        group=0,
        skills=[],
    ),
    AgentDef(
        name="scene_expert",
        display_name="景点规划专家",
        icon="🏔️",
        role_type="expert",
        description="梳理目的地景点，按地理片区分类，推荐游览顺序和门票预算",
        stage=Stage.EXECUTION,
        group=1,
        skills=["flyai_search_poi", "flyai_keyword_search"],
        input_vars=["requirements"],
        output_key="scene_expert",
    ),
    AgentDef(
        name="hotel_expert",
        display_name="酒店规划专家",
        icon="🏨",
        role_type="expert",
        description="根据景点位置推荐高性价比住宿方案，计算住宿总费用",
        stage=Stage.EXECUTION,
        group=2,
        depends_on="scene_expert",
        skills=["flyai_search_hotel", "flyai_keyword_search"],
        input_vars=["requirements", "scene_plan"],
        output_key="hotel_expert",
    ),
    AgentDef(
        name="food_expert",
        display_name="美食搜索专家",
        icon="🍜",
        role_type="expert",
        description="挖掘本地特色美食，推荐餐厅和必点菜，估算餐饮预算",
        stage=Stage.EXECUTION,
        group=3,
        depends_on="hotel_expert",
        skills=["flyai_keyword_search", "flyai_ai_search"],
        input_vars=["requirements", "hotel_plan", "scene_plan"],
        output_key="food_expert",
    ),
    AgentDef(
        name="route_expert",
        display_name="路线规划专家",
        icon="🚗",
        role_type="expert",
        description="综合酒店景点美食推荐，规划每日最优行程路线和交通方案",
        stage=Stage.EXECUTION,
        group=4,
        depends_on="food_expert",
        skills=["flyai_search_poi", "flyai_keyword_search"],
        input_vars=["requirements", "hotel_plan", "scene_plan", "food_plan"],
        output_key="route_expert",
    ),
    AgentDef(
        name="checker",
        display_name="攻略检查师",
        icon="🔍",
        role_type="checker",
        description="审查攻略完整性、逻辑一致性和预算准确性",
        stage=Stage.COMPLETE,
        group=0,
        skills=[],
    ),
]


# ============================================================
# Skill-to-Tool Mapping (what CLI command each skill uses)
# ============================================================

SKILL_TOOL_MAP = {
    "flyai_search_poi": "flyai search-poi",
    "flyai_search_hotel": "flyai search-hotel",
    "flyai_keyword_search": "flyai keyword-search",
    "flyai_ai_search": "flyai ai-search",
}


# ============================================================
# Variable Name Mapping (expert output -> downstream input)
# ============================================================

VAR_MAP = {
    "hotel_expert": "hotel_plan",
    "scene_expert": "scene_plan",
    "food_expert": "food_plan",
    "route_expert": "route_plan",
}


# ============================================================
# Requirements Field Definitions (for planner inquiry)
# ============================================================

@dataclass
class RequirementField:
    key: str
    cn_name: str
    required: bool
    priority: int  # 1=must ask first, 2=can ask later
    options: list[str] = field(default_factory=list)  # predefined choices
    allow_custom: bool = False  # allow user to type custom value
    hint: str = ""  # extra hint for the field


REQUIREMENT_FIELDS = [
    RequirementField("destination", "目的地", True, 1,
        hint="具体的城市或区域，越具体越好"),
    RequirementField("dates", "出行时间", True, 1,
        hint="具体日期或大致时间范围，如6月19日-23日"),
    RequirementField("travelers", "出行人数", True, 1,
        hint="人数+人员构成，如2人情侣、一家三口"),
    RequirementField("budget", "预算范围", True, 1,
        hint="人均预算或总预算，如人均3000"),
    RequirementField("origin", "出发城市", True, 2,
        hint="从哪个城市出发"),
    RequirementField("transport", "大交通方式", False, 2,
        options=["飞机", "高铁", "自驾", "火车硬卧", "大巴"],
        allow_custom=True,
        hint="如何到达目的地"),
    RequirementField("vehicle", "当地交通偏好", False, 3,
        options=["租车自驾", "包车+司机", "打车/网约车", "公共交通", "步行+骑行"],
        allow_custom=False,
        hint="在当地怎么出行"),
    RequirementField("accommodation", "住宿偏好", False, 3,
        options=["经济型酒店(人均100-200)", "舒适型酒店(人均300-500)", "精品民宿(人均200-400)", "高端度假酒店(人均500+)"],
        allow_custom=True,
        hint="住宿类型和价位偏好"),
    RequirementField("companion_type", "同行关系", False, 2,
        options=["情侣/夫妻", "朋友结伴", "亲子家庭", "独自旅行", "带父母长辈"],
        allow_custom=False,
        hint="和谁一起去"),
    RequirementField("interest", "兴趣偏好", False, 3,
        options=["自然风光", "人文历史", "美食探店", "摄影打卡", "户外徒步", "休闲度假"],
        allow_custom=True,
        hint="喜欢什么类型的体验"),
    RequirementField("pace", "行程节奏", False, 3,
        options=["轻松慢游(每天1-2个点)", "适中节奏(每天2-3个点)", "高效打卡(每天4+个点)"],
        allow_custom=False,
        hint="每天的行程密度"),
    RequirementField("dietary", "饮食禁忌", False, 3,
        options=["无特殊要求", "不吃辣", "素食", "清真", "海鲜过敏"],
        allow_custom=True,
        hint="有什么不能吃/不爱吃的"),
    RequirementField("fitness", "体力水平", False, 3,
        options=["轻松散步型", "正常体力", "特种兵不怕累"],
        allow_custom=False,
        hint="能接受多大的体力消耗"),
    RequirementField("special", "特殊需求", False, 3,
        allow_custom=True,
        hint="如婴儿车友好、无障碍设施、宠物同行等"),
]


# ============================================================
# Inquiry Strategy: what to ask in each round
# ============================================================

# Each round is a list of RequirementField keys to ask about together
INQUIRY_ROUNDS = [
    ["destination", "dates", "travelers", "budget"],
    ["origin", "transport", "companion_type"],
    ["accommodation", "vehicle", "interest", "pace"],
    ["dietary", "fitness", "special"],
]


# ============================================================
# Lookup helpers
# ============================================================

def get_agent_def(name: str) -> Optional[AgentDef]:
    for a in AGENTS:
        if a.name == name:
            return a
    return None


def get_field_def(key: str) -> Optional[RequirementField]:
    for f in REQUIREMENT_FIELDS:
        if f.key == key:
            return f
    return None


def get_required_fields() -> list[str]:
    return [f.key for f in REQUIREMENT_FIELDS if f.required]


def get_field_cn(key: str) -> str:
    f = get_field_def(key)
    return f.cn_name if f else key


def get_agents_for_stage(stage: str) -> list[AgentDef]:
    return [a for a in AGENTS if a.stage == stage and a.role_type != "orchestrator"]


def get_skills_for_agent(name: str) -> list[str]:
    a = get_agent_def(name)
    return a.skills if a else []


def get_var_for_agent_output(name: str) -> str:
    return VAR_MAP.get(name, name)
