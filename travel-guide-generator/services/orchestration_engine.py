"""Orchestration engine for multi-agent collaboration."""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from models import AgentExecutionLog, db
from services.agent_registry_service import AgentRegistryService
from services.prompt_template_service import PromptTemplateService


class OrchestrationEngine:
    """Manages execution flow between orchestrator and expert agents."""

    def __init__(self):
        self.registry = AgentRegistryService()
        # Eagerly init prompt service so its DB cache is loaded in the main thread
        # (ThreadPoolExecutor workers have no Flask app context)
        self._prompt_service = PromptTemplateService()

    def _get_prompt_service(self):
        return self._prompt_service

    def get_execution_plan(self, stage: str, source: str = "planner") -> list[dict]:
        """Get the execution plan (ordered expert calls) for a stage.

        Returns list of expert configs with relation metadata.
        """
        return self.registry.get_experts_for_stage(stage, source)

    def can_add_relation(self, source: str, target: str) -> bool:
        """Check if a new relation would create a cycle."""
        if source == target:
            return False
        return not self.registry.has_cycle(source, target)

    def execute_plan(self, plan: list[dict], context: dict, session_id: str) -> dict:
        """Execute orchestration plan with parallel/serial groups.

        Args:
            plan: List of expert configs from get_execution_plan()
            context: Shared context dict (e.g., requirements)
            session_id: Session ID for logging

        Returns:
            Dict mapping expert_name -> result_text
        """
        results = {}

        # Group experts by group number
        groups = {}
        for expert in plan:
            group_num = expert.get("group", 0)
            groups.setdefault(group_num, []).append(expert)

        # Execute groups in order
        for group_num in sorted(groups.keys()):
            experts = groups[group_num]

            if len(experts) == 1:
                # Single expert, execute directly
                expert = experts[0]
                ctx = {**context, **results}
                result = self._execute_expert_safe(
                    expert["name"], context=ctx, session_id=session_id
                )
                if result is not None:
                    results[expert["name"]] = result
            else:
                # Multiple experts in same group, execute in parallel
                with ThreadPoolExecutor(max_workers=len(experts)) as executor:
                    futures = {}
                    for expert in experts:
                        ctx = {**context, **results}
                        future = executor.submit(
                            self._execute_expert_safe,
                            expert["name"],
                            context=ctx,
                            session_id=session_id,
                        )
                        futures[future] = expert["name"]

                    for future in as_completed(futures):
                        expert_name = futures[future]
                        try:
                            result = future.result()
                            if result is not None:
                                results[expert_name] = result
                        except Exception as e:
                            print(f"[Orchestration] Expert {expert_name} failed: {e}")

        return results

    def _execute_expert_safe(
        self, agent_name: str, context: dict = None, session_id: str = None
    ) -> str | None:
        """Execute an expert agent with error handling.

        Returns result text on success, None on failure (non-blocking).
        """
        try:
            return self.execute_expert(
                agent_name, messages=[], context=context, session_id=session_id
            )
        except Exception as e:
            import sys
            import traceback
            print(f"[Orchestration] Expert {agent_name} execution failed: {e}", file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)
            return None

    def execute_expert(
        self,
        agent_name: str,
        messages: list[dict],
        context: dict = None,
        session_id: str = None,
        stage: str = None,
    ) -> str:
        """Execute an expert agent with given messages and context.

        Args:
            agent_name: Name of the expert agent to execute.
            messages: Conversation messages (already formatted for LLM).
            context: Optional context dict with variables for prompt rendering.
            session_id: Optional session ID for logging.
            stage: Optional stage for logging.

        Returns:
            The agent's response text.
        """
        import json

        agent = self.registry.get_agent(agent_name)
        agent_role = agent.get("role_type", "expert") if agent else "expert"

        # Build system prompt from database templates
        svc = self._get_prompt_service()
        variables = context or {}
        # Map expert result keys (e.g. hotel_expert) to plan keys (e.g. hotel_plan)
        # so that downstream experts referencing {hotel_plan} can receive results
        mapped_variables = dict(variables)
        for k, v in list(mapped_variables.items()):
            if k.endswith("_expert"):
                mapped_variables[k.replace("_expert", "_plan")] = v
        rendered, missing = svc.render_prompt(agent_name, mapped_variables)

        # If no database prompt, fallback to txt file
        if not rendered:
            from pathlib import Path

            prompt_path = (
                Path(__file__).parent.parent / "agents" / "prompts" / f"{agent_name}.txt"
            )
            if prompt_path.exists():
                rendered = prompt_path.read_text(encoding="utf-8")
                # Apply variable substitution for txt fallback (DB path does this via render_prompt)
                import re
                for key, value in mapped_variables.items():
                    placeholder = "{" + key + "}"
                    if placeholder in rendered:
                        rendered = rendered.replace(placeholder, str(value))
            else:
                role_desc = agent.get("description", "") if agent else ""
                rendered = f"你是一位{role_desc}专家。请根据上下文提供专业的分析和建议。"

        # Prepend system message
        full_messages = [{"role": "system", "content": rendered}] + messages
        input_text = json.dumps(full_messages, ensure_ascii=False)[:4000]

        # Create execution log (skip if no app context, e.g. ThreadPoolExecutor threads)
        log = None
        has_app_ctx = False
        try:
            from flask import has_app_context
            has_app_ctx = has_app_context()
        except Exception:
            pass

        if session_id and has_app_ctx:
            log = AgentExecutionLog(
                session_id=session_id,
                stage=stage or "",
                agent_name=agent_name,
                agent_role=agent_role,
                input_text=input_text,
                status="running",
            )
            try:
                db.session.add(log)
                db.session.commit()
            except Exception:
                try:
                    db.session.rollback()
                except Exception:
                    pass
                log = None

        start_time = time.time()
        try:
            client = self.registry.create_llm_client(agent_name)

            # Experts use chat() directly. Tool calling with flyai CLI takes
            # 30s+ per round and can loop up to 3 times causing browser SSE
            # timeout. Expert prompts already contain domain knowledge sufficient
            # for high-quality travel recommendations.
            result = client.chat(full_messages)

            latency = int((time.time() - start_time) * 1000)
            print(f"[Orchestration] Expert {agent_name} completed in {latency}ms, result length: {len(result) if result else 0}")
            if log and has_app_ctx:
                log.output_text = result[:4000] if result else ""
                log.latency_ms = latency
                log.status = "success"
                try:
                    db.session.commit()
                except Exception:
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
            return result
        except Exception as e:
            latency = int((time.time() - start_time) * 1000)
            if log and has_app_ctx:
                log.latency_ms = latency
                log.status = "error"
                log.error_message = str(e)[:1000]
                try:
                    db.session.commit()
                except Exception:
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
            raise
