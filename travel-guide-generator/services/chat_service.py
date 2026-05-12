"""Chat service with state machine for conversation flow."""
import json
import re

from models import Conversation, Guide, db, generate_uuid


class ChatStage:
    REQUIREMENT = "REQUIREMENT"
    REQUIREMENT_CONFIRMED = "REQUIREMENT_CONFIRMED"
    EXECUTION = "EXECUTION"
    COMPLETE = "COMPLETE"


class ChatService:
    """Manages conversation state and agent interactions."""

    STAGE_FLOW = [
        ChatStage.REQUIREMENT,
        ChatStage.REQUIREMENT_CONFIRMED,
        ChatStage.EXECUTION,
        ChatStage.COMPLETE,
    ]

    REQUIRED_FIELDS = ["destination", "dates", "travelers", "budget"]

    ALL_FIELDS_MAPPING = {
        "destination": "目的地",
        "dates": "出行时间",
        "travelers": "出行人数",
        "budget": "预算范围",
        "origin": "出发城市",
        "transport": "大交通方式",
        "vehicle": "当地交通偏好",
        "accommodation": "住宿偏好",
        "companion_type": "同行关系",
        "interest": "兴趣偏好",
        "pace": "行程节奏",
        "dietary": "饮食禁忌",
        "fitness": "体力水平",
        "special": "特殊需求",
    }

    def __init__(self):
        from config import app_config
        from agents.planner_agent import PlannerAgent
        from agents.orchestrator_agent import OrchestratorAgent
        from agents.checker_agent import CheckerAgent
        from services.agent_registry_service import AgentRegistryService

        self.planner = PlannerAgent(app_config.planner_config)
        self.orchestrator = OrchestratorAgent(app_config.orchestrator_config)
        self.checker = CheckerAgent(app_config.checker_config)
        self.agent_registry = AgentRegistryService()

    def get_history(self, session_id: str) -> list[dict]:
        """Get conversation history for a session.

        Maps internal roles (planner, checker) to API-compatible role (assistant).
        """
        rows = (
            Conversation.query.filter_by(session_id=session_id)
            .order_by(Conversation.created_at)
            .all()
        )
        role_map = {"user": "user", "planner": "assistant", "orchestrator": "assistant", "checker": "assistant"}
        return [
            {"role": role_map.get(r.role, r.role), "content": r.message}
            for r in rows
            if r.role in ("user", "planner", "checker")
        ]

    def get_current_stage(self, session_id: str) -> str:
        """Get the current stage of a session."""
        last_msg = (
            Conversation.query.filter_by(session_id=session_id)
            .order_by(Conversation.created_at.desc())
            .first()
        )
        return last_msg.stage if last_msg else ChatStage.REQUIREMENT

    def advance_stage(self, session_id: str) -> str:
        """Advance to the next stage."""
        current = self.get_current_stage(session_id)
        if current in self.STAGE_FLOW:
            idx = self.STAGE_FLOW.index(current)
            if idx + 1 < len(self.STAGE_FLOW):
                return self.STAGE_FLOW[idx + 1]
        return current

    def add_message(self, session_id: str, role: str, message: str, stage: str):
        """Add a message to the conversation."""
        conv = Conversation(
            session_id=session_id, role=role, message=message, stage=stage
        )
        db.session.add(conv)
        db.session.commit()

    def process_user_message(self, session_id: str, message: str) -> str:
        """Process user message and return agent response."""
        stage = self.get_current_stage(session_id)

        self.add_message(session_id, "user", message, stage)

        history = self.get_history(session_id)

        response = self.planner.generate(history, stage=stage)

        next_stage = self._infer_next_stage(stage, message, response, history=history)

        clean_response = ChatService._strip_markup(response.replace("[TASK_DISPATCH]", ""))

        self.add_message(session_id, "planner", clean_response, next_stage)

        if next_stage == ChatStage.REQUIREMENT_CONFIRMED:
            try:
                self.save_requirements(session_id, response)
                self._run_llm_requirements_extraction(session_id)
            except Exception as e:
                print(f"[ChatService] Failed to save requirements: {e}")

        return clean_response

    def _infer_next_stage(self, current: str, user_msg: str, response: str, msg_count: int = 0, history: list = None) -> str:
        """Infer the next stage based on model signal and hard validation.

        When orchestrator outputs [TASK_DISPATCH]:
        1. Extract requirements from the response
        2. Hard-validate that all REQUIRED_FIELDS are present
        3. If complete -> REQUIREMENT_CONFIRMED (user must confirm)
        4. If incomplete -> stay in REQUIREMENT (ignore dispatch signal)
        """
        current_idx = self.STAGE_FLOW.index(current) if current in self.STAGE_FLOW else 0

        if "[TASK_DISPATCH]" in response:
            req = self._extract_requirements(response)
            missing = [f for f in self.REQUIRED_FIELDS if not req.get(f)]
            if missing:
                missing_names = [self.ALL_FIELDS_MAPPING.get(f, f) for f in missing]
                print(f"[ChatService] TASK_DISPATCH ignored - missing required fields: {missing_names}")
                return current
            target_stage = ChatStage.REQUIREMENT_CONFIRMED
            if target_stage in self.STAGE_FLOW:
                return target_stage
            return current

        return current

    def confirm_requirements(self, session_id: str) -> str:
        """User confirms requirements - advance to EXECUTION stage."""
        current = self.get_current_stage(session_id)
        if current != ChatStage.REQUIREMENT_CONFIRMED:
            return current

        guide = Guide.query.filter_by(session_id=session_id).first()
        if guide:
            guide.status = "generating"
            db.session.commit()

        return ChatStage.EXECUTION

    def reject_requirements(self, session_id: str, feedback: str = "") -> str:
        """User rejects requirements - go back to REQUIREMENT for modification."""
        current = self.get_current_stage(session_id)
        if current != ChatStage.REQUIREMENT_CONFIRMED:
            return current

        guide = Guide.query.filter_by(session_id=session_id).first()
        if guide:
            guide.requirements = "{}"
            db.session.commit()

        if feedback:
            self.add_message(session_id, "user",
                f"我想修改一下需求：{feedback}", ChatStage.REQUIREMENT)

        return ChatStage.REQUIREMENT

    def validate_requirements_completeness(self, requirements: dict) -> tuple[bool, list[str]]:
        """Hard-validate that all required fields are present and non-empty.

        Returns:
            (is_complete, list_of_missing_field_cn_names)
        """
        missing = []
        for field in self.REQUIRED_FIELDS:
            if not requirements.get(field):
                missing.append(self.ALL_FIELDS_MAPPING.get(field, field))
        return len(missing) == 0, missing

    def get_requirements_for_confirmation(self, session_id: str) -> dict:
        """Get requirements summary for the confirmation card."""
        guide = Guide.query.filter_by(session_id=session_id).first()
        if not guide or not guide.requirements:
            return {"requirements": {}, "missing": list(self.REQUIRED_FIELDS)}

        try:
            requirements = json.loads(guide.requirements)
        except (json.JSONDecodeError, TypeError):
            requirements = {}

        is_complete, missing = self.validate_requirements_completeness(requirements)

        return {
            "requirements": requirements,
            "is_complete": is_complete,
            "missing": missing,
            "display_fields": {
                k: v for k, v in self.ALL_FIELDS_MAPPING.items()
                if k in requirements or k in self.REQUIRED_FIELDS
            },
        }

    @staticmethod
    def _extract_requirements(text: str) -> dict:
        """Extract structured requirements from orchestrator summary text.

        Uses regex first, then falls back to loose matching.
        """
        req = {}
        mapping = {
            "目的地": "destination",
            "出行时间": "dates",
            "出行人数": "travelers",
            "预算范围": "budget",
            "出发城市": "origin",
            "大交通方式": "transport",
            "交通方式": "transport",
            "当地交通": "vehicle",
            "当地交通偏好": "vehicle",
            "住宿偏好": "accommodation",
            "同行关系": "companion_type",
            "兴趣偏好": "interest",
            "行程节奏": "pace",
            "饮食禁忌": "dietary",
            "体力水平": "fitness",
            "特殊需求": "special",
        }
        for cn, en in mapping.items():
            pattern = rf"[-*\u2022]\s*{re.escape(cn)}[\s：:\uFF1A]+(.+)"
            match = re.search(pattern, text)
            if match:
                val = match.group(1).strip()
                val = re.sub(r"\*\*", "", val).strip()
                if val and val not in ("待确认", "待定", "未提供", "-", "--"):
                    if en not in req:
                        req[en] = val
        return req

    def _run_llm_requirements_extraction(self, session_id: str):
        """Use LLM to extract structured requirements more accurately.

        Runs after regex extraction to fill in missing fields from
        the full conversation context.
        """
        guide = Guide.query.filter_by(session_id=session_id).first()
        if not guide:
            return

        try:
            existing = json.loads(guide.requirements) if guide.requirements else {}
        except (json.JSONDecodeError, TypeError):
            existing = {}

        missing = [f for f in self.REQUIRED_FIELDS if not existing.get(f)]

        if not missing:
            return

        try:
            history = self.get_history(session_id)
            extraction_prompt = (
                "请从以下对话历史中提取旅行需求的关键信息，以JSON格式返回。"
                "只提取以下字段中能在对话中找到的信息：\n\n"
            )
            for field in missing:
                extraction_prompt += f"- {self.ALL_FIELDS_MAPPING.get(field, field)} ({field})\n"
            extraction_prompt += (
                "\n请严格返回JSON格式，不要包含任何markdown代码块标记：\n"
                '{"destination": "提取的值", "dates": "提取的值", ...}\n'
                "如果某个字段确实找不到，就不要包含该字段。"
            )

            extraction_messages = [
                {"role": "system", "content": "你是一个信息提取助手，只输出JSON。"},
            ]
            extraction_messages.extend(history[-8:])
            extraction_messages.append({"role": "user", "content": extraction_prompt})

            llm_response = self.planner.generate(extraction_messages, stage="EXTRACTION")

            json_match = re.search(r'\{[^{}]*\}', llm_response, re.DOTALL)
            if json_match:
                extracted = json.loads(json_match.group(0))
                for key, value in extracted.items():
                    if value and value.strip() and key in missing:
                        existing[key] = value.strip()

            guide.requirements = json.dumps(existing, ensure_ascii=False)
            for field_name in ["destination", "dates", "travelers"]:
                if existing.get(field_name):
                    setattr(guide, field_name, existing[field_name])
            db.session.commit()
        except Exception as e:
            print(f"[ChatService] LLM requirements extraction failed: {e}")
            db.session.rollback()

    def save_requirements(self, session_id: str, text: str):
        """Parse and save requirements from orchestrator text into Guide."""
        requirements = self._extract_requirements(text)
        guide = Guide.query.filter_by(session_id=session_id).first()
        if not guide:
            guide = Guide(session_id=session_id)
            db.session.add(guide)
        guide.requirements = json.dumps(requirements, ensure_ascii=False)
        if requirements.get("destination"):
            guide.destination = requirements["destination"]
        if requirements.get("dates"):
            guide.dates = requirements["dates"]
        if requirements.get("travelers"):
            guide.travelers = requirements["travelers"]
        db.session.commit()

    @staticmethod
    def _strip_markup(text: str) -> str:
        """Remove [QUESTION], [TEXT], [CHOICE], [TASK_DISPATCH] markup blocks from visible text.

        The raw blocks are parsed by extract_structured_options(), but must never
        appear in what the user sees or in stored message history.
        """
        import re
        # Strip [QUESTION]...[/QUESTION] blocks entirely
        text = re.sub(r'\s*\[QUESTION\].*?\[/QUESTION\]', '', text, flags=re.DOTALL)
        # Strip any remaining standalone tags
        text = re.sub(r'\[/?TEXT\]', '', text)
        text = re.sub(r'\[/?CHOICE\]\s*(?:single|multi)?', '', text)
        text = re.sub(r'\n\s*rows=\d+\s*\n', '\n', text)
        text = re.sub(r'\n\s*placeholder=.*', '', text)
        text = re.sub(r'\n\s*\[TASK_DISPATCH\]', '', text)
        # Clean up excessive blank lines
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    @staticmethod
    def extract_structured_options(text: str) -> dict | None:
        """Extract structured interaction options from model response.

        Primary format: [QUESTION]...[TEXT]...[CHOICE single/multi]...[/QUESTION]
        Fallback: lettered options and numbered options for backwards compat.

        Returns dict:
          type: "question_block" | "single" | "multi"
          For "question_block": fields[{key, type(text/choice_single/choice_multi),
            label, options[{label,text}], rows, placeholder}]
          For "single"/"multi": backwards-compatible question + options
        """
        import re

        # Step 1: Try [QUESTION] block format (new primary format)
        q_blocks = re.finditer(
            r'\[QUESTION\]\s*\n(.*?)\[/QUESTION\]', text, re.DOTALL
        )
        fields = []
        for qb in q_blocks:
            block = qb.group(1)
            # Step A: Parse [TEXT] blocks and remove them from the block
            def parse_text(m):
                label = m.group(1).strip()
                attrs_text = m.group(2).strip()
                attrs = {}
                for line in attrs_text.split('\n'):
                    line = line.strip()
                    if '=' in line:
                        k, v = line.split('=', 1)
                        attrs[k.strip()] = v.strip()
                fields.append({
                    "key": f"text_{len(fields)}",
                    "type": "text",
                    "label": label or "请输入",
                    "rows": int(attrs.get("rows", 1)),
                    "placeholder": attrs.get("placeholder", ""),
                })
                return ""  # remove from block
            block_after_text = re.sub(
                r'(.*?)\n\s*\[TEXT\]\s*\n(.*?)\[/TEXT\]', parse_text, block, flags=re.DOTALL
            )
            # Step B: Parse [CHOICE] blocks from remaining text
            for cm in re.finditer(
                r'(.*?)\n\s*\[CHOICE\]\s*(single|multi)\s*\n(.*?)\[/CHOICE\]', block_after_text, re.DOTALL
            ):
                label = cm.group(1).strip()
                choice_type = cm.group(2).strip()
                opts_text = cm.group(3).strip()
                opts = re.findall(r'([A-D])[\.\、]\s*(.+?)(?=\s*[A-D][\.\、]|\s*$)', opts_text)
                if opts:
                    fields.append({
                        "key": f"choice_{len(fields)}",
                        "type": f"choice_{choice_type}",
                        "label": label or "请选择",
                        "options": [{"label": l, "text": t.strip()} for l, t in opts],
                    })
            # If nothing matched inside [QUESTION], skip
            if not fields:
                continue

        if fields:
            return {
                "type": "question_block",
                "fields": fields,
            }

        # Step 2: Fallback to old segment-based multi-group detection
        segments = re.split(r'\n\s*\n\s*(?:---+\s*\n)?|\n---+\s*\n', text)
        groups = []

        for seg in segments:
            seg = seg.strip()
            if not seg:
                continue
            lettered = re.findall(r'([A-D])[\.\、]\s*(.+?)(?=\s*[A-D][\.\、]|\s*\n\s*$|\Z)', seg)
            if len(lettered) >= 2:
                opts = [(l, t.strip()) for l, t in lettered]
                first_opt_pos = seg.find(opts[0][0] + '.')
                if first_opt_pos > 0:
                    question = seg[:first_opt_pos].strip()
                    question = re.sub(r'\*\*', '', question).strip()
                    if len(question) > 4:
                        groups.append({
                            "question": question,
                            "options": [{"label": l, "text": t} for l, t in opts],
                        })

        if len(groups) >= 2:
            return {"type": "multi", "groups": groups}
        if len(groups) == 1:
            return {"type": "single", "question": groups[0]["question"], "options": groups[0]["options"]}

        # Step 3: Fallback to whole-text single-group detection
        lettered = re.findall(r'([A-D])[\.\、]\s*(.+?)(?=\s*[A-D][\.\、]|\s*$)', text)
        if len(lettered) >= 2:
            opts = [(l, t.strip()) for l, t in lettered]
            first_opt_pos = text.find(opts[0][0] + '.')
            if first_opt_pos > 0:
                question = text[:first_opt_pos].strip()
                question = re.sub(r'\*\*', '', question).strip()
                if len(question) > 8:
                    return {"type": "single", "question": question, "options": [{"label": l, "text": t} for l, t in opts]}

        # Step 4: Chinese numbered options (1. 2. 3. 4.)
        numbered = re.findall(r'([1-4])[\.\、\)]\s*(.+?)(?=\s*[1-4][\.\、\)]|\s*$)', text)
        if len(numbered) >= 2:
            opts = [(n, t.strip()) for n, t in numbered]
            first_opt_pos = text.find(opts[0][0] + '.')
            if first_opt_pos < 0:
                first_opt_pos = text.find(opts[0][0] + '、')
            if first_opt_pos < 0:
                first_opt_pos = text.find(opts[0][0] + ')')
            if first_opt_pos > 0:
                question = text[:first_opt_pos].strip()
                question = re.sub(r'\*\*', '', question).strip()
                if len(question) > 8:
                    return {"type": "single", "question": question, "options": [{"label": n, "text": t} for n, t in opts]}

        # Step 5: Bullet list options (- item)
        bullets = re.findall(r'^\s*[-\*]\s*(.+?)(?=\n\s*[-\*]|\n\n|\Z)', text, re.MULTILINE)
        if len(bullets) >= 2:
            # Find question before first bullet
            first_bullet_pos = text.find('- ' + bullets[0])
            if first_bullet_pos < 0:
                first_bullet_pos = text.find('* ' + bullets[0])
            if first_bullet_pos > 0:
                question = text[:first_bullet_pos].strip()
                question = re.sub(r'\*\*', '', question).strip()
                if len(question) > 8:
                    labels = ['A', 'B', 'C', 'D', 'E', 'F']
                    return {"type": "single", "question": question, "options": [{"label": labels[i], "text": b.strip()} for i, b in enumerate(bullets[:6])]}

        # Step 6: Fallback - if text contains a clear question but no options,
        # return a text input field so user can freely respond
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        last_line = lines[-1] if lines else ''
        if last_line.endswith('？') or last_line.endswith('?') or '确认' in last_line or '告诉' in last_line:
            # Extract the last paragraph as the question prompt
            paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
            question_text = paragraphs[-1] if paragraphs else text.strip()
            question_text = re.sub(r'\*\*', '', question_text).strip()
            if len(question_text) > 10:
                return {
                    "type": "question_block",
                    "fields": [{
                        "key": "text_response",
                        "type": "text",
                        "label": question_text,
                        "rows": 2,
                        "placeholder": "请在这里输入你的回复...",
                    }],
                }

        return None

    def run_checker(self, session_id: str) -> str:
        """Run checker agent on the final guide."""
        guide = Guide.query.filter_by(session_id=session_id).first()
        if not guide or not guide.content_md:
            return "No guide content to check."

        result = self.checker.check(guide.content_md)

        self.add_message(session_id, "checker", result, ChatStage.COMPLETE)

        return result
