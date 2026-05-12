"""SQLAlchemy data models for Travel Guide Generator."""
import uuid
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def generate_uuid() -> str:
    """Generate a short UUID for session IDs."""
    return str(uuid.uuid4())[:8]


class Conversation(db.Model):
    """Chat messages within a session."""

    __tablename__ = "conversations"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(16), nullable=False, index=True)
    role = db.Column(db.String(20), nullable=False)  # user / planner / checker / tool
    message = db.Column(db.Text, nullable=False)
    stage = db.Column(db.String(30), nullable=False, default="INIT")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "role": self.role,
            "message": self.message,
            "stage": self.stage,
            "created_at": self.created_at.isoformat(),
        }


class Guide(db.Model):
    """Travel guide drafts and final outputs."""

    __tablename__ = "guides"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(16), nullable=False, unique=True, index=True)
    title = db.Column(db.String(200))
    destination = db.Column(db.String(100))
    dates = db.Column(db.String(100))
    travelers = db.Column(db.String(100))
    content_md = db.Column(db.Text, default="")
    content_html = db.Column(db.Text, default="")
    requirements = db.Column(db.Text, default="{}")
    expert_results = db.Column(db.Text, default="{}")
    status = db.Column(db.String(20), default="draft")  # draft / final
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict:
        import json
        return {
            "id": self.id,
            "session_id": self.session_id,
            "title": self.title,
            "destination": self.destination,
            "dates": self.dates,
            "travelers": self.travelers,
            "content_md": self.content_md,
            "requirements": json.loads(self.requirements) if self.requirements else {},
            "expert_results": json.loads(self.expert_results) if self.expert_results else {},
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class ConfigStore(db.Model):
    """Key-value store for runtime configurations."""

    __tablename__ = "config_store"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @classmethod
    def get(cls, key: str, default=None):
        row = cls.query.filter_by(key=key).first()
        return row.value if row else default

    @classmethod
    def set(cls, key: str, value: str):
        row = cls.query.filter_by(key=key).first()
        if row:
            row.value = value
        else:
            row = cls(key=key, value=value)
            db.session.add(row)
        db.session.commit()


class AgentConfig(db.Model):
    """Agent configuration for dynamic orchestration."""

    __tablename__ = "agent_configs"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    display_name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, default="")
    role_type = db.Column(db.String(20), nullable=False, default="expert")
    # llm_config stored as JSON string for flexibility
    llm_config = db.Column(db.Text, default="{}")
    is_active = db.Column(db.Boolean, default=True)
    icon = db.Column(db.String(50), default="🤖")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict:
        import json
        return {
            "id": self.id,
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "role_type": self.role_type,
            "llm_config": json.loads(self.llm_config) if self.llm_config else {},
            "is_active": self.is_active,
            "icon": self.icon,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class AgentRelation(db.Model):
    """Orchestration relation between agents."""

    __tablename__ = "agent_relations"

    id = db.Column(db.Integer, primary_key=True)
    source_agent = db.Column(db.String(50), nullable=False)
    target_agent = db.Column(db.String(50), nullable=False)
    trigger_stage = db.Column(db.String(30), default="")
    trigger_condition = db.Column(db.Text, default="")
    input_mapping = db.Column(db.Text, default="{}")
    output_mapping = db.Column(db.Text, default="{}")
    order_index = db.Column(db.Integer, default=0)
    group = db.Column(db.Integer, default=0)
    depends_on = db.Column(db.String(50), default="")
    is_active = db.Column(db.Boolean, default=True)

    def to_dict(self) -> dict:
        import json
        return {
            "id": self.id,
            "source_agent": self.source_agent,
            "target_agent": self.target_agent,
            "trigger_stage": self.trigger_stage,
            "trigger_condition": self.trigger_condition,
            "input_mapping": json.loads(self.input_mapping) if self.input_mapping else {},
            "output_mapping": json.loads(self.output_mapping) if self.output_mapping else {},
            "order_index": self.order_index,
            "group": self.group,
            "depends_on": self.depends_on,
            "is_active": self.is_active,
        }


class AgentExecutionLog(db.Model):
    """Execution logs for multi-agent orchestration debugging."""

    __tablename__ = "agent_execution_logs"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(16), nullable=False, index=True)
    stage = db.Column(db.String(30))
    agent_name = db.Column(db.String(50))
    agent_role = db.Column(db.String(20))
    input_text = db.Column(db.Text)
    output_text = db.Column(db.Text)
    latency_ms = db.Column(db.Integer)
    status = db.Column(db.String(20), default="running")
    error_message = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "stage": self.stage,
            "agent_name": self.agent_name,
            "agent_role": self.agent_role,
            "input_text": self.input_text,
            "output_text": self.output_text,
            "latency_ms": self.latency_ms,
            "status": self.status,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class PromptTemplate(db.Model):
    """Prompt template with layer support."""

    __tablename__ = "prompt_templates"

    id = db.Column(db.Integer, primary_key=True)
    agent_name = db.Column(db.String(50), nullable=False, index=True)
    layer = db.Column(db.String(20), nullable=False, default="role")
    name = db.Column(db.String(50), nullable=False)
    content = db.Column(db.Text, default="")
    variables = db.Column(db.Text, default="[]")
    is_editable = db.Column(db.Boolean, default=True)
    is_active = db.Column(db.Boolean, default=True)
    version = db.Column(db.Integer, default=1)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict:
        import json
        return {
            "id": self.id,
            "agent_name": self.agent_name,
            "layer": self.layer,
            "name": self.name,
            "content": self.content,
            "variables": json.loads(self.variables) if self.variables else [],
            "is_editable": self.is_editable,
            "is_active": self.is_active,
            "version": self.version,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
